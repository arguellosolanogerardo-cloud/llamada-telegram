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
import shutil
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
    GetGroupParticipantsRequest,
    ToggleGroupCallSettingsRequest,
)
from telethon.tl.types import Channel, ChannelParticipantsAdmins, Chat, PeerUser, PeerChannel, PeerChat

from ia_resumen import generar_resumen_ia, guardar_minuta, buscar_en_minutas, obtener_minuta
from generador_acta import generar_acta_pdf
from catalogo_audios import identificar_audio_catalogo, formatear_info_audio, identificar_todos_los_audios, formatear_cola_audios
from publicar_tarea import extraer_fecha_de_texto
from drive_manager import obtener_o_descargar_audio
import re
import unicodedata

# Ecualizador automático de voz (opcional: si falta el archivo, el bot sigue igual)
try:
    from mejorar_audio import (
        AjusteEQ,
        analizar_audio_async,
        demucs_disponible,
        describir_ajuste,
        mejorar_audio_async,
        recortar_desde_async,
    )
    MEJORA_AUDIO = True
except Exception as _e_eq:
    print("Nota: mejorar_audio.py no disponible, el audio se reproduce sin procesar:", _e_eq)
    MEJORA_AUDIO = False

try:
    from pytgcalls import PyTgCalls
    from pytgcalls.types.raw import Stream, AudioStream, AudioParameters
    from ntgcalls import MediaSource
    PYTGCALLS_AVAILABLE = True
except ImportError:
    PYTGCALLS_AVAILABLE = False

# Credenciales obligatorias
API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION = os.environ.get("TG_SESSION", "")
GRUPO = os.environ.get("TG_GROUP", "")  # @usuario, o id numérico (-100...)
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # opcional
BOT_ID = int(BOT_TOKEN.split(":")[0]) if (BOT_TOKEN and ":" in BOT_TOKEN) else None
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


def determinar_fecha_y_etiqueta_tarea(texto: str, fecha_referencia: datetime = None) -> tuple[str, str]:
    """Determina si la tarea es para 'hoy' o 'mañana' o una fecha específica."""
    tz_col = ZoneInfo("America/Bogota")
    if fecha_referencia:
        if fecha_referencia.tzinfo is None:
            ahora = fecha_referencia.replace(tzinfo=tz_col)
        else:
            ahora = fecha_referencia.astimezone(tz_col)
    else:
        ahora = datetime.now(tz_col)
    t_lower = (texto or "").lower()

    es_manana_explicito = "mañana" in t_lower or "manana" in t_lower
    ya_paso_hora_hoy = ahora.hour > 20 or (ahora.hour == 20 and ahora.minute >= 32)
    fecha_extraida = extraer_fecha_de_texto(texto, fecha_referencia=ahora)

    dias_semana = {
        0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
        4: "viernes", 5: "sábado", 6: "domingo"
    }
    meses_nom = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }

    hoy_real = datetime.now(tz_col).date()
    if fecha_extraida:
        try:
            d_obj = datetime.strptime(fecha_extraida, "%d/%m/%Y").replace(tzinfo=tz_col)
            if d_obj.date() == hoy_real and not (ya_paso_hora_hoy and fecha_referencia is None):
                return "hoy a las 8:32 PM", "Tarea de hoy"
            elif d_obj.date() == (hoy_real + timedelta(days=1)):
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


ids_mensajes_efimeros = set()


def avisar_con_bot(texto: str, boton_url: str = None, reply_markup: dict = None, es_efimero: bool = False) -> list[int]:
    if not BOT_TOKEN:
        return []
    texto = texto.replace("{CA}", hora_california())
    # El bot envía texto plano: quitar marcas Markdown para que no se vean asteriscos
    texto = texto.replace("**", "").replace("`", "")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    bloques = dividir_mensaje(texto)
    ids_enviados = []
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
                res_data = json.loads(r.read().decode("utf-8"))
                mid = res_data.get("result", {}).get("message_id")
                if mid:
                    ids_enviados.append(mid)
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

    if es_efimero and ids_enviados:
        ids_mensajes_efimeros.update(ids_enviados)

    return ids_enviados


