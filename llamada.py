import asyncio
import csv
from datetime import datetime, timedelta
import json
import time
import math
import os
import random
import struct
import subprocess
import urllib.request
import wave
from zoneinfo import ZoneInfo

from telethon import TelegramClient, events
from telethon.errors import RPCError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.functions.phone import (
    CreateGroupCallRequest,
    DiscardGroupCallRequest,
    EditGroupCallParticipantRequest,
    GetGroupCallRequest,
    ToggleGroupCallSettingsRequest,
)
from telethon.tl.types import Channel, ChannelParticipantsAdmins, Chat, PeerUser

from ia_resumen import generar_resumen_ia, guardar_minuta, buscar_en_minutas, obtener_minuta
from generador_acta import generar_acta_pdf
from catalogo_audios import identificar_audio_catalogo, formatear_info_audio
from publicar_tarea import extraer_fecha_de_texto

try:
    from pytgcalls import PyTgCalls
    PYTGCALLS_AVAILABLE = True
except ImportError:
    PYTGCALLS_AVAILABLE = False

# Credenciales obligatorias
API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION = os.environ.get("TG_SESSION", "")
GRUPO = os.environ.get("TG_GROUP", "")  # @usuario, o id numérico (-100...)
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # opcional
CHAT_ID = os.environ.get("CHAT_ID", GRUPO)  # id del grupo para el bot
TITULO = os.environ.get("CALL_TITLE", "Llamada diaria")
AVISO = os.environ.get(
    "AVISO",
    "📞 ¡Empieza la llamada diaria! Entra al chat de voz del grupo.",
)

# Parámetros de monitoreo, asistencia y moderación de voz
DURACION_MAXIMA_MINUTOS = int(os.environ.get("DURACION_MAXIMA_MINUTOS", "360"))  # Hasta 6 horas
INTERVALO_SONDEO_SEGUNDOS = int(os.environ.get("INTERVALO_SONDEO_SEGUNDOS", "2"))  # Sondeo rápido a 2s
MIN_MINUTOS_ASISTENCIA = int(os.environ.get("MIN_MINUTOS_ASISTENCIA", "10"))
AUTO_CIERRE_MIN_USUARIOS = int(os.environ.get("AUTO_CIERRE_MIN_USUARIOS", "2"))
AUTO_CIERRE_ESPERA_MINUTOS = int(os.environ.get("AUTO_CIERRE_ESPERA_MINUTOS", "45"))
SEGUNDOS_INACTIVIDAD_MUTE = int(os.environ.get("SEGUNDOS_INACTIVIDAD_MUTE", "15"))  # 15s de silencio antes de cortar mic
DURACION_BLOQUEO_MUTE_SEGUNDOS = int(os.environ.get("DURACION_BLOQUEO_MUTE_SEGUNDOS", "5"))  # Solo 5s de bloqueo antes de auto-desbloquear
MAX_ORADORES_SIMULTANEOS = int(os.environ.get("MAX_ORADORES_SIMULTANEOS", "2"))   # Máx 2 personas hablando

RUTA_PUNTOS = os.path.join("data", "puntos.json")
CARPETA_ASISTENCIAS = os.path.join("data", "asistencias")
CARPETA_MEDITACIONES = os.path.join("data", "meditaciones")


def hora_california() -> str:
    bogota = ZoneInfo("America/Bogota")
    california = ZoneInfo("America/Los_Angeles")
    hoy = datetime.now(bogota).replace(hour=19, minute=56, second=0, microsecond=0)
    return hoy.astimezone(california).strftime("%I:%M %p").lstrip("0").lower()


def determinar_fecha_y_etiqueta_tarea(texto: str) -> tuple[str, str]:
    """Determina si la tarea es para 'hoy' o 'mañana' o una fecha específica."""
    tz_col = ZoneInfo("America/Bogota")
    ahora = datetime.now(tz_col)
    t_lower = (texto or "").lower()

    es_manana_explicito = "mañana" in t_lower or "manana" in t_lower
    ya_paso_hora_hoy = ahora.hour > 20 or (ahora.hour == 20 and ahora.minute >= 32)
    fecha_extraida = extraer_fecha_de_texto(texto)

    dias_semana = {
        0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
        4: "viernes", 5: "sábado", 6: "domingo"
    }
    meses_nom = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }

    if fecha_extraida:
        try:
            d_obj = datetime.strptime(fecha_extraida, "%d/%m/%Y").replace(tzinfo=tz_col)
            if d_obj.date() == ahora.date() and not ya_paso_hora_hoy:
                return "hoy a las 8:32 PM", "Tarea de hoy"
            elif d_obj.date() == (ahora + timedelta(days=1)).date():
                nom_dia = dias_semana.get(d_obj.weekday(), "")
                nom_mes = meses_nom.get(d_obj.month, "")
                txt_dia = f"mañana {nom_dia} {d_obj.day} de {nom_mes}"
                return f"{txt_dia} a las 8:32 PM", f"Tarea para mañana ({nom_dia.title()} {d_obj.day}/{d_obj.month})"
            else:
                nom_dia = dias_semana.get(d_obj.weekday(), "")
                nom_mes = meses_nom.get(d_obj.month, "")
                txt_dia = f"el {nom_dia} {d_obj.day} de {nom_mes}"
                return f"{txt_dia} a las 8:32 PM", f"Tarea programada para el {d_obj.day}/{d_obj.month}"
        except Exception:
            pass

    if es_manana_explicito or ya_paso_hora_hoy:
        manana = ahora + timedelta(days=1)
        nom_dia = dias_semana.get(manana.weekday(), "")
        nom_mes = meses_nom.get(manana.month, "")
        txt_dia = f"mañana {nom_dia} {manana.day} de {nom_mes}"
        return f"{txt_dia} a las 8:32 PM", f"Tarea para mañana ({nom_dia.title()} {manana.day}/{manana.month})"

    return "hoy a las 8:32 PM", "Tarea de hoy"


async def obtener_url_llamada(client, entidad, full_chat) -> str | None:
    link_env = os.environ.get("GROUP_INVITE_LINK", "").strip()
    if link_env:
        return f"{link_env}?videochat" if not link_env.endswith("?videochat") else link_env

    if GRUPO.startswith("@"):
        return f"https://t.me/{GRUPO.lstrip('@')}?videochat"
    elif GRUPO.startswith("https://t.me/"):
        return f"{GRUPO}?videochat"

    # Si la entidad tiene username público
    username = getattr(entidad, "username", None)
    if username:
        return f"https://t.me/{username}?videochat"

    # Si el chat tiene enlace exportado
    exported = getattr(full_chat, "exported_invite", None)
    if exported and getattr(exported, "link", None):
        return f"{exported.link}?videochat"

    # Si no, exportar enlace de invitación con Telethon
    try:
        from telethon.tl.functions.messages import ExportChatInviteRequest
        inv = await client(ExportChatInviteRequest(peer=entidad))
        if getattr(inv, "link", None):
            return f"{inv.link}?videochat"
    except Exception as e:
        print("Nota resolviendo enlace de invitacion:", e)

    return None


def obtener_username_bot() -> str | None:
    if not BOT_TOKEN:
        return None
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        req = urllib.request.Request(url, headers={"User-Agent": "BotLlamadas"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            if data.get("ok"):
                return data["result"].get("username")
    except Exception as e:
        print("Nota obteniendo username del bot:", e)
    return None


def dividir_mensaje(texto: str, limite: int = 3500) -> list:
    """Divide un texto largo en bloques seguros (< límite de 4096 de Telegram) cortando por líneas."""
    bloques, actual = [], ""
    for linea in texto.split("\n"):
        while len(linea) > limite:
            if actual:
                bloques.append(actual)
                actual = ""
            bloques.append(linea[:limite])
            linea = linea[limite:]
        if len(actual) + len(linea) + 1 > limite:
            bloques.append(actual)
            actual = linea
        else:
            actual = f"{actual}\n{linea}" if actual else linea
    if actual:
        bloques.append(actual)
    return bloques or [""]


def avisar_con_bot(texto: str, boton_url: str = None, reply_markup: dict = None) -> None:
    if not BOT_TOKEN:
        return
    texto = texto.replace("{CA}", hora_california())
    # El bot envía texto plano: quitar marcas Markdown para que no se vean asteriscos
    texto = texto.replace("**", "").replace("`", "")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    bloques = dividir_mensaje(texto)
    for idx, bloque in enumerate(bloques):
        payload = {"chat_id": CHAT_ID, "text": bloque}

        if idx == 0:
            if reply_markup:
                payload["reply_markup"] = reply_markup
            elif boton_url:
                inline_keyboard = [
                    [{"text": "🟢 ¡SALA EN VIVO! TOCAR PARA ENTRAR 🎙️", "url": boton_url}]
                ]
                bot_user = obtener_username_bot()
                if bot_user:
                    inline_keyboard.append([
                        {"text": "🏆 Ver Ranking", "url": f"https://t.me/{bot_user}?start=ranking"},
                        {"text": "📜 Reglas y Puntos", "url": f"https://t.me/{bot_user}?start=reglas"}
                    ])
                payload["reply_markup"] = {"inline_keyboard": inline_keyboard}

        datos = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=datos, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                print(f"Aviso del bot enviado ({idx + 1}/{len(bloques)}):", r.status)
        except urllib.error.HTTPError as e:
            detalle = ""
            try:
                detalle = e.read().decode()
            except Exception:
                pass
            print("Error al enviar mensaje con el bot:", e, detalle)
        except Exception as e:
            print("Error al enviar mensaje con el bot:", e)


def enviar_foto_con_bot(ruta_foto: str, caption: str = "") -> None:
    if not BOT_TOKEN or not ruta_foto or not os.path.exists(ruta_foto):
        return
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        with open(ruta_foto, "rb") as f:
            file_bytes = f.read()

        body = bytearray()
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{CHAT_ID}\r\n".encode())
        if caption:
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode())
        filename = os.path.basename(ruta_foto)
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{filename}\"\r\nContent-Type: image/png\r\n\r\n".encode())
        body.extend(file_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            url,
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            print("Foto del podio enviada con bot exitosamente:", r.status)
    except Exception as e:
        print("Nota enviando foto con bot:", e)


def generar_sonido_campana_gong(ruta_salida: str = os.path.join(CARPETA_MEDITACIONES, "campana.wav"), duracion: float = 3.5) -> str:
    """Genera sintéticamente un tono armónico de cuenco tibetano / campana zen a 432 Hz."""
    os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)
    sample_rate = 44100
    num_samples = int(sample_rate * duracion)
    try:
        with wave.open(ruta_salida, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            frames = bytearray()
            for i in range(num_samples):
                t = i / sample_rate
                envelope = math.exp(-t / 1.1)
                sig = (
                    0.60 * math.sin(2 * math.pi * 432.0 * t) +
                    0.25 * math.sin(2 * math.pi * 864.0 * t) +
                    0.15 * math.sin(2 * math.pi * 1296.0 * t)
                ) * envelope
                sample = int(sig * 32767 * 0.7)
                sample = max(-32768, min(32767, sample))
                frames.extend(struct.pack("<h", sample))
            w.writeframes(frames)
        return ruta_salida
    except Exception as e:
        print("Nota generando campana gong:", e)
        return ruta_salida


def agregar_gongs_al_audio(ruta_audio: str) -> str:
    """Inserta campana de cuenco tibetano al inicio y al final de la meditación."""
    if not os.path.exists(ruta_audio):
        return ruta_audio
    campana = generar_sonido_campana_gong()
    ruta_con_gong = os.path.join(CARPETA_MEDITACIONES, "meditacion_con_gong.mp3")
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", campana,
            "-i", ruta_audio,
            "-i", campana,
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
            "-map", "[out]",
            ruta_con_gong
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0 and os.path.exists(ruta_con_gong) and os.path.getsize(ruta_con_gong) > 0:
            return ruta_con_gong
    except Exception as e:
        print("Nota combinando gong con audio:", e)
    return ruta_audio


def generar_imagen_podio(fecha_str: str, duracion_min: int, total_personas: int, hubo_meditacion: bool, top_3: list, ruta_salida: str = os.path.join(CARPETA_ASISTENCIAS, "podio_hoy.png")) -> str | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
        os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)
        width, height = 1000, 1000
        img = Image.new("RGB", (width, height), color=(15, 23, 42))
        draw = ImageDraw.Draw(img)

        # Header Box
        draw.rounded_rectangle([(40, 40), (960, 180)], radius=20, fill=(30, 27, 75), outline=(79, 70, 229), width=2)
        try:
            font_title = ImageFont.truetype("arial.ttf", 38)
            font_sub = ImageFont.truetype("arial.ttf", 24)
            font_stats = ImageFont.truetype("arial.ttf", 22)
            font_podio_num = ImageFont.truetype("arial.ttf", 32)
            font_podio_name = ImageFont.truetype("arial.ttf", 28)
            font_podio_pts = ImageFont.truetype("arial.ttf", 26)
            font_footer = ImageFont.truetype("arial.ttf", 20)
        except Exception:
            font_title = font_sub = font_stats = font_podio_num = font_podio_name = font_podio_pts = font_footer = ImageFont.load_default()

        draw.text((70, 65), "🏆 PODIO DE ASISTENCIA Y PUNTOS", fill=(251, 191, 36), font=font_title)
        draw.text((70, 125), f"Fecha: {fecha_str} | Llamada Diaria 7:56 PM", fill=(199, 210, 254), font=font_sub)

        # Stats Summary Box
        draw.rounded_rectangle([(40, 205), (960, 285)], radius=15, fill=(30, 41, 59), outline=(51, 65, 85), width=2)
        med_txt = "Sí (+30 pts)" if hubo_meditacion else "No"
        stats_line = f"⏱️ Duración: {duracion_min} min   |   👥 Asistentes: {total_personas}   |   🧘 Meditación: {med_txt}"
        draw.text((70, 235), stats_line, fill=(241, 245, 249), font=font_stats)

        colors = [
            ((69, 26, 3), (245, 158, 11), "1", (254, 243, 199)),
            ((30, 41, 59), (148, 163, 184), "2", (241, 245, 249)),
            ((67, 20, 7), (217, 119, 6), "3", (255, 237, 213)),
        ]

        y_start = 315
        for i in range(3):
            bg, border, num, txt_color = colors[i]
            top_y = y_start + (i * 185)
            bot_y = top_y + 160
            draw.rounded_rectangle([(40, top_y), (960, bot_y)], radius=20, fill=bg, outline=border, width=3)
            draw.rounded_rectangle([(65, top_y + 25), (175, bot_y - 25)], radius=15, fill=border)
            draw.text((105, top_y + 55), f"#{num}", fill=(15, 23, 42), font=font_podio_num)

            if i < len(top_3):
                p = top_3[i]
                nombre = p.get("nombre", "Participante")[:28]
                pts = p.get("pts_hoy", 0)
                rango = p.get("rango", "")
                draw.text((205, top_y + 40), nombre, fill=(255, 255, 255), font=font_podio_name)
                draw.text((205, top_y + 90), f"+{pts} pts hoy  •  Rango: {rango}", fill=txt_color, font=font_podio_pts)
            else:
                draw.text((205, top_y + 65), "Lugar Disponible", fill=(148, 163, 184), font=font_podio_name)

        draw.text((240, 930), "¡Nos vemos mañana a las 7:56 PM! • Bot de Asistencia", fill=(148, 163, 184), font=font_footer)
        img.save(ruta_salida, "PNG")
        return ruta_salida
    except Exception as e:
        print("Nota generando imagen del podio:", e)
        return None