async def limpiar_mensajes_temporales(client, entidad, ids_a_borrar: set) -> None:
    if not ids_a_borrar:
        return
    lista_ids = [int(i) for i in ids_a_borrar if i]
    print(f"Iniciando eliminación de {len(lista_ids)} mensajes y ventanas temporales de la sala...")
    # 1. Intentar borrar en lotes mediante Telethon (con permisos de administración del grupo)
    try:
        for k in range(0, len(lista_ids), 100):
            lote = lista_ids[k:k+100]
            await client.delete_messages(entidad, lote)
        print("Ventanas y avisos temporales eliminados exitosamente con Telethon.")
        return
    except Exception as e:
        print("Nota borrando mensajes con Telethon, aplicando respaldo con Bot API:", e)

    # 2. Respaldo directo vía Bot API deleteMessage
    if BOT_TOKEN:
        for mid in lista_ids:
            try:
                url_del = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
                datos = json.dumps({"chat_id": CHAT_ID, "message_id": mid}).encode()
                req = urllib.request.Request(url_del, data=datos, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    pass
            except Exception:
                pass
        print("Ventanas y avisos temporales eliminados con Bot API.")


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
        fbin = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [
            fbin, "-y",
            "-i", campana,
            "-i", ruta_audio,
            "-i", campana,
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
            "-map", "[out]",
            ruta_con_gong
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        if res.returncode == 0 and os.path.exists(ruta_con_gong) and os.path.getsize(ruta_con_gong) > 0:
            return ruta_con_gong
    except Exception as e:
        print("Nota combinando gong con audio:", e)
    return ruta_audio


def convertir_audio_a_pcm(ruta_audio: str) -> str:
    """Convierte cualquier archivo de audio (MP3, WAV, M4A) a PCM s16le 48kHz estéreo para PyTgCalls FileReader nativo."""
    if not os.path.exists(ruta_audio):
        return ruta_audio
    ruta_raw = ruta_audio.rsplit(".", 1)[0] + ".raw"
    try:
        if os.path.exists(ruta_raw) and os.path.getsize(ruta_raw) > 5000 and os.path.getmtime(ruta_raw) >= os.path.getmtime(ruta_audio):
            return ruta_raw
    except Exception:
        pass

    fbin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        fbin, "-y",
        "-i", ruta_audio,
        "-f", "s16le",
        "-ac", "2",
        "-ar", "48000",
        ruta_raw
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        if res.returncode == 0 and os.path.exists(ruta_raw) and os.path.getsize(ruta_raw) > 5000:
            print(f"Audio convertido exitosamente a PCM nativo: {ruta_raw} ({os.path.getsize(ruta_raw)} bytes)")
            return ruta_raw
    except Exception as e:
        print("Nota convirtiendo audio a PCM:", e)
    return ruta_audio


def asegurar_mp3_desde_raw(ruta_mp3: str) -> str:
    """Si existe un archivo .raw generado por AudioFileWriter, lo convierte a .mp3 para almacenamiento y Gemini."""
    ruta_raw = ruta_mp3.rsplit(".", 1)[0] + ".raw"
    if os.path.exists(ruta_raw) and os.path.getsize(ruta_raw) > 5000:
        fbin = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [
            fbin, "-y",
            "-f", "s16le",
            "-ar", "48000",
            "-ac", "2",
            "-i", ruta_raw,
            "-codec:a", "libmp3lame",
            "-b:a", "128k",
            ruta_mp3
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            if res.returncode == 0 and os.path.exists(ruta_mp3) and os.path.getsize(ruta_mp3) > 1000:
                print(f"Grabación convertida exitosamente de RAW a MP3: {ruta_mp3}")
                return ruta_mp3
        except Exception as e:
            print("Nota convirtiendo RAW a MP3:", e)
    return ruta_mp3


def generar_imagen_podio(fecha_str: str, duracion_min: int, total_personas: int, hubo_meditacion: bool, top_puntuales: list, ruta_salida: str = os.path.join(CARPETA_ASISTENCIAS, "podio_hoy.png")) -> str | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
        dir_salida = os.path.dirname(ruta_salida)
        if dir_salida:
            os.makedirs(dir_salida, exist_ok=True)
        width, height = 1080, 1190
        img = Image.new("RGB", (width, height), color=(15, 23, 42))
        draw = ImageDraw.Draw(img)

        # Cargar fuentes compatibles
        font_title = font_sub = font_stats = font_badge = font_name = font_info = font_footer = None
        for font_candidate in ["segoeuib.ttf", "arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"]:
            try:
                font_title = ImageFont.truetype(font_candidate, 36)
                font_sub = ImageFont.truetype(font_candidate, 22)
                font_stats = ImageFont.truetype(font_candidate, 20)
                font_badge = ImageFont.truetype(font_candidate, 28)
                font_name = ImageFont.truetype(font_candidate, 24)
                font_info = ImageFont.truetype(font_candidate, 18)
                font_footer = ImageFont.truetype(font_candidate, 18)
                break
            except Exception:
                continue
        if not font_title:
            font_title = font_sub = font_stats = font_badge = font_name = font_info = font_footer = ImageFont.load_default()

        # Header Box
        draw.rounded_rectangle([(40, 35), (1040, 165)], radius=20, fill=(30, 27, 75), outline=(79, 70, 229), width=2)
        draw.text((70, 55), "PODIO DE PUNTUALIDAD (TOP 9)", fill=(251, 191, 36), font=font_title)
        draw.text((70, 115), f"Fecha: {fecha_str} | Apertura: 7:56 PM • Comunidad", fill=(199, 210, 254), font=font_sub)

        # Stats Summary Box
        draw.rounded_rectangle([(40, 185), (1040, 255)], radius=15, fill=(30, 41, 59), outline=(51, 65, 85), width=2)
        med_txt = "Sí (+30 pts)" if hubo_meditacion else "No"
        stats_line = f"Duracion: {duracion_min} min   |   Asistentes: {total_personas} personas   |   Meditacion: {med_txt}"
        draw.text((70, 210), stats_line, fill=(241, 245, 249), font=font_stats)

        colors_top3 = [
            ((69, 26, 3), (245, 158, 11), (245, 158, 11), (15, 23, 42), "#1", (254, 243, 199)),
            ((30, 41, 59), (148, 163, 184), (148, 163, 184), (15, 23, 42), "#2", (241, 245, 249)),
            ((67, 20, 7), (217, 119, 6), (217, 119, 6), (15, 23, 42), "#3", (255, 237, 213)),
        ]

        y_start = 275
        row_h = 82
        row_gap = 10

        for i in range(9):
            top_y = y_start + i * (row_h + row_gap)
            bot_y = top_y + row_h
            if i < 3:
                bg, border, badge_bg, badge_txt, badge_label, info_color = colors_top3[i]
            else:
                bg = (24, 32, 47)
                border = (51, 65, 85)
                badge_bg = (30, 41, 59)
                badge_txt = (203, 213, 225)
                badge_label = f"#{i+1}"
                info_color = (148, 163, 184)

            draw.rounded_rectangle([(40, top_y), (1040, bot_y)], radius=16, fill=bg, outline=border, width=2)
            draw.rounded_rectangle([(55, top_y + 14), (160, bot_y - 14)], radius=10, fill=badge_bg)
            draw.text((85 if len(badge_label) == 2 else 75, top_y + 22), badge_label, fill=badge_txt, font=font_badge)

            if i < len(top_puntuales):
                p = top_puntuales[i]
                nombre = str(p.get("nombre", "Participante"))[:30]
                hora_str = ""
                pe = p.get("primera_entrada")
                if hasattr(pe, "strftime"):
                    hora_str = pe.strftime("%I:%M:%S %p")
                elif pe:
                    hora_str = str(pe)

                rango_str = str(p.get("rango", "Bronce")).split()[-1]
                pts = p.get("pts_hoy", 0)

                draw.text((185, top_y + 15), nombre, fill=(255, 255, 255), font=font_name)
                detalles = f"Entrada: {hora_str}"
                if pts:
                    detalles += f"   •   +{pts} pts hoy"
                if rango_str:
                    detalles += f"   •   Rango: {rango_str}"
                draw.text((185, top_y + 48), detalles, fill=info_color, font=font_info)
            else:
                draw.text((185, top_y + 26), "Lugar Disponible (Únete a las 7:56 PM)", fill=(100, 116, 139), font=font_name)

        draw.text((280, 1125), "¡Nos vemos mañana a las 7:56 PM! • Bot Oficial de Asistencia", fill=(148, 163, 184), font=font_footer)
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


def generar_texto_miperfil(user_id: int, db_puntos: dict, user_nombre: str = "", username: str = "", es_admin: bool = False) -> str:
    if es_admin:
        nombre = user_nombre or "Administrador"
        return (
            f"👑 **PERFIL DE MODERACIÓN: {nombre}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ **Rol:** Administrador / Moderador de la Sala\n\n"
            "ℹ️ *Los administradores y moderadores están exentos del sistema de puntos y no participan en los rankings ni podios de puntualidad, garantizando una competencia justa y transparente para toda la comunidad.*"
        )

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


def generar_texto_ranking(db_puntos: dict, admin_ids: set = None) -> str:
    usuarios = db_puntos.get("usuarios", {})
    if not usuarios:
        return "🏆 **Ranking Mensual:** Aún no hay registros de asistencia este mes."

    if admin_ids:
        usuarios_filtrados = [u for u in usuarios.values() if int(u.get("id", 0)) not in admin_ids]
    else:
        usuarios_filtrados = list(usuarios.values())

    if not usuarios_filtrados:
        return "🏆 **Ranking Mensual:** Aún no hay registros de participantes de la comunidad este mes."

    top = sorted(usuarios_filtrados, key=lambda x: x.get("puntos_mes", x.get("puntos_totales", 0)), reverse=True)[:10]
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
        "• 🛡️ *Puntualidad de Hierro:* 5 días seguidos en el podio (Top 9 de puntualidad).\n"
        "• 🎙️ *Voz de la Comunidad:* Hablar en 7 llamadas consecutivas.\n"
        "• 🧘 *Mente Serena:* Completar 10 meditaciones en el mes.\n"
        "• 👑 *Centinela:* Asistir a más del 90% de las reuniones del mes.\n\n"
        "👑 **ADMINISTRADORES Y MODERADORES:**\n"
        "• Los administradores y moderadores están exentos del sistema de puntos y no participan en rankings ni podios, garantizando una competencia comunitaria justa.\n\n"
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


def plural_personas(n: int) -> str:
    return f"{n} persona" if n == 1 else f"{n} personas"


async def obtener_todos_participantes_llamada(client, input_call) -> tuple[list, dict, dict]:
    """
    Obtiene TODOS los participantes conectados a la llamada de voz en Telegram
    (tanto oradores como oyentes silenciosos) usando GetGroupParticipantsRequest con paginación.
    Retorna (lista_participantes, dict_usuarios, dict_chats).
    """
    participantes_completos = []
    users_dict = {}
    chats_dict = {}
    offset = ""
    max_paginas = 15  # Hasta 1500 participantes

    for _ in range(max_paginas):
        try:
            res = await client(GetGroupParticipantsRequest(
                call=input_call,
                ids=[],
                sources=[],
                offset=offset,
                limit=100
            ))
            if not res or not getattr(res, "participants", None):
                break
            for p in res.participants:
                participantes_completos.append(p)
            for u in getattr(res, "users", []):
                users_dict[u.id] = u
            for c in getattr(res, "chats", []):
                chats_dict[c.id] = c
            next_off = getattr(res, "next_offset", "")
            if not next_off or next_off == offset:
                break
            offset = next_off
        except Exception as e:
            print("Nota obteniendo participantes con GetGroupParticipantsRequest:", e)
            break

    return participantes_completos, users_dict, chats_dict


def guardar_cola_hoy(cola: list[dict], fecha_destino: str = None) -> None:
    """Guarda la lista de reproducción del día en cola_hoy.json y meta_hoy.json."""
    try:
        os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
        tz_col = ZoneInfo("America/Bogota")
        fecha = fecha_destino or datetime.now(tz_col).strftime("%d/%m/%Y")
        payload = {
            "fecha": fecha,
            "cola": cola
        }
        ruta_cola = os.path.join(CARPETA_MEDITACIONES, "cola_hoy.json")
        with open(ruta_cola, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        if cola:
            ruta_meta = os.path.join(CARPETA_MEDITACIONES, "meta_hoy.json")
            info_meta = dict(cola[0].get("info") or {})
            info_meta["fecha_tarea_admin"] = fecha
            if len(cola) > 1:
                info_meta["cola_audios"] = [c.get("info") for c in cola if c.get("info")]
            with open(ruta_meta, "w", encoding="utf-8") as fm:
                json.dump(info_meta, fm, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando cola_hoy.json:", e)


def guardar_cola_manana(cola: list[dict], fecha_destino: str = None) -> None:
    """Guarda la lista de reproducción programada para mañana en cola_manana.json y meta_manana.json."""
    try:
        os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
        tz_col = ZoneInfo("America/Bogota")
        fecha = fecha_destino or (datetime.now(tz_col) + timedelta(days=1)).strftime("%d/%m/%Y")
        payload = {
            "fecha": fecha,
            "cola": cola
        }
        ruta_manana = os.path.join(CARPETA_MEDITACIONES, "cola_manana.json")
        with open(ruta_manana, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        if cola:
            ruta_meta_manana = os.path.join(CARPETA_MEDITACIONES, "meta_manana.json")
            info_meta = dict(cola[0].get("info") or {})
            info_meta["fecha_tarea_admin"] = fecha
            if len(cola) > 1:
                info_meta["cola_audios"] = [c.get("info") for c in cola if c.get("info")]
            with open(ruta_meta_manana, "w", encoding="utf-8") as fm:
                json.dump(info_meta, fm, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando cola_manana.json:", e)


def cargar_cola_hoy() -> list[dict]:
    """Carga y valida los audios previamente guardados en cola_hoy.json o promociona cola_manana.json si corresponde a hoy."""
    try:
        tz_col = ZoneInfo("America/Bogota")
        hoy_str = datetime.now(tz_col).strftime("%d/%m/%Y")

        # 1. Si existe cola_manana.json y su fecha coincide con HOY, promocionarla a la lista de hoy
        ruta_manana = os.path.join(CARPETA_MEDITACIONES, "cola_manana.json")
        if os.path.exists(ruta_manana):
            try:
                with open(ruta_manana, "r", encoding="utf-8") as fm:
                    d_manana = json.load(fm)
                fecha_m = d_manana.get("fecha") if isinstance(d_manana, dict) else None
                lista_m = d_manana.get("cola", []) if isinstance(d_manana, dict) else (d_manana if isinstance(d_manana, list) else [])
                if fecha_m == hoy_str and lista_m:
                    validos_m = [
                        d for d in lista_m
                        if isinstance(d, dict) and d.get("ruta")
                        and os.path.exists(d["ruta"]) and os.path.getsize(d["ruta"]) > 5000
                    ]
                    if validos_m:
                        print(f"Promocionando {len(validos_m)} audios de cola_manana.json a la lista oficial de hoy ({hoy_str}).")
                        guardar_cola_hoy(validos_m, fecha_destino=hoy_str)
                        try:
                            os.remove(ruta_manana)
                        except Exception:
                            pass
                        return validos_m
            except Exception as em:
                print("Nota procesando cola_manana.json:", em)

        # 2. Revisar cola_hoy.json
        ruta_cola = os.path.join(CARPETA_MEDITACIONES, "cola_hoy.json")
        if os.path.exists(ruta_cola):
            with open(ruta_cola, "r", encoding="utf-8") as f:
                datos = json.load(f)
            if isinstance(datos, dict):
                fecha_guardada = datos.get("fecha")
                if fecha_guardada == hoy_str:
                    lista = datos.get("cola", [])
                    validos = [
                        d for d in lista
                        if isinstance(d, dict) and d.get("ruta")
                        and os.path.exists(d["ruta"]) and os.path.getsize(d["ruta"]) > 5000
                    ]
                    if validos:
                        return validos
            elif isinstance(datos, list):
                # Compatibilidad hacia atrás: verificar si fue modificado en la fecha de hoy
                mtime = os.path.getmtime(ruta_cola)
                dt_mod = datetime.fromtimestamp(mtime, tz_col)
                if dt_mod.strftime("%d/%m/%Y") == hoy_str:
                    validos = [
                        d for d in datos
                        if isinstance(d, dict) and d.get("ruta")
                        and os.path.exists(d["ruta"]) and os.path.getsize(d["ruta"]) > 5000
                    ]
                    if validos:
                        return validos
    except Exception as e:
        print("Nota cargando cola_hoy.json:", e)
    return []


async def buscar_audio_meditacion(client, entidad, admin_ids) -> tuple[str | None, dict | None, list[dict]]:
    """
    Busca uno o varios audios de la tarea de hoy:
    1. En cola_hoy.json si ya fue programada (o promociona cola_manana.json si fue para hoy).
    2. En los últimos 60 mensajes del grupo (audios adjuntos subidos por administradores para hoy).
    3. Si no hay archivo adjunto pero hay anuncio de tarea en texto, descarga los audios de Google Drive para hoy.
    Retorna (ruta_primera, info_primera, lista_cola_completa).
    """
    try:
        os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
        tz_col = ZoneInfo("America/Bogota")
        hoy_str = datetime.now(tz_col).strftime("%d/%m/%Y")
        manana_str = (datetime.now(tz_col) + timedelta(days=1)).strftime("%d/%m/%Y")

        # 1. Revisar si ya existe cola_hoy.json guardada previamente para hoy
        cola_guardada = cargar_cola_hoy()
        if cola_guardada:
            primera = cola_guardada[0]
            return primera["ruta"], primera.get("info"), cola_guardada

        # 2. Escanear los últimos 60 mensajes del chat
        mensajes_audio_hoy = []
        textos_anuncio_hoy = []

        async for msg in client.iter_messages(entidad, limit=60):
            texto = (msg.raw_text or "").upper()
            sender_id = msg.sender_id
            es_de_admin = (sender_id in admin_ids) or bool(getattr(msg, "post", False))
            es_anuncio_tarea = any(k in texto for k in ["TAREA DEL DÍA", "TAREA DEL DIA", "MEDITACION #", "MEDITACIÓN #", "MENSAJE #", "MEDITACION DE TAREA", "MEDITACIÓN DE TAREA", "TAREA PARA HOY", "TAREA PARA"])

            if not (es_de_admin or es_anuncio_tarea):
                continue

            # Evaluar la fecha para la cual fue anunciado este mensaje
            fecha_msg_tar = extraer_fecha_de_texto(msg.raw_text or "", fecha_referencia=msg.date)
            if not fecha_msg_tar and msg.date:
                dt_msg = msg.date.astimezone(tz_col) if msg.date.tzinfo else msg.date.replace(tzinfo=tz_col)
                if dt_msg.hour > 20 or (dt_msg.hour == 20 and dt_msg.minute >= 32):
                    fecha_msg_tar = (dt_msg + timedelta(days=1)).strftime("%d/%m/%Y")
                else:
                    fecha_msg_tar = dt_msg.strftime("%d/%m/%Y")

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

            # Clasificar si el mensaje coincide con la fecha de HOY
            if fecha_msg_tar == hoy_str:
                if es_audio:
                    mensajes_audio_hoy.append((target_msg, nombre_archivo, msg.raw_text or ""))
                elif any(k in texto for k in ["MEDITACION", "MEDITACIÓN", "TAREA", "MENSAJE"]):
                    textos_anuncio_hoy.append(msg.raw_text or "")

        # Caso A: Se encontraron archivos de audio físicos en Telegram para HOY
        if mensajes_audio_hoy:
            cola_descargada = []
            mensajes_audio_hoy.reverse()  # Orden cronológico
            for idx, (m_audio, f_name, txt_m) in enumerate(mensajes_audio_hoy):
                nombre_base = "meditacion_hoy.mp3" if len(mensajes_audio_hoy) == 1 else f"meditacion_hoy_{idx+1}.mp3"
                ruta = os.path.join(CARPETA_MEDITACIONES, nombre_base)
                print(f"Descargando audio {idx+1}/{len(mensajes_audio_hoy)} desde mensaje ID {m_audio.id}...")
                await client.download_media(m_audio, file=ruta)
                info_cat = identificar_audio_catalogo(txt_m, f_name)
                cola_descargada.append({
                    "ruta": ruta,
                    "info": info_cat,
                    "titulo": (info_cat or {}).get("titulo") or f_name or f"Audio #{idx+1}"
                })

            if cola_descargada:
                guardar_cola_hoy(cola_descargada, fecha_destino=hoy_str)
                primera = cola_descargada[0]
                return primera["ruta"], primera.get("info"), cola_descargada

        # Caso B: Anuncio en texto correspondiente a HOY -> Buscar en Google Drive
        for txt_anuncio in textos_anuncio_hoy:
            items_detectados = identificar_todos_los_audios(txt_anuncio)
            if items_detectados:
                cola_drive = []
                for it in items_detectados:
                    t = it.get("tipo", "MEDITACION")
                    try:
                        n = int(it.get("numero"))
                    except (ValueError, TypeError):
                        n = None
                    if n:
                        print(f"Buscando audio de {t} #{n} en Google Drive (para hoy {hoy_str})...")
                        r_drive = obtener_o_descargar_audio(t, n)
                        if r_drive and os.path.exists(r_drive) and os.path.getsize(r_drive) > 5000:
                            cola_drive.append({
                                "ruta": r_drive,
                                "info": it,
                                "titulo": it.get("titulo", f"{t} #{n}")
                            })
                if cola_drive:
                    guardar_cola_hoy(cola_drive, fecha_destino=hoy_str)
                    primera = cola_drive[0]
                    return primera["ruta"], primera.get("info"), cola_drive

        # Caso C: Respaldo de meta_hoy.json si existía y coincide con la fecha
        ruta_meta = os.path.join(CARPETA_MEDITACIONES, "meta_hoy.json")
        if os.path.exists(ruta_meta):
            try:
                with open(ruta_meta, "r", encoding="utf-8") as fm:
                    meta = json.load(fm)
                f_meta = meta.get("fecha_tarea_admin")
                if not f_meta or f_meta == hoy_str:
                    if meta.get("numero") and meta.get("tipo"):
                        t = meta["tipo"]
                        n = int(meta["numero"])
                        r_drive = obtener_o_descargar_audio(t, n)
                        if r_drive and os.path.exists(r_drive):
                            item_c = {"ruta": r_drive, "info": meta, "titulo": meta.get("titulo", f"{t} #{n}")}
                            guardar_cola_hoy([item_c], fecha_destino=hoy_str)
                            return r_drive, meta, [item_c]
            except Exception:
                pass

    except Exception as e:
        print("Nota buscando audio de meditación:", e)

    return None, None, []


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
            try:
                from telethon.utils import get_peer_id
                admin_ids.add(get_peer_id(entidad))
            except Exception:
                pass
            try:
                admin_ids.add(int(f"-100{entidad.id}"))
                admin_ids.add(-int(entidad.id))
            except Exception:
                pass
        admin_ids.add(1087968824)  # @GroupAnonymousBot (modo anónimo)

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
        avisar_con_bot(AVISO, boton_url=url_llamada, es_efimero=True)

        if not full_chat or not full_chat.call:
            print("No hay llamada disponible para monitorear.")
            return

        input_call = full_chat.call
        print(f"Iniciando monitoreo de la sala (Máx: {DURACION_MAXIMA_MINUTOS} min)...")

        # Estado del sistema de moderación de voz y turnos
        participantes = {}
        participantes_conectados = set()  # uids actualmente conectados a la sala
        users_cache = {}  # uid -> User
        chats_cache = {}  # cid -> Chat / Channel
        cola_turnos = []  # [{"id": uid, "nombre": nom, "username": usr}]
        oradores_activos = set()  # uids actualmente hablando
        segundos_inactividad_mic = {}  # uid -> segundos con mic abierto y sin voz
        avisados_auto_mute = set()  # uids notificados cordialmente
        msg_turnos = None  # Mensaje en vivo con la cola de turnos
        lock_turnos = asyncio.Lock()
        mensajes_chat_recientes = 0
        ultimo_envio_turnos = 0
        bloqueo_flood_hasta = 0.0
        ultimo_texto_turnos = None
        INTERVALO_MIN_REPUBLICAR = 90  # segundos mínimos entre republicaciones al fondo

        async def actualizar_mensaje_turnos(forzar_al_fondo: bool = False):
            nonlocal msg_turnos, mensajes_chat_recientes, ultimo_envio_turnos, bloqueo_flood_hasta, ultimo_texto_turnos
            async with lock_turnos:
                nombres_oradores = [
                    participantes[u]["nombre"] if u in participantes else f"ID {u}"
                    for u in oradores_activos
                ]
                txt = generar_texto_turnos(cola_turnos, nombres_oradores)
                ahora = time.time()

                # Anti-spam: respetar FloodWait de Telegram y no repetir texto idéntico
                if ahora < bloqueo_flood_hasta:
                    return
                if msg_turnos and txt == ultimo_texto_turnos:
                    return
                ultimo_texto_turnos = txt

                puede_republicar = (ahora - ultimo_envio_turnos) >= INTERVALO_MIN_REPUBLICAR
                if not msg_turnos or ((forzar_al_fondo or mensajes_chat_recientes >= 5) and puede_republicar):
                    if msg_turnos:
                        try:
                            await client.delete_messages(entidad, msg_turnos)
                            ids_mensajes_efimeros.discard(getattr(msg_turnos, "id", None))
                        except Exception:
                            pass
                    try:
                        msg_turnos = await client.send_message(entidad, txt)
                        if msg_turnos and hasattr(msg_turnos, "id"):
                            ids_mensajes_efimeros.add(msg_turnos.id)
                        ultimo_envio_turnos = ahora
                        mensajes_chat_recientes = 0
                    except Exception as e:
                        segs = getattr(e, "seconds", None)
                        if segs:
                            bloqueo_flood_hasta = time.time() + int(segs) + 5
                        ultimo_texto_turnos = None
                        print("Nota publicando mensaje de turnos al fondo:", e)
                else:
                    try:
                        await client.edit_message(entidad, msg_turnos, txt)
                    except Exception as e:
                        segs = getattr(e, "seconds", None)
                        if segs:
                            bloqueo_flood_hasta = time.time() + int(segs) + 5
                            ultimo_texto_turnos = None
                        elif "not modified" in str(e).lower():
                            pass
                        elif puede_republicar:
                            try:
                                msg_turnos = await client.send_message(entidad, txt)
                                if msg_turnos and hasattr(msg_turnos, "id"):
                                    ids_mensajes_efimeros.add(msg_turnos.id)
                                ultimo_envio_turnos = ahora
                                mensajes_chat_recientes = 0
                            except Exception as e2:
                                print("Nota reenviando mensaje de turnos:", e2)

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
            if msg_fijado and hasattr(msg_fijado, "id"):
                ids_mensajes_efimeros.add(msg_fijado.id)
            await client.pin_message(entidad, msg_fijado, notify=False)
            print("Mensaje de estado fijado dinámicamente en el grupo.")
        except Exception as e:
            print("Nota fijando mensaje de estado:", e)

        # Publicar mensaje de lista de turnos en vivo en el grupo
        try:
            msg_turnos = await client.send_message(entidad, generar_texto_turnos(cola_turnos, []))
            if msg_turnos and hasattr(msg_turnos, "id"):
                ids_mensajes_efimeros.add(msg_turnos.id)
            print("Mensaje de turnos en vivo publicado en el grupo.")
        except Exception as e:
            print("Nota publicando mensaje de turnos:", e)

        # Rutas y control para grabación selectiva de voz (excluyendo meditación)
        os.makedirs(CARPETA_ASISTENCIAS, exist_ok=True)
        ruta_grabacion_pre = os.path.join(CARPETA_ASISTENCIAS, f"grabacion_pre_{fecha_hoy}.mp3")
        ruta_grabacion_post = os.path.join(CARPETA_ASISTENCIAS, f"grabacion_post_{fecha_hoy}.mp3")
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
            nueva_ruta = os.path.join(CARPETA_ASISTENCIAS, f"grabacion_seg_{contador_segmentos}_{fecha_hoy}.mp3")
            segmentos_grabados.append(nueva_ruta)
            if tgcalls:
                try:
                    nueva_ruta_raw = nueva_ruta.rsplit(".", 1)[0] + ".raw"
                    stream_rec = Stream(
                        speaker=AudioStream(
                            media_source=MediaSource.FILE,
                            path=os.path.abspath(nueva_ruta_raw),
                            parameters=AudioParameters(48000, 2)
                        )
                    )
                    await tgcalls.record(destino, stream_rec)
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
                    s_raw = s.rsplit(".", 1)[0] + ".raw"
                    if os.path.exists(s_raw):
                        os.remove(s_raw)
                except Exception:
                    pass
            for f_tmp in (ruta_grabacion_pre, ruta_grabacion_post, ruta_grabacion_completa):
                try:
                    if os.path.exists(f_tmp):
                        os.remove(f_tmp)
                    f_raw = f_tmp.rsplit(".", 1)[0] + ".raw"
                    if os.path.exists(f_raw):
                        os.remove(f_raw)
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

                # Inyectar input_call en el caché de PyTgCalls de inmediato
                try:
                    resolved_id = await tgcalls.resolve_chat_id(destino)
                    if hasattr(tgcalls, "_app") and hasattr(tgcalls._app, "_bind_client") and hasattr(tgcalls._app._bind_client, "_cache"):
                        tgcalls._app._bind_client._cache.set_cache(resolved_id, input_call)
                        print(f"input_call registrado en caché de PyTgCalls para {resolved_id}.")
                except Exception as e_c:
                    print("Nota registrando input_call en PyTgCalls:", e_c)

                # Iniciar grabación del segmento previo a la meditación usando AudioFileWriter nativo (.raw)
                try:
                    ruta_grab_raw = ruta_grabacion_pre.rsplit(".", 1)[0] + ".raw"
                    stream_rec = Stream(
                        speaker=AudioStream(
                            media_source=MediaSource.FILE,
                            path=os.path.abspath(ruta_grab_raw),
                            parameters=AudioParameters(48000, 2)
                        )
                    )
                    await tgcalls.record(destino, stream_rec)
                    print("Grabación de bienvenida y charla inicial iniciada.")
                except Exception as e:
                    print("Nota iniciando grabación inicial PyTgCalls:", e)
            except Exception as e:
                print("Nota iniciando PyTgCalls:", e)

        # Buscar si ya existe un audio o cola de meditación subida hoy por administradores
        ruta_meditacion, info_catalogo_hoy, cola_reproduccion = await buscar_audio_meditacion(client, entidad, admin_ids)
        indice_pista_actual = 0
        reproduciendo_meditacion = False
        reproduccion_iniciada = False
        aviso_oracion_enviado = False
        aviso_espera_enviado = False
        aviso_meditacion_enviado = False
        alerta_falta_audio_enviada = False
        meditacion_activa_hoy = False
        oracion_activa_hoy = False

        # ---------------- Ecualizador automático de voz (mejorar_audio.py) ----------------
        eq_estado = {
            "manual": None,      # AjusteEQ elegido por un admin con /eq (None = automático)
            "auto": None,        # AjusteEQ calculado por el análisis del audio
            "offset": 0.0,       # segundo del audio con el que arrancó el stream actual
            "t_play": None,
            "t_pausa": None,
            "seg_pausa": 0.0,
            "cambiando": False,  # True mientras se cambia de stream (evita falso "StreamEnded")
        }
        lock_eq = asyncio.Lock()
        DURACION_GONG_SEG = 3.5  # la campana inicial que añade agregar_gongs_al_audio

        def eq_efectivo():
            if not MEJORA_AUDIO:
                return None
            return eq_estado["manual"] or eq_estado["auto"]

        def iniciar_seguimiento_posicion(offset: float):
            eq_estado.update(offset=offset, t_play=time.monotonic(), t_pausa=None, seg_pausa=0.0)

        def marcar_pausa():
            if eq_estado["t_play"] and eq_estado["t_pausa"] is None:
                eq_estado["t_pausa"] = time.monotonic()

        def marcar_reanudacion():
            if eq_estado["t_pausa"] is not None:
                eq_estado["seg_pausa"] += time.monotonic() - eq_estado["t_pausa"]
                eq_estado["t_pausa"] = None

        def posicion_actual() -> float:
            if not eq_estado["t_play"]:
                return 0.0
            ref = eq_estado["t_pausa"] or time.monotonic()
            return max(0.0, eq_estado["offset"] + ref - eq_estado["t_play"] - eq_estado["seg_pausa"])

        async def preparar_audio_eq(ruta_especifica: str | None = None) -> str:
            """Devuelve el audio ya mejorado (con caché) o el original si algo falla."""
            if not MEJORA_AUDIO:
                return ruta_especifica or (ruta_meditacion or "")

            if ruta_especifica is None:
                # Pre-procesa todas las pistas de la cola en segundo plano
                rutas_a_preparar = [p["ruta"] for p in cola_reproduccion if p.get("ruta") and os.path.exists(p["ruta"])]
                if not rutas_a_preparar and ruta_meditacion:
                    rutas_a_preparar = [ruta_meditacion]
                for r in rutas_a_preparar:
                    async with lock_eq:
                        try:
                            if eq_estado["manual"] is None and eq_estado["auto"] is None:
                                eq_estado["auto"] = await analizar_audio_async(r)
                            await mejorar_audio_async(r, eq_efectivo())
                        except Exception as e:
                            print(f"Nota pre-procesando {r}:", e)
                return cola_reproduccion[0]["ruta"] if cola_reproduccion else (ruta_meditacion or "")

            if not os.path.exists(ruta_especifica):
                return ruta_especifica
            async with lock_eq:
                try:
                    if eq_estado["manual"] is None and eq_estado["auto"] is None:
                        eq_estado["auto"] = await analizar_audio_async(ruta_especifica)
                    return await mejorar_audio_async(ruta_especifica, eq_efectivo())
                except Exception as e:
                    print(f"Nota preparando audio mejorado ({ruta_especifica}):", e)
                    return ruta_especifica

        async def aplicar_eq_en_vivo() -> str:
            """Re-procesa con los niveles actuales y cambia el stream desde el mismo segundo."""
            if not (MEJORA_AUDIO and tgcalls and reproduciendo_meditacion and ruta_meditacion):
                return "guardado"
            async with lock_eq:
                try:
                    nuevo = await mejorar_audio_async(ruta_meditacion, eq_efectivo())
                    if nuevo == ruta_meditacion:
                        return "error"
                    pos = posicion_actual()  # se calcula DESPUÉS del render para no perder continuidad
                    en_pausa = eq_estado["t_pausa"] is not None
                    destino_resto = os.path.join(CARPETA_MEDITACIONES, "meditacion_eq_resto.mp3")
                    ruta_resto = await recortar_desde_async(nuevo, pos, destino_resto)
                    if ruta_resto == nuevo and pos > 1:
                        return "error"
                    eq_estado["cambiando"] = True
                    try:
                        ruta_resto_pcm = await asyncio.to_thread(convertir_audio_a_pcm, ruta_resto)
                        if ruta_resto_pcm.endswith(".raw") and os.path.exists(ruta_resto_pcm):
                            stream_eq = Stream(
                                microphone=AudioStream(
                                    media_source=MediaSource.FILE,
                                    path=os.path.abspath(ruta_resto_pcm),
                                    parameters=AudioParameters(48000, 2)
                                )
                            )
                            await tgcalls.play(destino, stream_eq)
                        else:
                            await tgcalls.play(destino, ruta_resto)
                        iniciar_seguimiento_posicion(pos)
                        if en_pausa:
                            await tgcalls.pause(destino)
                            marcar_pausa()
                        await asyncio.sleep(3)
                    finally:
                        eq_estado["cambiando"] = False
                    return "ok"
                except Exception as e:
                    print("Error aplicando ecualizador en vivo:", e)
                    return "error"

        if MEJORA_AUDIO and (cola_reproduccion or ruta_meditacion):
            # Pre-procesa en segundo plano para que los audios estén listos a la hora de reproducir
            asyncio.create_task(preparar_audio_eq())

        ultimo_error_reproduccion = ""

        async def reproducir_meditacion(pista_idx: int = 0):
            nonlocal reproduciendo_meditacion, meditacion_activa_hoy, indice_pista_actual, ruta_meditacion, info_catalogo_hoy, ultimo_error_reproduccion
            ultimo_error_reproduccion = ""
            if not tgcalls:
                ultimo_error_reproduccion = "Servicio PyTgCalls no disponible"
                return False

            if not cola_reproduccion and ruta_meditacion and os.path.exists(ruta_meditacion):
                cola_reproduccion.append({
                    "ruta": ruta_meditacion,
                    "info": info_catalogo_hoy,
                    "titulo": (info_catalogo_hoy or {}).get("titulo", "Meditación")
                })

            if not cola_reproduccion:
                ultimo_error_reproduccion = "Cola de reproducción vacía"
                return False

            if pista_idx >= len(cola_reproduccion):
                ultimo_error_reproduccion = f"Índice de pista fuera de rango ({pista_idx} >= {len(cola_reproduccion)})"
                return False

            indice_pista_actual = pista_idx
            pista_actual = cola_reproduccion[indice_pista_actual]
            ruta_pista = pista_actual.get("ruta")
            if not ruta_pista or not os.path.exists(ruta_pista):
                ultimo_error_reproduccion = f"Archivo de audio no encontrado: {ruta_pista}"
                return False

            ruta_meditacion = ruta_pista
            info_catalogo_hoy = pista_actual.get("info")

            try:
                # 1. Si PyTgCalls estaba conectado en modo escucha/grabación, cerrar la sesión previa para renegociar con Telegram en modo emisión (sendrecv)
                try:
                    await tgcalls.leave_call(destino)
                    await asyncio.sleep(1.0)
                    print("Sesión de escucha previa liberada para reiniciar en modo emisión oficial.")
                except Exception:
                    pass

                # 2. Desactivar temporalmente join_muted para que el robot ingrese con micrófono activo
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
                except Exception:
                    pass

                # 3. Incorporar campanas tibetanas / gong zen al inicio y final
                ruta_base_audio = await preparar_audio_eq(ruta_pista)
                ruta_a_reproducir = await asyncio.to_thread(agregar_gongs_al_audio, ruta_base_audio)

                # Asegurar registro de input_call en PyTgCalls
                try:
                    resolved_id = await tgcalls.resolve_chat_id(destino)
                    if hasattr(tgcalls, "_app") and hasattr(tgcalls._app, "_bind_client") and hasattr(tgcalls._app._bind_client, "_cache"):
                        tgcalls._app._bind_client._cache.set_cache(resolved_id, input_call)
                except Exception:
                    pass

                # 4. Conectar reproducción de audio con canal de micrófono activo
                from pytgcalls.types import MediaStream, AudioQuality
                try:
                    stream_play = MediaStream(
                        ruta_a_reproducir,
                        audio_parameters=AudioQuality.HIGH,
                    )
                    await tgcalls.play(destino, stream_play)
                    print(f"Emisión de audio iniciada con MediaStream: {ruta_a_reproducir}")
                except Exception as e_ms:
                    print("Nota reproduciendo con MediaStream, usando fallback:", e_ms)
                    await tgcalls.play(destino, ruta_a_reproducir)

                await asyncio.sleep(1.0)

                # 5. Desmutear PyTgCalls a nivel WebRTC y maximizar volumen de emisión
                try:
                    await tgcalls.unmute(destino)
                except Exception:
                    pass
                try:
                    await tgcalls.resume(destino)
                except Exception:
                    pass
                try:
                    await tgcalls.change_volume_call(destino, 200)
                except Exception:
                    pass

                # 6. Activar silencio para nuevos participantes regulares (evitar ruidos de fondo durante la meditación)
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=True))
                except Exception:
                    pass

                # 7. Garantizar micrófono activo para el robot en Telegram
                try:
                    me_user = await client.get_me()
                    me_peer = await client.get_input_entity(me_user)
                    await client(EditGroupCallParticipantRequest(call=input_call, participant=me_peer, muted=False, volume=20000))
                    print("Micrófono del robot confirmado activo en Telegram.")
                except Exception as e_me:
                    print("Nota desmuteando robot en Telegram:", e_me)

                # 8. Garantizar explícitamente que TODOS los administradores tengan el micrófono desbloqueado (NUNCA silenciados)
                for aid in admin_ids:
                    try:
                        admin_peer = await client.get_input_entity(aid)
                        await client(EditGroupCallParticipantRequest(call=input_call, participant=admin_peer, muted=False))
                    except Exception:
                        pass
                print("Todos los administradores confirmados con permiso de voz libre y desbloqueado.")
                iniciar_seguimiento_posicion(-DURACION_GONG_SEG)
                reproduciendo_meditacion = True
                meditacion_activa_hoy = True

                total_pistas = len(cola_reproduccion)
                info_act = pista_actual.get("info")
                if total_pistas == 1:
                    if info_act:
                        avisar_con_bot(f"▶️ **Iniciando reproducción oficial:**\n{formatear_info_audio(info_act)}\n🧘 Por favor disfruten de su sesión en silencio.", es_efimero=True)
                    else:
                        avisar_con_bot("▶️ **Iniciando reproducción de la meditación diaria en la sala de voz.**\n🧘 Por favor disfruten de su sesión en silencio.", es_efimero=True)
                else:
                    txt_act = formatear_info_audio(info_act) if info_act else f"🧘 **Pista #{indice_pista_actual + 1}:** {pista_actual.get('titulo', 'Meditación')}"
                    avisar_con_bot(f"▶️ **Iniciando reproducción (Pista {indice_pista_actual + 1} de {total_pistas}):**\n\n{txt_act}\n\n📋 Total de pistas programadas: {total_pistas}\n🧘 Por favor disfruten de su sesión en silencio.", es_efimero=True)
                return True
            except Exception as e:
                print("Error reproduciendo meditación:", e)
                ultimo_error_reproduccion = str(e)
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
                parts_completos, _, _ = await obtener_todos_participantes_llamada(client, input_call)
                for p in parts_completos:
                    if getattr(p, "left", False):
                        continue
                    p_uid = getattr(p.peer, "user_id", None) or getattr(p.peer, "channel_id", None) or getattr(p.peer, "chat_id", None)
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
                        nonlocal reproduciendo_meditacion, indice_pista_actual
                        if reproduciendo_meditacion and not eq_estado["cambiando"]:
                            # Verificar si aún quedan más audios en la cola
                            if indice_pista_actual + 1 < len(cola_reproduccion):
                                print(f"Pista {indice_pista_actual + 1} finalizada. Pasando a pista {indice_pista_actual + 2} de {len(cola_reproduccion)}...")
                                sig_idx = indice_pista_actual + 1
                                siguiente_item = cola_reproduccion[sig_idx]
                                total_p = len(cola_reproduccion)
                                inf_sig = siguiente_item.get("info")
                                txt_sig = formatear_info_audio(inf_sig) if inf_sig else f"🧘 **Audio #{sig_idx + 1}:** {siguiente_item.get('titulo', 'Meditación')}"
                                avisar_con_bot(
                                    f"🔔 **Pista {indice_pista_actual + 1} finalizada.**\n\n▶️ **Continuando con la pista {sig_idx + 1} de {total_p}:**\n{txt_sig}\n\n🧘 Por favor continúen en silencio...",
                                    es_efimero=True
                                )
                                ok_sig = await reproducir_meditacion(sig_idx)
                                if not ok_sig:
                                    print("Error reproduciendo siguiente pista, finalizando sesión de meditación.")
                                    reproduciendo_meditacion = False
                                    await desbloquear_todos_los_participantes()
                            else:
                                reproduciendo_meditacion = False
                                print("Reproducción de la sesión de meditación concluida automáticamente.")
                                await desbloquear_todos_los_participantes()
                                avisar_con_bot("🧘✨ **La meditación ha concluido.**\nLos micrófonos han sido restablecidos. ¡Esperamos que hayan tenido una gran sesión!", es_efimero=True)
                                # Reanudar grabación para el segmento post-meditación si no fue cancelada
                                if not grabacion_cancelada and not grabacion_pausada:
                                    segmentos_grabados.append(ruta_grabacion_post)
                                    try:
                                        ruta_post_raw = ruta_grabacion_post.rsplit(".", 1)[0] + ".raw"
                                        stream_rec_post = Stream(
                                            speaker=AudioStream(
                                                media_source=MediaSource.FILE,
                                                path=os.path.abspath(ruta_post_raw),
                                                parameters=AudioParameters(48000, 2)
                                            )
                                        )
                                        await tgcalls.record(destino, stream_rec_post)
                                        print("Grabación de preguntas y testimonios reanudada tras la meditación.")
                                    except Exception as e:
                                        print("Nota reanudando grabación:", e)
            except Exception as e:
                print("Nota configurando StreamEnded handler:", e)

        # Escuchar comandos de usuarios (/puntos, /ranking, /reglas, /ayuda, /meditacion, /turno, /ceder, /turnos, /buscar, /resumen, /acta, /oracion)
        @client.on(events.NewMessage(pattern=r"^/(puntos|miperfil|ranking|top|ayuda|reglas|start|meditacion|audio|turno|pedirturno|mano|ceder|turnos|buscar|resumen|acta|oracion)"))
        async def responder_comandos_en_vivo(event):
            sender = await event.get_sender()
            if sender and getattr(sender, "bot", False):
                return
            uid = sender.id if sender else event.sender_id
            if BOT_ID and uid == BOT_ID:
                return
            partes = event.raw_text.strip().split()
            texto_cmd = partes[0].lower().split("@")[0]
            param = partes[1].lower() if len(partes) > 1 else ""
            db = cargar_puntos()
            nom = f"{getattr(sender, 'first_name', '') or ''} {getattr(sender, 'last_name', '') or ''}".strip() or "Participante"
            usr = getattr(sender, "username", "") or ""

            # Si el comando es de turnos / moderación interactiva en el grupo, marcar para limpieza temporal
            es_cmd_efimero = texto_cmd in ("/turno", "/pedirturno", "/mano", "/ceder", "/turnos", "/oracion")
            if event.is_group and es_cmd_efimero and getattr(event, "message", None) and hasattr(event.message, "id"):
                ids_mensajes_efimeros.add(event.message.id)

            async def responder(texto_resp, **kwargs):
                r = await event.reply(texto_resp, **kwargs)
                if event.is_group and es_cmd_efimero and r and hasattr(r, "id"):
                    ids_mensajes_efimeros.add(r.id)
                return r

            if texto_cmd in ("/puntos", "/miperfil"):
                resp = generar_texto_miperfil(uid, db, nom, usr, es_admin=(uid in admin_ids))
                await responder(resp)
            elif texto_cmd in ("/ranking", "/top") or (texto_cmd == "/start" and param == "ranking"):
                resp = generar_texto_ranking(db, admin_ids=admin_ids)
                await responder(resp)
            elif texto_cmd in ("/meditacion", "/audio"):
                ruta_med = os.path.join(CARPETA_MEDITACIONES, "meditacion_hoy.mp3")
                if os.path.exists(ruta_med) and os.path.getsize(ruta_med) > 0:
                    await responder("🧘 **Meditación del día:** Aquí tienes el audio para tu práctica diaria.", file=ruta_med)
                else:
                    await responder("🧘 Aún no hay un archivo de meditación disponible para hoy. Consulta más tarde.")
            elif texto_cmd in ("/turno", "/pedirturno", "/mano"):
                if uid in admin_ids:
                    await responder("👑 Como administrador puedes hablar libremente cuando gustes.")
                    return
                for idx, t in enumerate(cola_turnos, 1):
                    if t["id"] == uid:
                        await responder(f"ℹ️ Ya estás en la lista de turnos (Posición #{idx}). Te avisaremos cuando sea tu momento.")
                        await actualizar_mensaje_turnos(forzar_al_fondo=True)
                        return
                if uid in oradores_activos:
                    await responder("🎙️ ¡Ya tienes el micrófono habilitado para hablar!")
                    return
                cola_turnos.append({"id": uid, "nombre": nom, "username": usr})
                pos = len(cola_turnos)
                await responder(f"✋ **{nom}**, has sido añadido a la lista de turnos (Posición #{pos}). Te avisaremos cuando sea tu momento.")
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
                    await responder(f"🤝 **{nom}**, has cedido tu turno de palabra. ¡Muchas gracias por compartir!")
                    await actualizar_mensaje_turnos(forzar_al_fondo=True)
                else:
                    await responder("ℹ️ No estás en la lista de turnos ni tienes el micrófono activo.")
            elif texto_cmd in ("/turnos",):
                await actualizar_mensaje_turnos(forzar_al_fondo=True)
            elif texto_cmd in ("/buscar",):
                query = " ".join(partes[1:]) if len(partes) > 1 else ""
                resp = buscar_en_minutas(query)
                await responder(resp)
            elif texto_cmd in ("/resumen",):
                fecha_req = partes[1].strip() if len(partes) > 1 else None
                minuta = obtener_minuta(fecha_req)
                if minuta:
                    resp = f"📝 **MINUTA DE LA REUNIÓN ({minuta['fecha']})**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{minuta['resumen']}"
                    await responder(resp)
                else:
                    await responder(f"ℹ️ No se encontró ninguna minuta registrada para {fecha_req or 'la última fecha'}.")
            elif texto_cmd in ("/acta",):
                fecha_req = partes[1].strip() if len(partes) > 1 else None
                minuta = obtener_minuta(fecha_req)
                if minuta and minuta.get("ruta_pdf") and os.path.exists(minuta["ruta_pdf"]):
                    await responder(f"📄 **Acta Oficial de la Reunión ({minuta['fecha']}):**", file=minuta["ruta_pdf"])
                else:
                    await responder("ℹ️ No hay un documento PDF de acta disponible para esa fecha.")
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
                await responder(resp)
            else:
                resp = generar_texto_reglas()
                await responder(resp)

        # Escuchar controles de meditación, moderación de turnos y control de grabación exclusivos para administradores
        @client.on(events.NewMessage(pattern=r"^/(reproducir|play|pausar|pause|continuar|resume|detener|stop|volumen|vol|siguiente|next|saltaraudio|siguienteaudio|nextaudio|limpiarturnos|limpiarsala|limpiaravisos|hablar|desmutear|mutear|desmuteartodos|abrir|desbloquear|pausargrabacion|pausar_rec|reanudargrabacion|reanudar_rec|detenergrabacion|cancelar_rec|estadograbacion|estado_rec)"))
        async def controlar_meditacion_admin(event):
            sender = await event.get_sender()
            if sender and getattr(sender, "bot", False):
                return
            uid = sender.id if sender else event.sender_id
            if BOT_ID and uid == BOT_ID:
                return
            if event.is_group and getattr(event, "message", None) and hasattr(event.message, "id"):
                ids_mensajes_efimeros.add(event.message.id)

            async def responder_admin(texto_resp, **kwargs):
                r = await event.reply(texto_resp, **kwargs)
                if event.is_group and r and hasattr(r, "id"):
                    ids_mensajes_efimeros.add(r.id)
                return r

            if uid not in admin_ids:
                await responder_admin("⛔ Solo los administradores pueden utilizar este comando.")
                return

            partes_cmd = event.raw_text.strip().split()
            cmd = partes_cmd[0].lower().split("@")[0]
            if cmd in ("/reproducir", "/play"):
                nonlocal ruta_meditacion, info_catalogo_hoy, cola_reproduccion, indice_pista_actual
                if not cola_reproduccion and (not ruta_meditacion or not os.path.exists(ruta_meditacion)):
                    ruta_meditacion, info_catalogo_hoy, cola_reproduccion = await buscar_audio_meditacion(client, entidad, admin_ids)
                if cola_reproduccion and indice_pista_actual >= len(cola_reproduccion):
                    indice_pista_actual = 0
                if tgcalls and (cola_reproduccion or (ruta_meditacion and os.path.exists(ruta_meditacion))):
                    ok = await reproducir_meditacion(indice_pista_actual)
                    if ok:
                        await responder_admin("▶️ Reproduciendo meditación en la sala de voz...")
                    else:
                        detalle = f"\n*(Detalle: {ultimo_error_reproduccion})*" if ultimo_error_reproduccion else ""
                        await responder_admin(f"❌ Error iniciando la reproducción de la meditación.{detalle}")
                else:
                    await responder_admin("⚠️ No se encontró ningún archivo de meditación de tarea disponible.")
            elif cmd in ("/saltaraudio", "/siguienteaudio", "/nextaudio"):
                if not reproduciendo_meditacion:
                    await responder_admin("⚠️ No hay reproducción activa en este momento.")
                elif indice_pista_actual + 1 < len(cola_reproduccion):
                    await responder_admin(f"⏭️ Saltando a la pista {indice_pista_actual + 2} de {len(cola_reproduccion)}...")
                    await reproducir_meditacion(indice_pista_actual + 1)
                else:
                    if tgcalls:
                        await tgcalls.leave_call(destino)
                    reproduciendo_meditacion = False
                    await desbloquear_todos_los_participantes()
                    await responder_admin("⏹️ Era la última pista de la lista. Reproducción finalizada y micrófonos desbloqueados.")
            elif cmd in ("/pausar", "/pause"):
                if tgcalls:
                    try:
                        await tgcalls.pause(destino)
                        marcar_pausa()
                        await responder_admin("⏸️ Meditación pausada.")
                    except Exception as e:
                        await responder_admin(f"Error al pausar: {e}")
            elif cmd in ("/continuar", "/resume"):
                if tgcalls:
                    try:
                        await tgcalls.resume(destino)
                        marcar_reanudacion()
                        await responder_admin("▶️ Meditación reanudada.")
                    except Exception as e:
                        await responder_admin(f"Error al reanudar: {e}")
            elif cmd in ("/volumen", "/vol"):
                if len(partes_cmd) > 1 and partes_cmd[1].isdigit():
                    nuevo_vol = max(1, min(200, int(partes_cmd[1])))
                    if tgcalls:
                        try:
                            await tgcalls.change_volume_call(destino, nuevo_vol)
                            await responder_admin(f"🔊 Volumen ajustado a **{nuevo_vol}%**.")
                        except Exception as e:
                            await responder_admin(f"Error al ajustar volumen: {e}")
                    else:
                        await responder_admin("⚠️ El reproductor no está activo.")
                else:
                    await responder_admin("ℹ️ Uso: `/volumen 1-200` (Ejemplo: `/volumen 80`).")
            elif cmd in ("/detener", "/stop"):
                if tgcalls:
                    try:
                        await tgcalls.leave_call(destino)
                        reproduciendo_meditacion = False
                        await desbloquear_todos_los_participantes()
                        await responder_admin("⏹️ Reproducción finalizada. Micrófonos restablecidos y desbloqueados.")
                    except Exception as e:
                        await responder_admin(f"Error al detener: {e}")
            elif cmd in ("/desmuteartodos", "/abrir", "/desbloquear"):
                await desbloquear_todos_los_participantes()
                await responder_admin("🔓 **Todos los micrófonos han sido desbloqueados.**\nLos participantes ahora pueden activar su micrófono libremente cuando deseen hablar.")
                avisar_con_bot("🔓 **Micrófonos abiertos:** El candado de silencio ha sido retirado para todos los asistentes. Pueden activar su micrófono para compartir.", es_efimero=True)
            elif cmd in ("/siguiente", "/next"):
                if not cola_turnos:
                    await responder_admin("ℹ️ No hay participantes esperando en la lista de turnos.")
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
                await responder_admin(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Tu micrófono ha sido habilitado.")
                avisar_con_bot(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Por favor abre tu micrófono para compartir.", es_efimero=True)
            elif cmd in ("/limpiarturnos",):
                cola_turnos.clear()
                await actualizar_mensaje_turnos(forzar_al_fondo=True)
                await responder_admin("🧹 **Lista de turnos vaciada exitosamente.**")
            elif cmd in ("/limpiarsala", "/limpiaravisos"):
                cant = len(ids_mensajes_efimeros)
                if cant > 0:
                    a_borrar = set(ids_mensajes_efimeros)
                    ids_mensajes_efimeros.clear()
                    r_aviso = await responder_admin(f"🧹 Limpiando {cant} notificaciones y ventanas temporales de la sala...")
                    await limpiar_mensajes_temporales(client, entidad, a_borrar)
                    if r_aviso and hasattr(r_aviso, "id"):
                        ids_mensajes_efimeros.discard(r_aviso.id)
                        await asyncio.sleep(4)
                        try:
                            await client.delete_messages(entidad, [r_aviso.id])
                        except Exception:
                            pass
                else:
                    await responder_admin("✨ La sala ya está limpia de notificaciones temporales.")
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
                    await responder_admin(f"🎙️ Micrófono habilitado para **{t_nom}**.")
                else:
                    await responder_admin("ℹ️ Uso: `/hablar @usuario` o responde al mensaje del usuario en el grupo.")
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
                    await responder_admin(f"🔇 Micrófono silenciado para **{t_nom}** (se desbloqueará automáticamente en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s).")
                else:
                    await responder_admin("ℹ️ Uso: `/mutear @usuario` o responde al mensaje del usuario en el grupo.")
            elif cmd in ("/pausargrabacion", "/pausar_rec"):
                ok, msg = await pausar_grabacion()
                await responder_admin(msg)
                avisar_con_bot(msg, es_efimero=True)
            elif cmd in ("/reanudargrabacion", "/reanudar_rec"):
                ok, msg = await reanudar_grabacion()
                await responder_admin(msg)
                avisar_con_bot(msg, es_efimero=True)
            elif cmd in ("/detenergrabacion", "/cancelar_rec"):
                ok, msg = await cancelar_grabacion()
                await responder_admin(msg)
                avisar_con_bot(msg, es_efimero=True)
            elif cmd in ("/estadograbacion", "/estado_rec"):
                msg = estado_grabacion_str()
                await event.reply(msg)

        # Ecualizador de voz en vivo (solo administradores): /eq
        @client.on(events.NewMessage(pattern=r"(?i)^/(eq|ecualizador)(@\w+)?(\s|$)"))
        async def controlar_ecualizador(event):
            sender = await event.get_sender()
            if sender and getattr(sender, "bot", False):
                return
            uid = sender.id if sender else event.sender_id
            if BOT_ID and uid == BOT_ID:
                return
            if event.is_group and getattr(event, "message", None) and hasattr(event.message, "id"):
                ids_mensajes_efimeros.add(event.message.id)

            async def resp(texto_resp, **kwargs):
                r = await event.reply(texto_resp, **kwargs)
                if event.is_group and r and hasattr(r, "id"):
                    ids_mensajes_efimeros.add(r.id)
                return r

            if uid not in admin_ids:
                await resp("⛔ Solo los administradores pueden usar el ecualizador.")
                return
            if not MEJORA_AUDIO:
                await resp("⚠️ El módulo mejorar_audio.py no está disponible en el servidor.")
                return

            nonlocal_ruta = ruta_meditacion
            if eq_estado["auto"] is None and nonlocal_ruta and os.path.exists(nonlocal_ruta):
                eq_estado["auto"] = await analizar_audio_async(nonlocal_ruta)
            actual = eq_efectivo() or AjusteEQ()

            partes_eq = event.raw_text.strip().split()[1:]
            sin_acentos = "".join(
                c for c in unicodedata.normalize("NFD", "".join(partes_eq).lower())
                if unicodedata.category(c) != "Mn"
            )

            nuevo = None
            if sin_acentos in ("auto", "automatico"):
                eq_estado["manual"] = None
                nuevo = "auto"
            elif sin_acentos == "reset":
                eq_estado["manual"] = AjusteEQ()
                nuevo = "reset"
            elif sin_acentos == "separar":
                if not demucs_disponible():
                    await resp("⚠️ La separación voz/música no está disponible (requiere AUDIO_DEMUCS=1 y `pip install demucs`).")
                    return
                eq_estado["manual"] = actual.con(separar=not actual.separar)
                nuevo = "separar"
            else:
                m_eq = re.match(r"^(voz|musica|limpieza)([+\-]|[0-3])?$", sin_acentos)
                if m_eq:
                    campo, signo = m_eq.group(1), m_eq.group(2)
                    valor = getattr(actual, campo)
                    if signo is None or signo == "+":
                        valor += 1
                    elif signo == "-":
                        valor -= 1
                    else:
                        valor = int(signo)
                    eq_estado["manual"] = actual.con(**{campo: valor})
                    nuevo = campo

            if nuevo is None:
                modo = "manual" if eq_estado["manual"] else "automático"
                await resp(
                    "🎚️ **ECUALIZADOR DE VOZ**\n"
                    f"{describir_ajuste(actual)}\n"
                    f"Modo: {modo}\n\n"
                    "`/eq voz+` / `/eq voz-` — más / menos voz\n"
                    "`/eq musica+` / `/eq musica-` — atenuar más / menos la música\n"
                    "`/eq limpieza+` / `/eq limpieza-` — quitar más / menos ruido\n"
                    "`/eq auto` — análisis automático · `/eq reset` — valores base"
                )
                return

            actual = eq_efectivo() or AjusteEQ()
            if not reproduciendo_meditacion:
                await resp(f"✅ Guardado: {describir_ajuste(actual)}\nSe aplicará al iniciar la meditación.")
                asyncio.create_task(preparar_audio_eq())  # deja el audio listo con los nuevos niveles
                return

            await resp(f"⏳ Aplicando: {describir_ajuste(actual)}\nPuede tardar 1-2 minutos; la meditación sigue sonando mientras tanto.")

            async def _aplicar():
                estado = await aplicar_eq_en_vivo()
                if estado == "ok":
                    await resp("✅ Ecualizador aplicado. Si ya estaba bien, no hace falta tocar nada más.")
                else:
                    await resp("⚠️ No se pudo aplicar el cambio; la meditación continúa con el audio anterior.")

            asyncio.create_task(_aplicar())

        # Gestionar lista de reproducción: /cola, /playlist, /encolar, /agregar, /limpiarcola
        @client.on(events.NewMessage(pattern=r"(?i)^/(cola|playlist|encolar|agregar|limpiarcola|vaciarcola)(@\w+)?(\s|$)"))
        async def gestionar_cola_reproduccion(event):
            sender = await event.get_sender()
            if sender and getattr(sender, "bot", False):
                return
            uid = sender.id if sender else event.sender_id
            if BOT_ID and uid == BOT_ID:
                return
            if event.is_group and getattr(event, "message", None) and hasattr(event.message, "id"):
                ids_mensajes_efimeros.add(event.message.id)

            async def resp_q(texto_resp, **kwargs):
                r = await event.reply(texto_resp, **kwargs)
                if event.is_group and r and hasattr(r, "id"):
                    ids_mensajes_efimeros.add(r.id)
                return r

            if uid not in admin_ids:
                await resp_q("⛔ Solo los administradores pueden gestionar la lista de reproducción.")
                return

            partes = event.raw_text.strip().split(maxsplit=1)
            cmd_q = partes[0].lower().split("@")[0]
            arg_q = partes[1].strip() if len(partes) > 1 else ""

            nonlocal ruta_meditacion, info_catalogo_hoy, cola_reproduccion, indice_pista_actual

            if cmd_q in ("/cola", "/playlist"):
                if not cola_reproduccion and ruta_meditacion:
                    cola_reproduccion.append({
                        "ruta": ruta_meditacion,
                        "info": info_catalogo_hoy,
                        "titulo": (info_catalogo_hoy or {}).get("titulo", "Meditación")
                    })
                txt_cola = formatear_cola_audios(cola_reproduccion, indice_pista_actual, reproduciendo_meditacion)
                txt_ayuda = "\n\n💡 *Comandos disponibles:*\n• `/encolar [número]` — Añadir audio a la lista\n• `/saltaraudio` — Pasar al siguiente audio\n• `/limpiarcola` — Vaciar la programación"
                await resp_q(txt_cola + txt_ayuda)

            elif cmd_q in ("/limpiarcola", "/vaciarcola"):
                cola_reproduccion.clear()
                ruta_meditacion = None
                info_catalogo_hoy = None
                indice_pista_actual = 0
                guardar_cola_hoy([])
                await resp_q("🗑️ **Lista de reproducción vaciada.** Puedes encolar nuevos audios con `/encolar` o enviándolos al grupo.")

            elif cmd_q in ("/encolar", "/agregar"):
                if not arg_q:
                    await resp_q("ℹ️ Uso: `/encolar [número]` (Ejemplo: `/encolar 15` o `/encolar mensaje 606`).")
                    return
                items_encontrados = identificar_todos_los_audios(arg_q)
                if not items_encontrados:
                    await resp_q(f"⚠️ No se encontró ningún audio en el catálogo para: «{arg_q}».")
                    return
                anadidos = []
                for it in items_encontrados:
                    t = it.get("tipo", "MEDITACION")
                    try:
                        n = int(it.get("numero"))
                    except (ValueError, TypeError):
                        n = None
                    if n:
                        r_drive = obtener_o_descargar_audio(t, n)
                        if r_drive and os.path.exists(r_drive) and os.path.getsize(r_drive) > 5000:
                            item_c = {
                                "ruta": r_drive,
                                "info": it,
                                "titulo": it.get("titulo", f"{t} #{n}")
                            }
                            cola_reproduccion.append(item_c)
                            anadidos.append(it)
                            if MEJORA_AUDIO:
                                asyncio.create_task(preparar_audio_eq(r_drive))
                if anadidos:
                    if not reproduccion_iniciada and len(cola_reproduccion) > 0:
                        ruta_meditacion = cola_reproduccion[0]["ruta"]
                        info_catalogo_hoy = cola_reproduccion[0].get("info")
                    guardar_cola_hoy(cola_reproduccion)
                    txt_anadidos = "\n".join(f"• **{x.get('tipo', 'Audio').capitalize()} #{x.get('numero')}:** «{x.get('titulo', '')}»" for x in anadidos)
                    await resp_q(f"✅ **Audios añadidos a la lista de reproducción:**\n{txt_anadidos}\n\n📋 Total en cola: **{len(cola_reproduccion)} pistas**.")
                else:
                    await resp_q("⚠️ No se pudieron descargar los audios correspondientes desde Google Drive.")

        # Mantener la lista de turnos siempre visible al fondo si hay conversación activa en el chat
        @client.on(events.NewMessage(chats=entidad))
        async def mantener_turnos_al_fondo_por_chat(event):
            nonlocal mensajes_chat_recientes
            if event.out:
                return
            sender = await event.get_sender()
            if sender and getattr(sender, "bot", False):
                return
            if msg_turnos and event.message.id == getattr(msg_turnos, "id", None):
                return
            mensajes_chat_recientes += 1
            if mensajes_chat_recientes >= 6 and (cola_turnos or oradores_activos):
                await actualizar_mensaje_turnos(forzar_al_fondo=True)

        # Escuchar si un admin sube la meditación de tarea en vivo o la anuncia
        @client.on(events.NewMessage(chats=entidad))
        async def detectar_nueva_meditacion(event):
            nonlocal ruta_meditacion, info_catalogo_hoy, cola_reproduccion, indice_pista_actual
            if event.out:
                return

            sender = await event.get_sender()
            if sender and getattr(sender, "bot", False):
                return

            sender_id = event.sender_id
            if sender_id not in admin_ids or sender_id == me.id or (BOT_ID and sender_id == BOT_ID):
                return

            if hasattr(entidad, "id") and sender_id == entidad.id:
                return

            texto_raw = (event.raw_text or "").strip()
            texto = texto_raw.upper()

            # Ignorar mensajes automáticos de bot o sistema para prevenir bucles
            if any(texto_raw.startswith(p) for p in ("✅", "📢", "🕊️", "▶️", "🔍", "📋", "🧘✨", "🎙️", "ℹ️", "⚠️", "⛔", "[", "🔴", "⚪")):
                return
            if any(k in texto for k in [
                "DESDE GOOGLE DRIVE", "OBTENIDOS DESDE", "BUSCANDO AUDIO",
                "TAREA DEL DÍA", "TAREA DEL DIA", "LISTA DE REPRODUCCIÓN",
                "PROGRAMADOS PARA REPRODUCIRSE"
            ]):
                return

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
                    info_cat = identificar_audio_catalogo(event.raw_text or "", nombre_archivo)
                    txt_horario, lbl_tarea = determinar_fecha_y_etiqueta_tarea(event.raw_text or "")
                    es_para_hoy = "hoy" in txt_horario.lower()

                    if es_para_hoy:
                        idx_nuevo = len(cola_reproduccion) + 1
                        nombre_f = "meditacion_hoy.mp3" if idx_nuevo == 1 else f"meditacion_hoy_{idx_nuevo}.mp3"
                        ruta = os.path.join(CARPETA_MEDITACIONES, nombre_f)
                        await client.download_media(target_msg, file=ruta)

                        item_cola = {
                            "ruta": ruta,
                            "info": info_cat,
                            "titulo": (info_cat or {}).get("titulo") or nombre_archivo or f"Audio #{idx_nuevo}"
                        }
                        cola_reproduccion.append(item_cola)

                        if not reproduccion_iniciada and len(cola_reproduccion) == 1:
                            ruta_meditacion = ruta
                            info_catalogo_hoy = info_cat

                        if MEJORA_AUDIO:
                            asyncio.create_task(preparar_audio_eq(ruta))

                        guardar_cola_hoy(cola_reproduccion)
                        print(f"Nueva meditación recibida y guardada para hoy ({lbl_tarea}):", ruta)

                        if info_cat:
                            txt_card = formatear_info_audio(info_cat)
                            await event.reply(f"✅ **Audio #{len(cola_reproduccion)} añadido a la lista de reproducción de hoy:**\n\n{txt_card}\n\nProgramado para reproducirse {txt_horario} en la sala de voz (Total en cola: {len(cola_reproduccion)}).")
                            avisar_con_bot(f"📢 **{lbl_tarea} registrada (Pista #{len(cola_reproduccion)}):**\n\n{txt_card}")
                        else:
                            await event.reply(f"✅ Meditación recibida para hoy (Pista #{len(cola_reproduccion)}). Programada para reproducirse {txt_horario} en la sala de voz.")
                    else:
                        ruta = os.path.join(CARPETA_MEDITACIONES, "meditacion_manana.mp3")
                        await client.download_media(target_msg, file=ruta)
                        item_manana = {
                            "ruta": ruta,
                            "info": info_cat,
                            "titulo": (info_cat or {}).get("titulo") or nombre_archivo or "Audio para mañana"
                        }
                        guardar_cola_manana([item_manana])
                        print(f"Nueva meditación recibida y guardada para mañana ({lbl_tarea}):", ruta)
                        if info_cat:
                            txt_card = formatear_info_audio(info_cat)
                            await event.reply(f"✅ **Audio recibido y programado para mañana ({lbl_tarea}):**\n\n{txt_card}\n\nProgramado para reproducirse {txt_horario} en la sala de voz.\n*(La lista de reproducción de la sala de hoy se mantiene intacta).*")
                            avisar_con_bot(f"📢 **{lbl_tarea} registrada:**\n\n{txt_card}")
                        else:
                            await event.reply(f"✅ Meditación recibida y programada para mañana ({lbl_tarea}). Reproducción: {txt_horario}.")
                else:
                    items_cat = identificar_todos_los_audios(event.raw_text or "")
                    if items_cat:
                        txt_horario, lbl_tarea = determinar_fecha_y_etiqueta_tarea(event.raw_text or "")
                        es_para_hoy = "hoy" in txt_horario.lower()
                        descargados = []
                        for it in items_cat:
                            tipo = it.get("tipo", "MEDITACION")
                            try:
                                numero = int(it.get("numero"))
                            except (ValueError, TypeError):
                                numero = None
                            if numero:
                                print(f"Detectado anuncio de {tipo} #{numero} en texto ({lbl_tarea}). Buscando en Google Drive...")
                                r_drive = obtener_o_descargar_audio(tipo, numero)
                                if r_drive and os.path.exists(r_drive) and os.path.getsize(r_drive) > 5000:
                                    item_c = {
                                        "ruta": r_drive,
                                        "info": it,
                                        "titulo": it.get("titulo", f"{tipo} #{numero}")
                                    }
                                    descargados.append(item_c)
                                    if MEJORA_AUDIO:
                                        asyncio.create_task(preparar_audio_eq(r_drive))

                        if descargados:
                            if es_para_hoy:
                                for it_c in descargados:
                                    cola_reproduccion.append(it_c)
                                if not reproduccion_iniciada and len(cola_reproduccion) > 0:
                                    ruta_meditacion = cola_reproduccion[0]["ruta"]
                                    info_catalogo_hoy = cola_reproduccion[0].get("info")

                                guardar_cola_hoy(cola_reproduccion)
                                txt_cola = formatear_cola_audios(cola_reproduccion)
                                await event.reply(f"✅ **Audios obtenidos automáticamente desde Google Drive (Hoy):**\n\n{txt_cola}\n\nProgramados para reproducirse {txt_horario} en la sala de voz.")
                                avisar_con_bot(f"📢 **{lbl_tarea} confirmada desde Google Drive:**\n\n{txt_cola}")
                            else:
                                guardar_cola_manana(descargados)
                                txt_cola_manana = formatear_cola_audios(descargados)
                                await event.reply(f"✅ **Audios obtenidos desde Google Drive y programados para mañana ({lbl_tarea}):**\n\n{txt_cola_manana}\n\nProgramados para reproducirse {txt_horario} en la sala de voz.\n*(La lista de reproducción de la sala de hoy se mantiene intacta).*")
                                avisar_con_bot(f"📢 **{lbl_tarea} confirmada desde Google Drive:**\n\n{txt_cola_manana}")

        # Escuchar comandos por lenguaje natural de administradores en el grupo
        @client.on(events.NewMessage(chats=entidad))
        async def comandos_naturales_admin(event):
            sender = await event.get_sender()
            if sender and getattr(sender, "bot", False):
                return
            sender_id = event.sender_id
            if sender_id not in admin_ids or (BOT_ID and sender_id == BOT_ID):
                return
            if hasattr(entidad, "id") and sender_id == entidad.id:
                return
            texto_raw = (event.raw_text or "").strip().lower()
            if not texto_raw or texto_raw.startswith("/"):
                return
            if any(texto_raw.startswith(p) for p in ("✅", "📢", "🕊️", "▶️", "🔍", "📋", "🧘", "🎙️", "ℹ️", "⚠️", "⛔", "[", "🔴", "⚪")):
                return

            if getattr(event, "message", None) and hasattr(event.message, "id"):
                ids_mensajes_efimeros.add(event.message.id)

            async def responder_nat(txt_resp, **kwargs):
                r = await event.reply(txt_resp, **kwargs)
                if r and hasattr(r, "id"):
                    ids_mensajes_efimeros.add(r.id)
                return r

            # Reproducir meditación por lenguaje natural de administración
            if any(p in texto_raw for p in ["reproducir meditacion", "reproducir meditación", "reproduce la meditacion", "reproduce la meditación", "poner meditacion", "poner meditación", "pon la meditacion", "pon la meditación", "iniciar meditacion", "iniciar meditación", "reproducir audio", "reproduce el audio"]):
                nonlocal ruta_meditacion, info_catalogo_hoy, cola_reproduccion, indice_pista_actual, ultimo_error_reproduccion
                if not cola_reproduccion and (not ruta_meditacion or not os.path.exists(ruta_meditacion)):
                    ruta_meditacion, info_catalogo_hoy, cola_reproduccion = await buscar_audio_meditacion(client, entidad, admin_ids)
                if cola_reproduccion and indice_pista_actual >= len(cola_reproduccion):
                    indice_pista_actual = 0
                if tgcalls and (cola_reproduccion or (ruta_meditacion and os.path.exists(ruta_meditacion))):
                    ok = await reproducir_meditacion(indice_pista_actual)
                    if ok:
                        await responder_nat("▶️ Reproduciendo meditación en la sala de voz...")
                    else:
                        detalle = f"\n*(Detalle: {ultimo_error_reproduccion})*" if ultimo_error_reproduccion else ""
                        await responder_nat(f"❌ Error iniciando la reproducción de la meditación.{detalle}")
                else:
                    await responder_nat("⚠️ No se encontró ningún archivo de meditación de tarea disponible.")
            # Pausar meditación
            elif any(p in texto_raw for p in ["pausar meditacion", "pausa la meditacion", "pausar meditación", "pausa la meditación", "pausar audio", "pausa el audio"]):
                if tgcalls:
                    try:
                        await tgcalls.pause(destino)
                        marcar_pausa()
                        await responder_nat("⏸️ Meditación pausada por indicación de administración.")
                    except Exception as e:
                        await responder_nat(f"Nota al pausar: {e}")
            # Reanudar meditación
            elif any(p in texto_raw for p in ["reanudar meditacion", "continua la meditacion", "reanudar meditación", "continuar meditación", "seguir meditación", "reanudar audio", "seguir con el audio"]):
                if tgcalls:
                    try:
                        await tgcalls.resume(destino)
                        marcar_reanudacion()
                        await responder_nat("▶️ Meditación reanudada por indicación de administración.")
                    except Exception as e:
                        await responder_nat(f"Nota al reanudar: {e}")
            # Detener meditación
            elif any(p in texto_raw for p in ["detener meditacion", "parar meditacion", "detener meditación", "parar meditación", "parar audio", "detener audio"]):
                if tgcalls:
                    try:
                        nonlocal reproduciendo_meditacion
                        await tgcalls.leave_call(destino)
                        reproduciendo_meditacion = False
                        await desbloquear_todos_los_participantes()
                        await responder_nat("⏹️ Meditación detenida. Micrófonos restablecidos y desbloqueados.")
                    except Exception as e:
                        await responder_nat(f"Nota al detener: {e}")
            # Siguiente audio en la cola de reproducción
            elif any(p in texto_raw for p in ["siguiente audio", "pasar al siguiente audio", "saltar audio", "siguiente meditacion", "siguiente meditación", "pasar audio"]):
                if not reproduciendo_meditacion:
                    await responder_nat("⚠️ No hay reproducción activa en este momento.")
                elif indice_pista_actual + 1 < len(cola_reproduccion):
                    await responder_nat(f"⏭️ Saltando a la pista {indice_pista_actual + 2} de {len(cola_reproduccion)}...")
                    await reproducir_meditacion(indice_pista_actual + 1)
                else:
                    if tgcalls:
                        await tgcalls.leave_call(destino)
                    reproduciendo_meditacion = False
                    await desbloquear_todos_los_participantes()
                    await responder_nat("⏹️ Era la última pista de la lista. Reproducción finalizada y micrófonos desbloqueados.")
            # Desbloquear micrófonos / Abrir sala
            elif any(p in texto_raw for p in ["abrir microfonos", "abrir micrófonos", "desmutear a todos", "desbloquear microfonos", "desbloquear micrófonos", "abrir la sala", "liberar microfonos", "liberar micrófonos"]):
                await desbloquear_todos_los_participantes()
                await responder_nat("🔓 Micrófonos desbloqueados para todos los participantes.")
                avisar_con_bot("🔓 **Micrófonos abiertos:** El candado de silencio ha sido retirado para todos los asistentes.", es_efimero=True)
            # Siguiente orador
            elif any(p in texto_raw for p in ["siguiente turno", "siguiente orador", "siguiente persona", "pasar al siguiente"]):
                if not cola_turnos:
                    await responder_nat("ℹ️ No hay participantes en espera en la lista de turnos.")
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
                    await responder_nat(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Tu micrófono ha sido habilitado.")
                    avisar_con_bot(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Por favor abre tu micrófono para compartir.", es_efimero=True)
            # Limpiar notificaciones y ventanas de la sala a petición del administrador
            elif any(p in texto_raw for p in [
                "notificaciones del robot",
                "notificaciones del bot",
                "ventanas del robot",
                "ventanas del bot",
                "limpia la sala de notificaciones",
                "limpiar la sala de notificaciones",
                "limpiar notificaciones",
                "limpia las notificaciones",
                "limpia la sala",
                "limpiar la sala",
                "limpiar sala",
                "borrar notificaciones",
                "borra las notificaciones",
                "borrar ventanas",
                "limpiar avisos",
            ]) or (
                any(v in texto_raw for v in ["limpia", "limpiar", "borra", "borrar"])
                and any(t in texto_raw for t in ["notificacion", "notificaciones", "ventana", "ventanas", "aviso", "avisos"])
                and "turno" not in texto_raw
            ):
                cant = len(ids_mensajes_efimeros)
                if cant > 0:
                    a_borrar = set(ids_mensajes_efimeros)
                    ids_mensajes_efimeros.clear()
                    r_aviso = await responder_nat(f"🧹 Limpiando {cant} notificaciones y ventanas temporales de la sala...")
                    await limpiar_mensajes_temporales(client, entidad, a_borrar)
                    if r_aviso and hasattr(r_aviso, "id"):
                        ids_mensajes_efimeros.discard(r_aviso.id)
                        await asyncio.sleep(4)
                        try:
                            await client.delete_messages(entidad, [r_aviso.id])
                        except Exception:
                            pass
                else:
                    await responder_nat("✨ La sala ya está limpia de notificaciones temporales.")

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
                if not cola_reproduccion and (not ruta_meditacion or not os.path.exists(ruta_meditacion)):
                    try:
                        ruta_meditacion, info_catalogo_hoy, cola_reproduccion = await buscar_audio_meditacion(client, entidad, admin_ids)
                    except Exception as e:
                        print("Nota re-buscando audio a las 8:15 PM:", e)
                if not cola_reproduccion and (not ruta_meditacion or not os.path.exists(ruta_meditacion)):
                    try:
                        await client.send_message(
                            "me",
                            "⚠️ **RECORDATORIO PREVENTIVO DE MEDITACIÓN (8:15 PM)**\n\n"
                            "Aún no se ha detectado el archivo de audio con `MEDITACION DE TAREA` en el grupo.\n"
                            "Por favor súbelo antes de las 8:30 PM para que inicie automáticamente a las 8:32 PM."
                        )
                    except Exception:
                        pass
                    avisar_con_bot("⚠️ **Aviso Administradores:** Aún no se ha publicado la `MEDITACION DE TAREA` de hoy. Recuerden subir el archivo .mp3 antes de las 8:30 PM.", es_efimero=True)

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
                avisar_con_bot(texto_oracion, reply_markup=keyboard_oracion, es_efimero=True)

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

                if not cola_reproduccion and (not ruta_meditacion or not os.path.exists(ruta_meditacion)):
                    try:
                        ruta_meditacion, info_catalogo_hoy, cola_reproduccion = await buscar_audio_meditacion(client, entidad, admin_ids)
                    except Exception as e:
                        print("Nota re-buscando audio a las 8:31 PM:", e)

                if cola_reproduccion or (ruta_meditacion and os.path.exists(ruta_meditacion)):
                    total_p = len(cola_reproduccion)
                    if total_p > 1:
                        lista_txt = "\n".join(
                            f"• {x.get('tipo', 'Audio').capitalize()} #{x.get('info', {}).get('numero', i+1)}: «{x.get('titulo', '')}»"
                            for i, x in enumerate(cola_reproduccion)
                        )
                        txt_alerta_med = (
                            f"{prefijo}🧘 **En 1 minuto (8:32 PM) dará inicio la sesión de meditación ({total_p} audios programados):**\n\n"
                            f"{lista_txt}\n\n"
                            "Los micrófonos han sido habilitados. Por favor tomen una postura cómoda y permanezcan en silencio."
                        )
                    elif info_catalogo_hoy:
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
                    avisar_con_bot(txt_alerta_med, es_efimero=True)
                elif prefijo:
                    avisar_con_bot(f"{prefijo}Los micrófonos han sido habilitados para la comunidad.", es_efimero=True)

            # 8:32 PM: Reproducción automática de la meditación
            if hora_col == 20 and min_col >= 32 and not reproduccion_iniciada:
                if not cola_reproduccion and (not ruta_meditacion or not os.path.exists(ruta_meditacion)):
                    try:
                        ruta_meditacion, info_catalogo_hoy, cola_reproduccion = await buscar_audio_meditacion(client, entidad, admin_ids)
                    except Exception as e:
                        print("Nota re-buscando audio a las 8:32 PM:", e)
                if cola_reproduccion or (ruta_meditacion and os.path.exists(ruta_meditacion)):
                    reproduccion_iniciada = True
                    await reproducir_meditacion(0)

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

            # Actualizar diccionario de usuarios y chats devueltos en la llamada actual
            for u in getattr(call_info, "users", []):
                users_cache[u.id] = u
            for c in getattr(call_info, "chats", []):
                chats_cache[c.id] = c

            p_count_servidor = getattr(getattr(call_info, "call", None), "participants_count", 0)
            offset_disp = getattr(call_info, "participants_next_offset", "")

            # Sondeo periódico de la lista completa de participantes (cada ~6s o si faltan según Telegram)
            debe_refrescar_completo = (
                segundos_totales <= INTERVALO_SONDEO_SEGUNDOS
                or (segundos_totales // INTERVALO_SONDEO_SEGUNDOS) % 3 == 0
                or bool(offset_disp)
                or p_count_servidor > len(participantes_conectados)
            )

            if debe_refrescar_completo:
                parts_completos, users_nuevos, chats_nuevos = await obtener_todos_participantes_llamada(client, input_call)
                users_cache.update(users_nuevos)
                chats_cache.update(chats_nuevos)
                uids_en_servidor = set()
                for p in parts_completos:
                    if getattr(p, "left", False):
                        continue
                    p_uid = getattr(p.peer, "user_id", None) or getattr(p.peer, "channel_id", None) or getattr(p.peer, "chat_id", None)
                    if not p_uid:
                        continue
                    uids_en_servidor.add(p_uid)
                    if p_uid not in participantes:
                        u_obj = users_cache.get(p_uid)
                        c_obj = chats_cache.get(p_uid)
                        nombre_part = f"{u_obj.first_name or ''} {u_obj.last_name or ''}".strip() if u_obj else (getattr(c_obj, "title", "Usuario") if c_obj else "Usuario")
                        username_part = getattr(u_obj, "username", "") or getattr(c_obj, "username", "") or ""
                        f_ent = p.date.astimezone(tz_col) if getattr(p, "date", None) else ahora
                        participantes[p_uid] = {
                            "id": p_uid,
                            "nombre": nombre_part,
                            "username": username_part,
                            "primera_entrada": f_ent,
                            "ultima_salida": ahora,
                            "segundos_acumulados": 0.0,
                            "segundos_hablando": 0.0,
                            "activo_ahora": True,
                            "ultimo_check": ahora,
                            "reconexiones": 0,
                            "hablo": False,
                            "orden_llegada": len(participantes) + 1,
                            "meditacion_completada": reproduciendo_meditacion,
                        }
                        print(f"👥 Participante registrado en sala: {nombre_part} ({p_uid}) | Total registrados: {len(participantes)}")
                    else:
                        part = participantes[p_uid]
                        if not part["activo_ahora"]:
                            part["reconexiones"] += 1
                            part["activo_ahora"] = True
                            part["ultimo_check"] = ahora

                # Marcar desconectados si ya no figuran en la llamada de Telegram
                total_activos_previos = len(participantes_conectados)
                desconectados_este_tick = 0
                for p_uid in list(participantes_conectados):
                    if p_uid not in uids_en_servidor:
                        desconectados_este_tick += 1
                        if p_uid in participantes and participantes[p_uid]["activo_ahora"]:
                            participantes[p_uid]["activo_ahora"] = False
                            participantes[p_uid]["ultima_salida"] = ahora

                if total_activos_previos >= 4 and desconectados_este_tick >= max(3, int(total_activos_previos * 0.6)):
                    hubo_caida_masiva_sala = True
                    print("⚡ Detección de caída masiva o parpadeo general en la sala de Telegram.")

                participantes_conectados = uids_en_servidor

            activos_en_tick = set()
            hubo_cambio_turnos = False

            # Monitoreo de oradores activos y moderación en el tick actual (2s)
            for p in getattr(call_info, "participants", []):
                if getattr(p, "left", False):
                    continue
                uid = getattr(p.peer, "user_id", None) or getattr(p.peer, "channel_id", None) or getattr(p.peer, "chat_id", None)
                if not uid:
                    continue

                activos_en_tick.add(uid)
                participantes_conectados.add(uid)
                u = users_cache.get(uid)
                c = chats_cache.get(uid)
                nombre = f"{u.first_name or ''} {u.last_name or ''}".strip() if u else (getattr(c, "title", "Usuario") if c else "Usuario")
                username = getattr(u, "username", "") or getattr(c, "username", "") or ""

                if uid not in participantes:
                    f_ent = p.date.astimezone(tz_col) if getattr(p, "date", None) else ahora
                    participantes[uid] = {
                        "id": uid,
                        "nombre": nombre,
                        "username": username,
                        "primera_entrada": f_ent,
                        "ultima_salida": ahora,
                        "segundos_acumulados": 0.0,
                        "segundos_hablando": 0.0,
                        "activo_ahora": True,
                        "ultimo_check": ahora,
                        "reconexiones": 0,
                        "hablo": False,
                        "orden_llegada": len(participantes) + 1,
                        "meditacion_completada": reproduciendo_meditacion,
                    }

                # Detección de micrófono y estado de silencio
                hablo_ahora = False
                if getattr(p, "active_date", None):
                    hablo_ahora = True
                elif getattr(p, "muted", True) is False and getattr(p, "volume", 0) and getattr(p, "volume", 0) > 0:
                    hablo_ahora = True

                if hablo_ahora:
                    participantes[uid]["hablo"] = True
                    participantes[uid]["segundos_hablando"] = participantes[uid].get("segundos_hablando", 0.0) + INTERVALO_SONDEO_SEGUNDOS

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
                    # Y garantizar que la cuenta del robot nunca quede con micrófono apagado durante reproducción
                    debe_desmutear = False
                    if getattr(p, "can_self_unmute", True) is False or getattr(p, "muted_by_you", False) is True:
                        debe_desmutear = True
                    elif uid == me.id and reproduciendo_meditacion and getattr(p, "muted", False) is True:
                        debe_desmutear = True

                    if debe_desmutear:
                        try:
                            input_peer = await client.get_input_entity(p.peer)
                            await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=False))
                            if uid != me.id:
                                print(f"🔓 Candado de silencio retirado para administrador {nombre} ({uid}).")
                            else:
                                print("🔓 Micrófono del robot reactivado para transmisión de audio.")
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
                                        avisar_con_bot(f"⚠️ **{nombre}**, ya hay {MAX_ORADORES_SIMULTANEOS} personas hablando a la vez. Tu micrófono se desbloqueará en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s y te hemos añadido a la lista de turnos para no interrumpir.", es_efimero=True)
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
                                            avisar_con_bot(f"🔇 **Micrófono silenciado:** {nombre} por inactividad. Se desbloqueará en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s para que puedas volver a hablar cuando desees.", es_efimero=True)
                                        print(f"Auto-mute aplicado a {nombre} ({uid}) tras {seg_inac}s de inactividad. Desbloqueo programado en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s.")
                                    except Exception as e:
                                        print(f"Nota auto-muteando a {nombre}:", e)
                        else:
                            # Micrófono cerrado
                            segundos_inactividad_mic[uid] = 0
                            if uid in oradores_activos:
                                oradores_activos.discard(uid)
                                hubo_cambio_turnos = True

            # Acumular segundos para TODOS los participantes conectados (oyentes y oradores)
            for uid in list(participantes_conectados):
                if uid in participantes:
                    part = participantes[uid]
                    if not part["activo_ahora"]:
                        part["reconexiones"] += 1
                        part["activo_ahora"] = True
                        part["ultimo_check"] = ahora
                    else:
                        delta = (ahora - part["ultimo_check"]).total_seconds()
                        part["segundos_acumulados"] += max(0.0, delta)
                        part["ultimo_check"] = ahora
                        part["ultima_salida"] = ahora
                    if reproduciendo_meditacion:
                        part["meditacion_completada"] = True

            if hubo_cambio_turnos:
                await actualizar_mensaje_turnos(forzar_al_fondo=True)

            # Reglas de Auto-Cierre inteligente:
            num_activos = len(participantes_conectados)
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

        # Desfijar mensaje dinámico y actualizar ventanas informativas al terminar la llamada
        if msg_fijado:
            try:
                await client.unpin_message(entidad, msg_fijado)
            except Exception:
                pass
            try:
                texto_concluido = (
                    "🎙️ **SALA DE VOZ CONCLUIDA**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📅 Fecha: {fecha_hoy} | ⏰ Fin: {datetime.now(tz_col).strftime('%I:%M %p')}\n"
                    "✨ Gracias a todos por acompañarnos en esta sesión diaria.\n"
                    "📊 Los reportes y actas oficiales se publican a continuación."
                )
                await client.edit_message(entidad, msg_fijado, texto_concluido)
            except Exception:
                pass

        if msg_turnos:
            try:
                await client.edit_message(
                    entidad,
                    msg_turnos,
                    "🎙️ **LISTA DE TURNOS CERRADA**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nLa sala de voz ha concluido por el día de hoy."
                )
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

        # Purgar administradores de la base de datos de puntos
        for aid in admin_ids:
            usuarios_db.pop(str(aid), None)

        # Filtrar solo participantes de la comunidad (excluir administradores para el podio de 9 puestos)
        participantes_comunidad = [p for p in participantes.values() if p["id"] not in admin_ids]
        podio_puntuales = sorted(participantes_comunidad, key=lambda x: x["primera_entrada"])[:9]
        ids_podio = {p["id"] for p in podio_puntuales}

        asistentes_validos = []
        visitas_fugaces = []

        for uid, part in participantes.items():
            mins = int(round(part["segundos_acumulados"] / 60))
            part["minutos"] = mins
            pct = int(round((part["segundos_acumulados"] / (duracion_reunion_minutos * 60)) * 100))
            part["porcentaje"] = min(100, pct)

            # Si es administrador, no gana puntos ni entra al ranking
            if uid in admin_ids:
                part["pts_hoy"] = 0
                part["pts_mes"] = 0
                part["pts_totales"] = 0
                part["racha"] = 0
                part["rango"] = "👑 Admin"
                part["nuevas_medallas"] = []
                part["desglose"] = "👑 Moderador / Admin (Exento de puntos)"
                if mins >= MIN_MINUTOS_ASISTENCIA:
                    asistentes_validos.append(part)
                else:
                    visitas_fugaces.append(part)
                continue

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
                "% Reunion", "Hablo", "Minutos Voz", "Meditacion", "Reconexiones", "Puntos Hoy",
                "Puntos Mes", "Puntos Totales", "Rango", "Medallas"
            ])
            for part in asistentes_validos:
                u_info = usuarios_db.get(str(part["id"]), {})
                mins_voz = round(part.get("segundos_hablando", 0.0) / 60.0, 1)
                writer.writerow([
                    part["id"], part["nombre"], f"@{part['username']}" if part["username"] else "",
                    part["primera_entrada"].strftime("%I:%M:%S %p"),
                    part["ultima_salida"].strftime("%I:%M:%S %p"),
                    part["minutos"], f"{part['porcentaje']}%",
                    "Si" if part["hablo"] else "No",
                    mins_voz,
                    "Si" if part.get("meditacion_completada") else "No",
                    part["reconexiones"],
                    part.get("pts_hoy", 0), part.get("pts_mes", 0),
                    part.get("pts_totales", 0), part.get("rango", ""),
                    " / ".join(u_info.get("medallas", []))
                ])
            for part in visitas_fugaces:
                mins_voz = round(part.get("segundos_hablando", 0.0) / 60.0, 1)
                writer.writerow([
                    part["id"], part["nombre"], f"@{part['username']}" if part["username"] else "",
                    part["primera_entrada"].strftime("%I:%M:%S %p"),
                    part["ultima_salida"].strftime("%I:%M:%S %p"),
                    part["minutos"], f"{part['porcentaje']}%",
                    "Si" if part["hablo"] else "No",
                    mins_voz,
                    "No", part["reconexiones"],
                    0, 0, usuarios_db.get(str(part["id"]), {}).get("puntos_totales", 0), "Visita Fugaz", ""
                ])

        # 6. Construir y Enviar Reportes
        asistentes_validos.sort(key=lambda x: x.get("pts_hoy", 0), reverse=True)
        ranking_mes = sorted([u for u in usuarios_db.values() if int(u.get("id", 0)) not in admin_ids], key=lambda x: x.get("puntos_mes", 0), reverse=True)[:5]
        es_fin_de_mes = (inicio_llamada + timedelta(days=1)).month != inicio_llamada.month

        total_asistentes_sala = len(participantes)
        total_validos = len(asistentes_validos)
        txt_asistentes_pub = plural_personas(total_asistentes_sala)
        if total_validos < total_asistentes_sala:
            txt_asistentes_pub += f" ({total_validos} con permanencia completa)"

        lineas_pub = [
            "📊 **REPORTE DE ASISTENCIA Y PUNTOS — LLAMADA DIARIA**",
            f"🗓️ Fecha: {inicio_llamada.strftime('%d/%m/%Y')}",
            f"⏱️ Duración: {duracion_reunion_minutos} min | 👥 Asistentes: {txt_asistentes_pub}\n",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "🏆 **PODIO DE PUNTUALIDAD (TOP 9):**",
        ]
        simbolos_podio = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
        if podio_puntuales:
            for idx, p in enumerate(podio_puntuales):
                tag = f"(@{p['username']})" if p["username"] else ""
                lineas_pub.append(f"{simbolos_podio[idx]} **{p['nombre']}** {tag} — {p['primera_entrada'].strftime('%I:%M:%S %p')}")
        else:
            lineas_pub.append("No se registraron participantes de la comunidad hoy.")

        lineas_pub.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lineas_pub.append("🌟 **PUNTOS GANADOS HOY:**")
        puntos_comunidad = [p for p in asistentes_validos if p["id"] not in admin_ids and p.get("pts_hoy", 0) > 0]
        if puntos_comunidad:
            for p in puntos_comunidad:
                tag = f"(@{p['username']})" if p["username"] else ""
                icono_voz = "🎙️" if p["hablo"] else "🎧"
                estrella = "⭐ " if p["porcentaje"] >= 80 else "• "
                aviso_medalla = f"\n   🎉 ¡Nueva medalla: {', '.join(p['nuevas_medallas'])}!" if p.get("nuevas_medallas") else ""
                lineas_pub.append(
                    f"{estrella}**{p['nombre']}** {tag} ➔ **+{p['pts_hoy']} pts** {icono_voz}\n"
                    f"   [{p['desglose']}] — Racha: 🔥 {p['racha']} días ({p['rango']}){aviso_medalla}"
                )
        else:
            lineas_pub.append("No se registraron asistencias comunitarias que sumaran puntos hoy.")

        if es_fin_de_mes:
            lineas_pub.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lineas_pub.append("👑 **🏆 CUADRO DE HONOR — CAMPEONES DEL MES 🏆** 👑")
            campeones_mes = sorted([u for u in usuarios_db.values() if int(u.get("id", 0)) not in admin_ids], key=lambda x: x.get("puntos_mes", 0), reverse=True)[:3]
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

        # Generar imagen gráfica profesional del podio de puntualidad (Top 9) y enviarla al grupo
        try:
            ruta_img_podio = generar_imagen_podio(
                fecha_str=inicio_llamada.strftime("%d/%m/%Y"),
                duracion_min=duracion_reunion_minutos,
                total_personas=len(participantes),
                hubo_meditacion=meditacion_activa_hoy,
                top_puntuales=podio_puntuales,
            )
            if ruta_img_podio and os.path.exists(ruta_img_podio):
                enviar_foto_con_bot(ruta_img_podio, caption=f"🏆 **PODIO OFICIAL DE PUNTUALIDAD — LLAMADA {inicio_llamada.strftime('%d/%m/%Y')}** 🏆")
        except Exception as e:
            print("Nota generando o enviando imagen del podio:", e)

        reporte_publico = "\n".join(lineas_pub)
        avisar_con_bot(reporte_publico)

        # Enviar notificación privada personalizada a cada asistente de la comunidad (excluye administradores)
        if BOT_TOKEN:
            print("Enviando resúmenes individuales privados a asistentes...")
            for p in asistentes_validos:
                if p["id"] in admin_ids:
                    continue
                try:
                    meds_p = p.get("nuevas_medallas", [])
                    txt_nuevas_meds = f"\n🎖️ **¡Nueva medalla desbloqueada!** {', '.join(meds_p)}" if meds_p else ""
                    reconex = p.get("reconexiones", 0)

                    if reconex == 0:
                        txt_calidad_senal = "🟢 **Excelente (100% estable, 0 caídas)**"
                        txt_diagnostico_red = ""
                    elif reconex == 1:
                        txt_calidad_senal = "🟡 **Buena (1 micro-desconexión breve)**"
                        txt_diagnostico_red = ""
                    else:
                        txt_calidad_senal = f"⚠️ **Inestable ({reconex} micro-desconexiones)**"
                        if hubo_caida_masiva_sala:
                            txt_diagnostico_red = (
                                f"\n\n📡 **Estabilidad de llamada:** Detectamos **{reconex} reconexiones** en tu sesión. "
                                "Notamos fluctuaciones generales en los servidores de Telegram hoy, por lo que la interrupción pudo deberse a la plataforma."
                            )
                        else:
                            txt_diagnostico_red = (
                                f"\n\n⚠️ **ESTABILIDAD DE TU CONEXIÓN:**\n"
                                f"Registraste **{reconex} salidas de la sala** (mientras el resto de la comunidad se mantuvo estable).\n\n"
                                f"💡 **¿Telegram te saca frecuentemente de la llamada? Sigue estos pasos:**\n"
                                f"1. 🔋 **Batería (Principal causa):** En tu celular ve a _Ajustes > Aplicaciones > Telegram > Batería_ y selecciona **'Sin restricciones'** (evita que el celular cierre la llamada al apagar la pantalla).\n"
                                f"2. 📶 **Señal:** Procura no alternar entre WiFi y datos móviles durante la reunión.\n"
                                f"3. 🧹 **Caché:** En Telegram ve a _Ajustes > Datos y almacenamiento > Uso de almacenamiento > Borrar caché_."
                            )

                    seg_hablo = p.get("segundos_hablando", 0.0)
                    if p.get("hablo") or seg_hablo > 0:
                        if seg_hablo >= 60:
                            txt_uso_mic = f"🎙️ Participaste al micrófono: **{round(seg_hablo / 60.0, 1)} min**"
                        else:
                            txt_uso_mic = f"🎙️ Participaste al micrófono: **{max(1, round(seg_hablo))} seg**"
                    else:
                        txt_uso_mic = "🎧 Oyente en silencio (escucha activa y respetuosa)"

                    txt_meditacion_ind = "• Meditación diaria: **🧘 Completada con éxito**\n" if p.get("meditacion_completada") else ""

                    txt_privado_usuario = (
                        f"👋 ¡Hola **{p['nombre']}**!\n\n"
                        f"🎉 **Resumen de tu llamada de hoy:**\n"
                        f"• Tiempo conectado: **{p['minutos']} min** ({p['porcentaje']}% de la sesión)\n"
                        f"• Calidad de tu conexión: {txt_calidad_senal}\n"
                        f"• Participación de voz: {txt_uso_mic}\n"
                        f"{txt_meditacion_ind}"
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

            # Enviar reporte de conexión a usuarios de visitas fugaces (<10 min) que sufrieron caídas
            for p in visitas_fugaces:
                if p["id"] in admin_ids:
                    continue
                reconex = p.get("reconexiones", 0)
                if reconex >= 1 or p["minutos"] >= 1:
                    try:
                        seg_hablo = p.get("segundos_hablando", 0.0)
                        txt_mic_fugaz = f"• Micrófono: **{round(seg_hablo)} seg**\n" if seg_hablo > 0 else ""
                        txt_visita_red = (
                            f"👋 ¡Hola **{p['nombre']}**!\n\n"
                            f"📡 **Reporte de conexión de la llamada de hoy:**\n"
                            f"• Tiempo en sala: **{p['minutos']} min** ({p['porcentaje']}% de la reunión)\n"
                            f"• Desconexiones registradas: **{reconex} salidas de la sala**\n"
                            f"{txt_mic_fugaz}"
                            f"⚠️ Notamos que tu llamada se interrumpió y no lograste alcanzar los 10 minutos mínimos para sumar puntos hoy.\n\n"
                            f"💡 **¿Telegram te saca frecuentemente de la llamada? Sigue estos 3 pasos:**\n"
                            f"1. 🔋 **Batería (Principal causa):** En tu celular ve a _Ajustes > Aplicaciones > Telegram > Batería_ y selecciona **'Sin restricciones'** (evita que el celular cierre la llamada al apagar la pantalla).\n"
                            f"2. 📶 **Señal:** Procura no alternar entre WiFi y datos móviles durante la llamada.\n"
                            f"3. 🧹 **Caché:** En Telegram ve a _Ajustes > Datos y almacenamiento > Uso de almacenamiento > Borrar caché_.\n\n"
                            f"✨ ¡Te esperamos mañana a las 7:56 PM para compartir juntos!"
                        )
                        url_usr = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                        datos_usr = json.dumps({
                            "chat_id": p["id"],
                            "text": txt_visita_red,
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
            seg_hablo = p.get("segundos_hablando", 0.0)
            if seg_hablo >= 60:
                mic = f"🎙️ Habló {round(seg_hablo / 60.0, 1)} min"
            elif seg_hablo > 0:
                mic = f"🎙️ Habló {max(1, round(seg_hablo))}s"
            else:
                mic = "🎧 Solo oyente"
            med_txt = " | 🧘 Asistió a meditación" if p.get("meditacion_completada") else ""
            u_info = usuarios_db.get(str(p["id"]), {})
            meds_txt = ", ".join(u_info.get("medallas", [])) or "Ninguna"
            caidas_tag = ""
            if p.get("reconexiones", 0) >= 2:
                caidas_tag = " [⚠️ Celular/Red del usuario]" if not hubo_caida_masiva_sala else " [⚡ Telegram global]"
            elif p.get("reconexiones", 0) == 1:
                caidas_tag = " [Estable]"
            else:
                caidas_tag = " [100% fluido]"
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
                caidas_f = f" | Caídas: {p['reconexiones']}" if p.get("reconexiones", 0) else ""
                seg_hablo = p.get("segundos_hablando", 0.0)
                voz_f = f" | 🎙️ {round(seg_hablo)}s" if seg_hablo > 0 else ""
                lineas_priv.append(f"• {p['nombre']} (ID: `{p['id']}` | {tag}) — {p['minutos']} min{caidas_f}{voz_f} (Salió {p['ultima_salida'].strftime('%I:%M:%S %p')})")

        lineas_priv.append(f"\n📎 Se generó el archivo de auditoría: `{ruta_csv}`")
        reporte_privado = "\n".join(lineas_priv)

        # 7. Generar Resumen con IA (Gemini) y Diarización de Oradores
        oradores_sesion = [
            p["nombre"] for p in participantes.values() if p.get("hablo")
        ]

        # Unir grabaciones de voz si existen y no fueron canceladas (excluyendo meditación)
        audio_para_ia = None
        if not grabacion_cancelada:
            for s in segmentos_grabados:
                asegurar_mp3_desde_raw(s)
            valid_segments = [s for s in segmentos_grabados if os.path.exists(s) and os.path.getsize(s) > 1000]
            if len(valid_segments) == 1:
                try:
                    if valid_segments[0] != ruta_grabacion_completa:
                        shutil.copy2(valid_segments[0], ruta_grabacion_completa)
                        audio_para_ia = ruta_grabacion_completa
                    else:
                        audio_para_ia = valid_segments[0]
                except Exception:
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

        ruta_transcripcion_txt = os.path.join(CARPETA_ASISTENCIAS, f"transcripcion_{fecha_hoy}.txt")
        resumen_ia = generar_resumen_ia(
            ruta_audio=audio_para_ia,
            oradores=oradores_sesion,
            fecha=fecha_hoy,
            duracion_minutos=duracion_reunion_minutos,
            total_asistentes=len(participantes),
            info_catalogo=info_catalogo_hoy,
            ruta_transcripcion_salida=ruta_transcripcion_txt,
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
            total_participantes=len(participantes),
        )

        # Guardar en base histórica de minutas para búsquedas posteriores
        guardar_minuta(
            fecha=fecha_hoy,
            duracion_minutos=duracion_reunion_minutos,
            asistentes_count=len(participantes),
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
                # Enviar transcripción completa en texto generada por IA
                if os.path.exists(ruta_transcripcion_txt) and os.path.getsize(ruta_transcripcion_txt) > 0:
                    await client.send_file(
                        me.id,
                        ruta_transcripcion_txt,
                        caption=f"📝 **Transcripción Oficial de la Reunión (Texto) - {fecha_hoy}**\nRegistro de intervenciones generado con IA.",
                    )
                    print("Transcripción de texto enviada a Mensajes Guardados del dueño.")
                # Enviar grabación de audio de la sesión (excluyendo meditación) exclusivamente al dueño
                if audio_para_ia and os.path.exists(audio_para_ia) and os.path.getsize(audio_para_ia) > 1000 and not grabacion_cancelada:
                    await client.send_file(
                        me.id,
                        audio_para_ia,
                        caption=f"🎙️ **Grabación de Audio Oficial (MP3) - {fecha_hoy}**\nSesión comunitaria (sin meditación).",
                    )
                    print("Grabación de audio MP3 enviada a Mensajes Guardados del dueño.")
                elif not grabacion_cancelada:
                    msg_diag_audio = (
                        "⚠️ **Aviso de Grabación de Audio:**\n"
                        "No se pudo generar el archivo MP3 de la sesión porque no se capturaron flujos de voz entrantes en el servidor."
                    )
                    await client.send_message(me.id, msg_diag_audio)
                if os.path.exists(RUTA_PUNTOS):
                    await client.send_file(
                        me.id,
                        RUTA_PUNTOS,
                        caption=f"💾 Respaldo de puntos - {fecha_hoy}",
                    )
                print("CSV, Acta PDF, transcripción, audio MP3 y respaldo de puntos enviados al dueño.")
            except Exception as e:
                print("Error enviando archivos al dueño:", e)

        # Limpiar temporales de grabación cruda una vez enviados
        for s in segmentos_grabados:
            try:
                if os.path.exists(s):
                    os.remove(s)
                s_raw = s.rsplit(".", 1)[0] + ".raw"
                if os.path.exists(s_raw):
                    os.remove(s_raw)
            except Exception:
                pass
        for f_tmp in (ruta_grabacion_pre, ruta_grabacion_post, ruta_grabacion_completa):
            try:
                if os.path.exists(f_tmp):
                    os.remove(f_tmp)
                f_raw = f_tmp.rsplit(".", 1)[0] + ".raw"
                if os.path.exists(f_raw):
                    os.remove(f_raw)
            except Exception:
                pass

        # Esperar 1 hora (o MINUTOS_ESPERA_LIMPIEZA) para limpiar ventanas y avisos temporales de la sala
        minutos_espera_limpieza = int(os.environ.get("MINUTOS_ESPERA_LIMPIEZA", "60"))
        segundos_espera_limpieza = max(0, minutos_espera_limpieza * 60)
        if segundos_espera_limpieza > 0:
            print(f"⏳ Sala concluida y reportes entregados. Esperando {minutos_espera_limpieza} min ({segundos_espera_limpieza}s) para limpiar ventanas y avisos temporales de la sala...")
            await asyncio.sleep(segundos_espera_limpieza)
        print(f"🧹 Iniciando limpieza de ventanas y notificaciones temporales ({len(ids_mensajes_efimeros)} mensajes)...")
        await limpiar_mensajes_temporales(client, entidad, ids_mensajes_efimeros)
        print("✨ Limpieza completada: la sala quedó limpia de mensajes y ventanas operativas.")


if __name__ == "__main__":
    asyncio.run(main())