def obtener_rango(puntos: int) -> str:
    if puntos >= 1800:
        return "💎 Diamante"
    if puntos >= 750:
        return "🥇 Oro"
    if puntos >= 250:
        return "🥈 Plata"
    return "🥉 Bronce"


def cargar_puntos() -> dict:
    if os.path.exists(RUTA_PUNTOS):
        try:
            with open(RUTA_PUNTOS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("Error leyendo puntos.json, inicializando nuevo:", e)
    return {"version": 2, "usuarios": {}}


def guardar_puntos(data: dict) -> None:
    os.makedirs(os.path.dirname(RUTA_PUNTOS), exist_ok=True)
    with open(RUTA_PUNTOS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generar_texto_miperfil(user_id: int, db_puntos: dict, user_nombre: str = "", username: str = "") -> str:
    usuarios = db_puntos.get("usuarios", {})
    str_uid = str(user_id)
    u = usuarios.get(str_uid)
    if not u:
        nombre = user_nombre or "Compañero"
        return (
            f"👤 **Perfil de Asistencia:** {nombre}\n\n"
            f"Aún no registras asistencias válidas en las llamadas.\n"
            f"¡Únete hoy a las 7:56 PM para ganar tus primeros puntos y subir de rango!"
        )
    nombre = u.get("nombre", user_nombre or "Usuario")
    pts_mes = u.get("puntos_mes", u.get("puntos_totales", 0))
    pts_tot = u.get("puntos_totales", 0)
    rango = obtener_rango(pts_tot)
    racha = u.get("racha_actual", 0)
    asistencias_mes = u.get("asistencias_mes", 0)
    asistencias_tot = u.get("asistencias_totales", 0)
    medallas = u.get("medallas", [])
    txt_medallas = "\n• " + "\n• ".join(medallas) if medallas else "Ninguna aún"

    return (
        f"👤 **FICHA DE USUARIO: {nombre}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎖️ **Rango actual:** {rango}\n"
        f"🏆 **Puntos del mes:** {pts_mes} pts\n"
        f"⭐ **Puntos históricos:** {pts_tot} pts\n"
        f"🔥 **Racha actual:** {racha} días consecutivos\n"
        f"📅 **Asistencias:** {asistencias_mes} este mes ({asistencias_tot} en total)\n\n"
        f"🏅 **Medallas obtenidas:**{txt_medallas}"
    )


def generar_texto_ranking(db_puntos: dict) -> str:
    usuarios = db_puntos.get("usuarios", {})
    if not usuarios:
        return "🏆 **Ranking Mensual:** Aún no hay registros de asistencia este mes."

    top = sorted(usuarios.values(), key=lambda x: x.get("puntos_mes", x.get("puntos_totales", 0)), reverse=True)[:10]
    lineas = [
        "🏆 **TOP 10 DE ASISTENCIA Y PUNTOS (ESTE MES)** 🏆",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    medallas_top = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
    for i, u in enumerate(top):
        pts = u.get("puntos_mes", u.get("puntos_totales", 0))
        rango = obtener_rango(u.get("puntos_totales", 0))
        medallas = " ".join([m.split()[0] for m in u.get("medallas", [])])
        lineas.append(f"{medallas_top[i]} {rango} **{u['nombre']}** — {pts} pts {medallas}".strip())

    lineas.append("\n💡 Escribe `/puntos` para ver tus estadísticas personales.")
    return "\n".join(lineas)


def generar_texto_reglas() -> str:
    return (
        "📜 **SISTEMA DE PUNTOS Y REGLAS DE LA COMUNIDAD**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Cada noche a las 7:56 PM se abre la llamada diaria. ¡Participa y suma puntos!\n\n"
        "⏰ **PUNTUALIDAD:**\n"
        "• Entrar en los primeros 5 min: **+25 pts**\n"
        "• Entrar entre min 5 y 10: **+15 pts**\n\n"
        "🌟 **PERMANENCIA:**\n"
        "• Asistencia completa (>= 80% de la sesión): **+50 pts**\n"
        "• Asistencia parcial: **+20 a +35 pts**\n\n"
        "🎙️ **MICRÓFONO / VOZ:**\n"
        "• Hablar y aportar activamente: **+20 pts**\n\n"
        "🧘 **MEDITACIÓN DIARIA (8:32 PM):**\n"
        "• Participar en la meditación: **+30 pts**\n\n"
        "🔥 **RACHAS:**\n"
        "• Asistir días seguidos: **+5 pts extra por día consecutivo**\n\n"
        "🏅 **MEDALLAS ESPECIALES:**\n"
        "• 🛡️ *Puntualidad de Hierro:* 5 días seguidos en el podio (Top 3 primeros).\n"
        "• 🎙️ *Voz de la Comunidad:* Hablar en 7 llamadas consecutivas.\n"
        "• 🧘 *Mente Serena:* Completar 10 meditaciones en el mes.\n"
        "• 👑 *Centinela:* Asistir a más del 90% de las reuniones del mes.\n\n"
        "✋ **TURNOS Y MODERACIÓN DE MICRÓFONOS:**\n"
        "• Escribe `/turno` en el grupo o levanta la mano ✋ en la sala para pedir la palabra.\n"
        "• Máximo 2 personas hablando a la vez para evitar interferencias.\n"
        "• Si dejas el micrófono abierto sin hablar por 5 segundos, el bot lo silenciará automáticamente para proteger la sala de ruidos de fondo.\n\n"
        "📝 **MINUTAS Y ACTAS CON IA:**\n"
        "• Escribe `/resumen` para leer la minuta oficial de la última sesión.\n"
        "• Escribe `/buscar <palabra>` para encontrar temas tratados en llamadas anteriores.\n"
        "• Escribe `/acta [fecha]` para consultar el documento formal.\n\n"
        "👑 **GRABACIÓN (SOLO ADMINS):**\n"
        "• `/estadograbacion` — Consultar estado actual.\n"
        "• `/pausargrabacion` — Pausar la grabación (ej. tema confidencial).\n"
        "• `/reanudargrabacion` — Reanudar la grabación.\n"
        "• `/detenergrabacion` — Cancelar y borrar grabación de hoy.\n\n"
        "💎 **RANGOS:** Bronce (<250) | Plata (250+) | Oro (750+) | Diamante (1800+)\n"
        "¡Los 3 primeros del mes reciben mención de honor!"
    )


async def obtener_full_chat(client, entidad):
    if isinstance(entidad, Channel):
        full = await client(GetFullChannelRequest(entidad))
        return full.full_chat
    elif isinstance(entidad, Chat):
        full = await client(GetFullChatRequest(entidad.id))
        return full.full_chat
    return None


async def buscar_audio_meditacion(client, entidad, admin_ids) -> tuple[str | None, dict | None]:
    """Busca en los últimos 60 mensajes del grupo un audio de tarea publicado por administradores."""
    try:
        async for msg in client.iter_messages(entidad, limit=60):
            sender_id = msg.sender_id
            if sender_id not in admin_ids:
                continue

            texto = (msg.raw_text or "").upper()
            if any(k in texto for k in ["MEDITACION", "MEDITACIÓN", "TAREA", "MENSAJE"]):
                target_msg = msg
                es_audio = False
                nombre_archivo = ""
                if target_msg.audio or target_msg.voice:
                    es_audio = True
                    nombre_archivo = getattr(target_msg.audio, "file_name", "") or getattr(target_msg.voice, "file_name", "") or ""
                elif target_msg.document and (
                    (target_msg.document.mime_type and "audio" in target_msg.document.mime_type)
                    or any(getattr(a, "file_name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")) for a in getattr(target_msg.document, "attributes", []))
                ):
                    es_audio = True
                    for a in getattr(target_msg.document, "attributes", []):
                        if getattr(a, "file_name", ""):
                            nombre_archivo = getattr(a, "file_name", "")
                elif target_msg.is_reply:
                    reply = await target_msg.get_reply_message()
                    if reply and (reply.audio or reply.voice or (reply.document and (
                        (reply.document.mime_type and "audio" in reply.document.mime_type)
                        or any(getattr(a, "file_name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")) for a in getattr(reply.document, "attributes", []))
                    ))):
                        target_msg = reply
                        es_audio = True
                        if target_msg.document:
                            for a in getattr(target_msg.document, "attributes", []):
                                if getattr(a, "file_name", ""):
                                    nombre_archivo = getattr(a, "file_name", "")

                if es_audio:
                    os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
                    ruta = os.path.join(CARPETA_MEDITACIONES, "meditacion_hoy.mp3")
                    print(f"Descargando audio de meditación del mensaje ID {target_msg.id}...")
                    await client.download_media(target_msg, file=ruta)
                    print("Audio de meditación descargado exitosamente en:", ruta)
                    info_cat = identificar_audio_catalogo(msg.raw_text or "", nombre_archivo)
                    if info_cat:
                        try:
                            ruta_meta = os.path.join(CARPETA_MEDITACIONES, "meta_hoy.json")
                            with open(ruta_meta, "w", encoding="utf-8") as fm:
                                json.dump(info_cat, fm, ensure_ascii=False, indent=2)
                        except Exception:
                            pass
                    return ruta, info_cat
    except Exception as e:
        print("Nota buscando audio de meditación:", e)
    return None, None


def generar_texto_turnos(cola: list, oradores: list) -> str:
    lineas = [
        "🎙️ **LISTA DE TURNOS EN VIVO** ✋",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if oradores:
        txt_oradores = ", ".join([f"**{o}**" for o in oradores])
        lineas.append(f"🗣️ **Hablando ahora:** {txt_oradores}")
    else:
        lineas.append("🗣️ **Hablando ahora:** Micrófono disponible 🎙️")

    lineas.append("\n⏳ **En lista de espera:**")
    if cola:
        for idx, item in enumerate(cola, 1):
            sufijo = " *(le toca a continuación)*" if idx == 1 else ""
            lineas.append(f"{idx}. ✋ **{item['nombre']}**{sufijo}")
    else:
        lineas.append("Nadie en lista de espera.")

    lineas.append("\n💡 Escribe `/turno` en el grupo o levanta la mano ✋ en la sala para pedir la palabra.")
    return "\n".join(lineas)


async def main() -> None:
    tz_col = ZoneInfo("America/Bogota")
    inicio_llamada = datetime.now(tz_col)
    fecha_hoy = inicio_llamada.strftime("%Y-%m-%d")
    fecha_ayer = (inicio_llamada - timedelta(days=1)).strftime("%Y-%m-%d")

    async with TelegramClient(StringSession(SESSION), API_ID, API_HASH) as client:
        await client.get_dialogs()
        try:
            destino = int(GRUPO)
        except ValueError:
            destino = GRUPO
        entidad = await client.get_entity(destino)

        # 0. Obtener IDs de Administradores
        admin_ids = set()
        me = await client.get_me()
        if me:
            admin_ids.add(me.id)
        if hasattr(entidad, "id"):
            admin_ids.add(entidad.id)

        env_admins = os.environ.get("ADMIN_IDS", "") or os.environ.get("ADMIN_ID", "")
        for aid_str in env_admins.replace(",", " ").split():
            if aid_str.strip().isdigit():
                admin_ids.add(int(aid_str.strip()))

        try:
            if isinstance(entidad, (Channel, Chat)):
                async for admin in client.iter_participants(entidad, filter=ChannelParticipantsAdmins):
                    admin_ids.add(admin.id)
        except Exception as e:
            print("Nota obteniendo administradores:", e)

        full_chat = await obtener_full_chat(client, entidad)
        if not full_chat:
            print("No se pudo obtener información del chat.")
            return

        # 1. Crear o reutilizar la sala de voz
        if not full_chat.call:
            try:
                await client(
                    CreateGroupCallRequest(
                        peer=entidad,
                        random_id=random.randint(1, 2**31 - 1),
                        title=TITULO,
                    )
                )
                print("Chat de voz creado exitosamente.")
                await asyncio.sleep(2)
                full_chat = await obtener_full_chat(client, entidad)
            except RPCError as e:
                print("Error creando el chat de voz:", type(e).__name__, e)
        else:
            print("Ya existía un chat de voz activo en el grupo.")

        # Enviar aviso inicial con panel interactivo
        url_llamada = await obtener_url_llamada(client, entidad, full_chat)
        print("Enlace de llamada obtenido para el botón:", url_llamada)
        avisar_con_bot(AVISO, boton_url=url_llamada)

        if not full_chat or not full_chat.call:
            print("No hay llamada disponible para monitorear.")
            return

        input_call = full_chat.call
        print(f"Iniciando monitoreo de la sala (Máx: {DURACION_MAXIMA_MINUTOS} min)...")

        # Estado del sistema de moderación de voz y turnos
        participantes = {}
        cola_turnos = []  # [{"id": uid, "nombre": nom, "username": usr}]
        oradores_activos = set()  # uids actualmente hablando
        segundos_inactividad_mic = {}  # uid -> segundos con mic abierto y sin voz
        avisados_auto_mute = set()  # uids notificados cordialmente
        msg_turnos = None  # Mensaje en vivo con la cola de turnos
        lock_turnos = asyncio.Lock()
        mensajes_chat_recientes = 0
        ultimo_envio_turnos = 0

        async def actualizar_mensaje_turnos(forzar_al_fondo: bool = False):
            nonlocal msg_turnos, mensajes_chat_recientes, ultimo_envio_turnos
            async with lock_turnos:
                nombres_oradores = [
                    participantes[u]["nombre"] if u in participantes else f"ID {u}"
                    for u in oradores_activos
                ]
                txt = generar_texto_turnos(cola_turnos, nombres_oradores)
                ahora = time.time()

                # Si se solicita explícitamente al fondo, o si aún no hay mensaje, o si pasaron >= 5 mensajes en el chat
                if forzar_al_fondo or not msg_turnos or mensajes_chat_recientes >= 5:
                    if msg_turnos:
                        try:
                            await client.delete_messages(entidad, msg_turnos)
                        except Exception:
                            pass
                    try:
                        msg_turnos = await client.send_message(entidad, txt)
                        ultimo_envio_turnos = ahora
                        mensajes_chat_recientes = 0
                    except Exception as e:
                        print("Nota publicando mensaje de turnos al fondo:", e)
                else:
                    try:
                        await client.edit_message(entidad, msg_turnos, txt)
                    except Exception:
                        try:
                            msg_turnos = await client.send_message(entidad, txt)
                            ultimo_envio_turnos = ahora
                            mensajes_chat_recientes = 0
                        except Exception:
                            pass

        # Mensaje fijado dinámico en el grupo
        msg_fijado = None
        texto_fijado_base = (
            "🎙️ **ESTADO DE LA SALA EN VIVO**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Fecha: {fecha_hoy} | ⏰ Inicio: {inicio_llamada.strftime('%I:%M %p')}\n"
            "👥 **Conectados ahora:** 0 personas\n"
            "⏳ **Fase actual:** 💬 Charla inicial y bienvenida\n"
            "🧘 **Meditación programada:** 8:32 PM\n\n"
            "🟢 Entra al chat de voz tocando el botón del anuncio principal."
        )
        try:
            msg_fijado = await client.send_message(entidad, texto_fijado_base)
            await client.pin_message(entidad, msg_fijado, notify=False)
            print("Mensaje de estado fijado dinámicamente en el grupo.")
        except Exception as e:
            print("Nota fijando mensaje de estado:", e)

        # Publicar mensaje de lista de turnos en vivo en el grupo
        try:
            msg_turnos = await client.send_message(entidad, generar_texto_turnos(cola_turnos, []))
            print("Mensaje de turnos en vivo publicado en el grupo.")
        except Exception as e:
            print("Nota publicando mensaje de turnos:", e)

        # Rutas y control para grabación selectiva de voz (excluyendo meditación)
        os.makedirs(CARPETA_ASISTENCIAS, exist_ok=True)
        ruta_grabacion_pre = os.path.join(CARPETA_ASISTENCIAS, f"grabacion_pre_{fecha_hoy}.wav")
        ruta_grabacion_post = os.path.join(CARPETA_ASISTENCIAS, f"grabacion_post_{fecha_hoy}.wav")
        ruta_grabacion_completa = os.path.join(CARPETA_ASISTENCIAS, f"audio_sesion_{fecha_hoy}.mp3")

        grabacion_activa = True
        grabacion_pausada = False
        grabacion_cancelada = False
        segmentos_grabados = [ruta_grabacion_pre]
        contador_segmentos = 0

        async def pausar_grabacion():
            nonlocal grabacion_pausada
            if grabacion_cancelada:
                return False, "⚠️ La grabación ya fue cancelada definitivamente para la sesión de hoy."
            if grabacion_pausada:
                return False, "ℹ️ La grabación ya se encuentra pausada."
            grabacion_pausada = True
            if tgcalls:
                try:
                    await tgcalls.pause(destino)
                except Exception:
                    pass
            print("Grabación pausada manualmente por un administrador.")
            return True, "⏸️ **Grabación de audio pausada por administración.**\nLos temas compartidos durante esta pausa no quedarán registrados en el audio ni en la minuta."

        async def reanudar_grabacion():
            nonlocal grabacion_pausada, contador_segmentos
            if grabacion_cancelada:
                return False, "⚠️ La grabación fue cancelada definitivamente para esta sesión."
            if not grabacion_pausada:
                return False, "ℹ️ La grabación ya está activa y grabando."
            grabacion_pausada = False
            contador_segmentos += 1
            nueva_ruta = os.path.join(CARPETA_ASISTENCIAS, f"grabacion_seg_{contador_segmentos}_{fecha_hoy}.wav")
            segmentos_grabados.append(nueva_ruta)
            if tgcalls:
                try:
                    await tgcalls.record(destino, nueva_ruta)
                except Exception as e:
                    print("Nota reanudando grabación:", e)
            print("Grabación reanudada manualmente por un administrador.")
            return True, "▶️ **Grabación de audio reanudada por administración.**\nSe continúa documentando la sesión con normalidad."

        async def cancelar_grabacion():
            nonlocal grabacion_cancelada, grabacion_activa, grabacion_pausada
            grabacion_cancelada = True
            grabacion_activa = False
            grabacion_pausada = False
            for s in segmentos_grabados:
                try:
                    if os.path.exists(s):
                        os.remove(s)
                except Exception:
                    pass
            for f_tmp in (ruta_grabacion_pre, ruta_grabacion_post, ruta_grabacion_completa):
                try:
                    if os.path.exists(f_tmp):
                        os.remove(f_tmp)
                except Exception:
                    pass
            print("Grabación cancelada y eliminada por un administrador.")
            return True, "⏹️ **Grabación cancelada y eliminada para la sesión de hoy.**\nNo se generará audio ni minuta con IA al finalizar la sala."

        def estado_grabacion_str():
            if grabacion_cancelada:
                return "⏹️ **Estado de Grabación:** Cancelada / Desactivada (no se procesará con IA hoy)."
            elif grabacion_pausada:
                return "⏸️ **Estado de Grabación:** Pausada temporalmente (espacio confidencial)."
            elif grabacion_activa:
                return "🔴 **Estado de Grabación:** Activa (documentando charla comunitaria)."
            return "⚪ **Estado de Grabación:** Inactiva."

        # Iniciar servicio PyTgCalls si está disponible
        tgcalls = None
        if PYTGCALLS_AVAILABLE:
            try:
                tgcalls = PyTgCalls(client)
                await tgcalls.start()
                print("Servicio de audio PyTgCalls iniciado exitosamente.")
                # Iniciar grabación del segmento previo a la meditación
                try:
                    await tgcalls.record(destino, ruta_grabacion_pre)
                    print("Grabación de bienvenida y charla inicial iniciada.")
                except Exception as e:
                    print("Nota iniciando grabación inicial PyTgCalls:", e)
            except Exception as e:
                print("Nota iniciando PyTgCalls:", e)

        # Buscar si ya existe un audio de meditación subido hoy por administradores
        ruta_meditacion, info_catalogo_hoy = await buscar_audio_meditacion(client, entidad, admin_ids)
        reproduciendo_meditacion = False
        reproduccion_iniciada = False
        aviso_oracion_enviado = False
        aviso_espera_enviado = False
        aviso_meditacion_enviado = False
        alerta_falta_audio_enviada = False
        meditacion_activa_hoy = False
        oracion_activa_hoy = False

        async def reproducir_meditacion():
            nonlocal reproduciendo_meditacion, meditacion_activa_hoy
            if not tgcalls or not ruta_meditacion or not os.path.exists(ruta_meditacion):
                return False
            try:
                # Silenciar a nuevos participantes para evitar ruidos de fondo
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=True))
                except Exception:
                    pass

                # Garantizar explícitamente que los administradores NUNCA tengan el micrófono bloqueado
                for aid in admin_ids:
                    try:
                        admin_peer = await client.get_input_entity(aid)
                        await client(EditGroupCallParticipantRequest(call=input_call, participant=admin_peer, muted=False))
                    except Exception:
                        pass

                # Incorporar campanas tibetanas / gong zen al inicio y final
                ruta_a_reproducir = agregar_gongs_al_audio(ruta_meditacion)

                # PyTgCalls conmuta a reproducir el audio de meditación (omitiendo meditación de la grabación)
                await tgcalls.play(destino, ruta_a_reproducir)
                reproduciendo_meditacion = True
                meditacion_activa_hoy = True
                if info_catalogo_hoy:
                    avisar_con_bot(f"▶️ **Iniciando reproducción oficial:**\n{formatear_info_audio(info_catalogo_hoy)}\n🧘 Por favor disfruten de su sesión en silencio.")
                else:
                    avisar_con_bot("▶️ **Iniciando reproducción de la meditación diaria en la sala de voz.**\n🧘 Por favor disfruten de su sesión en silencio.")
                return True
            except Exception as e:
                print("Error reproduciendo meditación:", e)
                return False

        async def auto_desbloquear_microfono(uid_target: int, segundos: int = DURACION_BLOQUEO_MUTE_SEGUNDOS):
            """Espera los segundos configurados (5s) y retira el bloqueo de administrador de Telegram."""
            await asyncio.sleep(segundos)
            if reproduciendo_meditacion and uid_target not in admin_ids:
                return
            if aviso_oracion_enviado and not aviso_espera_enviado and uid_target not in admin_ids:
                return
            try:
                input_peer = await client.get_input_entity(uid_target)
                await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=False))
                print(f"🔓 Micrófono desbloqueado automáticamente para usuario {uid_target} tras {segundos}s.")
            except Exception as e:
                print(f"Nota auto-desbloqueando {uid_target}:", e)

        async def desbloquear_todos_los_participantes():
            """Retira el candado de silencio a todos los participantes no administradores."""
            try:
                call_info_actual = await client(GetGroupCallRequest(call=input_call, limit=100))
                for p in getattr(call_info_actual, "participants", []):
                    if getattr(p, "left", False):
                        continue
                    p_uid = getattr(p.peer, "user_id", None) if isinstance(getattr(p, "peer", None), PeerUser) else None
                    if not p_uid or p_uid in admin_ids:
                        continue
                    try:
                        input_peer = await client.get_input_entity(p.peer)
                        await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=False))
                    except Exception:
                        pass
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
                except Exception:
                    pass
                print("🔓 Todos los participantes han sido desbloqueados en la sala de voz.")
            except Exception as e:
                print("Nota desbloqueando todos los participantes:", e)

        # Configurar evento de fin de audio en PyTgCalls
        if tgcalls:
            try:
                from pytgcalls.types import StreamEnded
                @tgcalls.on_update()
                async def manejar_fin_stream(client_call, update):
                    if isinstance(update, StreamEnded):
                        nonlocal reproduciendo_meditacion
                        if reproduciendo_meditacion:
                            reproduciendo_meditacion = False
                            print("Reproducción de meditación concluida automáticamente.")
                            await desbloquear_todos_los_participantes()
                            avisar_con_bot("🧘✨ **La meditación ha concluido.**\nLos micrófonos han sido restablecidos. ¡Esperamos que hayan tenido una gran sesión!")
                            # Reanudar grabación para el segmento post-meditación si no fue cancelada
                            if not grabacion_cancelada and not grabacion_pausada:
                                segmentos_grabados.append(ruta_grabacion_post)
                                try:
                                    await tgcalls.record(destino, ruta_grabacion_post)
                                    print("Grabación de preguntas y testimonios reanudada tras la meditación.")
                                except Exception as e:
                                    print("Nota reanudando grabación:", e)
            except Exception as e:
                print("Nota configurando StreamEnded handler:", e)

        # Escuchar comandos de usuarios (/puntos, /ranking, /reglas, /ayuda, /meditacion, /turno, /ceder, /turnos, /buscar, /resumen, /acta, /oracion)
        @client.on(events.NewMessage(pattern=r"^/(puntos|miperfil|ranking|top|ayuda|reglas|start|meditacion|audio|turno|pedirturno|mano|ceder|turnos|buscar|resumen|acta|oracion)"))
        async def responder_comandos_en_vivo(event):
            partes = event.raw_text.strip().split()
            texto_cmd = partes[0].lower().split("@")[0]
            param = partes[1].lower() if len(partes) > 1 else ""
            db = cargar_puntos()
            sender = await event.get_sender()
            uid = sender.id if sender else event.sender_id
            nom = f"{getattr(sender, 'first_name', '') or ''} {getattr(sender, 'last_name', '') or ''}".strip() or "Participante"
            usr = getattr(sender, "username", "") or ""

            if texto_cmd in ("/puntos", "/miperfil"):
                resp = generar_texto_miperfil(uid, db, nom, usr)
                await event.reply(resp)
            elif texto_cmd in ("/ranking", "/top") or (texto_cmd == "/start" and param == "ranking"):
                resp = generar_texto_ranking(db)
                await event.reply(resp)
            elif texto_cmd in ("/meditacion", "/audio"):
                ruta_med = os.path.join(CARPETA_MEDITACIONES, "meditacion_hoy.mp3")
                if os.path.exists(ruta_med) and os.path.getsize(ruta_med) > 0:
                    await event.reply("🧘 **Meditación del día:** Aquí tienes el audio para tu práctica diaria.", file=ruta_med)
                else:
                    await event.reply("🧘 Aún no hay un archivo de meditación disponible para hoy. Consulta más tarde.")
            elif texto_cmd in ("/turno", "/pedirturno", "/mano"):
                if uid in admin_ids:
                    await event.reply("👑 Como administrador puedes hablar libremente cuando gustes.")
                    return
                for idx, t in enumerate(cola_turnos, 1):
                    if t["id"] == uid:
                        await event.reply(f"ℹ️ Ya estás en la lista de turnos (Posición #{idx}). Te avisaremos cuando sea tu momento.")
                        await actualizar_mensaje_turnos(forzar_al_fondo=True)
                        return
                if uid in oradores_activos:
                    await event.reply("🎙️ ¡Ya tienes el micrófono habilitado para hablar!")
                    return
                cola_turnos.append({"id": uid, "nombre": nom, "username": usr})
                pos = len(cola_turnos)
                await event.reply(f"✋ **{nom}**, has sido añadido a la lista de turnos (Posición #{pos}). Te avisaremos cuando sea tu momento.")
                await actualizar_mensaje_turnos(forzar_al_fondo=True)
            elif texto_cmd in ("/ceder",):
                en_cola = any(t["id"] == uid for t in cola_turnos)
                era_orador = uid in oradores_activos
                cola_turnos[:] = [t for t in cola_turnos if t["id"] != uid]
                oradores_activos.discard(uid)
                if era_orador or en_cola:
                    try:
                        input_peer = await client.get_input_entity(uid)
                        await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=True))
                        asyncio.create_task(auto_desbloquear_microfono(uid, DURACION_BLOQUEO_MUTE_SEGUNDOS))
                    except Exception:
                        pass
                    await event.reply(f"🤝 **{nom}**, has cedido tu turno de palabra. ¡Muchas gracias por compartir!")
                    await actualizar_mensaje_turnos(forzar_al_fondo=True)
                else:
                    await event.reply("ℹ️ No estás en la lista de turnos ni tienes el micrófono activo.")
            elif texto_cmd in ("/turnos",):
                await actualizar_mensaje_turnos(forzar_al_fondo=True)
            elif texto_cmd in ("/buscar",):
                query = " ".join(partes[1:]) if len(partes) > 1 else ""
                resp = buscar_en_minutas(query)
                await event.reply(resp)
            elif texto_cmd in ("/resumen",):
                fecha_req = partes[1].strip() if len(partes) > 1 else None
                minuta = obtener_minuta(fecha_req)
                if minuta:
                    resp = f"📝 **MINUTA DE LA REUNIÓN ({minuta['fecha']})**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{minuta['resumen']}"
                    await event.reply(resp)
                else:
                    await event.reply(f"ℹ️ No se encontró ninguna minuta registrada para {fecha_req or 'la última fecha'}.")
            elif texto_cmd in ("/acta",):
                fecha_req = partes[1].strip() if len(partes) > 1 else None
                minuta = obtener_minuta(fecha_req)
                if minuta and minuta.get("ruta_pdf") and os.path.exists(minuta["ruta_pdf"]):
                    await event.reply(f"📄 **Acta Oficial de la Reunión ({minuta['fecha']}):**", file=minuta["ruta_pdf"])
                else:
                    await event.reply("ℹ️ No hay un documento PDF de acta disponible para esa fecha.")
            elif texto_cmd in ("/oracion",) or (texto_cmd == "/start" and param == "oracion"):
                resp = (
                    "🕊️ **ORACIÓN Y RECOGIMIENTO COMUNITARIO**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "\"En este momento de quietud y gratitud, acallamos nuestra mente y abrimos el corazón.\n\n"
                    "Agradecemos por este día, por cada respiración, por los aprendizajes recibidos y por la presencia de cada persona en esta comunidad.\n\n"
                    "Pedimos paz profunda en nuestro interior, claridad en los pensamientos, serenidad en las acciones y bienestar para nuestras familias.\n\n"
                    "Guardamos silencio y respiramos en calma, presentes en el aquí y el ahora.\"\n\n"
                    "🙏 *Mantengamos silencio en la sala para cultivar la paz interior de todos.*"
                )
                await event.reply(resp)
            else:
                resp = generar_texto_reglas()
                await event.reply(resp)

        # Escuchar controles de meditación, moderación de turnos y control de grabación exclusivos para administradores
        @client.on(events.NewMessage(pattern=r"^/(reproducir|play|pausar|pause|continuar|resume|detener|stop|volumen|vol|siguiente|next|limpiarturnos|hablar|desmutear|mutear|desmuteartodos|abrir|desbloquear|pausargrabacion|pausar_rec|reanudargrabacion|reanudar_rec|detenergrabacion|cancelar_rec|estadograbacion|estado_rec)"))
        async def controlar_meditacion_admin(event):
            sender = await event.get_sender()
            uid = sender.id if sender else event.sender_id
            if uid not in admin_ids:
                await event.reply("⛔ Solo los administradores pueden utilizar este comando.")
                return

            partes_cmd = event.raw_text.strip().split()
            cmd = partes_cmd[0].lower().split("@")[0]
            if cmd in ("/reproducir", "/play"):
                nonlocal ruta_meditacion, info_catalogo_hoy
                if not ruta_meditacion or not os.path.exists(ruta_meditacion):
                    ruta_meditacion, info_catalogo_hoy = await buscar_audio_meditacion(client, entidad, admin_ids)
                if tgcalls and ruta_meditacion and os.path.exists(ruta_meditacion):
                    ok = await reproducir_meditacion()
                    if ok:
                        await event.reply("▶️ Reproduciendo meditación en la sala de voz...")
                    else:
                        await event.reply("❌ Error iniciando la reproducción de la meditación.")
                else:
                    await event.reply("⚠️ No se encontró ningún archivo de meditación de tarea disponible.")
            elif cmd in ("/pausar", "/pause"):
                if tgcalls:
                    try:
                        await tgcalls.pause(destino)
                        await event.reply("⏸️ Meditación pausada.")
                    except Exception as e:
                        await event.reply(f"Error al pausar: {e}")
            elif cmd in ("/continuar", "/resume"):
                if tgcalls:
                    try:
                        await tgcalls.resume(destino)
                        await event.reply("▶️ Meditación reanudada.")
                    except Exception as e:
                        await event.reply(f"Error al reanudar: {e}")
            elif cmd in ("/volumen", "/vol"):
                if len(partes_cmd) > 1 and partes_cmd[1].isdigit():
                    nuevo_vol = max(1, min(200, int(partes_cmd[1])))
                    if tgcalls:
                        try:
                            await tgcalls.change_volume_call(destino, nuevo_vol)
                            await event.reply(f"🔊 Volumen ajustado a **{nuevo_vol}%**.")
                        except Exception as e:
                            await event.reply(f"Error al ajustar volumen: {e}")
                    else:
                        await event.reply("⚠️ El reproductor no está activo.")
                else:
                    await event.reply("ℹ️ Uso: `/volumen 1-200` (Ejemplo: `/volumen 80`).")
            elif cmd in ("/detener", "/stop"):
                if tgcalls:
                    try:
                        await tgcalls.leave_call(destino)
                        reproduciendo_meditacion = False
                        await desbloquear_todos_los_participantes()
                        await event.reply("⏹️ Reproducción finalizada. Micrófonos restablecidos y desbloqueados.")
                    except Exception as e:
                        await event.reply(f"Error al detener: {e}")
            elif cmd in ("/desmuteartodos", "/abrir", "/desbloquear"):
                await desbloquear_todos_los_participantes()
                await event.reply("🔓 **Todos los micrófonos han sido desbloqueados.**\nLos participantes ahora pueden activar su micrófono libremente cuando deseen hablar.")
                avisar_con_bot("🔓 **Micrófonos abiertos:** El candado de silencio ha sido retirado para todos los asistentes. Pueden activar su micrófono para compartir.")
            elif cmd in ("/siguiente", "/next"):
                if not cola_turnos:
                    await event.reply("ℹ️ No hay participantes esperando en la lista de turnos.")
                    return
                siguiente_u = cola_turnos.pop(0)
                s_uid = siguiente_u["id"]
                s_nom = siguiente_u["nombre"]
                oradores_activos.add(s_uid)
                segundos_inactividad_mic[s_uid] = 0
                avisados_auto_mute.discard(s_uid)
                try:
                    input_peer = await client.get_input_entity(s_uid)
                    await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=False))
                except Exception as e:
                    print(f"Nota desmuteando a {s_nom}:", e)
                await actualizar_mensaje_turnos(forzar_al_fondo=True)
                await event.reply(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Tu micrófono ha sido habilitado.")
                avisar_con_bot(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Por favor abre tu micrófono para compartir.")
            elif cmd in ("/limpiarturnos",):
                cola_turnos.clear()
                await actualizar_mensaje_turnos(forzar_al_fondo=True)
                await event.reply("🧹 **Lista de turnos vaciada exitosamente.**")
            elif cmd in ("/hablar", "/desmutear"):
                target_user = None
                if event.is_reply:
                    reply_msg = await event.get_reply_message()
                    if reply_msg:
                        target_user = await reply_msg.get_sender()
                elif len(partes_cmd) > 1:
                    try:
                        target_user = await client.get_entity(partes_cmd[1])
                    except Exception:
                        pass

                if target_user:
                    t_uid = target_user.id
                    t_nom = f"{getattr(target_user, 'first_name', '') or ''} {getattr(target_user, 'last_name', '') or ''}".strip() or "Usuario"
                    oradores_activos.add(t_uid)
                    segundos_inactividad_mic[t_uid] = 0
                    avisados_auto_mute.discard(t_uid)
                    cola_turnos[:] = [t for t in cola_turnos if t["id"] != t_uid]
                    try:
                        input_peer = await client.get_input_entity(t_uid)
                        await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=False))
                    except Exception as e:
                        print(f"Nota habilitando micrófono a {t_nom}:", e)
                    await actualizar_mensaje_turnos(forzar_al_fondo=True)
                    await event.reply(f"🎙️ Micrófono habilitado para **{t_nom}**.")
                else:
                    await event.reply("ℹ️ Uso: `/hablar @usuario` o responde al mensaje del usuario en el grupo.")
            elif cmd in ("/mutear",):
                target_user = None
                if event.is_reply:
                    reply_msg = await event.get_reply_message()
                    if reply_msg:
                        target_user = await reply_msg.get_sender()
                elif len(partes_cmd) > 1:
                    try:
                        target_user = await client.get_entity(partes_cmd[1])
                    except Exception:
                        pass

                if target_user:
                    t_uid = target_user.id
                    t_nom = f"{getattr(target_user, 'first_name', '') or ''} {getattr(target_user, 'last_name', '') or ''}".strip() or "Usuario"
                    oradores_activos.discard(t_uid)
                    try:
                        input_peer = await client.get_input_entity(t_uid)
                        await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=True))
                        asyncio.create_task(auto_desbloquear_microfono(t_uid, DURACION_BLOQUEO_MUTE_SEGUNDOS))
                    except Exception as e:
                        print(f"Nota silenciando a {t_nom}:", e)
                    await actualizar_mensaje_turnos(forzar_al_fondo=True)
                    await event.reply(f"🔇 Micrófono silenciado para **{t_nom}** (se desbloqueará automáticamente en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s).")
                else:
                    await event.reply("ℹ️ Uso: `/mutear @usuario` o responde al mensaje del usuario en el grupo.")
            elif cmd in ("/pausargrabacion", "/pausar_rec"):
                ok, msg = await pausar_grabacion()
                await event.reply(msg)
                avisar_con_bot(msg)
            elif cmd in ("/reanudargrabacion", "/reanudar_rec"):
                ok, msg = await reanudar_grabacion()
                await event.reply(msg)
                avisar_con_bot(msg)
            elif cmd in ("/detenergrabacion", "/cancelar_rec"):
                ok, msg = await cancelar_grabacion()
                await event.reply(msg)
                avisar_con_bot(msg)
            elif cmd in ("/estadograbacion", "/estado_rec"):
                msg = estado_grabacion_str()
                await event.reply(msg)

        # Mantener la lista de turnos siempre visible al fondo si hay conversación activa en el chat
        @client.on(events.NewMessage(chats=entidad))
        async def mantener_turnos_al_fondo_por_chat(event):
            nonlocal mensajes_chat_recientes
            if msg_turnos and event.message.id == getattr(msg_turnos, "id", None):
                return
            mensajes_chat_recientes += 1
            if mensajes_chat_recientes >= 6 and (cola_turnos or oradores_activos):
                await actualizar_mensaje_turnos(forzar_al_fondo=True)

        # Escuchar si un admin sube la meditación de tarea en vivo
        @client.on(events.NewMessage(chats=entidad))
        async def detectar_nueva_meditacion(event):
            nonlocal ruta_meditacion, info_catalogo_hoy
            sender_id = event.sender_id
            if sender_id not in admin_ids:
                return

            texto = (event.raw_text or "").upper()
            if any(k in texto for k in ["MEDITACION", "MEDITACIÓN", "TAREA", "MENSAJE"]):
                target_msg = event.message
                es_audio = False
                nombre_archivo = ""
                if target_msg.audio or target_msg.voice:
                    es_audio = True
                    nombre_archivo = getattr(target_msg.audio, "file_name", "") or getattr(target_msg.voice, "file_name", "") or ""
                elif target_msg.document and (
                    (target_msg.document.mime_type and "audio" in target_msg.document.mime_type)
                    or any(getattr(a, "file_name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")) for a in getattr(target_msg.document, "attributes", []))
                ):
                    es_audio = True
                    for a in getattr(target_msg.document, "attributes", []):
                        if getattr(a, "file_name", ""):
                            nombre_archivo = getattr(a, "file_name", "")
                elif target_msg.is_reply:
                    reply = await target_msg.get_reply_message()
                    if reply and (reply.audio or reply.voice or (reply.document and (
                        (reply.document.mime_type and "audio" in reply.document.mime_type)
                        or any(getattr(a, "file_name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")) for a in getattr(reply.document, "attributes", []))
                    ))):
                        target_msg = reply
                        es_audio = True
                        if target_msg.document:
                            for a in getattr(target_msg.document, "attributes", []):
                                if getattr(a, "file_name", ""):
                                    nombre_archivo = getattr(a, "file_name", "")

                if es_audio:
                    os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
                    ruta = os.path.join(CARPETA_MEDITACIONES, "meditacion_hoy.mp3")
                    await client.download_media(target_msg, file=ruta)
                    info_cat = identificar_audio_catalogo(event.raw_text or "", nombre_archivo)
                    txt_horario, lbl_tarea = determinar_fecha_y_etiqueta_tarea(event.raw_text or "")
                    if not reproduccion_iniciada and "hoy" in txt_horario:
                        ruta_meditacion = ruta
                        info_catalogo_hoy = info_cat
                    print(f"Nueva meditación recibida y guardada ({lbl_tarea}):", ruta)
                    if info_cat:
                        try:
                            ruta_meta = os.path.join(CARPETA_MEDITACIONES, "meta_hoy.json")
                            with open(ruta_meta, "w", encoding="utf-8") as fm:
                                json.dump(info_cat, fm, ensure_ascii=False, indent=2)
                        except Exception:
                            pass
                        txt_card = formatear_info_audio(info_cat)
                        await event.reply(f"✅ **Audio identificado en el Catálogo:**\n\n{txt_card}\n\nProgramado para reproducirse {txt_horario} en la sala de voz.")
                        avisar_con_bot(f"📢 **{lbl_tarea} registrada:**\n\n{txt_card}")
                    else:
                        await event.reply(f"✅ Meditación recibida. Programada para reproducirse {txt_horario} en la sala de voz.")

        # Escuchar comandos por lenguaje natural de administradores en el grupo
        @client.on(events.NewMessage(chats=entidad))
        async def comandos_naturales_admin(event):
            sender_id = event.sender_id
            if sender_id not in admin_ids:
                return
            texto_raw = (event.raw_text or "").strip().lower()
            if not texto_raw or texto_raw.startswith("/"):
                return

            # Pausar meditación
            if any(p in texto_raw for p in ["pausar meditacion", "pausa la meditacion", "pausar meditación", "pausa la meditación", "pausar audio", "pausa el audio"]):
                if tgcalls:
                    try:
                        await tgcalls.pause(destino)
                        await event.reply("⏸️ Meditación pausada por indicación de administración.")
                    except Exception as e:
                        await event.reply(f"Nota al pausar: {e}")
            # Reanudar meditación
            elif any(p in texto_raw for p in ["reanudar meditacion", "continua la meditacion", "reanudar meditación", "continuar meditación", "seguir meditación", "reanudar audio", "seguir con el audio"]):
                if tgcalls:
                    try:
                        await tgcalls.resume(destino)
                        await event.reply("▶️ Meditación reanudada por indicación de administración.")
                    except Exception as e:
                        await event.reply(f"Nota al reanudar: {e}")
            # Detener meditación
            elif any(p in texto_raw for p in ["detener meditacion", "parar meditacion", "detener meditación", "parar meditación", "parar audio", "detener audio"]):
                if tgcalls:
                    try:
                        nonlocal reproduciendo_meditacion
                        await tgcalls.leave_call(destino)
                        reproduciendo_meditacion = False
                        await desbloquear_todos_los_participantes()
                        await event.reply("⏹️ Meditación detenida. Micrófonos restablecidos y desbloqueados.")
                    except Exception as e:
                        await event.reply(f"Nota al detener: {e}")
            # Desbloquear micrófonos / Abrir sala
            elif any(p in texto_raw for p in ["abrir microfonos", "abrir micrófonos", "desmutear a todos", "desbloquear microfonos", "desbloquear micrófonos", "abrir la sala", "liberar microfonos", "liberar micrófonos"]):
                await desbloquear_todos_los_participantes()
                await event.reply("🔓 Micrófonos desbloqueados para todos los participantes.")
                avisar_con_bot("🔓 **Micrófonos abiertos:** El candado de silencio ha sido retirado para todos los asistentes.")
            # Siguiente orador
            elif any(p in texto_raw for p in ["siguiente turno", "siguiente orador", "siguiente persona", "pasar al siguiente"]):
                if not cola_turnos:
                    await event.reply("ℹ️ No hay participantes en espera en la lista de turnos.")
                else:
                    siguiente_u = cola_turnos.pop(0)
                    s_uid = siguiente_u["id"]
                    s_nom = siguiente_u["nombre"]
                    oradores_activos.add(s_uid)
                    segundos_inactividad_mic[s_uid] = 0
                    avisados_auto_mute.discard(s_uid)
                    try:
                        input_peer = await client.get_input_entity(s_uid)
                        await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=False))
                    except Exception as e:
                        print(f"Nota desmuteando a {s_nom}:", e)
                    await actualizar_mensaje_turnos(forzar_al_fondo=True)
                    await event.reply(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Tu micrófono ha sido habilitado.")
                    avisar_con_bot(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Por favor abre tu micrófono para compartir.")

        segundos_totales = 0
        tiempo_limite_segundos = DURACION_MAXIMA_MINUTOS * 60
        consecutivos_vacio = 0
        consecutivos_menos_de_dos = 0
        cerrado_por_admin = False
        motivo_cierre = "tiempo_limite"
        hubo_caida_masiva_sala = False

        # 2. Bucle de Monitoreo en Vivo
        while segundos_totales < tiempo_limite_segundos:
            await asyncio.sleep(INTERVALO_SONDEO_SEGUNDOS)
            segundos_totales += INTERVALO_SONDEO_SEGUNDOS
            ahora = datetime.now(tz_col)

            # Control de hora para la Meditación Automática
            hora_col = ahora.hour
            min_col = ahora.minute

            # Alerta preventiva a las 8:15 PM si aún no se ha subido el audio
            if hora_col == 20 and min_col == 15 and not alerta_falta_audio_enviada:
                alerta_falta_audio_enviada = True
                if not ruta_meditacion or not os.path.exists(ruta_meditacion):
                    try:
                        await client.send_message(
                            "me",
                            "⚠️ **RECORDATORIO PREVENTIVO DE MEDITACIÓN (8:15 PM)**\n\n"
                            "Aún no se ha detectado el archivo de audio con `MEDITACION DE TAREA` en el grupo.\n"
                            "Por favor súbelo antes de las 8:30 PM para que inicie automáticamente a las 8:32 PM."
                        )
                    except Exception:
                        pass
                    avisar_con_bot("⚠️ **Aviso Administradores:** Aún no se ha publicado la `MEDITACION DE TAREA` de hoy. Recuerden subir el archivo .mp3 antes de las 8:30 PM.")

            # 8:28 PM: Inicio de los 3 Minutos de Oración en Silencio Comunitario
            if hora_col == 20 and min_col == 28 and not aviso_oracion_enviado:
                aviso_oracion_enviado = True
                oracion_activa_hoy = True

                # Pausar grabación para omitir los 3 min de oración
                if tgcalls and not grabacion_pausada and not grabacion_cancelada:
                    try:
                        for m in ("pause_record", "stop_record", "pause"):
                            if hasattr(tgcalls, m):
                                fn = getattr(tgcalls, m)
                                res = fn(destino)
                                if asyncio.iscoroutine(res):
                                    await res
                                break
                        print("Grabación pausada para respetar el momento de oración y silencio sagrado.")
                    except Exception as e:
                        print("Nota pausando grabación en oración:", e)

                # Silenciar micrófonos para garantizar silencio y respeto en la sala (No afecta a administradores)
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=True))
                    for uid_orador in list(oradores_activos):
                        if uid_orador in admin_ids:
                            continue
                        try:
                            input_peer = await client.get_input_entity(uid_orador)
                            await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=True))
                        except Exception:
                            pass
                    oradores_activos = {u for u in oradores_activos if u in admin_ids}
                    # Garantizar que todos los administradores tengan el micrófono habilitado
                    for aid in admin_ids:
                        try:
                            admin_peer = await client.get_input_entity(aid)
                            await client(EditGroupCallParticipantRequest(call=input_call, participant=admin_peer, muted=False))
                        except Exception:
                            pass
                    await actualizar_mensaje_turnos(forzar_al_fondo=True)
                except Exception as e:
                    print("Nota silenciando micrófonos para oración:", e)

                # Construir botones interactivos grandes para el anuncio
                bot_user = obtener_username_bot()
                link_sala = url_llamada or (f"https://t.me/{getattr(entidad, 'username', '')}" if getattr(entidad, "username", None) else "https://t.me")
                keyboard_oracion = {
                    "inline_keyboard": [
                        [{"text": "🕊️ ENTRAR A LA SALA DE VOZ (ORACIÓN) 🎧", "url": link_sala}],
                        [{"text": "📖 LEER GUÍA DE ORACIÓN DEL DÍA 🕊️", "url": f"https://t.me/{bot_user}?start=oracion" if bot_user else link_sala}],
                        [{"text": "🤫 SILENCIO SAGRADO EN CURSO (3 MIN)", "url": link_sala}],
                    ]
                }

                extra_med_txt = ""
                if info_catalogo_hoy:
                    extra_med_txt = f": {info_catalogo_hoy['tipo']} #{info_catalogo_hoy['numero']} - «{info_catalogo_hoy['titulo']}» ({info_catalogo_hoy['maestro']})"

                texto_oracion = (
                    "🕊️ **MOMENTO DE ORACIÓN EN SILENCIO (3 MINUTOS)** 🕊️\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Entramos en nuestro espacio de oración y recogimiento comunitario.\n\n"
                    "🤫 **POR FAVOR GUARDEN SILENCIO:**\n"
                    "Durante estos 3 minutos mantengan sus micrófonos apagados para honrar la concentración y paz de todos.\n\n"
                    "⏰ **Cronograma del momento:**\n"
                    "• **8:28 PM – 8:31 PM:** Oración y recogimiento en silencio (3 min).\n"
                    f"• **8:32 PM:** Inicio de la Meditación diaria{extra_med_txt}."
                )
                avisar_con_bot(texto_oracion, reply_markup=keyboard_oracion)

            # 8:31 PM: Conclusión de los 3 minutos de oración y alerta 1 minuto antes de la meditación
            if hora_col == 20 and min_col == 31 and not aviso_meditacion_enviado:
                aviso_meditacion_enviado = True
                if aviso_oracion_enviado and not aviso_espera_enviado:
                    aviso_espera_enviado = True
                    oracion_activa_hoy = False
                    await desbloquear_todos_los_participantes()
                    prefijo = "⏳✨ **Concluyen los 3 minutos de oración.**\n\n"
                else:
                    prefijo = ""

                if ruta_meditacion and os.path.exists(ruta_meditacion):
                    if info_catalogo_hoy:
                        txt_alerta_med = (
                            f"{prefijo}🧘 **En 1 minuto (8:32 PM) dará inicio la {info_catalogo_hoy['tipo'].lower()} diaria:**\n"
                            f"📌 **{info_catalogo_hoy['tipo']} #{info_catalogo_hoy['numero']}:** «{info_catalogo_hoy['titulo']}»\n"
                            f"👤 **Guía / Maestro:** {info_catalogo_hoy['maestro']}\n"
                            f"🗓️ **Grabación original:** {info_catalogo_hoy['fecha']}\n\n"
                            "Los micrófonos han sido habilitados. Por favor tomen una postura cómoda y permanezcan en silencio."
                        )
                    else:
                        txt_alerta_med = (
                            f"{prefijo}🧘 **En 1 minuto (8:32 PM) dará inicio la meditación diaria.**\n"
                            "Los micrófonos han sido habilitados. Por favor tomen una postura cómoda y permanezcan en silencio."
                        )
                    avisar_con_bot(txt_alerta_med)
                elif prefijo:
                    avisar_con_bot(f"{prefijo}Los micrófonos han sido habilitados para la comunidad.")

            # 8:32 PM: Reproducción automática de la meditación
            if hora_col == 20 and min_col >= 32 and not reproduccion_iniciada and ruta_meditacion and os.path.exists(ruta_meditacion):
                reproduccion_iniciada = True
                await reproducir_meditacion()

            try:
                call_info = await client(GetGroupCallRequest(call=input_call, limit=100))
            except RPCError as e:
                print("Llamada finalizada por un administrador o cerrada externamente:", type(e).__name__, e)
                cerrado_por_admin = True
                motivo_cierre = "admin"
                break
            except Exception as e:
                print("Error de conexión al consultar llamada:", e)
                await asyncio.sleep(2)
                try:
                    call_info = await client(GetGroupCallRequest(call=input_call, limit=100))
                except Exception:
                    cerrado_por_admin = True
                    motivo_cierre = "admin"
                    break

            if not getattr(call_info, "call", None):
                print("La llamada ya no se encuentra activa en Telegram.")
                cerrado_por_admin = True
                motivo_cierre = "admin"
                break

            # Cada 10 ciclos (~3 min), verificar el estado de la llamada en el chat
            if (segundos_totales // INTERVALO_SONDEO_SEGUNDOS) % 10 == 0:
                try:
                    fc = await obtener_full_chat(client, entidad)
                    if not fc or not fc.call or getattr(fc.call, "id", None) != getattr(input_call, "id", None):
                        print("El chat de voz fue finalizado por un administrador.")
                        cerrado_por_admin = True
                        motivo_cierre = "admin"
                        break
                except Exception as e:
                    print("Nota verificando chat:", e)

            users_dict = {u.id: u for u in getattr(call_info, "users", [])}
            activos_en_tick = set()
            hubo_cambio_turnos = False

            for p in getattr(call_info, "participants", []):
                if getattr(p, "left", False):
                    continue
                uid = getattr(p.peer, "user_id", None) if isinstance(getattr(p, "peer", None), PeerUser) else None
                if not uid:
                    continue

                activos_en_tick.add(uid)
                u = users_dict.get(uid)
                nombre = f"{u.first_name or ''} {u.last_name or ''}".strip() if u else "Usuario"
                username = u.username or "" if u else ""

                # Detección de micrófono y estado de silencio
                hablo_ahora = False
                if getattr(p, "active_date", None):
                    hablo_ahora = True
                elif getattr(p, "muted", True) is False and getattr(p, "volume", 0) and getattr(p, "volume", 0) > 0:
                    hablo_ahora = True

                p_muted = getattr(p, "muted", True)

                # Detección de mano levantada nativa en Telegram (✋ raise_hand_rating != 0)
                raise_hand = getattr(p, "raise_hand_rating", 0)
                if raise_hand and uid not in admin_ids:
                    if not any(t["id"] == uid for t in cola_turnos) and uid not in oradores_activos:
                        cola_turnos.append({"id": uid, "nombre": nombre, "username": username})
                        print(f"✋ {nombre} levantó la mano en Telegram y fue añadido a la lista de turnos.")
                        hubo_cambio_turnos = True

                # Moderación de micrófonos en vivo
                if uid in admin_ids:
                    # Garantizar que ningún administrador tenga candado de silencio en ningún momento (ni en meditación)
                    if getattr(p, "can_self_unmute", True) is False or getattr(p, "muted_by_you", False) is True:
                        try:
                            input_peer = await client.get_input_entity(p.peer)
                            await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=False))
                            print(f"🔓 Candado de silencio retirado para administrador {nombre} ({uid}).")
                        except Exception:
                            pass
                else:
                    if reproduciendo_meditacion:
                        # Durante la meditación, silenciar a cualquier participante regular que tenga el micrófono abierto
                        if not p_muted:
                            try:
                                input_peer = await client.get_input_entity(uid)
                                await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=True))
                                oradores_activos.discard(uid)
                                hubo_cambio_turnos = True
                                print(f"Silenciado participante {nombre} ({uid}) durante la reproducción de meditación.")
                            except Exception as e:
                                print(f"Nota silenciando en meditación a {nombre}:", e)
                    else:
                        if not p_muted:
                            # Micrófono abierto
                            if hablo_ahora:
                                segundos_inactividad_mic[uid] = 0
                                avisados_auto_mute.discard(uid)
                                if uid not in oradores_activos:
                                    oradores_activos.add(uid)
                                    hubo_cambio_turnos = True

                                # Regla: Máximo MAX_ORADORES_SIMULTANEOS (2) personas a la vez
                                if len(oradores_activos) > MAX_ORADORES_SIMULTANEOS and uid not in list(oradores_activos)[:MAX_ORADORES_SIMULTANEOS]:
                                    oradores_activos.discard(uid)
                                    try:
                                        input_peer = await client.get_input_entity(uid)
                                        await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=True))
                                        asyncio.create_task(auto_desbloquear_microfono(uid, DURACION_BLOQUEO_MUTE_SEGUNDOS))
                                        if not any(t["id"] == uid for t in cola_turnos):
                                            cola_turnos.append({"id": uid, "nombre": nombre, "username": username})
                                        hubo_cambio_turnos = True
                                        avisar_con_bot(f"⚠️ **{nombre}**, ya hay {MAX_ORADORES_SIMULTANEOS} personas hablando a la vez. Tu micrófono se desbloqueará en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s y te hemos añadido a la lista de turnos para no interrumpir.")
                                        print(f"Límite de oradores alcanzado. {nombre} silenciado temporalmente ({DURACION_BLOQUEO_MUTE_SEGUNDOS}s) y añadido a la cola.")
                                    except Exception as e:
                                        print(f"Nota limitando oradores simultáneos para {nombre}:", e)
                            else:
                                # Micrófono abierto pero NO está hablando (olvido, ancianos, ruido de fondo)
                                seg_inac = segundos_inactividad_mic.get(uid, 0) + INTERVALO_SONDEO_SEGUNDOS
                                segundos_inactividad_mic[uid] = seg_inac

                                if seg_inac >= SEGUNDOS_INACTIVIDAD_MUTE:
                                    try:
                                        input_peer = await client.get_input_entity(uid)
                                        await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=True))
                                        asyncio.create_task(auto_desbloquear_microfono(uid, DURACION_BLOQUEO_MUTE_SEGUNDOS))
                                        oradores_activos.discard(uid)
                                        segundos_inactividad_mic[uid] = 0
                                        hubo_cambio_turnos = True
                                        if uid not in avisados_auto_mute:
                                            avisados_auto_mute.add(uid)
                                            avisar_con_bot(f"🔇 **Micrófono silenciado:** {nombre} por inactividad. Se desbloqueará en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s para que puedas volver a hablar cuando desees.")
                                        print(f"Auto-mute aplicado a {nombre} ({uid}) tras {seg_inac}s de inactividad. Desbloqueo programado en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s.")
                                    except Exception as e:
                                        print(f"Nota auto-muteando a {nombre}:", e)
                        else:
                            # Micrófono cerrado
                            segundos_inactividad_mic[uid] = 0
                            if uid in oradores_activos:
                                oradores_activos.discard(uid)
                                hubo_cambio_turnos = True

                if uid not in participantes:
                    participantes[uid] = {
                        "id": uid,
                        "nombre": nombre,
                        "username": username,
                        "primera_entrada": ahora,
                        "ultima_salida": ahora,
                        "segundos_acumulados": 0.0,
                        "activo_ahora": True,
                        "ultimo_check": ahora,
                        "reconexiones": 0,
                        "hablo": hablo_ahora,
                        "orden_llegada": len(participantes) + 1,
                        "meditacion_completada": reproduciendo_meditacion,
                    }
                else:
                    part = participantes[uid]
                    if nombre != "Usuario" and part["nombre"] == "Usuario":
                        part["nombre"] = nombre
                    if username and not part["username"]:
                        part["username"] = username
                    if hablo_ahora:
                        part["hablo"] = True
                    if reproduciendo_meditacion:
                        part["meditacion_completada"] = True

                    if not part["activo_ahora"]:
                        part["reconexiones"] += 1
                        part["activo_ahora"] = True
                        part["ultimo_check"] = ahora
                    else:
                        delta = (ahora - part["ultimo_check"]).total_seconds()
                        part["segundos_acumulados"] += max(0.0, delta)
                        part["ultimo_check"] = ahora
                        part["ultima_salida"] = ahora

            if hubo_cambio_turnos:
                await actualizar_mensaje_turnos(forzar_al_fondo=True)

            # Marcar desconectados
            total_activos_previos = sum(1 for p in participantes.values() if p["activo_ahora"])
            desconectados_este_tick = 0
            for uid, part in participantes.items():
                if uid not in activos_en_tick and part["activo_ahora"]:
                    part["activo_ahora"] = False
                    part["ultima_salida"] = ahora
                    desconectados_este_tick += 1

            if total_activos_previos >= 4 and desconectados_este_tick >= max(3, int(total_activos_previos * 0.6)):
                hubo_caida_masiva_sala = True
                print("⚡ Detección de caída masiva o parpadeo general en la sala de Telegram.")

            # Reglas de Auto-Cierre inteligente:
            num_activos = len(activos_en_tick)
            minutos_transcurridos = segundos_totales // 60

            # Actualización del mensaje fijado dinámico cada ~5 min
            if msg_fijado and (segundos_totales // INTERVALO_SONDEO_SEGUNDOS) % 15 == 0:
                if reproduciendo_meditacion:
                    if info_catalogo_hoy:
                        fase = f"🧘 {info_catalogo_hoy['tipo']} #{info_catalogo_hoy['numero']}: «{info_catalogo_hoy['titulo']}» en curso..."
                    else:
                        fase = "🧘 Meditación diaria en curso..."
                elif reproduccion_iniciada:
                    fase = "🎙️ Ronda de preguntas y compartir"
                elif aviso_espera_enviado and not reproduccion_iniciada:
                    fase = "🧘 Preparación para la meditación (8:32 PM)"
                elif aviso_oracion_enviado and not aviso_espera_enviado:
                    fase = "🕊️ Momento de Oración en Silencio (3 min)"
                else:
                    fase = "💬 Charla inicial y bienvenida"

                txt_med_status = "Reproducida" if reproduccion_iniciada else "8:32 PM"
                if info_catalogo_hoy:
                    txt_med_status += f" ({info_catalogo_hoy['tipo']} #{info_catalogo_hoy['numero']})"

                nuevo_texto_fijado = (
                    "🎙️ **ESTADO DE LA SALA EN VIVO**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📅 Fecha: {fecha_hoy} | ⏰ En vivo desde: {inicio_llamada.strftime('%I:%M %p')}\n"
                    f"👥 **Conectados ahora:** {num_activos} personas\n"
                    f"⏳ **Fase actual:** {fase}\n"
                    f"🧘 **Meditación:** {txt_med_status}\n\n"
                    "🟢 Entra al chat de voz tocando el botón del anuncio principal."
                )
                try:
                    await client.edit_message(entidad, msg_fijado, nuevo_texto_fijado)
                except Exception:
                    pass

            # Regla 1: Sala completamente vacía durante 2 min continuos (tras primeros 5 min)
            if minutos_transcurridos >= 5:
                if num_activos == 0:
                    consecutivos_vacio += 1
                    if consecutivos_vacio >= (120 // INTERVALO_SONDEO_SEGUNDOS):
                        print(f"Auto-cierre: Sala vacía durante 2 min continuos tras {minutos_transcurridos} min.")
                        motivo_cierre = "sala_vacia"
                        break
                else:
                    consecutivos_vacio = 0

            # Regla 2: Menos de 2 personas conectadas durante 3 min continuos (tras 45 min)
            if minutos_transcurridos >= AUTO_CIERRE_ESPERA_MINUTOS:
                if num_activos < AUTO_CIERRE_MIN_USUARIOS:
                    consecutivos_menos_de_dos += 1
                    if consecutivos_menos_de_dos >= (180 // INTERVALO_SONDEO_SEGUNDOS):
                        print(f"Auto-cierre: Menos de {AUTO_CIERRE_MIN_USUARIOS} usuarios tras {minutos_transcurridos} min.")
                        motivo_cierre = "pocos_usuarios"
                        break
                else:
                    consecutivos_menos_de_dos = 0

        # Desfijar mensaje dinámico y limpiar mensaje de turnos al terminar la llamada
        if msg_fijado:
            try:
                await client.unpin_message(entidad, msg_fijado)
            except Exception:
                pass
        if msg_turnos:
            try:
                await client.delete_messages(entidad, msg_turnos)
            except Exception:
                pass

        # 3. Finalización y Consolidación de Asistencia
        fin_llamada = datetime.now(tz_col)
        duracion_reunion_minutos = max(1, int(round((fin_llamada - inicio_llamada).total_seconds() / 60)))

        for uid, part in participantes.items():
            if part["activo_ahora"]:
                delta = (fin_llamada - part["ultimo_check"]).total_seconds()
                part["segundos_acumulados"] += max(0.0, delta)
                part["ultima_salida"] = fin_llamada
                part["activo_ahora"] = False

        # Desconectar reproductor de PyTgCalls y cerrar sala
        if tgcalls:
            try:
                await tgcalls.leave_call(destino)
            except Exception:
                pass

        if not cerrado_por_admin:
            try:
                await client(DiscardGroupCallRequest(call=input_call))
                print("Chat de voz cerrado automáticamente por el bot al terminar la sesión.")
            except Exception as e:
                print("Nota al cerrar llamada:", e)

        # 4. Procesamiento de Puntos, Medallas, Meditación y Temporada Mensual
        db_puntos = cargar_puntos()
        mes_actual = inicio_llamada.strftime("%Y-%m")

        if db_puntos.get("mes_actual") != mes_actual:
            db_puntos["mes_actual"] = mes_actual
            db_puntos["total_llamadas_mes"] = 0
            for u in db_puntos.get("usuarios", {}).values():
                u["puntos_mes"] = 0
                u["asistencias_mes"] = 0
                u["minutos_mes"] = 0
                u["meditaciones_mes"] = 0

        db_puntos["total_llamadas_mes"] = db_puntos.get("total_llamadas_mes", 0) + 1
        total_llamadas_mes = db_puntos["total_llamadas_mes"]

        usuarios_db = db_puntos.setdefault("usuarios", {})
        podio_puntuales = sorted(participantes.values(), key=lambda x: x["primera_entrada"])[:3]
        ids_podio = {p["id"] for p in podio_puntuales}

        asistentes_validos = []
        visitas_fugaces = []

        for uid, part in participantes.items():
            mins = int(round(part["segundos_acumulados"] / 60))
            part["minutos"] = mins
            pct = int(round((part["segundos_acumulados"] / (duracion_reunion_minutos * 60)) * 100))
            part["porcentaje"] = min(100, pct)

            if mins >= MIN_MINUTOS_ASISTENCIA:
                minutos_desde_inicio = (part["primera_entrada"] - inicio_llamada).total_seconds() / 60
                pts_puntualidad = 25 if minutos_desde_inicio <= 5 else (15 if minutos_desde_inicio <= 10 else 5)
                pts_permanencia = 50 if pct >= 80 else (35 if mins >= 45 else (20 if mins >= 20 else 10))
                pts_voz = 20 if part["hablo"] else 0
                pts_meditacion = 30 if part.get("meditacion_completada") else 0

                str_uid = str(uid)
                u_data = usuarios_db.get(str_uid, {
                    "id": uid,
                    "nombre": part["nombre"],
                    "username": part["username"],
                    "puntos_mes": 0,
                    "puntos_totales": 0,
                    "racha_actual": 0,
                    "mejor_racha": 0,
                    "racha_podio": 0,
                    "racha_voz": 0,
                    "asistencias_mes": 0,
                    "asistencias_totales": 0,
                    "minutos_mes": 0,
                    "minutos_totales": 0,
                    "meditaciones_mes": 0,
                    "meditaciones_totales": 0,
                    "medallas": [],
                    "ultima_fecha": "",
                })

                ultima_f = u_data.get("ultima_fecha", "")
                racha = u_data.get("racha_actual", 0)
                if ultima_f == fecha_ayer:
                    racha += 1
                    pts_racha = min(racha * 5, 25)
                elif ultima_f == fecha_hoy:
                    pts_racha = 0
                else:
                    racha = 1
                    pts_racha = 0

                if uid in ids_podio:
                    u_data["racha_podio"] = u_data.get("racha_podio", 0) + 1
                else:
                    u_data["racha_podio"] = 0

                if part["hablo"]:
                    u_data["racha_voz"] = u_data.get("racha_voz", 0) + 1
                else:
                    u_data["racha_voz"] = 0

                medallas_set = set(u_data.get("medallas", []))
                nuevas_medallas = []

                if u_data["racha_podio"] >= 5 and "🛡️ Puntualidad de Hierro" not in medallas_set:
                    medallas_set.add("🛡️ Puntualidad de Hierro")
                    nuevas_medallas.append("🛡️ Puntualidad de Hierro")

                if u_data["racha_voz"] >= 7 and "🎙️ Voz de la Comunidad" not in medallas_set:
                    medallas_set.add("🎙️ Voz de la Comunidad")
                    nuevas_medallas.append("🎙️ Voz de la Comunidad")

                asistencias_mes_actual = u_data.get("asistencias_mes", 0) + 1
                if total_llamadas_mes >= 10 and (asistencias_mes_actual / total_llamadas_mes) >= 0.90:
                    if "👑 Centinela" not in medallas_set:
                        medallas_set.add("👑 Centinela")
                        nuevas_medallas.append("👑 Centinela")

                # Medalla especial: Mente Serena (10 meditaciones en el mes)
                if part.get("meditacion_completada"):
                    u_data["meditaciones_mes"] = u_data.get("meditaciones_mes", 0) + 1
                    u_data["meditaciones_totales"] = u_data.get("meditaciones_totales", 0) + 1
                    if u_data["meditaciones_mes"] >= 10 and "🧘 Mente Serena" not in medallas_set:
                        medallas_set.add("🧘 Mente Serena")
                        nuevas_medallas.append("🧘 Mente Serena")

                u_data["medallas"] = list(medallas_set)

                total_hoy = pts_puntualidad + pts_permanencia + pts_voz + pts_racha + pts_meditacion

                u_data["nombre"] = part["nombre"]
                u_data["username"] = part["username"]
                u_data["puntos_mes"] = u_data.get("puntos_mes", 0) + total_hoy
                u_data["puntos_totales"] = u_data.get("puntos_totales", 0) + total_hoy
                u_data["racha_actual"] = racha
                u_data["mejor_racha"] = max(u_data.get("mejor_racha", 0), racha)
                u_data["ultima_fecha"] = fecha_hoy
                u_data["asistencias_mes"] = asistencias_mes_actual
                u_data["asistencias_totales"] = u_data.get("asistencias_totales", 0) + 1
                u_data["minutos_mes"] = u_data.get("minutos_mes", 0) + mins
                u_data["minutos_totales"] = u_data.get("minutos_totales", 0) + mins
                usuarios_db[str_uid] = u_data

                part["pts_hoy"] = total_hoy
                part["pts_mes"] = u_data["puntos_mes"]
                part["pts_totales"] = u_data["puntos_totales"]
                part["racha"] = racha
                part["rango"] = obtener_rango(u_data["puntos_totales"])
                part["nuevas_medallas"] = nuevas_medallas
                part["desglose"] = (
                    f"⏰ Puntual +{pts_puntualidad} | "
                    f"🌟 Perm +{pts_permanencia}"
                    + (f" | 🎙️ Voz +{pts_voz}" if pts_voz else "")
                    + (f" | 🧘 Medit +{pts_meditacion}" if pts_meditacion else "")
                    + (f" | 🔥 Racha +{pts_racha}" if pts_racha else "")
                )
                asistentes_validos.append(part)
            else:
                visitas_fugaces.append(part)

        db_puntos["actualizado"] = fecha_hoy
        guardar_puntos(db_puntos)

        # 5. Generar Archivo CSV
        os.makedirs(CARPETA_ASISTENCIAS, exist_ok=True)
        ruta_csv = os.path.join(CARPETA_ASISTENCIAS, f"asistencia_{fecha_hoy}.csv")
        with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID", "Nombre", "Usuario", "Entrada", "Salida", "Minutos",
                "% Reunion", "Hablo", "Meditacion", "Reconexiones", "Puntos Hoy",
                "Puntos Mes", "Puntos Totales", "Rango", "Medallas"
            ])
            for part in asistentes_validos:
                u_info = usuarios_db.get(str(part["id"]), {})
                writer.writerow([
                    part["id"], part["nombre"], f"@{part['username']}" if part["username"] else "",
                    part["primera_entrada"].strftime("%I:%M:%S %p"),
                    part["ultima_salida"].strftime("%I:%M:%S %p"),
                    part["minutos"], f"{part['porcentaje']}%",
                    "Si" if part["hablo"] else "No",
                    "Si" if part.get("meditacion_completada") else "No",
                    part["reconexiones"],
                    part.get("pts_hoy", 0), part.get("pts_mes", 0),
                    part.get("pts_totales", 0), part.get("rango", ""),
                    " / ".join(u_info.get("medallas", []))
                ])
            for part in visitas_fugaces:
                writer.writerow([
                    part["id"], part["nombre"], f"@{part['username']}" if part["username"] else "",
                    part["primera_entrada"].strftime("%I:%M:%S %p"),
                    part["ultima_salida"].strftime("%I:%M:%S %p"),
                    part["minutos"], f"{part['porcentaje']}%",
                    "Si" if part["hablo"] else "No", "No", part["reconexiones"],
                    0, 0, usuarios_db.get(str(part["id"]), {}).get("puntos_totales", 0), "Visita Fugaz", ""
                ])

        # 6. Construir y Enviar Reportes
        asistentes_validos.sort(key=lambda x: x.get("pts_hoy", 0), reverse=True)
        ranking_mes = sorted(usuarios_db.values(), key=lambda x: x.get("puntos_mes", 0), reverse=True)[:5]
        es_fin_de_mes = (inicio_llamada + timedelta(days=1)).month != inicio_llamada.month

        lineas_pub = [
            "📊 **REPORTE DE ASISTENCIA Y PUNTOS — LLAMADA DIARIA**",
            f"🗓️ Fecha: {inicio_llamada.strftime('%d/%m/%Y')}",
            f"⏱️ Duración: {duracion_reunion_minutos} min | 👥 Asistentes: {len(asistentes_validos)} personas\n",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "🏆 **PODIO DE PUNTUALIDAD:**",
        ]
        medallas_podio = ["🥇", "🥈", "🥉"]
        for idx, p in enumerate(podio_puntuales):
            tag = f"(@{p['username']})" if p["username"] else ""
            lineas_pub.append(f"{medallas_podio[idx]} {p['nombre']} {tag} — {p['primera_entrada'].strftime('%I:%M:%S %p')}")

        lineas_pub.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lineas_pub.append("🌟 **PUNTOS GANADOS HOY:**")
        if asistentes_validos:
            for p in asistentes_validos:
                tag = f"(@{p['username']})" if p["username"] else ""
                icono_voz = "🎙️" if p["hablo"] else "🎧"
                estrella = "⭐ " if p["porcentaje"] >= 80 else "• "
                aviso_medalla = f"\n   🎉 ¡Nueva medalla: {', '.join(p['nuevas_medallas'])}!" if p.get("nuevas_medallas") else ""
                lineas_pub.append(
                    f"{estrella}**{p['nombre']}** {tag} ➔ **+{p['pts_hoy']} pts** {icono_voz}\n"
                    f"   [{p['desglose']}] — Racha: 🔥 {p['racha']} días ({p['rango']}){aviso_medalla}"
                )
        else:
            lineas_pub.append("No se registraron asistencias que cumplieran el tiempo mínimo hoy.")

        if es_fin_de_mes:
            lineas_pub.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lineas_pub.append("👑 **🏆 CUADRO DE HONOR — CAMPEONES DEL MES 🏆** 👑")
            campeones_mes = sorted(usuarios_db.values(), key=lambda x: x.get("puntos_mes", 0), reverse=True)[:3]
            titulos = ["🥇 CAMPEÓN DEL MES", "🥈 SUBCAMPEÓN", "🥉 TERCER PUESTO"]
            for idx, c in enumerate(campeones_mes):
                lineas_pub.append(f"{titulos[idx]}: **{c['nombre']}** con {c.get('puntos_mes', 0)} pts")
            lineas_pub.append("✨ ¡Felicitaciones a los ganadores de la temporada!")

        lineas_pub.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lineas_pub.append("🏆 **TOP 5 DEL MES (TABLA GENERAL):**")
        for i, u in enumerate(ranking_mes, start=1):
            meds = " ".join([m.split()[0] for m in u.get("medallas", [])])
            lineas_pub.append(f"{i}. {obtener_rango(u.get('puntos_totales', 0))} **{u['nombre']}** — {u.get('puntos_mes', 0)} pts {meds}".strip())

        lineas_pub.append("\n🎙️ = Participó hablando  |  🎧 = Oyente | 🧘 = Meditación")
        lineas_pub.append("💡 Comandos disponibles: `/puntos` | `/ranking` | `/reglas` | `/meditacion`")
        lineas_pub.append("¡Gracias a todos por participar! Nos vemos mañana a las 7:56 PM.")

        # Generar imagen gráfica profesional del podio y enviarla al grupo
        try:
            ruta_img_podio = generar_imagen_podio(
                fecha_str=inicio_llamada.strftime("%d/%m/%Y"),
                duracion_min=duracion_reunion_minutos,
                total_personas=len(participantes),
                hubo_meditacion=meditacion_activa_hoy,
                top_3=asistentes_validos[:3],
            )
            if ruta_img_podio and os.path.exists(ruta_img_podio):
                enviar_foto_con_bot(ruta_img_podio, caption=f"🏆 **PODIO OFICIAL — LLAMADA {inicio_llamada.strftime('%d/%m/%Y')}** 🏆")
        except Exception as e:
            print("Nota generando o enviando imagen del podio:", e)

        reporte_publico = "\n".join(lineas_pub)
        avisar_con_bot(reporte_publico)

        # Enviar notificación privada personalizada a cada asistente
        if BOT_TOKEN and asistentes_validos:
            print("Enviando resúmenes individuales privados a asistentes...")
            for p in asistentes_validos:
                try:
                    meds_p = p.get("nuevas_medallas", [])
                    txt_nuevas_meds = f"\n🎖️ **¡Nueva medalla desbloqueada!** {', '.join(meds_p)}" if meds_p else ""
                    reconex = p.get("reconexiones", 0)
                    txt_diagnostico_red = ""
                    if reconex >= 2:
                        if hubo_caida_masiva_sala:
                            txt_diagnostico_red = (
                                f"\n\n📡 **Estabilidad de llamada:** Detectamos **{reconex} reconexiones** en tu sesión. "
                                "Notamos fluctuaciones generales en los servidores de Telegram hoy, por lo que la interrupción pudo deberse a la plataforma."
                            )
                        else:
                            txt_diagnostico_red = (
                                f"\n\n⚠️ **ESTABILIDAD DE TU CONEXIÓN:**\n"
                                f"Registraste **{reconex} micro-desconexiones** (mientras el resto de la sala se mantuvo 100% estable).\n\n"
                                f"💡 **¿Telegram te saca de la llamada frecuentemente? Prueba esto:**\n"
                                f"1. 🔋 **Batería (Principal causa):** En tu celular ve a _Ajustes > Aplicaciones > Telegram > Batería_ y selecciona **'Sin restricciones'** (así tu celular no cerrará la llamada al apagar la pantalla).\n"
                                f"2. 📶 **Señal:** Procura no alternar entre WiFi y datos móviles durante la reunión.\n"
                                f"3. 🧹 **Caché:** En Telegram ve a _Ajustes > Datos y almacenamiento > Uso de almacenamiento > Borrar caché_."
                            )
                    txt_privado_usuario = (
                        f"👋 ¡Hola **{p['nombre']}**!\n\n"
                        f"🎉 **Resumen de tu llamada de hoy:**\n"
                        f"• Tiempo conectado: **{p['minutos']} min** ({p['porcentaje']}% de la sesión)\n"
                        f"• Puntos sumados hoy: **+{p['pts_hoy']} pts**\n"
                        f"  _{p['desglose']}_\n"
                        f"• Puntos del mes: **{p['pts_mes']} pts** (Histórico: {p['pts_totales']})\n"
                        f"• Rango actual: **{p['rango']}**\n"
                        f"• Racha diaria: **🔥 {p['racha']} días consecutivos**\n"
                        f"{txt_nuevas_meds}"
                        f"{txt_diagnostico_red}\n\n"
                        f"✨ ¡Gracias por tu compromiso y asistencia! Nos vemos mañana a las 7:56 PM."
                    )
                    url_usr = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                    datos_usr = json.dumps({
                        "chat_id": p["id"],
                        "text": txt_privado_usuario,
                        "parse_mode": "Markdown",
                    }).encode()
                    req_usr = urllib.request.Request(url_usr, data=datos_usr, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req_usr, timeout=5) as r:
                        pass
                except Exception:
                    pass

        # Reporte Privado para el Dueño
        med_detalle = 'Sí' if meditacion_activa_hoy else 'No'
        if meditacion_activa_hoy and info_catalogo_hoy:
            med_detalle += f" ({info_catalogo_hoy['tipo']} #{info_catalogo_hoy['numero']}: «{info_catalogo_hoy['titulo']}» | Maestro: {info_catalogo_hoy['maestro']} | Grabado: {info_catalogo_hoy['fecha']})"

        lineas_priv = [
            "🔐 **REPORTE ADMINISTRATIVO DETALLADO (SOLO DUEÑO)**",
            f"📅 Fecha: {fecha_hoy} | ⏰ {inicio_llamada.strftime('%I:%M:%S %p')} – {fin_llamada.strftime('%I:%M:%S %p')}",
            f"⏱️ Duración total: {duracion_reunion_minutos} minutos (Motivo cierre: {motivo_cierre})",
            f"🧘 Meditación/Mensaje reproducido: {med_detalle}",
            f"👥 Total que entraron: {len(participantes)} | ✅ Válidos: {len(asistentes_validos)} | ⚠️ Fugaces: {len(visitas_fugaces)}\n",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "📋 **DESGLOSE INDIVIDUAL DE ASISTENTES:**",
        ]
        for i, p in enumerate(asistentes_validos, start=1):
            tag = f"@{p['username']}" if p['username'] else "Sin alias"
            mic = "🎙️ Habló activamente" if p["hablo"] else "🎧 Solo oyente"
            med_txt = " | 🧘 Asistió a meditación" if p.get("meditacion_completada") else ""
            u_info = usuarios_db.get(str(p["id"]), {})
            meds_txt = ", ".join(u_info.get("medallas", [])) or "Ninguna"
            caidas_tag = ""
            if p.get("reconexiones", 0) >= 2:
                caidas_tag = " [⚠️ Celular/Red del usuario]" if not hubo_caida_masiva_sala else " [⚡ Telegram global]"
            lineas_priv.append(
                f"{i}. **{p['nombre']}** (ID: `{p['id']}` | {tag})\n"
                f"   • Conexión: {p['primera_entrada'].strftime('%I:%M:%S %p')} ➔ {p['ultima_salida'].strftime('%I:%M:%S %p')}\n"
                f"   • Tiempo: {p['minutos']} min ({p['porcentaje']}% de sesión) | Caídas: {p['reconexiones']}{caidas_tag}\n"
                f"   • Micrófono: {mic}{med_txt} | Hoy: +{p['pts_hoy']} pts (Mes: {p['pts_mes']} | Histórico: {p['pts_totales']})\n"
                f"   • Medallas: {meds_txt}"
            )

        if visitas_fugaces:
            lineas_priv.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lineas_priv.append(f"⚠️ **VISITAS FUGACES (<{MIN_MINUTOS_ASISTENCIA} min):**")
            for p in visitas_fugaces:
                tag = f"@{p['username']}" if p['username'] else "Sin alias"
                lineas_priv.append(f"• {p['nombre']} (ID: `{p['id']}` | {tag}) — {p['minutos']} min (Salió {p['ultima_salida'].strftime('%I:%M:%S %p')})")

        lineas_priv.append(f"\n📎 Se generó el archivo de auditoría: `{ruta_csv}`")
        reporte_privado = "\n".join(lineas_priv)

        # 7. Generar Resumen con IA (Gemini) y Diarización de Oradores
        oradores_sesion = [
            p["nombre"] for p in participantes.values() if p.get("hablo")
        ]

        # Unir grabaciones de voz si existen y no fueron canceladas (excluyendo meditación)
        audio_para_ia = None
        if not grabacion_cancelada:
            valid_segments = [s for s in segmentos_grabados if os.path.exists(s) and os.path.getsize(s) > 1000]
            if len(valid_segments) == 1:
                audio_para_ia = valid_segments[0]
            elif len(valid_segments) > 1:
                try:
                    ruta_concat_list = os.path.join(CARPETA_ASISTENCIAS, "concat_list.txt")
                    with open(ruta_concat_list, "w", encoding="utf-8") as f:
                        for seg in valid_segments:
                            clean_path = seg.replace("\\", "/")
                            f.write(f"file '{clean_path}'\n")
                    cmd_cat = [
                        "ffmpeg", "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", ruta_concat_list,
                        "-c:a", "libmp3lame",
                        "-b:a", "64k",
                        ruta_grabacion_completa
                    ]
                    subprocess.run(cmd_cat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
                    if os.path.exists(ruta_grabacion_completa) and os.path.getsize(ruta_grabacion_completa) > 1000:
                        audio_para_ia = ruta_grabacion_completa
                    try:
                        os.remove(ruta_concat_list)
                    except Exception:
                        pass
                except Exception as e:
                    print("Nota combinando grabaciones con ffmpeg:", e)
        else:
            print("Grabación cancelada durante la sesión; no se procesará audio.")

        resumen_ia = generar_resumen_ia(
            ruta_audio=audio_para_ia,
            oradores=oradores_sesion,
            fecha=fecha_hoy,
            duracion_minutos=duracion_reunion_minutos,
            total_asistentes=len(asistentes_validos),
            info_catalogo=info_catalogo_hoy,
        )
        if grabacion_cancelada:
            resumen_ia = "⚠️ *Nota: La grabación de audio fue cancelada por la administración durante la sesión. Este informe se generó con base en los datos de participación sin almacenamiento de audio.*\n\n" + resumen_ia

        # Publicar Minuta Oficial en el Grupo
        txt_minuta_grupo = (
            f"📝 **MINUTA Y RESUMEN OFICIAL — LLAMADA {inicio_llamada.strftime('%d/%m/%Y')}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{resumen_ia}"
        )
        avisar_con_bot(txt_minuta_grupo)

        # Generar Acta Oficial en PDF
        ruta_acta_pdf = generar_acta_pdf(
            fecha=fecha_hoy,
            inicio_str=inicio_llamada.strftime("%I:%M %p"),
            fin_str=fin_llamada.strftime("%I:%M %p"),
            duracion_minutos=duracion_reunion_minutos,
            asistentes=asistentes_validos,
            resumen_ia=resumen_ia,
            info_catalogo=info_catalogo_hoy,
        )

        # Guardar en base histórica de minutas para búsquedas posteriores
        guardar_minuta(
            fecha=fecha_hoy,
            duracion_minutos=duracion_reunion_minutos,
            asistentes_count=len(asistentes_validos),
            oradores=oradores_sesion,
            resumen_texto=resumen_ia,
            ruta_pdf=ruta_acta_pdf,
            info_catalogo=info_catalogo_hoy,
        )

        me = await client.get_me()
        if me:
            try:
                for bloque in dividir_mensaje(reporte_privado):
                    await client.send_message(me.id, bloque)
                print("Reporte privado enviado a Mensajes Guardados del dueño.")
            except Exception as e:
                print("Error enviando reporte privado al dueño:", e)
            try:
                if os.path.exists(ruta_csv):
                    await client.send_file(
                        me.id,
                        ruta_csv,
                        caption=f"📊 Archivo de Asistencia y Puntos - {fecha_hoy}",
                    )
                if os.path.exists(ruta_acta_pdf):
                    caption_acta = f"📄 **Acta Oficial de la Reunión (PDF) - {fecha_hoy}**\nIncluye lista de asistencia y resumen."
                    if info_catalogo_hoy:
                        caption_acta += f"\n🧘 {info_catalogo_hoy['tipo']} #{info_catalogo_hoy['numero']}: «{info_catalogo_hoy['titulo']}» ({info_catalogo_hoy['maestro']})"
                    await client.send_file(
                        me.id,
                        ruta_acta_pdf,
                        caption=caption_acta,
                    )
                # Enviar grabación de audio de la sesión (excluyendo meditación) exclusivamente al dueño
                if audio_para_ia and os.path.exists(audio_para_ia) and not grabacion_cancelada:
                    await client.send_file(
                        me.id,
                        audio_para_ia,
                        caption=f"🎙️ **Grabación de Audio Oficial (MP3) - {fecha_hoy}**\nSesión comunitaria (sin meditación).",
                    )
                    print("Grabación de audio MP3 enviada a Mensajes Guardados del dueño.")
                if os.path.exists(RUTA_PUNTOS):
                    await client.send_file(
                        me.id,
                        RUTA_PUNTOS,
                        caption=f"💾 Respaldo de puntos - {fecha_hoy}",
                    )
                print("CSV, Acta PDF, audio MP3 y respaldo de puntos enviados al dueño.")
            except Exception as e:
                print("Error enviando archivos al dueño:", e)

        # Limpiar temporales de grabación cruda una vez enviados
        for s in segmentos_grabados:
            try:
                if os.path.exists(s):
                    os.remove(s)
            except Exception:
                pass
        for f_tmp in (ruta_grabacion_pre, ruta_grabacion_post, ruta_grabacion_completa):
            try:
                if os.path.exists(f_tmp):
                    os.remove(f_tmp)
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
