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
import threading
import shutil
import tempfile
import urllib.request
import urllib.parse
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
API_ID = int((os.environ.get("TG_API_ID", "0") or "0").strip())
API_HASH = (os.environ.get("TG_API_HASH", "") or "").strip()
SESSION = (os.environ.get("TG_SESSION", "") or "").strip()
GRUPO = (os.environ.get("TG_GROUP", "") or "").strip()
BOT_TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()
BOT_ID = int(BOT_TOKEN.split(":")[0]) if (BOT_TOKEN and ":" in BOT_TOKEN) else None
CHAT_ID = (os.environ.get("CHAT_ID") or GRUPO or "").strip()
TITULO = os.environ.get("CALL_TITLE", "VIDEOLLAMADA ''GRUPO LA VERDAD OS HARA LIBRES UNIFICADOS AL MAESTRO MARIO CARRILLO DURAN''")
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
SEGUNDOS_INACTIVIDAD_MUTE = int(os.environ.get("SEGUNDOS_INACTIVIDAD_MUTE", "30"))  # 30s de silencio antes de auto-cerrar mic por olvido
# Durante la meditación, un usuario NORMAL con el micrófono abierto solo se silencia tras esta gracia continua (no a los 2s)
SEGUNDOS_GRACIA_MUTE_MEDITACION = int(os.environ.get("SEGUNDOS_GRACIA_MUTE_MEDITACION", "25"))
# Nombres de los administradores principales: jamás se silencian
NOMBRES_ADMIN_PROTEGIDOS = ("gerardo", "mario", "claudia", "maricela", "carrillo")
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
    es_hoy_explicito = any(k in t_lower for k in (
        "reunión de hoy", "reunion de hoy", "práctica de hoy", "practica de hoy",
        "audio adicional", "30 minutos después", "30 minutos despues",
        "mensaje del maestro jesus mario", "se programo nuevo audio"
    ))
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
    if es_hoy_explicito and not es_manana_explicito:
        return "hoy a las 8:32 PM", "Tarea de hoy"

    if fecha_extraida:
        try:
            d_obj = datetime.strptime(fecha_extraida, "%d/%m/%Y").replace(tzinfo=tz_col)
            if d_obj.date() == hoy_real and not es_manana_explicito:
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


def avisar_con_bot(texto: str, boton_url: str = None, reply_markup: dict = None, es_efimero: bool = False, parse_mode: str = None) -> list[int]:
    if not BOT_TOKEN:
        return []
    texto = texto.replace("{CA}", hora_california())
    if not parse_mode:
        texto = texto.replace("**", "").replace("`", "")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    bloques = dividir_mensaje(texto)
    ids_enviados = []
    for idx, bloque in enumerate(bloques):
        payload = {"chat_id": CHAT_ID, "text": bloque}
        if parse_mode:
            payload["parse_mode"] = parse_mode

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


def editar_mensaje_bot_sync(message_id: int, texto: str, reply_markup: dict = None, parse_mode: str = "Markdown") -> bool:
    if not BOT_TOKEN or not message_id or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "text": texto,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


async def editar_mensaje_bot(message_id: int, texto: str, reply_markup: dict = None, parse_mode: str = "Markdown") -> bool:
    return await asyncio.to_thread(editar_mensaje_bot_sync, message_id, texto, reply_markup, parse_mode)


def responder_callback_query_sync(callback_query_id: str, texto: str = None, alert: bool = False) -> bool:
    if not BOT_TOKEN or not callback_query_id:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if texto:
        payload["text"] = texto
        payload["show_alert"] = alert
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


async def responder_callback_query(callback_query_id: str, texto: str = None, alert: bool = False) -> bool:
    return await asyncio.to_thread(responder_callback_query_sync, callback_query_id, texto, alert)


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
    dir_salida = os.path.dirname(ruta_salida)
    if dir_salida:
        os.makedirs(dir_salida, exist_ok=True)
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


def obtener_duracion_segundos(ruta_audio: str) -> float:
    """Obtiene la duración en segundos de un archivo de audio usando ffprobe."""
    if not ruta_audio or not os.path.exists(ruta_audio):
        return 3.5
    try:
        fbin = shutil.which("ffprobe") or "ffprobe"
        cmd = [
            fbin, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            ruta_audio
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception:
        pass
    return 3.5


def obtener_sonido_campana_inicio() -> str:
    """Busca el archivo de sonido para el inicio de la meditación o genera uno por defecto."""
    candidatos = [
        "sonido inicio meditacion.flac",
        "sonido inicio meditacion.wav",
        "sonido inicio meditacion.mp3",
        os.path.join("data", "sonido inicio meditacion.flac"),
        os.path.join("data", "sonido inicio meditacion.wav"),
        os.path.join("data", "sonido inicio meditacion.mp3"),
        os.path.join(CARPETA_MEDITACIONES, "sonido inicio meditacion.flac"),
        os.path.join(CARPETA_MEDITACIONES, "sonido inicio meditacion.wav"),
        os.path.join(CARPETA_MEDITACIONES, "sonido inicio meditacion.mp3"),
        "tibetan-singing-bowl-for-meditation-cuenco-tibetano-para-meditacion.mp3",
        os.path.join("data", "tibetan-singing-bowl-for-meditation-cuenco-tibetano-para-meditacion.mp3"),
        os.path.join(CARPETA_MEDITACIONES, "tibetan-singing-bowl-for-meditation-cuenco-tibetano-para-meditacion.mp3"),
    ]
    for c in candidatos:
        if os.path.exists(c) and os.path.getsize(c) > 1000:
            return os.path.abspath(c)
    return generar_sonido_campana_gong()


def obtener_sonido_campana_salida() -> str:
    """Busca el archivo de sonido para el final de la meditación o genera uno por defecto."""
    candidatos = [
        "sonido salida meditacion.wav",
        "sonido salida meditacion.flac",
        "sonido salida meditacion.mp3",
        os.path.join("data", "sonido salida meditacion.wav"),
        os.path.join("data", "sonido salida meditacion.flac"),
        os.path.join("data", "sonido salida meditacion.mp3"),
        os.path.join(CARPETA_MEDITACIONES, "sonido salida meditacion.wav"),
        os.path.join(CARPETA_MEDITACIONES, "sonido salida meditacion.flac"),
        os.path.join(CARPETA_MEDITACIONES, "sonido salida meditacion.mp3"),
    ]
    for c in candidatos:
        if os.path.exists(c) and os.path.getsize(c) > 1000:
            return os.path.abspath(c)
    return generar_sonido_campana_gong()


def obtener_pitido_inicial_oracion() -> str | None:
    """Retorna la ruta absoluta del pitido inicial de oración si existe."""
    candidatos = [
        "PITIDO INICIAL ORACION.wav",
        os.path.join("data", "PITIDO INICIAL ORACION.wav"),
        os.path.join(CARPETA_MEDITACIONES, "PITIDO INICIAL ORACION.wav"),
    ]
    for c in candidatos:
        if os.path.exists(c) and os.path.getsize(c) > 1000:
            return os.path.abspath(c)
    return None


def obtener_pitido_final_oracion() -> str | None:
    """Retorna la ruta absoluta del pitido final de oración si existe."""
    candidatos = [
        "PITIDO FINAL ORACION.wav",
        os.path.join("data", "PITIDO FINAL ORACION.wav"),
        os.path.join(CARPETA_MEDITACIONES, "PITIDO FINAL ORACION.wav"),
    ]
    for c in candidatos:
        if os.path.exists(c) and os.path.getsize(c) > 1000:
            return os.path.abspath(c)
    return None


_lock_gongs = threading.Lock()


def agregar_gongs_al_audio(ruta_audio: str) -> str:
    """Inserta sonido de inicio y salida antes y después de la meditación de forma atómica y segura."""
    if not os.path.exists(ruta_audio):
        return ruta_audio
    with _lock_gongs:
        ruta_con_gong = os.path.join(CARPETA_MEDITACIONES, "meditacion_con_gong.mp3")
        ruta_con_gong_tmp = os.path.join(CARPETA_MEDITACIONES, "meditacion_con_gong.tmp.mp3")
        s_inicio = obtener_sonido_campana_inicio()
        s_salida = obtener_sonido_campana_salida()
        dur_base = obtener_duracion_segundos(ruta_audio)
        try:
            mtime_max = max(
                os.path.getmtime(ruta_audio),
                os.path.getmtime(s_inicio) if os.path.exists(s_inicio) else 0,
                os.path.getmtime(s_salida) if os.path.exists(s_salida) else 0,
            )
            # Reutilizar si ya fue generado válidamente (tamaño > 5000 y duración completa comprobada)
            if os.path.exists(ruta_con_gong) and os.path.getsize(ruta_con_gong) > 5000 and os.path.getmtime(ruta_con_gong) >= mtime_max:
                dur_existente = obtener_duracion_segundos(ruta_con_gong)
                if dur_base <= 0 or dur_existente >= (dur_base - 5.0):
                    return ruta_con_gong
        except Exception:
            pass
        try:
            fbin = shutil.which("ffmpeg") or "ffmpeg"
            filter_str = (
                "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a0];"
                "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a1];"
                "[2:a]aformat=sample_rates=48000:channel_layouts=stereo[a2];"
                "[a0][a1][a2]concat=n=3:v=0:a=1[out]"
            )
            cmd = [
                fbin, "-y",
                "-i", s_inicio,
                "-i", ruta_audio,
                "-i", s_salida,
                "-filter_complex", filter_str,
                "-map", "[out]",
                "-c:a", "libmp3lame", "-b:a", "192k",
                ruta_con_gong_tmp,
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            if res.returncode == 0 and os.path.exists(ruta_con_gong_tmp) and os.path.getsize(ruta_con_gong_tmp) > 5000:
                dur_tmp = obtener_duracion_segundos(ruta_con_gong_tmp)
                # Validación de seguridad: no reemplazar si la duración quedó truncada respecto al audio base
                if dur_base > 0 and dur_tmp < (dur_base - 5.0):
                    print(f"⚠️ Audio ensamblado incompleto ({dur_tmp:.1f}s vs {dur_base:.1f}s base). Descartando temporal.")
                    if os.path.exists(ruta_con_gong_tmp):
                        try:
                            os.remove(ruta_con_gong_tmp)
                        except Exception:
                            pass
                    return ruta_audio

                if os.path.exists(ruta_con_gong):
                    try:
                        os.remove(ruta_con_gong)
                    except Exception:
                        pass
                os.replace(ruta_con_gong_tmp, ruta_con_gong)
                try:
                    print(f"🎵 Audio ensamblado con sonidos: Inicio ({os.path.basename(s_inicio)}) + Meditación ({dur_tmp:.1f}s) + Salida ({os.path.basename(s_salida)})")
                except Exception:
                    print("Audio ensamblado con sonidos: Inicio + Meditacion + Salida")
                return ruta_con_gong
        except Exception as e:
            print("Nota combinando gong con audio:", e)
        finally:
            if os.path.exists(ruta_con_gong_tmp):
                try:
                    os.remove(ruta_con_gong_tmp)
                except Exception:
                    pass
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


def generar_barra_progreso(segundos_actual: float, segundos_total: float, ancho: int = 14) -> str:
    if segundos_total <= 0:
        return "🔘" + "─" * (ancho - 1)
    ratio = max(0.0, min(1.0, segundos_actual / segundos_total))
    pos_bolita = int(round(ratio * (ancho - 1)))
    barra = ""
    for i in range(ancho):
        if i == pos_bolita:
            barra += "🔘"
        elif i < pos_bolita:
            barra += "━"
        else:
            barra += "─"
    return barra


def formatear_tiempo_mm_ss(segundos: float) -> str:
    s = max(0, int(round(segundos)))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def generar_caratula_meditacion(
    numero: str,
    titulo: str,
    maestro: str,
    duracion_seg: float = 0.0,
    ruta_salida: str = None,
    tipo: str = "MEDITACION",
) -> str | None:
    dur_s = float(duracion_seg) if duracion_seg > 0 else 1800.0
    if 0 < dur_s <= 120.0:
        dur_s *= 60.0

    tipo_norm = str(tipo or "MEDITACION").strip().upper()
    es_mensaje = "MENSAJE" in tipo_norm
    tipo_tag = "mensaje" if es_mensaje else "meditacion"
    tag = f"{tipo_tag}_{numero}" if numero else f"{tipo_tag}_diario"

    # 1. Intentar reutilizar video animado MP4 si ya fue generado para este audio específico
    if ruta_salida and ruta_salida.lower().endswith(".mp4"):
        ruta_mp4 = ruta_salida
    else:
        ruta_mp4 = os.path.join(CARPETA_MEDITACIONES, f"caratula_{tag}.mp4")

    if os.path.exists(ruta_mp4) and os.path.getsize(ruta_mp4) > 50000:
        dur_existente = obtener_duracion_segundos(ruta_mp4)
        if abs(dur_existente - dur_s) <= 15.0:
            print(f"🎬 Carátula de video MP4 ({tag}) ya existente y sincronizada ({dur_existente:.1f}s), reutilizando.")
            return ruta_mp4

    try:
        from astronomia_luna import generar_video_meditacion_luna
        vid = generar_video_meditacion_luna(
            numero=numero,
            titulo=titulo,
            maestro=maestro,
            duracion_seg=dur_s,
            ruta_salida=ruta_mp4,
            tipo=tipo_norm,
        )
        if vid and os.path.exists(vid) and os.path.getsize(vid) > 5000:
            return vid
    except Exception as e_v:
        print(f"Nota generando video animado ({tag}), usando fallback a carátula estática:", e_v)

    # 2. Fallback a imagen estática JPG de alta calidad
    try:
        from astronomia_luna import generar_caratula_meditacion_luna
        ruta_jpg = os.path.join(CARPETA_MEDITACIONES, f"caratula_{tag}.jpg")
        return generar_caratula_meditacion_luna(
            numero=numero,
            titulo=titulo,
            maestro=maestro,
            duracion_seg=dur_s,
            progreso_seg=0.0,
            ruta_salida=ruta_jpg,
            tipo=tipo_norm,
        )
    except Exception as e:
        print(f"Nota generando carátula lunar ({tag}) con astronomia_luna:", e)
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
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
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
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🎖️ **Rango actual:** {rango}\n"
        f"🏆 **Puntos del mes:** {pts_mes} pts\n"
        f"⏳ricos:** {pts_tot} pts\n"
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
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    ]
    medallas_top = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
    for i, u in enumerate(top):
        pts = u.get("puntos_mes", u.get("puntos_totales", 0))
        rango = obtener_rango(u.get("puntos_totales", 0))
        medallas = " ".join([m.split()[0] for m in u.get("medallas", [])])
        lineas.append(f"{medallas_top[i]} {rango} **{u['nombre']}** — {pts} pts {medallas}".strip())

    lineas.append("\n💡 Escribe `/puntos` para ver tus estadísticas personales.")
    return "\n".join("> " + line if line.strip() else ">" for line in lineas)


def generar_texto_reglas() -> str:
    return (
        "📜 **SISTEMA DE PUNTOS Y REGLAS DE LA COMUNIDAD**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "Cada noche a las 7:56 PM se abre la llamada diaria. ¡Participa y suma puntos!\n\n"
        "⏰ **PUNTUALIDAD:**\n"
        "• Entrar en los primeros 5 min: **+25 pts**\n"
        "• Entrar entre min 5 y 10: **+15 pts**\n\n"
        "🌟 **PERMANENCIA:**\n"
        "• Permanencia completa (>75% de la sesión): **+50 pts**\n"
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
        "✋ **TURNOS Y PARTICIPACIÓN:**\n"
        "• Escribe `/turno` en el grupo o levanta la mano ✋ en la sala para coordinar la palabra en orden.\n"
        "• Micrófonos 100% libres y sin cortes automáticos: cada participante gestiona su micrófono de forma responsable.\n\n"
        "📝 **MINUTAS Y ACTAS CON IA:**\n"
        "• Al finalizar la llamada, la IA de Google Gemini genera un resumen y acta oficial de la sesión.\n"
        "• Escribe `/buscar <palabra>` para encontrar temas tratados en llamadas anteriores.\n"
        "• Escribe `/acta [fecha]` para consultar el documento formal.\n\n"
        "👑 **GRABACIÓN (SOLO ADMINS):**\n"
        "• `/estadograbacion` — Consultar estado actual.\n"
        "• `/pausargrabacion` — Pausar grabación (ej. tema confidencial).\n"
        "• `/reanudargrabacion` — Reanudar grabación.\n"
        "• `/cancelargrabacion` — Cancelar y eliminar grabación de hoy.\n\n"
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
        ahora = datetime.now(tz_col)
        if ahora.hour < 4:
            ahora -= timedelta(days=1)
        fecha = fecha_destino or ahora.strftime("%d/%m/%Y")
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
            else:
                info_meta.pop("cola_audios", None)
            with open(ruta_meta, "w", encoding="utf-8") as fm:
                json.dump(info_meta, fm, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando cola_hoy.json:", e)


def guardar_cola_manana(cola: list[dict], fecha_destino: str = None) -> None:
    """Guarda la lista de reproducción programada para mañana en cola_manana.json y meta_manana.json."""
    try:
        os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
        tz_col = ZoneInfo("America/Bogota")
        ahora = datetime.now(tz_col)
        if ahora.hour < 4:
            ahora -= timedelta(days=1)
        fecha = fecha_destino or (ahora + timedelta(days=1)).strftime("%d/%m/%Y")
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
            else:
                info_meta.pop("cola_audios", None)
            with open(ruta_meta_manana, "w", encoding="utf-8") as fm:
                json.dump(info_meta, fm, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando cola_manana.json:", e)


def cargar_cola_hoy() -> list[dict]:
    """Carga y valida los audios previamente guardados en cola_hoy.json o promociona cola_manana.json si corresponde a hoy."""
    try:
        tz_col = ZoneInfo("America/Bogota")
        ahora = datetime.now(tz_col)
        if ahora.hour < 4:
            ahora -= timedelta(days=1)
        hoy_str = ahora.strftime("%d/%m/%Y")

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


def obtener_pista_oficial_3am(ahora: datetime | None = None) -> dict | None:
    """
    Obtiene de forma determinista e inquebrantable la Pista #1 oficial programada a las 3:00 AM para el día actual.
    Jerarquía de resolución:
    1. Si existe meta_hoy.json con fecha de HOY y un override explícito de administrador (admin_override=True), lo respeta.
    2. En cualquier otro caso, usa el número oficial del calendario matemático de las 3:00 AM (obtener_numero_meditacion_fecha).
    Retorna el diccionario de pista listo para ser Pista #1 en cola_reproduccion, con 'es_oficial_3am': True.
    """
    try:
        os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
        tz_col = ZoneInfo("America/Bogota")
        if ahora is None:
            ahora = datetime.now(tz_col)
            if ahora.hour < 4:
                ahora -= timedelta(days=1)
        hoy_str = ahora.strftime("%d/%m/%Y")
        hoy_iso = ahora.strftime("%Y-%m-%d")

        from schedule_meditaciones import obtener_numero_meditacion_fecha
        num_oficial = obtener_numero_meditacion_fecha(ahora.date())
        tipo_oficial = "MEDITACION"
        info_oficial = None

        ruta_meta = os.path.join(CARPETA_MEDITACIONES, "meta_hoy.json")
        if os.path.exists(ruta_meta):
            try:
                with open(ruta_meta, "r", encoding="utf-8") as fm:
                    meta = json.load(fm)
                f_meta = meta.get("fecha_tarea_admin") or meta.get("fecha_iso")
                if f_meta and (f_meta == hoy_str or f_meta == hoy_iso):
                    if meta.get("admin_override") and meta.get("numero") and meta.get("tipo"):
                        num_oficial = int(meta["numero"])
                        tipo_oficial = str(meta["tipo"]).upper()
                        info_oficial = dict(meta)
                    elif str(meta.get("numero", "")).strip() == str(num_oficial):
                        info_oficial = dict(meta)
            except Exception as e_m:
                print("Nota leyendo meta_hoy.json en obtener_pista_oficial_3am:", e_m)

        if not info_oficial:
            info_oficial = identificar_audio_catalogo(f"{tipo_oficial.lower()} {num_oficial}") or {
                "numero": num_oficial,
                "tipo": tipo_oficial,
                "titulo": f"Meditación #{num_oficial}",
                "fecha": ahora.strftime("%d/%m/%y"),
                "maestro": "Alaniso",
                "detectado_como": tipo_oficial,
            }

        info_oficial.pop("cola_audios", None)
        info_oficial["fecha_tarea_admin"] = hoy_str
        info_oficial["fecha_iso"] = hoy_iso
        info_oficial["es_oficial_3am"] = True
        info_oficial["es_adicional"] = False
        info_oficial["es_mario"] = False

        print(f"🌟 Asegurando Pista #1 Oficial de las 3:00 AM: {tipo_oficial} #{num_oficial} (para hoy {hoy_str})...")
        r_drive = obtener_o_descargar_audio(tipo_oficial, int(num_oficial))
        if r_drive and os.path.exists(r_drive) and os.path.getsize(r_drive) > 5000:
            return {
                "ruta": r_drive,
                "info": info_oficial,
                "titulo": info_oficial.get("titulo", f"{tipo_oficial} #{num_oficial}"),
                "es_oficial_3am": True,
            }
    except Exception as e_of:
        print("Nota en obtener_pista_oficial_3am:", e_of)
    return None


async def sincronizar_cola_con_render_y_grupo(client, entidad, cola_actual: list, hoy_str: str | None = None) -> list[dict]:
    """
    Sincroniza la cola de reproducción local (en GitHub Actions) con:
    1) La Pista #1 Oficial programada a las 3:00 AM (prioridad absoluta e inquebrantable).
    2) El endpoint /estado_cola de Render (https://bot-meditaciones.onrender.com/estado_cola).
    3) Los últimos 50 mensajes del grupo en Telegram (detectando audios adicionales del Maestro Mario Carrillo subidos hoy).
    Garantiza SIEMPRE que la Meditación Oficial de las 3:00 AM sea Pista #1 y cualquier otro audio sea Pista #2+.
    """
    try:
        os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
        tz_col = ZoneInfo("America/Bogota")
        ahora = datetime.now(tz_col)
        if ahora.hour < 4:
            ahora -= timedelta(days=1)
        if not hoy_str:
            hoy_str = ahora.strftime("%d/%m/%Y")

        from schedule_meditaciones import obtener_numero_meditacion_fecha
        num_oficial_3am = obtener_numero_meditacion_fecha(ahora.date())

        def _es_pista_oficial_3am(item_p: dict) -> bool:
            if not isinstance(item_p, dict):
                return False
            if item_p.get("es_oficial_3am"):
                return True
            inf_p = item_p.get("info") or {}
            if inf_p.get("es_oficial_3am"):
                return True
            if inf_p.get("es_mario") or inf_p.get("es_adicional"):
                return False
            num_p = str(inf_p.get("numero") or "").strip()
            return bool(num_p and num_p == str(num_oficial_3am))

        def _ya_en_cola(inf_cand: dict, tit_cand: str = "", msg_id_cand: int | None = None) -> bool:
            vid_c = str((inf_cand or {}).get("video_id") or "").strip()
            mid_c = msg_id_cand or (inf_cand or {}).get("msg_id_audio")
            num_c = str((inf_cand or {}).get("numero") or "").strip()
            tipo_c = str((inf_cand or {}).get("tipo") or "").strip().upper()
            tit_c_norm = (tit_cand or (inf_cand or {}).get("titulo") or "").strip().lower()
            for it_ex in cola_actual:
                inf_ex = it_ex.get("info") or {}
                if vid_c and str(inf_ex.get("video_id") or "").strip() == vid_c:
                    return True
                if mid_c and inf_ex.get("msg_id_audio") and str(inf_ex.get("msg_id_audio")) == str(mid_c):
                    return True
                if num_c and str(inf_ex.get("numero") or "").strip() == num_c and str(inf_ex.get("tipo") or "").strip().upper() == tipo_c:
                    return True
                tit_ex_norm = (it_ex.get("titulo") or inf_ex.get("titulo") or "").strip().lower()
                if tit_c_norm and len(tit_c_norm) > 6 and (tit_c_norm == tit_ex_norm or tit_c_norm in tit_ex_norm or (tit_ex_norm and len(tit_ex_norm) > 6 and tit_ex_norm in tit_c_norm)):
                    return True
            return False

        hubo_cambios = False

        # 0. BLINDAJE INQUEBRANTABLE: Garantizar que la Pista #1 Oficial de las 3:00 AM esté presente en la cola
        if not any(_es_pista_oficial_3am(it) for it in cola_actual):
            pista_3am = await asyncio.to_thread(obtener_pista_oficial_3am, ahora)
            if pista_3am:
                cola_actual.insert(0, pista_3am)
                hubo_cambios = True
                print(f"🛡️ Blindaje 3:00 AM: Pista #1 oficial insertada al frente -> {pista_3am.get('titulo')}")

        # 1. Consultar /estado_cola en Render
        def _fetch_estado_render():
            try:
                url_r = "https://bot-meditaciones.onrender.com/estado_cola"
                req_r = urllib.request.Request(url_r, headers={"User-Agent": "LlamadaSync"})
                with urllib.request.urlopen(req_r, timeout=6) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception:
                return {}

        datos_render = await asyncio.to_thread(_fetch_estado_render)
        if isinstance(datos_render, dict) and datos_render.get("status") == "ok" and datos_render.get("fecha") == hoy_str:
            items_remotos = []
            for c_rem in (datos_render.get("cola_hoy") or []):
                if isinstance(c_rem, dict) and c_rem.get("info"):
                    items_remotos.append(c_rem["info"])
            info_h_rem = datos_render.get("info_hoy") or {}
            for c_aud in (info_h_rem.get("cola_audios") or []):
                if isinstance(c_aud, dict):
                    items_remotos.append(c_aud)

            for inf_r in items_remotos:
                if _ya_en_cola(inf_r):
                    continue
                vid_r = str(inf_r.get("video_id") or "").strip()
                mid_r = inf_r.get("msg_id_audio")
                ruta_local_r = None

                if vid_r:
                    cand_yt = os.path.join(CARPETA_MEDITACIONES, f"yt_dl_{vid_r}.mp3")
                    if os.path.exists(cand_yt) and os.path.getsize(cand_yt) > 5000:
                        ruta_local_r = cand_yt

                if not ruta_local_r and mid_r:
                    try:
                        msg_tg = await client.get_messages(entidad, ids=int(mid_r))
                        if msg_tg and (msg_tg.audio or msg_tg.voice or msg_tg.document):
                            dest_dl = os.path.join(CARPETA_MEDITACIONES, f"yt_dl_{vid_r or mid_r}.mp3")
                            await client.download_media(msg_tg, file=dest_dl)
                            if os.path.exists(dest_dl) and os.path.getsize(dest_dl) > 5000:
                                ruta_local_r = dest_dl
                    except Exception as e_dl_r:
                        print(f"Nota descargando msg_id_audio={mid_r} desde grupo:", e_dl_r)

                if not ruta_local_r and inf_r.get("numero") and inf_r.get("tipo") and not inf_r.get("es_mario"):
                    try:
                        r_drv = obtener_o_descargar_audio(inf_r["tipo"], int(inf_r["numero"]))
                        if r_drv and os.path.exists(r_drv) and os.path.getsize(r_drv) > 5000:
                            ruta_local_r = r_drv
                    except Exception:
                        pass

                if ruta_local_r and os.path.exists(ruta_local_r) and os.path.getsize(ruta_local_r) > 5000:
                    inf_copia = dict(inf_r)
                    if str(inf_copia.get("numero") or "").strip() != str(num_oficial_3am):
                        inf_copia["es_adicional"] = True
                    cola_actual.append({
                        "ruta": ruta_local_r,
                        "info": inf_copia,
                        "titulo": inf_copia.get("titulo") or f"Pista #{len(cola_actual) + 1}"
                    })
                    hubo_cambios = True
                    print(f"🔄 Pista sincronizada desde Render (/estado_cola): {inf_copia.get('titulo')} -> {ruta_local_r}")

        # 2. Escanear los últimos 50 mensajes del grupo buscando audios adicionales subidos hoy (incluso por BOT_ID)
        audios_extra_grupo = []
        try:
            async for msg_g in client.iter_messages(entidad, limit=50):
                if not (msg_g.audio or msg_g.voice or (msg_g.document and getattr(msg_g.document, "mime_type", "") and "audio" in msg_g.document.mime_type)):
                    continue
                txt_g = (msg_g.raw_text or "").strip()
                txt_g_up = txt_g.upper()
                es_adicional_mario = (
                    "MENSAJE DEL MAESTRO JESUS MARIO CARRILLO" in txt_g_up
                    or "AUDIO ADICIONAL PREPARADO PARA SONAR" in txt_g_up
                    or "ENCOLADO +30 MIN" in txt_g_up
                )
                if not es_adicional_mario:
                    continue
                fecha_m = extraer_fecha_de_texto(txt_g, fecha_referencia=msg_g.date)
                if not fecha_m and msg_g.date:
                    dt_m = msg_g.date.astimezone(tz_col) if msg_g.date.tzinfo else msg_g.date.replace(tzinfo=tz_col)
                    if dt_m.hour < 4:
                        dt_m -= timedelta(days=1)
                    fecha_m = dt_m.strftime("%d/%m/%Y")
                if fecha_m == hoy_str:
                    audios_extra_grupo.append(msg_g)
        except Exception as e_sc_g:
            print("Nota escaneando grupo para audios adicionales:", e_sc_g)

        for m_ext in reversed(audios_extra_grupo):
            txt_ext = (m_ext.raw_text or "").strip()
            m_tit = re.search(r"«([^»]+)»", txt_ext)
            tit_ext = m_tit.group(1).strip() if m_tit else (getattr(m_ext.audio, "title", "") or getattr(m_ext.audio, "file_name", "") or f"Mensaje Maestro Mario Carrillo #{m_ext.id}")
            inf_cand = {
                "numero": "",
                "tipo": "MENSAJE",
                "titulo": tit_ext,
                "maestro": "JESUS MARIO CARRILLO DURAN",
                "fecha": hoy_str,
                "fecha_tarea_admin": hoy_str,
                "es_mario": True,
                "es_adicional": True,
                "espera_post_meditacion_min": 30,
                "msg_id_audio": m_ext.id
            }
            if _ya_en_cola(inf_cand, tit_cand=tit_ext, msg_id_cand=m_ext.id):
                continue
            dest_ext = os.path.join(CARPETA_MEDITACIONES, f"meditacion_extra_{m_ext.id}.mp3")
            if not (os.path.exists(dest_ext) and os.path.getsize(dest_ext) > 5000):
                try:
                    await client.download_media(m_ext, file=dest_ext)
                except Exception as e_dl_ext:
                    print(f"Nota descargando audio adicional msg={m_ext.id}:", e_dl_ext)
            if os.path.exists(dest_ext) and os.path.getsize(dest_ext) > 5000:
                cola_actual.append({
                    "ruta": dest_ext,
                    "info": inf_cand,
                    "titulo": tit_ext
                })
                hubo_cambios = True
                print(f"🔄 Audio adicional detectado en el grupo y encolado para hoy: «{tit_ext}» (msg_id={m_ext.id})")

        # 3. Asegurar SIEMPRE que la Pista #1 sea la Meditación Oficial de las 3:00 AM y todo lo demás vaya detrás (Pista #2+)
        if len(cola_actual) > 1:
            pistas_3am = [c for c in cola_actual if _es_pista_oficial_3am(c)]
            adicionales = [c for c in cola_actual if not _es_pista_oficial_3am(c)]
            if pistas_3am:
                for ad in adicionales:
                    if isinstance(ad.get("info"), dict):
                        ad["info"]["es_adicional"] = True
                nueva_orden = [pistas_3am[0]] + adicionales
                if nueva_orden != cola_actual:
                    cola_actual[:] = nueva_orden
                    hubo_cambios = True

        if hubo_cambios and cola_actual:
            guardar_cola_hoy(cola_actual, fecha_destino=hoy_str)
    except Exception as e_sync_all:
        print("Nota en sincronizar_cola_con_render_y_grupo:", e_sync_all)
    return cola_actual


async def buscar_audio_meditacion(client, entidad, admin_ids) -> tuple[str | None, dict | None, list[dict]]:
    """
    Resuelve la lista de reproducción de hoy con PRIORIDAD ABSOLUTA E INQUEBRANTABLE
    para la meditación programada a las 3:00 AM como Pista #1:
    1. Obtiene siempre la Meditación Oficial de las 3:00 AM (calendario oficial / meta_hoy.json) y la fija como Pista #1.
    2. Si existían pistas adicionales en cola_hoy.json para hoy, las conserva como Pista #2+.
    3. Sincroniza con Render (/estado_cola) y los audios adicionales del grupo (Maestro Mario Carrillo), siempre detrás de la Pista #1.
    Retorna (ruta_primera, info_primera, lista_cola_completa).
    """
    try:
        os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
        tz_col = ZoneInfo("America/Bogota")
        ahora = datetime.now(tz_col)
        if ahora.hour < 4:
            ahora -= timedelta(days=1)
        hoy_str = ahora.strftime("%d/%m/%Y")

        cola_base = []

        # 1. PRIORIDAD #1 INQUEBRANTABLE: Meditación Oficial programada a las 3:00 AM
        pista_oficial = await asyncio.to_thread(obtener_pista_oficial_3am, ahora)
        if pista_oficial:
            cola_base.append(pista_oficial)

        # 2. Conservar únicamente pistas adicionales legítimas guardadas previamente en cola_hoy.json para hoy
        cola_guardada = cargar_cola_hoy()
        if cola_guardada:
            num_of = str(((pista_oficial or {}).get("info") or {}).get("numero") or "").strip()
            for item_g in cola_guardada:
                inf_g = item_g.get("info") or {}
                num_g = str(inf_g.get("numero") or "").strip()
                if num_of and num_g == num_of and not inf_g.get("es_mario"):
                    continue  # Ya está en Pista #1
                if isinstance(inf_g, dict):
                    inf_g["es_adicional"] = True
                cola_base.append(item_g)

        # 3. Sincronizar SIEMPRE con Render (/estado_cola) y los audios adicionales del grupo en Telegram
        cola_base = await sincronizar_cola_con_render_y_grupo(client, entidad, cola_base, hoy_str=hoy_str)

        if cola_base:
            guardar_cola_hoy(cola_base, fecha_destino=hoy_str)
            primera = cola_base[0]
            return primera["ruta"], primera.get("info"), cola_base

    except Exception as e:
        print("Nota buscando audio de meditación:", e)

    return None, None, []


def generar_texto_turnos(cola: list, oradores: list) -> str:
    lineas = [
        "🎙️ **LISTA DE TURNOS EN VIVO** ✋",
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    ]
    if oradores:
        txt_oradores = ", ".join([f"**{o}**" for o in oradores])
        lineas.append(f"🗣️ **Hablando ahora:** {txt_oradores}")
    else:
        lineas.append("🗣️ **Hablando ahora:** Micrófono libre 🎙️")

    lineas.append("\n⏳ **En lista de espera:**")
    if cola:
        for idx, item in enumerate(cola, 1):
            nom_u = item['nombre']
            if idx == 1:
                # PRIMER TURNO: Máximo realce visual
                lineas.append("")
                lineas.append(f"✨👉 1️⃣ **{nom_u.upper()}** 👈✨")
                lineas.append(f"      🌟 *(¡LE TOCA A CONTINUACIÓN!)* 🌟")
                lineas.append(f"      ━━━━━━━━━━━━━━━━━━━━━━")
            else:
                lineas.append(f"{idx}. ✋ **{nom_u}**")
    else:
        lineas.append("Nadie en lista de espera.")

    lineas.append("")
    lineas.append("💡 Escribe `/turno` en el grupo o levanta la mano ✋ en la sala para pedir la palabra.")
    return "\n".join("> " + line if line.strip() else ">" for line in lineas)


async def main() -> None:
    tz_col = ZoneInfo("America/Bogota")
    inicio_llamada = datetime.now(tz_col)
    if inicio_llamada.hour < 4:
        inicio_llamada -= timedelta(days=1)
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
        checked_admins_cache = set()
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

        # Lista de Administradores Permanentes conocidos (Gerardo, Claudia, Maricela, Mario Carrillo) para protección total
        for hard_admin in (8204833441, 8278899029, 8916842088, 8384683142, 1779560581, 6902578190):
            admin_ids.add(hard_admin)

        # Cargar administradores oficiales vía Bot API si BOT_TOKEN está configurado
        if BOT_TOKEN and hasattr(entidad, "id"):
            try:
                import urllib.request
                import json
                for c_id in (entidad.id, f"-100{entidad.id}", f"-{entidad.id}"):
                    try:
                        url_adm = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatAdministrators?chat_id={c_id}"
                        req_adm = urllib.request.Request(url_adm, headers={"User-Agent": "BotLlamada"})
                        with urllib.request.urlopen(req_adm, timeout=6) as r_adm:
                            data_adm = json.loads(r_adm.read().decode())
                            if data_adm.get("ok"):
                                for item_adm in data_adm.get("result", []):
                                    u_adm = item_adm.get("user", {})
                                    if u_adm.get("id"):
                                        admin_ids.add(int(u_adm["id"]))
                                        print(f"👑 Admin detectado vía Bot API: {u_adm.get('first_name', '')} ({u_adm['id']})")
                                break
                    except Exception:
                        pass
            except Exception as e_adm_api:
                print("Nota obteniendo administradores vía bot API:", e_adm_api)

        try:
            if isinstance(entidad, (Channel, Chat)):
                async for admin in client.iter_participants(entidad, filter=ChannelParticipantsAdmins):
                    admin_ids.add(admin.id)
        except Exception as e:
            print("Nota obteniendo administradores:", e)
        async def background_admin_refresher():
            while True:
                await asyncio.sleep(60)
                try:
                    if isinstance(entidad, (Channel, Chat)):
                        async for admin in client.iter_participants(entidad, filter=ChannelParticipantsAdmins):
                            admin_ids.add(admin.id)
                except Exception:
                    pass
        client.loop.create_task(background_admin_refresher())

        ADMINS_OFICIALES_FIJOS = {8204833441, 8278899029, 8916842088, 8384683142, 1779560581, 6902578190, 8953593022}
        for hard_admin in ADMINS_OFICIALES_FIJOS:
            admin_ids.add(hard_admin)

        async def es_admin_seguro(ev, sender_obj=None) -> bool:
            try:
                # 0. Chequeo directo si ev es un ID numérico
                if isinstance(ev, int):
                    if ev in admin_ids or ev in ADMINS_OFICIALES_FIJOS:
                        return True
                    uid = ev
                else:
                    uid = getattr(sender_obj, "id", None) if sender_obj else getattr(ev, "sender_id", None)

                # 1. Chequeo si el emisor es el bot mismo
                if uid and (uid == me.id or (BOT_ID and uid == BOT_ID)):
                    return True

                # 2. Si el mensaje es una publicación del canal o enviado en nombre del grupo (modo anónimo)
                # En Telegram, SOLO los administradores pueden enviar mensajes en nombre del grupo o como canal anónimo
                if getattr(ev.message, "post", False):
                    return True

                # Telegram @GroupAnonymousBot o Servicio de Telegram
                if uid in (1087968824, 777000):
                    return True

                # Comparación con IDs del chat/canal (si se envía como el grupo)
                chat_id = getattr(ev, "chat_id", None)
                entidad_id = getattr(entidad, "id", None) if hasattr(entidad, "id") else None

                ids_grupo_posibles = set()
                if chat_id is not None:
                    ids_grupo_posibles.add(chat_id)
                    ids_grupo_posibles.add(abs(chat_id))
                if entidad_id is not None:
                    ids_grupo_posibles.add(entidad_id)
                    ids_grupo_posibles.add(-abs(entidad_id))
                    try:
                        ids_grupo_posibles.add(int(f"-100{entidad_id}"))
                    except Exception:
                        pass

                if uid is not None and uid in ids_grupo_posibles:
                    return True

                from_id = getattr(ev.message, "from_id", None)
                if from_id is None and getattr(ev, "is_group", False):
                    return True
                if isinstance(from_id, PeerChannel):
                    p_cid = getattr(from_id, "channel_id", None)
                    if p_cid and (p_cid == entidad_id or p_cid == abs(chat_id or 0)):
                        return True

                # 3. Si sender_obj es un Channel o Chat (enviado como canal o identidad de grupo)
                if sender_obj is None:
                    try:
                        sender_obj = await ev.get_sender()
                    except Exception:
                        sender_obj = None

                if isinstance(sender_obj, (Channel, Chat)):
                    s_id = getattr(sender_obj, "id", None)
                    if s_id and s_id in ids_grupo_posibles:
                        return True
                    s_tit = (getattr(sender_obj, "title", "") or "").lower()
                    if any(k in s_tit for k in ("verdad", "carrillo", "mario", "libres", "gerardo", "claudia", "maricela")):
                        if s_id:
                            admin_ids.add(s_id)
                        return True

                # 4. Chequeo por lista admin_ids o IDs duros de los 7 administradores
                if uid is not None and (uid in admin_ids or uid in ADMINS_OFICIALES_FIJOS):
                    admin_ids.add(uid)
                    return True

                # 5. Chequeo por Nombre, Apellido, Username o Título del emisor
                if sender_obj:
                    tokens = [
                        getattr(sender_obj, "first_name", "") or "",
                        getattr(sender_obj, "last_name", "") or "",
                        getattr(sender_obj, "username", "") or "",
                        getattr(sender_obj, "title", "") or "",
                    ]
                    nombre_completo = " ".join(tokens).lower()
                    if any(k in nombre_completo for k in ("gerardo", "mario", "claudia", "maricela", "carrillo")):
                        if uid:
                            admin_ids.add(uid)
                        return True

                # 6. Verificación dinámica en vivo con Telegram
                if uid:
                    for dest_cand in (entidad, chat_id):
                        if dest_cand is None:
                            continue
                        try:
                            perm_sender = await client.get_permissions(dest_cand, uid)
                            if (
                                getattr(perm_sender, "is_admin", False)
                                or getattr(perm_sender, "is_creator", False)
                                or getattr(perm_sender, "manage_call", False)
                                or getattr(perm_sender, "change_info", False)
                                or getattr(perm_sender, "delete_messages", False)
                            ):
                                admin_ids.add(uid)
                                return True
                        except Exception:
                            pass
            except Exception as e_chk:
                print("Nota en verificación de admin:", e_chk)

            return False

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
        avisar_con_bot(AVISO, boton_url=url_llamada, es_efimero=False)

        if not full_chat or not full_chat.call:
            print("No hay llamada disponible para monitorear.")
            return

        input_call = full_chat.call
        try:
            from telethon.tl.functions.phone import EditGroupCallTitleRequest
            await client(EditGroupCallTitleRequest(call=input_call, title=TITULO))
            print(f"🏷️ Título de la sala de voz configurado a: '{TITULO}'.")
        except Exception as e_tit:
            print(f"Nota actualizando título de sala: {e_tit}")
        try:
            await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
            print("🔓 Configuración de sala: join_muted=False (micrófonos libres al entrar).")
        except Exception as e_tg:
            print("Nota configurando join_muted=False:", e_tg)

        print(f"Iniciando monitoreo de la sala (Máx: {DURACION_MAXIMA_MINUTOS} min)...")

        # Estado del sistema de moderación de voz y turnos
        participantes = {}
        participantes_conectados = set()  # uids actualmente conectados a la sala
        users_cache = {}  # uid -> User
        chats_cache = {}  # cid -> Chat / Channel

        def es_participante_admin(uid, nombre="", peer=None) -> bool:
            """True si hay CUALQUIER indicio de que el participante es administrador (o una identidad
            no-usuario como canal/anónimo). Estos participantes NUNCA se silencian."""
            try:
                if uid in admin_ids or uid in ADMINS_OFICIALES_FIJOS:
                    return True
                # Identidad de canal/chat/anónimo en la llamada: no se puede verificar permisos -> proteger
                if peer is not None and not isinstance(peer, PeerUser):
                    return True
                nom = (nombre or "").lower()
                if any(k in nom for k in NOMBRES_ADMIN_PROTEGIDOS):
                    admin_ids.add(uid)
                    return True
                u_obj = users_cache.get(uid)
                if u_obj is not None:
                    nom_u = f"{getattr(u_obj, 'first_name', '') or ''} {getattr(u_obj, 'last_name', '') or ''}".lower()
                    if any(k in nom_u for k in NOMBRES_ADMIN_PROTEGIDOS):
                        admin_ids.add(uid)
                        return True
            except Exception as e_adm:
                print("Nota en es_participante_admin (se protege por defecto):", e_adm)
                return True
            return False
        cola_turnos = []  # [{"id": uid, "nombre": nom, "username": usr}]
        oradores_activos = set()  # uids actualmente hablando
        segundos_inactividad_mic = {}  # uid -> segundos con mic abierto y sin voz
        avisados_auto_mute = set()  # uids notificados cordialmente
        msg_turnos = None  # Mensaje en vivo con la cola de turnos
        lista_turnos_activa = True  # Permite activar/desactivar el cartel de LISTA DE TURNOS EN VIVO a conveniencia
        lock_turnos = asyncio.Lock()
        mensajes_chat_recientes = 0
        ultimo_envio_turnos = 0
        bloqueo_flood_hasta = 0.0
        ultimo_texto_turnos = None
        INTERVALO_MIN_REPUBLICAR = 90  # segundos mínimos entre republicaciones al fondo

        async def actualizar_mensaje_turnos(forzar_al_fondo: bool = False):
            nonlocal msg_turnos, mensajes_chat_recientes, ultimo_envio_turnos, bloqueo_flood_hasta, ultimo_texto_turnos
            if not lista_turnos_activa:
                return
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
                                ultimo_envio_turnos = ahora
                                mensajes_chat_recientes = 0
                            except Exception as e2:
                                print("Nota reenviando mensaje de turnos:", e2)

        async def cambiar_estado_lista_turnos(activar: bool | None = None) -> tuple[bool, str]:
            nonlocal lista_turnos_activa, msg_turnos, ultimo_texto_turnos, ultimo_envio_turnos
            nuevo_estado = (not lista_turnos_activa) if activar is None else bool(activar)
            lista_turnos_activa = nuevo_estado
            if not lista_turnos_activa:
                if msg_turnos:
                    try:
                        await client.delete_messages(entidad, msg_turnos)
                        ids_mensajes_efimeros.discard(getattr(msg_turnos, "id", None))
                    except Exception:
                        pass
                    msg_turnos = None
                ultimo_texto_turnos = None
                return False, "📴 **Cartel de `LISTA DE TURNOS EN VIVO` desactivado y ocultado del grupo.**\n*(Para volver a encenderlo escribe `/activarturnos` o presiona el botón en `/panel`)*."
            else:
                ultimo_texto_turnos = None
                ultimo_envio_turnos = 0
                await actualizar_mensaje_turnos(forzar_al_fondo=True)
                return True, "✅ **Cartel de `LISTA DE TURNOS EN VIVO` activado y visible en el grupo.**\n*(Para ocultarlo escribe `/apagarturnos` o presiona el botón en `/panel`)*."

        # Mensaje fijado dinámico en el grupo
        msg_fijado = None
        texto_fijado_base = (
            "🎙️ **ESTADO DE LA SALA EN VIVO**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
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
                return False, "🛑 La grabación ya fue cancelada definitivamente para la sesión de hoy."
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
                return False, "🛑 La grabación fue cancelada definitivamente para esta sesión."
            if not grabacion_pausada:
                return False, "ℹ️ La grabación ya está activa y grabando."
            grabacion_pausada = False
            contador_segmentos += 1
            nueva_ruta = os.path.join(CARPETA_ASISTENCIAS, f"grabacion_seg_{contador_segmentos}_{fecha_hoy}.mp3")
            segmentos_grabados.append(nueva_ruta)
            if tgcalls:
                try:
                    from pytgcalls.types import RecordStream
                    os.makedirs(os.path.dirname(os.path.abspath(nueva_ruta)), exist_ok=True)
                    await tgcalls.record(destino, RecordStream(nueva_ruta))
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
            return True, "🛑 **Grabación cancelada y eliminada para la sesión de hoy.**\nNo se generará audio ni minuta con IA al finalizar la sala."

        def estado_grabacion_str():
            if grabacion_cancelada:
                return "🔴 **Estado de Grabación:** Cancelada / Desactivada (no se procesará con IA hoy)."
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
                        tgcalls._app._bind_client._cache.set_cache(destino, input_call)
                        print(f"input_call registrado en caché de PyTgCalls para {resolved_id}.")
                except Exception as e_c:
                    print("Nota registrando input_call en PyTgCalls:", e_c)

                # Iniciar grabación de audio pre-meditación
                if not grabacion_cancelada:
                    try:
                        from pytgcalls.types import RecordStream
                        os.makedirs(os.path.dirname(os.path.abspath(ruta_grabacion_pre)), exist_ok=True)
                        await tgcalls.record(destino, RecordStream(ruta_grabacion_pre))
                        grabacion_activa = True
                        print(f"🎙️ Grabación PRE-meditación iniciada correctamente con PyTgCalls -> {ruta_grabacion_pre}")
                    except Exception as e_rec:
                        print(f"⚠️ Error iniciando grabación pre-meditación con PyTgCalls: {e_rec}")
            except Exception as e:
                print("Nota iniciando PyTgCalls:", e)

        # Buscar si ya existe un audio o cola de meditación subida hoy por administradores
        ruta_meditacion, info_catalogo_hoy, cola_reproduccion = await buscar_audio_meditacion(client, entidad, admin_ids)
        indice_pista_actual = 0
        pistas_completadas: set[int] = set()
        tarea_espera_post_meditacion: asyncio.Task | None = None
        reproduciendo_meditacion = False
        token_reproduccion = 0  # Se incrementa en cada reproducción; invalida watchdogs de reproducciones anteriores
        segundos_mic_abierto_med = {}  # uid -> segundos continuos con mic abierto durante la meditación (usuarios normales)
        reproduccion_iniciada = False
        aviso_oracion_enviado = False
        aviso_espera_enviado = False
        aviso_meditacion_enviado = False
        alerta_falta_audio_enviada = False
        meditacion_activa_hoy = False
        oracion_activa_hoy = False

        def cancelar_espera_post_meditacion():
            nonlocal tarea_espera_post_meditacion
            if tarea_espera_post_meditacion and not tarea_espera_post_meditacion.done():
                tarea_espera_post_meditacion.cancel()
            tarea_espera_post_meditacion = None

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
        DURACION_GONG_SEG = obtener_duracion_segundos(obtener_sonido_campana_inicio())  # duración real del audio de inicio (s)
        volumen_actual = 200
        dur_pista_actual = 0.0
        ruta_activa_audio = ""
        ruta_caratula_actual = ""
        msg_panel_meditacion_id = None
        ultimo_texto_panel = ""
        tarea_panel_progreso = None
        tarea_callbacks_bot = None
        tarea_preparacion_recursos: asyncio.Task | None = None
        recursos_meditacion_preparados: dict = {}

        def construir_teclado_reproduccion(en_pausa: bool):
            boton_play_pausa = (
                {"text": "▶️ Reanudar", "callback_data": "panel_play"}
                if en_pausa else
                {"text": "⏸️ Pausa", "callback_data": "panel_pausa"}
            )
            return {
                "inline_keyboard": [
                    [
                        {"text": "⏪ -30s", "callback_data": "panel_rewind"},
                        boton_play_pausa,
                        {"text": "⏩ +30s", "callback_data": "panel_forward"},
                    ],
                    [
                        {"text": "🔉 Vol -", "callback_data": "panel_voldown"},
                        {"text": "⏹️ Detener", "callback_data": "panel_stop"},
                        {"text": "🔊 Vol +", "callback_data": "panel_volup"},
                    ],
                    [
                        {"text": "➕ Encolar Audio", "callback_data": "panel_encolar"},
                        {"text": "📋 Ver Cola", "callback_data": "panel_vercola"},
                        {"text": "⏭️ Saltar", "callback_data": "panel_nextaudio"},
                    ],
                    [
                        {"text": "🗑️ Limpiar Cola", "callback_data": "panel_limpiarcola"},
                        {"text": "🎤 Sig. Turno", "callback_data": "panel_nextturno"},
                        {"text": "✋ Limpiar Turnos", "callback_data": "panel_limpiarturnos"},
                    ]
                ]
            }

        def construir_texto_panel(pos_s: float, dur_s: float, info: dict, en_pausa: bool, vol: int = 100) -> str:
            num = (info or {}).get("numero", "")
            tit = (info or {}).get("titulo", "Meditación Diaria")
            maestro = (info or {}).get("maestro", "Alaniso")
            tipo_pnl = str((info or {}).get("tipo", "MEDITACION")).strip().upper()
            if not tipo_pnl or tipo_pnl == "MEDITACION":
                if "MENSAJE" in str(tit).upper():
                    tipo_pnl = "MENSAJE"
            es_msg = "MENSAJE" in tipo_pnl

            icono_estado = "⏸️ *(En pausa)*" if en_pausa else "▶️ *(En reproducción)*"
            barra = generar_barra_progreso(pos_s, dur_s, ancho=14)
            t_act = formatear_tiempo_mm_ss(pos_s)
            t_tot = formatear_tiempo_mm_ss(dur_s)
            pct = int(round((pos_s / max(1.0, dur_s)) * 100))
            pct = max(0, min(100, pct))

            if es_msg:
                encabezado = f"📜✨ **MENSAJE #{num}** — *{tit}*" if num else f"📜✨ **{tit}**"
            else:
                encabezado = f"🧘✨ **MEDITACIÓN #{num}** — *{tit}*" if num else f"🧘✨ **{tit}**"

            # Información de la cola de reproducción
            total_cola = len(cola_reproduccion)
            if total_cola > 1:
                sig_txt = ""
                if indice_pista_actual + 1 < total_cola:
                    sig_item = cola_reproduccion[indice_pista_actual + 1]
                    sig_info = sig_item.get("info") or {}
                    sig_num = sig_info.get("numero")
                    sig_nom = sig_item.get("titulo") or sig_info.get("titulo") or "Audio"
                    sig_tipo_raw = str(sig_info.get("tipo", "")).upper()
                    sig_es_msg = "MENSAJE" in sig_tipo_raw or "MENSAJE" in str(sig_nom).upper()
                    sig_tipo = "Mensaje" if sig_es_msg else "Meditación"
                    pref_sig = f"{sig_tipo} #{sig_num}: " if sig_num else f"{sig_tipo}: "
                    sig_txt = f"\n⏳ **Próximo en cola:** *{pref_sig}{sig_nom}*"
                info_cola = f"📋 **Cola:** Pista {indice_pista_actual + 1} de {total_cola}{sig_txt}\n\n"
            else:
                info_cola = "📋 **Cola:** Pista 1 de 1 *(Prioridad oficial #1 activa)*\n\n"

            return (
                f"{encabezado}\n"
                f"👤 **Maestro:** {maestro}\n"
                f"🔊 **Volumen:** {vol}%\n\n"
                f"{icono_estado}\n"
                f"`{t_act}`  {barra}  `{t_tot}` ({pct}%)\n\n"
                f"{info_cola}"
                f"*(Controles táctiles solo para administradores)*"
            )

        async def actualizar_panel_progreso(forzar: bool = False):
            nonlocal msg_panel_meditacion_id, ultimo_texto_panel
            if not msg_panel_meditacion_id:
                return
            try:
                pos = posicion_actual()
                dur = dur_pista_actual or 1800.0
                en_pausa = eq_estado.get("t_pausa") is not None
                vol_pct = int(round((volumen_actual / 200.0) * 100)) if volumen_actual > 100 else volumen_actual
                nuevo_texto = construir_texto_panel(pos, dur, info_catalogo_hoy, en_pausa, vol_pct)
                if forzar or nuevo_texto != ultimo_texto_panel:
                    nuevo_teclado = construir_teclado_reproduccion(en_pausa)
                    exito = await editar_mensaje_bot(msg_panel_meditacion_id, nuevo_texto, reply_markup=nuevo_teclado)
                    if exito:
                        ultimo_texto_panel = nuevo_texto
            except Exception as e_pnl:
                print("Nota actualizando panel progreso:", e_pnl)

        async def _bucle_panel_progreso():
            nonlocal msg_panel_meditacion_id
            while reproduciendo_meditacion:
                try:
                    await asyncio.sleep(2)
                    if not reproduciendo_meditacion:
                        break
                    await actualizar_panel_progreso(forzar=False)
                except asyncio.CancelledError:
                    break
                except Exception as e_bucle:
                    print("Nota en bucle de panel de progreso:", e_bucle)

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

        async def cerrar_pantalla_emision_video():
            """Cierra de forma limpia la transmisión de video/pantalla compartida en Telegram sin salir de la llamada ni interrumpir micrófonos ni grabación."""
            nonlocal ruta_caratula_actual, tgcalls, destino, client, input_call
            print("📺 Cerrando pantalla de emisión de video en Telegram...")
            ruta_caratula_actual = ""

            # 1. Detener presentación a nivel PyTgCalls / WebRTC si estaba activa
            if tgcalls:
                try:
                    resolved_dest = await tgcalls.resolve_chat_id(destino)
                    if hasattr(tgcalls, "_join_presentation"):
                        await tgcalls._join_presentation(resolved_dest, False)
                    if hasattr(tgcalls, "_binding") and hasattr(tgcalls._binding, "stop_presentation"):
                        try:
                            await tgcalls._binding.stop_presentation(resolved_dest)
                        except Exception:
                            pass
                    if hasattr(tgcalls, "_presentations"):
                        tgcalls._presentations.discard(resolved_dest)
                        tgcalls._presentations.discard(destino)
                except Exception as e_tg_pres:
                    print("Nota cerrando presentación en PyTgCalls:", e_tg_pres)

            # 2. Dejar la presentación en Telegram MTProto para que la ventana de video se cierre en todos los dispositivos
            if client and input_call:
                try:
                    from telethon.tl.functions.phone import LeaveGroupCallPresentationRequest
                    await client(LeaveGroupCallPresentationRequest(call=input_call))
                    print("✅ Pantalla de emisión cerrada con LeaveGroupCallPresentationRequest.")
                except Exception as e_lv_pres:
                    print("Nota enviando LeaveGroupCallPresentationRequest:", e_lv_pres)

                # 3. Notificar video_stopped=True para el robot
                try:
                    from telethon.tl.types import InputPeerSelf
                    from telethon.tl.functions.phone import EditGroupCallParticipantRequest
                    await client(EditGroupCallParticipantRequest(
                        call=input_call,
                        participant=InputPeerSelf(),
                        video_stopped=True
                    ))
                    print("✅ Video confirmado detenido con EditGroupCallParticipantRequest(video_stopped=True).")
                except Exception as e_ed_vid:
                    print("Nota notificando video_stopped:", e_ed_vid)

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

        if (cola_reproduccion or ruta_meditacion):
            # Pre-procesa en segundo plano para que los recursos (audio con gong y video carátula) estén listos
            async def _preparar_meditacion_completa():
                try:
                    nonlocal ruta_caratula_actual, ruta_activa_audio
                    audio_base = (await preparar_audio_eq()) if MEJORA_AUDIO else (ruta_meditacion or (cola_reproduccion[0]["ruta"] if cola_reproduccion else ""))
                    if audio_base and os.path.exists(audio_base):
                        audio_con_gong = await asyncio.to_thread(agregar_gongs_al_audio, audio_base)
                        audio_con_gong = os.path.abspath(audio_con_gong)
                        recursos_meditacion_preparados["audio"] = audio_con_gong
                        ruta_activa_audio = audio_con_gong

                        p_act = cola_reproduccion[0] if cola_reproduccion else {}
                        inf_act = p_act.get("info") or info_catalogo_hoy or {}
                        n_act = inf_act.get("numero", "")
                        t_act = inf_act.get("titulo", "Meditación Diaria")
                        m_act = inf_act.get("maestro", "Alaniso")
                        tipo_act = inf_act.get("tipo") or ("MENSAJE" if "MENSAJE" in str(t_act).upper() else "MEDITACION")
                        dur_base_orig = obtener_duracion_segundos(audio_base)
                        dur_e = obtener_duracion_segundos(audio_con_gong if os.path.exists(audio_con_gong) else audio_base)
                        if dur_e < (dur_base_orig - 5.0):
                            dur_e = dur_base_orig
                        if dur_e <= 0:
                            dur_e = 1800.0
                        vid = await asyncio.to_thread(generar_caratula_meditacion, n_act, t_act, m_act, dur_e, None, tipo_act)
                        if vid and os.path.exists(vid) and vid.lower().endswith(".mp4"):
                            recursos_meditacion_preparados["video"] = os.path.abspath(vid)
                            ruta_caratula_actual = recursos_meditacion_preparados["video"]
                        print(f"✨ Recursos ({tipo_act} #{n_act}) pre-generados exitosamente en segundo plano.")
                except Exception as e_p:
                    print("Nota pre-procesando meditacion en segundo plano:", e_p)
            tarea_preparacion_recursos = asyncio.create_task(_preparar_meditacion_completa())

        async def _watchdog_fin_pista(p_idx: int, dur_s: float, mi_token: int):
            margen = 8.0
            espera = max(10.0, dur_s + margen)
            print(f"⏱️ Watchdog armado para pista {p_idx + 1}: dur={dur_s:.1f}s, espera={espera:.1f}s.")
            await asyncio.sleep(espera)
            nonlocal reproduciendo_meditacion, indice_pista_actual, token_reproduccion, tarea_panel_progreso, msg_panel_meditacion_id, tarea_espera_post_meditacion
            if reproduciendo_meditacion and indice_pista_actual == p_idx and mi_token == token_reproduccion:
                print(f"⏰ Watchdog: Tiempo cumplido para pista {p_idx + 1} ({dur_s:.1f}s). Finalizando automáticamente...")
                pistas_completadas.add(p_idx)
                if tarea_panel_progreso and not tarea_panel_progreso.done():
                    tarea_panel_progreso.cancel()
                if msg_panel_meditacion_id:
                    try:
                        t_tot_str = formatear_tiempo_mm_ss(dur_s)
                        inf_wd = (cola_reproduccion[p_idx].get("info") if (cola_reproduccion and p_idx < len(cola_reproduccion)) else (info_catalogo_hoy or {})) or {}
                        num_wd = inf_wd.get("numero", "")
                        tit_wd = inf_wd.get("titulo", "")
                        tipo_wd = str(inf_wd.get("tipo", "MEDITACION")).strip().upper()
                        if not tipo_wd or tipo_wd == "MEDITACION":
                            if "MENSAJE" in str(tit_wd).upper():
                                tipo_wd = "MENSAJE"
                        es_msg_wd = "MENSAJE" in tipo_wd
                        lbl_item = "MENSAJE" if es_msg_wd else "MEDITACIÓN"
                        lbl_concluido = "CONCLUIDO" if es_msg_wd else "CONCLUIDA"
                        icono_item = "📜" if es_msg_wd else "🧘"
                        cabecera_fin = f"{icono_item} **{lbl_item} #{num_wd} {lbl_concluido}**" if num_wd else f"{icono_item} **{lbl_item} {lbl_concluido}**"
                        txt_fin = (
                            f"{cabecera_fin}\n\n"
                            f"⏱️ **Duración:** {t_tot_str}\n"
                            f"🔓 **Micrófonos restablecidos.** ¡Gracias por su práctica y presencia!"
                        )
                        await editar_mensaje_bot(msg_panel_meditacion_id, txt_fin, reply_markup={"inline_keyboard": []})
                    except Exception:
                        pass
                    msg_panel_meditacion_id = None

                # Sincronizar cola por si se agregó un audio adicional durante la reproducción
                await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)

                if p_idx + 1 < len(cola_reproduccion):
                    sig_idx = p_idx + 1
                    indice_pista_actual = sig_idx  # Avanzar puntero inmediatamente a la siguiente pista
                    siguiente_item = cola_reproduccion[sig_idx]
                    inf_sig = siguiente_item.get("info")
                    tit_sig_raw = siguiente_item.get('titulo', 'Audio')
                    ico_sig = "📜" if (inf_sig and "MENSAJE" in str(inf_sig.get("tipo", "")).upper()) or ("MENSAJE" in str(tit_sig_raw).upper()) else "🧘"
                    txt_sig = formatear_info_audio(inf_sig) if inf_sig else f"{ico_sig} **Audio #{sig_idx + 1}:** {tit_sig_raw}"
                    espera_min = int((inf_sig or {}).get("espera_post_meditacion_min", 30 if p_idx == 0 else 0))
                    if espera_min > 0:
                        reproduciendo_meditacion = False
                        await desbloquear_todos_los_participantes()
                        if not grabacion_cancelada and not grabacion_pausada:
                            if ruta_grabacion_post not in segmentos_grabados:
                                segmentos_grabados.append(ruta_grabacion_post)
                            try:
                                from pytgcalls.types import RecordStream
                                os.makedirs(os.path.dirname(os.path.abspath(ruta_grabacion_post)), exist_ok=True)
                                await tgcalls.record(destino, RecordStream(ruta_grabacion_post))
                            except Exception as e_rec:
                                print("Nota reanudando grabación durante espera de 30m:", e_rec)
                        avisar_con_bot(
                            f"🧘 **Primera reproducción finalizada.** Los micrófonos han sido restablecidos.\n\n"
                            f"⏳ **En {espera_min} minutos se reproducirá automáticamente el siguiente audio encolado:**\n{txt_sig}",
                            es_efimero=False
                        )
                        print(f"⏳ Esperando {espera_min} minutos antes de reproducir pista {sig_idx + 1}...")
                        cancelar_espera_post_meditacion()
                        async def _esperar_wd_sig(idx_target, mins):
                            try:
                                await asyncio.sleep(mins * 60)
                                if not reproduciendo_meditacion and idx_target not in pistas_completadas:
                                    await reproducir_meditacion(idx_target)
                            except asyncio.CancelledError:
                                pass
                        tarea_espera_post_meditacion = asyncio.create_task(_esperar_wd_sig(sig_idx, espera_min))
                    else:
                        avisar_con_bot(
                            f"🔔 **Pista {p_idx + 1} finalizada.**\n\n▶️ **Continuando con la pista {sig_idx + 1} de {len(cola_reproduccion)}:**\n{txt_sig}\n\n{ico_sig} Por favor continúen en silencio...",
                            es_efimero=True
                        )
                        await reproducir_meditacion(sig_idx)
                else:
                    reproduciendo_meditacion = False
                    print("Watchdog: Sesión de meditación/mensaje concluida exitosamente.")
                    await desbloquear_todos_los_participantes()
                    avisar_con_bot("🧘 **Sesión finalizada:** Los micrófonos han sido restablecidos. ¡Esperamos que hayan tenido una gran sesión!", es_efimero=False)
                    if not grabacion_cancelada and not grabacion_pausada:
                        if ruta_grabacion_post not in segmentos_grabados:
                            segmentos_grabados.append(ruta_grabacion_post)
                        try:
                            from pytgcalls.types import RecordStream
                            os.makedirs(os.path.dirname(os.path.abspath(ruta_grabacion_post)), exist_ok=True)
                            await tgcalls.record(destino, RecordStream(ruta_grabacion_post))
                            print(f"🎙️ Grabación post-meditación iniciada vía watchdog -> {ruta_grabacion_post}")
                        except Exception as e_rec:
                            print("Nota reanudando grabación vía watchdog:", e_rec)


        async def saltar_a_posicion(nueva_pos: float) -> bool:
            nonlocal token_reproduccion, dur_pista_actual, ruta_activa_audio, ruta_caratula_actual
            if not (tgcalls and reproduciendo_meditacion and ruta_activa_audio):
                return False
            try:
                en_pausa = eq_estado.get("t_pausa") is not None
                dur_total = dur_pista_actual or 1800.0
                nueva_pos = max(0.0, min(max(0.0, dur_total - 5.0), nueva_pos))
                token_seek = int(time.time() * 1000) % 1000000
                destino_seek = os.path.join(CARPETA_MEDITACIONES, f"meditacion_seek_{token_seek}.mp3")

                if nueva_pos <= 1.0:
                    ruta_seek = ruta_activa_audio
                else:
                    ruta_seek = await recortar_desde_async(ruta_activa_audio, nueva_pos, destino_seek)
                    if not os.path.exists(ruta_seek) or os.path.getsize(ruta_seek) < 5000:
                        ruta_seek = ruta_activa_audio

                try:
                    num_m = (info_catalogo_hoy or {}).get("numero", "")
                    tit_m = (info_catalogo_hoy or {}).get("titulo", "Meditación Diaria")
                    m_m = (info_catalogo_hoy or {}).get("maestro", "Alaniso")
                    tipo_m = (info_catalogo_hoy or {}).get("tipo") or ("MENSAJE" if "MENSAJE" in str(tit_m).upper() else "MEDITACION")
                    tipo_tag_seek = "mensaje" if "MENSAJE" in str(tipo_m).upper() else "meditacion"
                    tag_seek = f"{tipo_tag_seek}_{num_m}" if num_m else f"{tipo_tag_seek}_diario"
                    ruta_video_base = ruta_caratula_actual if (ruta_caratula_actual and os.path.exists(ruta_caratula_actual) and ruta_caratula_actual.lower().endswith(".mp4")) else os.path.join(CARPETA_MEDITACIONES, f"caratula_{tag_seek}.mp4")
                    destino_video_seek = os.path.join(CARPETA_MEDITACIONES, f"caratula_seek_{token_seek}.mp4")
                    if os.path.exists(ruta_video_base) and os.path.getsize(ruta_video_base) > 5000:
                        import subprocess
                        cmd_seek_vid = [
                            "ffmpeg", "-y", "-ss", str(nueva_pos), "-i", ruta_video_base,
                            "-c", "copy", destino_video_seek
                        ]
                        await asyncio.to_thread(subprocess.run, cmd_seek_vid, capture_output=True)
                        if os.path.exists(destino_video_seek) and os.path.getsize(destino_video_seek) > 5000:
                            ruta_caratula_actual = destino_video_seek
                        else:
                            ruta_caratula_actual = ruta_video_base
                    else:
                        ruta_caratula_actual = await asyncio.to_thread(
                            generar_caratula_meditacion,
                            num_m, tit_m, m_m, dur_total, None, tipo_m
                        )
                except Exception as e_car_seek:
                    print("Nota actualizando carátula en salto:", e_car_seek)

                from pytgcalls.types import MediaStream, VideoQuality, AudioQuality
                if ruta_caratula_actual and os.path.exists(ruta_caratula_actual):
                    stream_seek = MediaStream(
                        ruta_caratula_actual,
                        audio_path=ruta_seek,
                        video_parameters=VideoQuality.HD_720p,
                        audio_parameters=AudioQuality.HIGH,
                    )
                else:
                    stream_seek = MediaStream(
                        ruta_seek,
                        audio_parameters=AudioQuality.HIGH,
                    )

                eq_estado["cambiando"] = True
                try:
                    await tgcalls.play(destino, stream_seek)
                    iniciar_seguimiento_posicion(nueva_pos)
                    try:
                        await tgcalls.unmute(destino)
                        await tgcalls.change_volume_call(destino, volumen_actual)
                    except Exception:
                        pass
                    if en_pausa:
                        await tgcalls.pause(destino)
                        marcar_pausa()
                    await asyncio.sleep(1.0)
                finally:
                    eq_estado["cambiando"] = False

                token_reproduccion += 1
                dur_restante = max(5.0, dur_total - nueva_pos)
                client.loop.create_task(_watchdog_fin_pista(indice_pista_actual, dur_restante, token_reproduccion))
                await actualizar_panel_progreso(forzar=True)
                return True
            except Exception as e_seek:
                print("Error en saltar_a_posicion:", e_seek)
                return False

        lock_panel_seek = asyncio.Lock()

        async def _bucle_callbacks_bot():
            """Monitorea eventos del panel de control vía IPC (control_panel_ipc.json) sin colisionar con el bot de Telegram."""
            ipc_file = os.path.join("data", "control_panel_ipc.json")
            ultimo_ts = time.time()
            print("🔘 Sistema de control del panel (⏪, ⏩, ▶️, ⏸️, ➕ Encolar, 🎤 Turnos) activo y sincronizado vía IPC.")

            while True:
                try:
                    await asyncio.sleep(0.2)
                    if not os.path.exists(ipc_file):
                        continue

                    try:
                        with open(ipc_file, "r", encoding="utf-8") as f_ipc:
                            ev_ipc = json.load(f_ipc)
                    except Exception:
                        continue

                    ts = ev_ipc.get("timestamp", 0)
                    if ts <= ultimo_ts:
                        continue

                    ultimo_ts = ts
                    accion = ev_ipc.get("accion", "")
                    cq_data = f"panel_{accion}"
                    sender_id = ev_ipc.get("sender_id")
                    nom_sender = ev_ipc.get("sender_nom", "Admin")

                    nonlocal volumen_actual, reproduciendo_meditacion, indice_pista_actual, token_reproduccion

                    if cq_data == "panel_rewind":
                        async with lock_panel_seek:
                            if reproduciendo_meditacion:
                                pos_act = posicion_actual()
                                nueva_pos = max(0.0, pos_act - 30.0)
                                print(f"⏪ Botón [-30s] presionado por {nom_sender}. De {pos_act:.1f}s a {nueva_pos:.1f}s.")
                                await saltar_a_posicion(nueva_pos)
                    elif cq_data == "panel_forward":
                        async with lock_panel_seek:
                            if reproduciendo_meditacion:
                                pos_act = posicion_actual()
                                dur_tot = dur_pista_actual or 1800.0
                                nueva_pos = min(max(0.0, dur_tot - 5.0), pos_act + 30.0)
                                print(f"⏩ Botón [+30s] presionado por {nom_sender}. De {pos_act:.1f}s a {nueva_pos:.1f}s.")
                                await saltar_a_posicion(nueva_pos)
                    elif cq_data == "panel_pausa":
                        if tgcalls and reproduciendo_meditacion:
                            try:
                                await tgcalls.pause(destino)
                                marcar_pausa()
                                await actualizar_panel_progreso(forzar=True)
                                print(f"⏸️ Botón [Pausa] presionado por {nom_sender}.")
                            except Exception as e_p:
                                print("Error pausando desde botón:", e_p)
                    elif cq_data == "panel_play":
                        if tgcalls and reproduciendo_meditacion and eq_estado.get("t_pausa") is not None:
                            try:
                                await tgcalls.resume(destino)
                                marcar_reanudacion()
                                await actualizar_panel_progreso(forzar=True)
                                print(f"▶️ Botón [Reanudar] presionado por {nom_sender}.")
                            except Exception as e_r:
                                print("Error reanudando desde botón:", e_r)
                        elif not reproduciendo_meditacion:
                            cancelar_espera_post_meditacion()
                            await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                            while indice_pista_actual in pistas_completadas and indice_pista_actual + 1 < len(cola_reproduccion):
                                indice_pista_actual += 1
                            if cola_reproduccion and indice_pista_actual < len(cola_reproduccion):
                                await reproducir_meditacion(indice_pista_actual)
                    elif cq_data == "panel_voldown":
                        volumen_actual = max(10, volumen_actual - 20)
                        vol_pct = int(round((volumen_actual / 200.0) * 100)) if volumen_actual > 100 else volumen_actual
                        if tgcalls:
                            try:
                                await tgcalls.change_volume_call(destino, volumen_actual)
                                await actualizar_panel_progreso(forzar=True)
                                print(f"🔉 Botón [Vol -] presionado por {nom_sender}: {vol_pct}%.")
                            except Exception:
                                pass
                    elif cq_data == "panel_volup":
                        volumen_actual = min(200, volumen_actual + 20)
                        vol_pct = int(round((volumen_actual / 200.0) * 100)) if volumen_actual > 100 else volumen_actual
                        if tgcalls:
                            try:
                                await tgcalls.change_volume_call(destino, volumen_actual)
                                await actualizar_panel_progreso(forzar=True)
                                print(f"🔊 Botón [Vol +] presionado por {nom_sender}: {vol_pct}%.")
                            except Exception:
                                pass
                    elif cq_data == "panel_stop":
                        cancelar_espera_post_meditacion()
                        token_reproduccion += 1
                        reproduciendo_meditacion = False
                        print(f"⏹️ Botón [Detener] presionado por {nom_sender}.")
                        try:
                            await cerrar_pantalla_emision_video()
                        except Exception:
                            pass
                        if tgcalls:
                            try:
                                await tgcalls.leave_call(destino)
                            except Exception:
                                pass
                        if tarea_panel_progreso and not tarea_panel_progreso.done():
                            tarea_panel_progreso.cancel()
                        if msg_panel_meditacion_id:
                            try:
                                await editar_mensaje_bot(
                                    msg_panel_meditacion_id,
                                    "⏹️ **REPRODUCCIÓN DETENIDA POR ADMINISTRADOR**\n🔓 Micrófonos desbloqueados.",
                                    reply_markup={"inline_keyboard": []}
                                )
                            except Exception:
                                pass
                            msg_panel_meditacion_id = None
                    elif cq_data in ("panel_nextaudio", "panel_saltaraudio"):
                        cancelar_espera_post_meditacion()
                        await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                        if reproduciendo_meditacion:
                            pistas_completadas.add(indice_pista_actual)
                        target_next = indice_pista_actual + 1 if (reproduciendo_meditacion or indice_pista_actual in pistas_completadas) else indice_pista_actual
                        if target_next < len(cola_reproduccion):
                            await reproducir_meditacion(target_next)
                        else:
                            avisar_con_bot("ℹ️ No hay más audios en la cola.", es_efimero=True)
                    elif cq_data == "panel_limpiarcola":
                        if len(cola_reproduccion) > (indice_pista_actual + 1):
                            cola_reproduccion[:] = cola_reproduccion[:indice_pista_actual + 1]
                            guardar_cola_hoy(cola_reproduccion)
                            avisar_con_bot("🗑️ **Cola de reproducción vaciada por un administrador.**", es_efimero=True)
                            await actualizar_panel_progreso(forzar=True)
                        else:
                            avisar_con_bot("ℹ️ No hay audios en espera en la cola.", es_efimero=True)
                    elif cq_data == "panel_vercola":
                        await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                        if not cola_reproduccion and ruta_meditacion:
                            cola_reproduccion.append({
                                "ruta": ruta_meditacion,
                                "info": info_catalogo_hoy,
                                "titulo": (info_catalogo_hoy or {}).get("titulo", "Meditación")
                            })
                        txt_cola = formatear_cola_audios(cola_reproduccion, indice_pista_actual, reproduciendo_meditacion)
                        avisar_con_bot(txt_cola, es_efimero=True)
                    elif cq_data == "panel_nextturno":
                        if not cola_turnos:
                            avisar_con_bot("ℹ️ No hay participantes en espera en la lista de turnos.", es_efimero=True)
                        else:
                            siguiente_u = cola_turnos.pop(0)
                            s_uid = siguiente_u["id"]
                            s_nom = siguiente_u["nombre"]
                            oradores_activos.add(s_uid)
                            segundos_inactividad_mic[s_uid] = 0
                            avisados_auto_mute.discard(s_uid)
                            await actualizar_mensaje_turnos(forzar_al_fondo=True)
                            avisar_con_bot(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Tu micrófono está listo.", es_efimero=True)
                            if not reproduciendo_meditacion:
                                lanzar_tarea(anunciar_turno_por_voz(s_nom))
                    elif cq_data == "panel_limpiarturnos":
                        cola_turnos.clear()
                        await actualizar_mensaje_turnos(forzar_al_fondo=True)
                        avisar_con_bot("🧹 **Lista de turnos vaciada por un administrador.**", es_efimero=True)
                except asyncio.CancelledError:
                    break
                except Exception as e_cb_loop:
                    await asyncio.sleep(1)

        tarea_callbacks_bot = asyncio.create_task(_bucle_callbacks_bot())

        ultimo_error_reproduccion = ""

        async def reproducir_meditacion(pista_idx: int = 0):
            with open("repro_debug.txt", "a", encoding="utf-8") as f: f.write(f"\\n--- Iniciando reproducir_meditacion {pista_idx} ---\\n")
            nonlocal reproduciendo_meditacion, meditacion_activa_hoy, indice_pista_actual, ruta_meditacion, info_catalogo_hoy, ultimo_error_reproduccion, token_reproduccion, tarea_panel_progreso, msg_panel_meditacion_id, ultimo_texto_panel, ruta_caratula_actual, ruta_activa_audio
            ultimo_error_reproduccion = ""
            cancelar_espera_post_meditacion()
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

            # Activar estado de reproducción y token desde el inicio para que /saltaraudio y /detener respondan al instante
            token_reproduccion += 1
            mi_token_repro = token_reproduccion
            reproduciendo_meditacion = True
            meditacion_activa_hoy = True
            eq_estado["cambiando"] = True

            if tarea_panel_progreso and not tarea_panel_progreso.done():
                tarea_panel_progreso.cancel()
            if msg_panel_meditacion_id:
                try:
                    await editar_mensaje_bot(msg_panel_meditacion_id, "⏭️ **Cambiando de pista...**", reply_markup={"inline_keyboard": []})
                except Exception:
                    pass
                msg_panel_meditacion_id = None

            try:
                # 1. Anuncio de voz por Toby antes de la meditación/mensaje
                try:
                    num = (info_catalogo_hoy or {}).get("numero", "")
                    tit = (info_catalogo_hoy or {}).get("titulo", "Meditación diaria")
                    maestro = (info_catalogo_hoy or {}).get("maestro", "Alaniso")
                    tipo_item = str((info_catalogo_hoy or {}).get("tipo", "MEDITACION")).strip().upper()
                    if not tipo_item or tipo_item == "MEDITACION":
                        if "MENSAJE" in str(tit).upper():
                            tipo_item = "MENSAJE"
                    es_msg = "MENSAJE" in tipo_item
                    lbl_anuncio = "el mensaje" if es_msg else "la meditación diaria"
                    if num:
                        txt_med = f"A continuación daremos inicio a {lbl_anuncio}, Hoy número {num}: {tit}, del maestro {maestro}."
                    else:
                        txt_med = f"A continuación daremos inicio a {lbl_anuncio}: {tit}, del maestro {maestro}."
                    print(f"🎙️ Emitiendo anuncio de {lbl_anuncio} #{num or 'diario'} con voz de Toby...")
                    await emitir_anuncio_tts(txt_med)
                    await asyncio.sleep(0.5)
                except Exception as e_tts_med:
                    print("Nota emitiendo anuncio TTS:", e_tts_med)

                if token_reproduccion != mi_token_repro or not reproduciendo_meditacion:
                    return False

                # 2. Si hay preparación de recursos en segundo plano para esta pista, esperarla (máximo 60s)
                if pista_idx == 0 and tarea_preparacion_recursos and not tarea_preparacion_recursos.done():
                    print("⏳ Esperando que finalice la preparación de recursos (audio HD y video carátula MP4)...")
                    try:
                        await asyncio.wait_for(asyncio.shield(tarea_preparacion_recursos), timeout=60.0)
                    except Exception as e_esp:
                        print("Nota esperando tarea de recursos:", e_esp)

                if token_reproduccion != mi_token_repro or not reproduciendo_meditacion:
                    return False

                # 3. Obtener audio con gongs (del cache preparado o generándolo)
                if pista_idx == 0 and recursos_meditacion_preparados.get("audio") and os.path.exists(recursos_meditacion_preparados["audio"]):
                    ruta_a_reproducir = recursos_meditacion_preparados["audio"]
                else:
                    ruta_base_audio = await preparar_audio_eq(ruta_pista)
                    ruta_a_reproducir = await asyncio.to_thread(agregar_gongs_al_audio, ruta_base_audio)
                    ruta_a_reproducir = os.path.abspath(ruta_a_reproducir)
                ruta_activa_audio = ruta_a_reproducir

                if token_reproduccion != mi_token_repro or not reproduciendo_meditacion:
                    return False

                # 4. Obtener video carátula MP4 dinámico
                if pista_idx == 0 and recursos_meditacion_preparados.get("video") and os.path.exists(recursos_meditacion_preparados["video"]):
                    ruta_caratula_actual = recursos_meditacion_preparados["video"]
                else:
                    try:
                        inf_pista = pista_actual.get("info") or info_catalogo_hoy or {}
                        num_med = inf_pista.get("numero", "")
                        tit_med = inf_pista.get("titulo") or pista_actual.get("titulo", "Meditación Diaria")
                        m_med = inf_pista.get("maestro", "Alaniso")
                        tipo_med = inf_pista.get("tipo") or ("MENSAJE" if "MENSAJE" in str(tit_med).upper() else "MEDITACION")
                        dur_pista_orig = obtener_duracion_segundos(ruta_pista)
                        dur_exacta = obtener_duracion_segundos(ruta_a_reproducir)
                        if dur_exacta < (dur_pista_orig - 5.0):
                            dur_exacta = dur_pista_orig
                        if dur_exacta <= 0:
                            dur_exacta = 1800.0
                        ruta_caratula_actual = await asyncio.to_thread(generar_caratula_meditacion, num_med, tit_med, m_med, dur_exacta, None, tipo_med)
                    except Exception as e_car:
                        print("Nota generando carátula:", e_car)
                        ruta_caratula_actual = ""

                if token_reproduccion != mi_token_repro or not reproduciendo_meditacion:
                    return False

                # 4. Asegurar que la sala permita la transmisión sin silenciamiento global
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
                except Exception:
                    pass

                # 5. Inyectar input_call en la caché de PyTgCalls ANTES de cualquier operación
                try:
                    resolved_id = await tgcalls.resolve_chat_id(destino)
                    if hasattr(tgcalls, "_app") and hasattr(tgcalls._app, "_bind_client") and hasattr(tgcalls._app._bind_client, "_cache"):
                        tgcalls._app._bind_client._cache.set_cache(resolved_id, input_call)
                        tgcalls._app._bind_client._cache.set_cache(destino, input_call)
                except Exception as e_c:
                    print("Nota registrando input_call:", e_c)

                # 7. Iniciar emisión con pantalla de video HD y audio de alta fidelidad (sin -re incompatible)
                try:
                    from pytgcalls.types import MediaStream, VideoQuality, AudioQuality
                    if ruta_caratula_actual and os.path.exists(ruta_caratula_actual):
                        stream_play = MediaStream(
                            ruta_caratula_actual,
                            audio_path=ruta_a_reproducir,
                            video_parameters=VideoQuality.HD_720p,
                            audio_parameters=AudioQuality.HIGH,
                        )
                    else:
                        stream_play = MediaStream(
                            ruta_a_reproducir,
                            audio_parameters=AudioQuality.HIGH,
                        )
                    
                    with open("repro_debug.txt", "a", encoding="utf-8") as f: f.write("Iniciando tgcalls.play con stream_play (video+audio)...\n")
                    await tgcalls.play(destino, stream_play)
                    with open("repro_debug.txt", "a", encoding="utf-8") as f: f.write("tgcalls.play con video completado exitosamente.\n")
                    print(f"Emisión de pantalla de video y audio iniciada: {ruta_a_reproducir}")
                except Exception as e_ms:
                    with open("repro_debug.txt", "a", encoding="utf-8") as f: f.write(f"Excepcion en play video: {e_ms}, usando audio directo\n")
                    print("Nota reproduciendo video en pantalla, usando fallback de audio:", e_ms)
                    try:
                        from pytgcalls.types import MediaStream, AudioQuality
                        stream_fb = MediaStream(ruta_a_reproducir, audio_parameters=AudioQuality.HIGH)
                        await tgcalls.play(destino, stream_fb)
                    except Exception:
                        await tgcalls.play(destino, ruta_a_reproducir)
                    with open("repro_debug.txt", "a", encoding="utf-8") as f: f.write("Fallback tgcalls.play completado.\n")

                await asyncio.sleep(0.5)
                if token_reproduccion == mi_token_repro:
                    eq_estado["cambiando"] = False

                # 8. Desmutear PyTgCalls a nivel WebRTC y maximizar volumen de emisión
                try:
                    await asyncio.wait_for(tgcalls.unmute(destino), timeout=3.0)
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(tgcalls.change_volume_call(destino, 200), timeout=2.0)
                except Exception:
                    pass

                # 9. Desmutear el micrófono del robot en Telegram utilizando InputPeerSelf
                try:
                    from telethon.tl.types import InputPeerSelf
                    await asyncio.wait_for(
                        client(EditGroupCallParticipantRequest(call=input_call, participant=InputPeerSelf(), muted=False)),
                        timeout=5.0
                    )
                    print("Micrófono del robot confirmado activo en Telegram (InputPeerSelf).")
                except Exception as e_me:
                    print("Nota desmuteando robot en Telegram:", e_me)

                # 7. Garantizar explícitamente que TODOS los administradores tengan el micrófono desbloqueado (NUNCA silenciados)
                for aid in admin_ids:
                    if aid != me.id:
                        try:
                            admin_peer = await client.get_input_entity(aid)
                            await client(EditGroupCallParticipantRequest(call=input_call, participant=admin_peer, muted=False))
                        except Exception:
                            pass
                print("Todos los administradores confirmados con permiso de voz libre y desbloqueado.")

                # 8. Modo libre: NO silenciar a los participantes ni activar candados de sala
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
                    print("🔓 Meditación: Sala completamente libre y sin restricciones de micrófono (join_muted=False).")
                except Exception as e:
                    print("Nota configurando join_muted=False en meditación:", e)

                iniciar_seguimiento_posicion(-DURACION_GONG_SEG)
                segundos_mic_abierto_med.clear()
                reproduciendo_meditacion = True
                meditacion_activa_hoy = True

                total_pistas = len(cola_reproduccion)
                info_act = pista_actual.get("info")
                tipo_act_repro = str((info_act or {}).get("tipo", "MEDITACION")).strip().upper()
                if not tipo_act_repro or tipo_act_repro == "MEDITACION":
                    if "MENSAJE" in str(pista_actual.get("titulo", "")).upper():
                        tipo_act_repro = "MENSAJE"
                es_msg_repro = "MENSAJE" in tipo_act_repro
                lbl_repro = "mensaje" if es_msg_repro else "meditación oficial"
                icono_repro = "📜" if es_msg_repro else "🧘"

                if total_pistas == 1:
                    if info_act:
                        avisar_con_bot(f"▶️ **Reproduciendo {lbl_repro}:**\n{formatear_info_audio(info_act)}\n{icono_repro} Por favor disfruten de su sesión en silencio.", es_efimero=False)
                    else:
                        avisar_con_bot(f"▶️ **Iniciando reproducción de {lbl_repro} en la sala de voz.**\n{icono_repro} Por favor disfruten de su sesión en silencio.", es_efimero=False)
                else:
                    txt_act = formatear_info_audio(info_act) if info_act else f"{icono_repro} **Pista #{indice_pista_actual + 1}:** {pista_actual.get('titulo', 'Audio')}"
                    avisar_con_bot(f"▶️ **Iniciando reproducción (Pista {indice_pista_actual + 1} de {total_pistas}):**\n\n{txt_act}\n\n📋 Total de pistas programadas: {total_pistas}\n{icono_repro} Por favor disfruten de su sesión en silencio.", es_efimero=False)
                # Determinar duración total de la pista
                dur_pista_orig = obtener_duracion_segundos(ruta_pista)
                dur_audio = obtener_duracion_segundos(ruta_a_reproducir)
                if dur_audio < (dur_pista_orig - 5.0):
                    dur_audio = dur_pista_orig
                if dur_audio <= 0:
                    dur_audio = 1800.0
                dur_pista_actual = dur_audio

                # Publicar el panel de control interactivo con barra de progreso en vivo (Opción B)
                try:
                    vol_pct = int(round((volumen_actual / 200.0) * 100)) if volumen_actual > 100 else volumen_actual
                    txt_panel = construir_texto_panel(0.0, dur_pista_actual, info_act, en_pausa=False, vol=vol_pct)
                    teclado_panel = construir_teclado_reproduccion(en_pausa=False)
                    ids_pnl = avisar_con_bot(txt_panel, reply_markup=teclado_panel, parse_mode="Markdown")
                    if ids_pnl:
                        msg_panel_meditacion_id = ids_pnl[0]
                        ultimo_texto_panel = txt_panel
                except Exception as e_pnl_init:
                    print("Nota publicando panel interactivo de meditación:", e_pnl_init)

                # Iniciar bucle de actualización en vivo del progreso
                if tarea_panel_progreso and not tarea_panel_progreso.done():
                    tarea_panel_progreso.cancel()
                tarea_panel_progreso = client.loop.create_task(_bucle_panel_progreso())

                # Armar el watchdog automático para la pista actual
                asyncio.create_task(_watchdog_fin_pista(pista_idx, dur_pista_actual, mi_token_repro))

                with open("repro_debug.txt", "a", encoding="utf-8") as f: f.write(f"reproducir_meditacion termino todo y retorna True.\\n")
                return True
            except Exception as e:
                if token_reproduccion == mi_token_repro:
                    reproduciendo_meditacion = False
                    eq_estado["cambiando"] = False
                with open("repro_debug.txt", "a", encoding="utf-8") as f: f.write(f"Excepcion general reproduciendo: {e}\\n")
                print("Error reproduciendo meditación:", e)
                ultimo_error_reproduccion = str(e)
                return False

        _bg_tasks = set()

        def lanzar_tarea(coro):
            task = asyncio.create_task(coro)
            _bg_tasks.add(task)
            task.add_done_callback(_bg_tasks.discard)
            return task

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
            """Retira el candado de silencio a todos los participantes en la sala."""
            try:
                parts_completos, _, _ = await obtener_todos_participantes_llamada(client, input_call)
                for p in parts_completos:
                    if getattr(p, "left", False):
                        continue
                    p_uid = getattr(p.peer, "user_id", None) or getattr(p.peer, "channel_id", None) or getattr(p.peer, "chat_id", None)
                    if not p_uid or p_uid == me.id:
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

        def dividir_texto_tts(texto_a_dividir: str, max_chars: int = 85) -> list[str]:
            """Divide un texto en fragmentos naturales por puntuación y palabras,
            respetando el límite estricto de Google Translate TTS (máx 100 caracteres)."""
            texto_limpio = " ".join(texto_a_dividir.split()).strip()
            if not texto_limpio:
                return []
            if len(texto_limpio) <= max_chars:
                return [texto_limpio]
            partes = re.split(r"([.,;:!?\n])", texto_limpio)
            frases = []
            acumulado = ""
            i = 0
            while i < len(partes):
                frag = partes[i]
                punc = partes[i + 1] if i + 1 < len(partes) else ""
                trozo = (frag + punc).strip()
                i += 2
                if not trozo:
                    continue
                if len(acumulado) + len(trozo) + 1 <= max_chars:
                    acumulado = f"{acumulado} {trozo}".strip()
                else:
                    if acumulado:
                        frases.append(acumulado)
                    if len(trozo) > max_chars:
                        sub = ""
                        for pal in trozo.split():
                            if len(sub) + len(pal) + 1 <= max_chars:
                                sub = f"{sub} {pal}".strip()
                            else:
                                if sub:
                                    frases.append(sub)
                                sub = pal
                        acumulado = sub
                    else:
                        acumulado = trozo
            if acumulado:
                frases.append(acumulado)
            return frases

        async def generar_audio_tts(texto: str, ruta_salida: str) -> bool:
            """Genera locución TTS de manera robusta e infalible (Google TTS por fragmentos + edge-tts)."""
            if not texto or not ruta_salida:
                return False

            dir_salida = os.path.dirname(os.path.abspath(ruta_salida))
            if dir_salida:
                os.makedirs(dir_salida, exist_ok=True)

            # 1. Intentar edge-tts con timeout corto (si Microsoft no bloquea con 403)
            try:
                import edge_tts
                voz_toby = os.getenv("VOZ_TOBY", "es-PE-AlexNeural")
                pitch_toby = os.getenv("VOZ_TOBY_PITCH", "+0Hz")
                rate_toby = os.getenv("VOZ_TOBY_RATE", "-3%")
                com = edge_tts.Communicate(texto, voz_toby, pitch=pitch_toby, rate=rate_toby)
                await asyncio.wait_for(com.save(ruta_salida), timeout=4.0)
                if os.path.exists(ruta_salida) and os.path.getsize(ruta_salida) > 1000:
                    print(f"✅ Locución TTS ({voz_toby}) generada con edge-tts ({os.path.getsize(ruta_salida)} bytes).")
                    return True
            except Exception as e_edge:
                pass

            # 2. Motor infalible: Google Translate TTS con fragmentación inteligente (<85 chars)
            def _descargar_gtts_chunks() -> bool:
                try:
                    import urllib.request
                    import urllib.parse
                    frases = dividir_texto_tts(texto, max_chars=85)
                    if not frases:
                        return False
                    audio_total = bytearray()
                    for f in frases:
                        q = urllib.parse.quote(f)
                        url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={q}&tl=es&client=tw-ob"
                        req = urllib.request.Request(
                            url,
                            headers={
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                            }
                        )
                        datos_chunk = None
                        for intento in range(2):
                            try:
                                with urllib.request.urlopen(req, timeout=8) as r:
                                    if r.status == 200:
                                        datos_chunk = r.read()
                                        break
                            except Exception:
                                time.sleep(0.3)
                        if not datos_chunk:
                            print(f"⚠️ No se pudo descargar fragmento TTS: «{f}»")
                            return False
                        audio_total.extend(datos_chunk)

                    if len(audio_total) > 1000:
                        with open(ruta_salida, "wb") as f_out:
                            f_out.write(audio_total)

                        # Modular suave y naturalmente sin distorsión de tono artificial
                        fbin = shutil.which("ffmpeg") or "ffmpeg"
                        ruta_temp = ruta_salida + ".raw_tts.mp3"
                        try:
                            os.replace(ruta_salida, ruta_temp)
                            cmd_robot = [
                                fbin, "-y",
                                "-i", ruta_temp,
                                "-af", "volume=1.1,atempo=0.95",
                                "-b:a", "128k",
                                ruta_salida
                            ]
                            res_r = subprocess.run(cmd_robot, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                            if res_r.returncode == 0 and os.path.exists(ruta_salida) and os.path.getsize(ruta_salida) > 1000:
                                print(f"🎙️ Locución modulada suavemente ({os.path.getsize(ruta_salida)} bytes).")
                            else:
                                if os.path.exists(ruta_temp) and not os.path.exists(ruta_salida):
                                    os.replace(ruta_temp, ruta_salida)
                        except Exception as e_mod:
                            print("Nota modulando voz suave:", e_mod)
                            if os.path.exists(ruta_temp) and not os.path.exists(ruta_salida):
                                os.replace(ruta_temp, ruta_salida)
                        finally:
                            if os.path.exists(ruta_temp):
                                try:
                                    os.remove(ruta_temp)
                                except Exception:
                                    pass

                        print(f"✅ Locución TTS generada exitosamente con Google TTS ({len(frases)} fragmentos, {len(audio_total)} bytes).")
                        return True
                except Exception as e_gtts:
                    print(f"Error generando Google TTS: {e_gtts}")
                return False

            ok_gtts = await asyncio.to_thread(_descargar_gtts_chunks)
            if ok_gtts and os.path.exists(ruta_salida) and os.path.getsize(ruta_salida) > 1000:
                return True

            return False

        async def anunciar_turno_por_voz(nombre_destinatario: str):
            """Emite la voz de Toby en vivo en la sala anunciando el turno del siguiente orador."""
            if not tgcalls or reproduciendo_meditacion:
                return
            nom_limpio = str(nombre_destinatario or "").split()[0][:20] or "Compañero"
            texto_tts = f"¡Turno de palabra para {nom_limpio}, adelante te escuchamos!"
            ruta_tts = os.path.join(tempfile.gettempdir(), f"toby_turno_{int(time.time()*1000)}.mp3")
            ruta_pcm = ruta_tts.rsplit(".", 1)[0] + ".raw"
            try:
                from telethon.tl.types import InputPeerSelf

                # 1. Generar audio TTS
                ok_tts = await generar_audio_tts(texto_tts, ruta_tts)
                if not ok_tts or not os.path.exists(ruta_tts) or os.path.getsize(ruta_tts) < 1000:
                    print(f"⚠️ TTS turno: audio no generado para {nom_limpio}")
                    return

                # 2. Refrescar input_call en caché de PyTgCalls
                try:
                    resolved_id = await tgcalls.resolve_chat_id(destino)
                    if hasattr(tgcalls, "_app") and hasattr(tgcalls._app, "_bind_client") and hasattr(tgcalls._app._bind_client, "_cache"):
                        tgcalls._app._bind_client._cache.set_cache(resolved_id, input_call)
                        tgcalls._app._bind_client._cache.set_cache(destino, input_call)
                except Exception:
                    pass

                # 3. Convertir a PCM nativo para latencia mínima
                pcm_generado = await asyncio.to_thread(convertir_audio_a_pcm, ruta_tts)
                if pcm_generado and os.path.exists(pcm_generado):
                    from pytgcalls.types.raw import Stream, AudioStream, AudioParameters
                    from ntgcalls import MediaSource
                    stream_play = Stream(
                        microphone=AudioStream(
                            media_source=MediaSource.FILE,
                            path=os.path.abspath(pcm_generado),
                            parameters=AudioParameters(48000, 2)
                        )
                    )
                else:
                    from pytgcalls.types import MediaStream, AudioQuality
                    stream_play = MediaStream(ruta_tts, audio_parameters=AudioQuality.HIGH)

                # 4. Desmutear robot en Telegram (servidor)
                try:
                    await client(EditGroupCallParticipantRequest(call=input_call, participant=InputPeerSelf(), muted=False))
                except Exception:
                    pass

                # 5. Emitir en la sala usando hot-swap de stream
                await tgcalls.play(destino, stream_play)
                try:
                    await tgcalls.unmute(destino)
                    await tgcalls.resume(destino)
                    await tgcalls.change_volume_call(destino, 200)
                except Exception:
                    pass

                print(f"🤖🎙️ Toby anunció por voz en la sala: Turno para {nom_limpio}")

                duracion_tts = obtener_duracion_segundos(ruta_tts)
                if duracion_tts > 0:
                    await asyncio.sleep(duracion_tts + 0.3)

            except Exception as e_voz:
                print(f"❌ Error emitiendo voz de Toby para turno: {e_voz}")
            finally:
                for r in (ruta_tts, ruta_pcm):
                    try:
                        if os.path.exists(r):
                            os.remove(r)
                    except Exception:
                        pass

        async def reproducir_audio_efimero(ruta_audio: str):
            """Reproduce un audio corto en la sala de voz sin desconectar la llamada."""
            if not tgcalls or not os.path.exists(ruta_audio):
                print(f"⚠️ Audio efímero no encontrado o tgcalls inactivo: {ruta_audio}")
                return
            try:
                from telethon.tl.types import InputPeerSelf

                try:
                    resolved_id = await tgcalls.resolve_chat_id(destino)
                    if hasattr(tgcalls, "_app") and hasattr(tgcalls._app, "_bind_client") and hasattr(tgcalls._app._bind_client, "_cache"):
                        tgcalls._app._bind_client._cache.set_cache(resolved_id, input_call)
                        tgcalls._app._bind_client._cache.set_cache(destino, input_call)
                except Exception:
                    pass

                ruta_pcm = await asyncio.to_thread(convertir_audio_a_pcm, ruta_audio)
                if ruta_pcm and os.path.exists(ruta_pcm):
                    from pytgcalls.types.raw import Stream, AudioStream, AudioParameters
                    from ntgcalls import MediaSource
                    stream_play = Stream(
                        microphone=AudioStream(
                            media_source=MediaSource.FILE,
                            path=os.path.abspath(ruta_pcm),
                            parameters=AudioParameters(48000, 2)
                        )
                    )
                else:
                    from pytgcalls.types import MediaStream, AudioQuality
                    stream_play = MediaStream(ruta_audio, audio_parameters=AudioQuality.HIGH)

                try:
                    await client(EditGroupCallParticipantRequest(call=input_call, participant=InputPeerSelf(), muted=False))
                except Exception:
                    pass

                await tgcalls.play(destino, stream_play)
                try:
                    await tgcalls.unmute(destino)
                    await tgcalls.resume(destino)
                    await tgcalls.change_volume_call(destino, 200)
                except Exception:
                    pass

                dur = obtener_duracion_segundos(ruta_audio)
                if dur > 0:
                    await asyncio.sleep(dur + 0.3)
                print(f"🔔 Audio efímero reproducido con éxito: {os.path.basename(ruta_audio)}")
            except Exception as e_ef:
                print(f"Nota reproduciendo audio efímero ({os.path.basename(ruta_audio)}):", e_ef)

        async def emitir_anuncio_tts(texto: str):
            """Genera locución con la voz de Toby y la emite en vivo en la sala de voz."""
            if not tgcalls or not texto:
                return
            ruta_tts = os.path.join(tempfile.gettempdir(), f"toby_anuncio_{int(time.time()*1000)}.mp3")
            ruta_pcm = ruta_tts.rsplit(".", 1)[0] + ".raw"
            try:
                ok_gen = await generar_audio_tts(texto, ruta_tts)
                if ok_gen and os.path.exists(ruta_tts) and os.path.getsize(ruta_tts) > 1000:
                    print(f"🗣️🎙️ Toby emitiendo locución TTS en la sala: «{texto}»")
                    await reproducir_audio_efimero(ruta_tts)
                else:
                    print(f"⚠️ TTS anuncio: no se pudo generar el audio para «{texto}»")
            except Exception as e_tts:
                print(f"❌ Error emitiendo anuncio TTS de Toby: {e_tts}")
            finally:
                for r in (ruta_tts, ruta_pcm):
                    try:
                        if os.path.exists(r):
                            os.remove(r)
                    except Exception:
                        pass

        # Configurar evento de fin de audio en PyTgCalls
        if tgcalls:
            try:
                from pytgcalls.types import StreamEnded
                @tgcalls.on_update()
                async def manejar_fin_stream(client_call, update):
                    if isinstance(update, StreamEnded):
                        nonlocal reproduciendo_meditacion, indice_pista_actual, tarea_panel_progreso, msg_panel_meditacion_id, tarea_espera_post_meditacion
                        if reproduciendo_meditacion and not eq_estado["cambiando"]:
                            p_fin = indice_pista_actual
                            pistas_completadas.add(p_fin)
                            # Sincronizar con Render y el grupo antes de decidir si hay siguiente pista
                            try:
                                await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                            except Exception as e_sync_st:
                                print("Nota sincronizando cola en fin de stream:", e_sync_st)

                            # Verificar si aún quedan más audios en la cola
                            if p_fin + 1 < len(cola_reproduccion):
                                sig_idx = p_fin + 1
                                indice_pista_actual = sig_idx
                                siguiente_item = cola_reproduccion[sig_idx]
                                total_p = len(cola_reproduccion)
                                inf_sig = siguiente_item.get("info")
                                tit_sig_raw = siguiente_item.get('titulo', 'Audio')
                                ico_sig = "📜" if (inf_sig and "MENSAJE" in str(inf_sig.get("tipo", "")).upper()) or ("MENSAJE" in str(tit_sig_raw).upper()) else "🧘"
                                txt_sig = formatear_info_audio(inf_sig) if inf_sig else f"{ico_sig} **Audio #{sig_idx + 1}:** {tit_sig_raw}"
                                espera_min = int((inf_sig or {}).get("espera_post_meditacion_min", 30 if p_fin == 0 else 0))
                                if espera_min > 0:
                                    reproduciendo_meditacion = False
                                    try:
                                        await cerrar_pantalla_emision_video()
                                    except Exception as e_cpv:
                                        print("Nota cerrando video post-pista:", e_cpv)
                                    if tarea_panel_progreso and not tarea_panel_progreso.done():
                                        tarea_panel_progreso.cancel()
                                    if msg_panel_meditacion_id:
                                        try:
                                            await editar_mensaje_bot(
                                                msg_panel_meditacion_id,
                                                f"⏹️ **PISTA #{p_fin + 1} FINALIZADA**\n🔓 Micrófonos desbloqueados.\n⏭️ Siguiente en cola ({espera_min} min): «{tit_sig_raw}»",
                                                reply_markup={
                                                    "inline_keyboard": [
                                                        [{"text": f"▶️ REPRODUCIR AHORA PISTA #{sig_idx + 1}", "callback_data": "panel_play_pause"}]
                                                    ]
                                                }
                                            )
                                        except Exception:
                                            pass
                                        msg_panel_meditacion_id = None
                                    await desbloquear_todos_los_participantes()
                                    avisar_con_bot(
                                        f"🧘 **Primera reproducción finalizada.** Los micrófonos han sido restablecidos.\n\n"
                                        f"⏳ **En {espera_min} minutos se reproducirá automáticamente el siguiente audio encolado (o usa `/reproducir` / `/saltaraudio` para iniciarlo ya):**\n{txt_sig}",
                                        es_efimero=False
                                    )
                                    cancelar_espera_post_meditacion()
                                    async def _esperar_y_reproducir_sig(idx_target, mins):
                                        try:
                                            await asyncio.sleep(mins * 60)
                                            await reproducir_meditacion(idx_target)
                                        except asyncio.CancelledError:
                                            print(f"⏹️ Espera post-meditación de {mins} min cancelada por comando manual.")
                                    tarea_espera_post_meditacion = asyncio.create_task(_esperar_y_reproducir_sig(sig_idx, espera_min))
                                else:
                                    avisar_con_bot(
                                        f"🔔 **Pista {p_fin + 1} finalizada.**\n\n▶️ **Continuando con la pista {sig_idx + 1} de {total_p}:**\n{txt_sig}\n\n{ico_sig} Por favor continúen en silencio...",
                                        es_efimero=True
                                    )
                                    ok_sig = await reproducir_meditacion(sig_idx)
                                    if not ok_sig:
                                        print("Error reproduciendo siguiente pista, finalizando sesión de meditación.")
                                        reproduciendo_meditacion = False
                                        try:
                                            await cerrar_pantalla_emision_video()
                                        except Exception:
                                            pass
                                        if tarea_panel_progreso and not tarea_panel_progreso.done():
                                            tarea_panel_progreso.cancel()
                                        msg_panel_meditacion_id = None
                                        await desbloquear_todos_los_participantes()
                            else:
                                reproduciendo_meditacion = False
                                try:
                                    await cerrar_pantalla_emision_video()
                                except Exception as e_cpv_fin:
                                    print("Nota cerrando video fin sesión:", e_cpv_fin)
                                if tarea_panel_progreso and not tarea_panel_progreso.done():
                                    tarea_panel_progreso.cancel()
                                if msg_panel_meditacion_id:
                                    try:
                                        await editar_mensaje_bot(
                                            msg_panel_meditacion_id,
                                            "⏹️ **REPRODUCCIÓN FINALIZADA**\n🔓 Micrófonos desbloqueados.",
                                            reply_markup={"inline_keyboard": []}
                                        )
                                    except Exception:
                                        pass
                                    msg_panel_meditacion_id = None
                                print("Reproducción de la sesión concluida automáticamente.")
                                await desbloquear_todos_los_participantes()
                                avisar_con_bot("🧘 **Sesión finalizada:** Los micrófonos han sido restablecidos. ¡Esperamos que hayan tenido una gran sesión!", es_efimero=False)
                                # Reanudar grabación para el segmento post-meditación si no fue cancelada
                                if not grabacion_cancelada and not grabacion_pausada:
                                    if ruta_grabacion_post not in segmentos_grabados:
                                        segmentos_grabados.append(ruta_grabacion_post)
                                    try:
                                        from pytgcalls.types import RecordStream
                                        os.makedirs(os.path.dirname(os.path.abspath(ruta_grabacion_post)), exist_ok=True)
                                        await tgcalls.record(destino, RecordStream(ruta_grabacion_post))
                                        print(f"🎙️ Grabación post-meditación (preguntas y testimonios) iniciada exitosamente -> {ruta_grabacion_post}")
                                    except Exception as e:
                                        print("Nota reanudando grabación tras meditación:", e)
            except Exception as e:
                print("Nota configurando StreamEnded handler:", e)

        # Escuchar comandos de usuarios (/puntos, /ranking, /reglas, /ayuda, /meditacion, /turno, /ceder, /turnos, /buscar, /resumen, /acta, /oracion)
        @client.on(events.NewMessage(pattern=r"(?i)^\s*/(puntos|miperfil|ranking|top|ayuda|reglas|start|meditacion|audio|turno|pedirturno|mano|ceder|turnos|buscar|resumen|acta|oracion|luna|faseluna)"))
        async def responder_comandos_en_vivo(event):
            sender = await event.get_sender()
            
            uid = sender.id if sender else event.sender_id
            
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
                        await responder(f"✋ Ya estás en la fila de espera (Posición #{idx}). Te avisaremos cuando sea tu momento.")
                        await actualizar_mensaje_turnos(forzar_al_fondo=True)
                        return
                if uid in oradores_activos:
                    await responder("🎙️ ¡Ya tienes el micrófono habilitado para hablar!")
                    return
                cola_turnos.append({"id": uid, "nombre": nom, "username": usr})
                pos = len(cola_turnos)
                await responder(f"✋ Turno solicitado con éxito (Posición #{pos}). Te avisaremos cuando sea tu momento.")
                await actualizar_mensaje_turnos(forzar_al_fondo=True)
            elif texto_cmd in ("/ceder",):
                en_cola = any(t["id"] == uid for t in cola_turnos)
                era_orador = uid in oradores_activos
                cola_turnos[:] = [t for t in cola_turnos if t["id"] != uid]
                oradores_activos.discard(uid)
                if era_orador or en_cola:
                    await responder(f"🤝 **{nom}**, has cedido tu turno de palabra. ¡Muchas gracias por compartir!")
                    await actualizar_mensaje_turnos(forzar_al_fondo=True)
                else:
                    await responder("⏳ No tenías turno en espera ni micrófono activo.")
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
                    resp = f"📝 **MINUTA DE LA REUNIÓN ({minuta['fecha']})**\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n{minuta['resumen']}"
                    await responder(resp)
                else:
                    await responder(f"⏳ ninguna minuta registrada para {fecha_req or 'la última fecha'}.")
            elif texto_cmd in ("/acta",):
                fecha_req = partes[1].strip() if len(partes) > 1 else None
                minuta = obtener_minuta(fecha_req)
                if minuta and minuta.get("ruta_pdf") and os.path.exists(minuta["ruta_pdf"]):
                    await responder(f"📄 **Acta Oficial de la Reunión ({minuta['fecha']}):**", file=minuta["ruta_pdf"])
                else:
                    await responder("ℹ️ No hay un documento PDF de acta disponible para esa fecha.")
            elif texto_cmd in ("/luna", "/faseluna"):
                try:
                    from astronomia_luna import calcular_astronomia_lunar
                    astro = calcular_astronomia_lunar()
                    resp = (
                        f"🌕 **FASE LUNAR DE HOY (Bucaramanga, Colombia)**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🌓 **Fase:** {astro['fase']}\n"
                        f"✨ **Iluminación:** {astro['iluminacion']}%\n"
                        f"📅 **Edad lunar:** {astro['edad']} días\n"
                        f"🌍 **Distancia:** {astro['distancia']:,} km\n\n"
                        f"🌙 ↗️ **Salida:** {astro['salida']}\n"
                        f"🌙 ↘️ **Puesta:** {astro['puesta']}\n"
                    ).replace(",", ".")
                    await responder(resp)
                except Exception as e_l_resp:
                    await responder(f"⚠️ Error calculando fase lunar: {e_l_resp}")
            elif texto_cmd in ("/oracion",) or (texto_cmd == "/start" and param == "oracion"):
                resp = (
                    "🕊️ **ORACIÓN Y RECOGIMIENTO COMUNITARIO**\n"
                    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                    "\"En este momento de quietud y gratitud, acallamos nuestra mente y abrimos el corazón.\n\n"
                    "Agradecemos por este día, por cada respiración, por los aprendizajes recibidos y por la presencia de cada persona en esta comunidad.\n\n"
                    "Pedimos paz profunda en nuestro interior, claridad en los pensamientos, serenidad en las acciones y bienestar para nuestras familias.\n\n"
                    "Guardamos silencio y respiramos en calma, presentes en el aquí y el ahora.\"\n\n"
                    "🙏*Mantengamos silencio en la sala para cultivar la paz interior de todos.*"
                )
                await responder(resp)
            else:
                resp = generar_texto_reglas()
                await responder(resp)

        # Escuchar controles de meditación, moderación de turnos y control de grabación exclusivos para administradores
        @client.on(events.NewMessage(pattern=r"(?i)^\s*/(reproducir|play|pausar|pause|continuar|resume|atrasar|retroceder|rewind|adelantar|avanzar|forward|volup|masvolumen|voldown|menosvolumen|detener|stop|volumen|vol|siguiente|next|saltaraudio|siguienteaudio|nextaudio|limpiarturnos|ocultarturnos|apagarturnos|desactivarturnos|turnosoff|mostrarturnos|encenderturnos|activarturnos|turnoson|toggleturnos|ventanaturnos|limpiarsala|limpiaravisos|hablar|desmutear|mutear|desmuteartodos|abrir|desbloquear|desbloquearadmins|liberaradmins|blindaradmins|pausargrabacion|pausar_rec|reanudargrabacion|reanudar_rec|detenergrabacion|cancelar_rec|estadograbacion|estado_rec)"))
        async def controlar_meditacion_admin(event):
            sender = await event.get_sender()
            
            uid = sender.id if sender else event.sender_id
            
            if event.is_group and getattr(event, "message", None) and hasattr(event.message, "id"):
                ids_mensajes_efimeros.add(event.message.id)

            async def responder_admin(texto_resp, **kwargs):
                try:
                    r = await event.reply(texto_resp, **kwargs)
                except Exception:
                    try:
                        r = await client.send_message(entidad, texto_resp)
                    except Exception:
                        r = None
                if event.is_group and r and hasattr(r, "id"):
                    ids_mensajes_efimeros.add(r.id)
                return r

            es_admin_emisor = await es_admin_seguro(event, sender)
            if not es_admin_emisor:
                await responder_admin("⛔ Solo los administradores pueden utilizar este comando.")
                return

            partes_cmd = event.raw_text.strip().split()
            cmd = partes_cmd[0].lower().split("@")[0]
            nonlocal ruta_meditacion, info_catalogo_hoy, cola_reproduccion, indice_pista_actual, reproduciendo_meditacion, volumen_actual, tarea_panel_progreso, msg_panel_meditacion_id, ultimo_texto_panel, token_reproduccion
            if cmd in ("/reproducir", "/play"):
                if reproduciendo_meditacion and eq_estado.get("t_pausa") is not None and len(partes_cmd) == 1:
                    if tgcalls:
                        try:
                            await tgcalls.resume(destino)
                            marcar_reanudacion()
                            await actualizar_panel_progreso(forzar=True)
                            await responder_admin("▶️ Meditación reanudada en el segundo actual.")
                            return
                        except Exception as e_res:
                            print("Nota reanudando:", e_res)

                cancelar_espera_post_meditacion()
                await responder_admin("🧘 **Iniciando reproducción...** Sincronizando lista de hoy y preparando emisión en vivo.")
                if not cola_reproduccion and (not ruta_meditacion or not os.path.exists(ruta_meditacion)):
                    ruta_meditacion, info_catalogo_hoy, cola_reproduccion = await buscar_audio_meditacion(client, entidad, admin_ids)
                else:
                    try:
                        await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                    except Exception as e_sync_play:
                        print("Nota sincronizando cola en /reproducir:", e_sync_play)

                # Si el admin indicó número de pista explícito (ej. /reproducir 2)
                if len(partes_cmd) > 1 and partes_cmd[1].isdigit():
                    idx_solicitado = int(partes_cmd[1]) - 1
                    if 0 <= idx_solicitado < len(cola_reproduccion):
                        indice_pista_actual = idx_solicitado
                        pistas_completadas.discard(indice_pista_actual)
                else:
                    # Avanzar automáticamente cualquier pista que ya haya terminado hoy
                    while indice_pista_actual in pistas_completadas and indice_pista_actual + 1 < len(cola_reproduccion):
                        indice_pista_actual += 1
                    if cola_reproduccion and indice_pista_actual >= len(cola_reproduccion):
                        indice_pista_actual = len(cola_reproduccion) - 1

                if tgcalls and (cola_reproduccion or (ruta_meditacion and os.path.exists(ruta_meditacion))):
                    tit_p = (cola_reproduccion[indice_pista_actual].get("titulo") if cola_reproduccion else "Meditación")
                    ok = await reproducir_meditacion(indice_pista_actual)
                    if ok:
                        await responder_admin(f"▶️ Reproduciendo **Pista #{indice_pista_actual + 1}** («{tit_p}») en la sala de voz...")
                    else:
                        detalle = f"\n*(Detalle: {ultimo_error_reproduccion})*" if ultimo_error_reproduccion else ""
                        await responder_admin(f"❌ Error al iniciar la reproducción de la pista.{detalle}")
                else:
                    await responder_admin("⚠️ No se encontró ningún archivo de meditación de tarea disponible.")
            elif cmd in ("/saltaraudio", "/siguienteaudio", "/nextaudio"):
                cancelar_espera_post_meditacion()
                try:
                    await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                except Exception as e_sync_skip:
                    print("Nota sincronizando cola en /saltaraudio:", e_sync_skip)

                if reproduciendo_meditacion:
                    pistas_completadas.add(indice_pista_actual)
                    target_idx = indice_pista_actual + 1
                else:
                    # Si no estaba reproduciendo (ej. en espera de 30 min o tras terminar pista 1), saltar a la primera pista pendiente
                    target_idx = indice_pista_actual + 1 if indice_pista_actual in pistas_completadas else indice_pista_actual
                    while target_idx in pistas_completadas and target_idx + 1 < len(cola_reproduccion):
                        target_idx += 1

                if target_idx < len(cola_reproduccion):
                    tit_sig = cola_reproduccion[target_idx].get("titulo") or f"Pista #{target_idx + 1}"
                    await responder_admin(f"⏭️ Saltando a la **Pista #{target_idx + 1} de {len(cola_reproduccion)}**: «{tit_sig}»...")
                    ok = await reproducir_meditacion(target_idx)
                    if not ok and ultimo_error_reproduccion:
                        await responder_admin(f"⚠️ No se pudo reproducir la pista #{target_idx + 1}: {ultimo_error_reproduccion}")
                elif reproduciendo_meditacion:
                    token_reproduccion += 1
                    reproduciendo_meditacion = False
                    eq_estado["cambiando"] = False
                    try:
                        await cerrar_pantalla_emision_video()
                    except Exception:
                        pass
                    if tgcalls:
                        try:
                            await tgcalls.leave_call(destino)
                        except Exception:
                            pass
                    if tarea_panel_progreso and not tarea_panel_progreso.done():
                        tarea_panel_progreso.cancel()
                    if msg_panel_meditacion_id:
                        try:
                            await editar_mensaje_bot(
                                msg_panel_meditacion_id,
                                "⏹️ **REPRODUCCIÓN FINALIZADA**\n🔓 Micrófonos desbloqueados.",
                                reply_markup={"inline_keyboard": []}
                            )
                        except Exception:
                            pass
                        msg_panel_meditacion_id = None
                    await desbloquear_todos_los_participantes()
                    await responder_admin("⏹️ No hay más audios en la cola. Reproducción finalizada y micrófonos desbloqueados.")
                else:
                    await responder_admin(f"ℹ️ No hay más pistas pendientes después de la pista #{indice_pista_actual + 1} (Total en cola: {len(cola_reproduccion)}). Usa `/cola` para verificar o `/reproducir 1` para repetir.")
            elif cmd in ("/pausar", "/pause"):
                if tgcalls and reproduciendo_meditacion:
                    try:
                        await tgcalls.pause(destino)
                        marcar_pausa()
                        await actualizar_panel_progreso(forzar=True)
                        await responder_admin("⏸️ Meditación pausada.")
                    except Exception as e:
                        await responder_admin(f"Error al pausar: {e}")
                else:
                    await responder_admin("⚠️ No hay reproducción activa para pausar.")
            elif cmd in ("/continuar", "/resume"):
                if tgcalls and reproduciendo_meditacion:
                    try:
                        await tgcalls.resume(destino)
                        marcar_reanudacion()
                        await actualizar_panel_progreso(forzar=True)
                        await responder_admin("▶️ Meditación reanudada.")
                    except Exception as e:
                        await responder_admin(f"Error al reanudar: {e}")
                else:
                    await responder_admin("⚠️ No hay reproducción en pausa para reanudar.")
            elif cmd in ("/atrasar", "/retroceder", "/rewind"):
                if not reproduciendo_meditacion:
                    await responder_admin("⚠️ No hay reproducción activa para retroceder.")
                else:
                    delta = 30.0
                    if len(partes_cmd) > 1 and partes_cmd[1].replace("-", "").isdigit():
                        delta = float(partes_cmd[1].replace("-", ""))
                    pos_act = posicion_actual()
                    nueva_pos = max(0.0, pos_act - delta)
                    ok = await saltar_a_posicion(nueva_pos)
                    if ok:
                        await responder_admin(f"⏪ Retrocedido a `{formatear_tiempo_mm_ss(nueva_pos)}` (-{int(delta)}s).")
                    else:
                        await responder_admin("⚠️ No se pudo retroceder la reproducción.")
            elif cmd in ("/adelantar", "/avanzar", "/forward"):
                if not reproduciendo_meditacion:
                    await responder_admin("⚠️ No hay reproducción activa para adelantar.")
                else:
                    delta = 30.0
                    if len(partes_cmd) > 1 and partes_cmd[1].replace("+", "").isdigit():
                        delta = float(partes_cmd[1].replace("+", ""))
                    pos_act = posicion_actual()
                    dur_tot = dur_pista_actual or 1800.0
                    nueva_pos = min(max(0.0, dur_tot - 5.0), pos_act + delta)
                    ok = await saltar_a_posicion(nueva_pos)
                    if ok:
                        await responder_admin(f"⏩ Adelantado a `{formatear_tiempo_mm_ss(nueva_pos)}` (+{int(delta)}s).")
                    else:
                        await responder_admin("⚠️ No se pudo adelantar la reproducción.")
            elif cmd in ("/voldown", "/menosvolumen"):
                volumen_actual = max(10, volumen_actual - 20)
                if tgcalls:
                    try:
                        await tgcalls.change_volume_call(destino, volumen_actual)
                        await actualizar_panel_progreso(forzar=True)
                        await responder_admin(f"🔉 Volumen: **{int(round(volumen_actual/2))}%**")
                    except Exception as e:
                        await responder_admin(f"Error al ajustar volumen: {e}")
            elif cmd in ("/volup", "/masvolumen"):
                volumen_actual = min(200, volumen_actual + 20)
                if tgcalls:
                    try:
                        await tgcalls.change_volume_call(destino, volumen_actual)
                        await actualizar_panel_progreso(forzar=True)
                        await responder_admin(f"🔊 Volumen: **{int(round(volumen_actual/2))}%**")
                    except Exception as e:
                        await responder_admin(f"Error al ajustar volumen: {e}")
            elif cmd in ("/volumen", "/vol"):
                if len(partes_cmd) > 1 and partes_cmd[1].isdigit():
                    nuevo_vol = max(1, min(200, int(partes_cmd[1])))
                    volumen_actual = nuevo_vol
                    if tgcalls:
                        try:
                            await tgcalls.change_volume_call(destino, nuevo_vol)
                            await actualizar_panel_progreso(forzar=True)
                            await responder_admin(f"🔊 Volumen ajustado a **{nuevo_vol}%**.")
                        except Exception as e:
                            await responder_admin(f"Error al ajustar volumen: {e}")
                    else:
                        await responder_admin("⚠️ El reproductor no está activo.")
                else:
                    await responder_admin("ℹ️ Uso: `/volumen 1-200` (Ejemplo: `/volumen 80`).")
            elif cmd in ("/detener", "/stop"):
                cancelar_espera_post_meditacion()
                token_reproduccion += 1
                reproduciendo_meditacion = False
                eq_estado["cambiando"] = False
                segundos_inactividad_mic.clear()
                avisados_auto_mute.clear()
                try:
                    await cerrar_pantalla_emision_video()
                except Exception:
                    pass
                if tarea_panel_progreso and not tarea_panel_progreso.done():
                    tarea_panel_progreso.cancel()
                if msg_panel_meditacion_id:
                    try:
                        await editar_mensaje_bot(
                            msg_panel_meditacion_id,
                            "⏹️ **REPRODUCCIÓN DETENIDA POR ADMINISTRACIÓN**\n🔓 Los micrófonos han sido desbloqueados.",
                            reply_markup={"inline_keyboard": []}
                        )
                    except Exception:
                        pass
                    msg_panel_meditacion_id = None
                if tgcalls:
                    try:
                        await tgcalls.leave_call(destino)
                    except Exception as e:
                        print("Nota saliendo de tgcalls al detener:", e)
                await desbloquear_todos_los_participantes()
                await responder_admin("⏹️ **Reproducción finalizada.** Modo meditación desactivado y micrófonos restablecidos para todos.")
                avisar_con_bot("⏹️ **Reproducción finalizada.** Los micrófonos han sido restablecidos.", es_efimero=False)
            elif cmd in ("/desbloquearadmins", "/liberaradmins", "/blindaradmins"):
                # Solo libera/blinda a los administradores. NO detiene la meditación ni toca a los usuarios normales.
                desbloqueados_count = 0
                for aid in list(admin_ids):
                    if aid != me.id:
                        try:
                            admin_peer = await client.get_input_entity(aid)
                            await client(EditGroupCallParticipantRequest(call=input_call, participant=admin_peer, muted=False))
                            desbloqueados_count += 1
                        except Exception:
                            pass
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
                except Exception:
                    pass
                await responder_admin(f"🔓 **Administradores liberados** ({desbloqueados_count}). La meditación/reproducción continúa sin interrupción y el candado global de la sala fue retirado.")
            elif cmd in ("/desmuteartodos", "/abrir", "/desbloquear"):
                reproduciendo_meditacion = False
                segundos_inactividad_mic.clear()
                avisados_auto_mute.clear()
                if tgcalls:
                    try:
                        await tgcalls.leave_call(destino)
                    except Exception as e_lv:
                        print("Nota saliendo de tgcalls al desbloquear:", e_lv)
                desbloqueados_count = 0
                for aid in list(admin_ids):
                    if aid != me.id:
                        try:
                            admin_peer = await client.get_input_entity(aid)
                            await client(EditGroupCallParticipantRequest(call=input_call, participant=admin_peer, muted=False))
                            desbloqueados_count += 1
                        except Exception:
                            pass
                await desbloquear_todos_los_participantes()
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
                except Exception:
                    pass
                await responder_admin(f"🔓 **¡ÉXITO TOTAL!** Modo meditación desactivado. Micrófonos liberados para {desbloqueados_count} administradores y todos los participantes en sala. El candado global fue desactivado.")
                avisar_con_bot("🔓 **Micrófonos abiertos:** El candado de silencio ha sido retirado para toda la sala. ¡Pueden abrir su micrófono cuando deseen hablar!", es_efimero=False)
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
                await actualizar_mensaje_turnos(forzar_al_fondo=True)
                await responder_admin(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Tu micrófono está listo.")
                avisar_con_bot(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Por favor abre tu micrófono para compartir.", es_efimero=True)
                if not reproduciendo_meditacion:
                    lanzar_tarea(anunciar_turno_por_voz(s_nom))
            elif cmd in ("/limpiarturnos",):
                cola_turnos.clear()
                await actualizar_mensaje_turnos(forzar_al_fondo=True)
                await responder_admin("🧹 **Lista de turnos vaciada exitosamente.**")
            elif cmd in ("/ocultarturnos", "/apagarturnos", "/desactivarturnos", "/turnosoff"):
                _, msg_est = await cambiar_estado_lista_turnos(False)
                await responder_admin(msg_est)
            elif cmd in ("/mostrarturnos", "/encenderturnos", "/activarturnos", "/turnoson"):
                _, msg_est = await cambiar_estado_lista_turnos(True)
                await responder_admin(msg_est)
            elif cmd in ("/toggleturnos", "/ventanaturnos"):
                _, msg_est = await cambiar_estado_lista_turnos(None)
                await responder_admin(msg_est)
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
                        lanzar_tarea(auto_desbloquear_microfono(t_uid, DURACION_BLOQUEO_MUTE_SEGUNDOS))
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
            
            uid = sender.id if sender else event.sender_id
            
            if event.is_group and getattr(event, "message", None) and hasattr(event.message, "id"):
                ids_mensajes_efimeros.add(event.message.id)

            async def resp(texto_resp, **kwargs):
                r = await event.reply(texto_resp, **kwargs)
                if event.is_group and r and hasattr(r, "id"):
                    ids_mensajes_efimeros.add(r.id)
                return r

            if not await es_admin_seguro(event, sender):
                await resp("⛔ Solo los administradores pueden usar el ecualizador.")
                return
            if not MEJORA_AUDIO:
                await resp("⏳dulo mejorar_audio.py no está disponible en el servidor.")
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

        # Gestionar lista de reproducción: /cola, /playlist, /encolar, /agregar, /quitar, /remover, /limpiarcola
        @client.on(events.NewMessage(pattern=r"(?i)^/(cola|playlist|encolar|agregar|quitar|remover|quitarcola|removercola|limpiarcola|vaciarcola)(@\w+)?(\s|$)"))
        async def gestionar_cola_reproduccion(event):
            sender = await event.get_sender()
            
            uid = sender.id if sender else event.sender_id
            
            if event.is_group and getattr(event, "message", None) and hasattr(event.message, "id"):
                ids_mensajes_efimeros.add(event.message.id)

            async def resp_q(texto_resp, **kwargs):
                try:
                    r = await event.reply(texto_resp, **kwargs)
                except Exception:
                    try:
                        r = await client.send_message(entidad, texto_resp)
                    except Exception:
                        r = None
                if event.is_group and r and hasattr(r, "id"):
                    ids_mensajes_efimeros.add(r.id)
                return r

            if not await es_admin_seguro(event, sender):
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
                try:
                    await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                except Exception as e_sync_c:
                    print("Nota sincronizando cola en /cola:", e_sync_c)
                txt_cola = formatear_cola_audios(cola_reproduccion, indice_pista_actual, reproduciendo_meditacion)
                txt_ayuda = "\n\n💡 *Comandos disponibles:*\n• `/quitar <número/posición>` — Quitar un audio de la cola (ej: `/quitar 2`)\n• `/encolar <número/nombre>` — Añadir audio a la cola\n• `/limpiarcola` — Vaciar la cola completa\n• `/saltaraudio` — Saltar a la siguiente pista"
                await resp_q(txt_cola + txt_ayuda)

            elif cmd_q in ("/limpiarcola", "/vaciarcola"):
                cancelar_espera_post_meditacion()
                pistas_completadas.clear()
                indice_pista_actual = 0
                pista_3am = await asyncio.to_thread(obtener_pista_oficial_3am)
                if pista_3am:
                    cola_reproduccion[:] = [pista_3am]
                    ruta_meditacion = pista_3am["ruta"]
                    info_catalogo_hoy = pista_3am.get("info")
                else:
                    cola_reproduccion.clear()
                    ruta_meditacion = None
                    info_catalogo_hoy = None
                guardar_cola_hoy(cola_reproduccion)
                await resp_q("🗑️ ** Audios adicionales eliminados.** Se mantiene como Pista #1 la Meditación Oficial programada a las 3:00 AM.")
                await actualizar_panel_progreso(forzar=True)

            elif cmd_q in ("/quitar", "/remover", "/quitarcola", "/removercola"):
                if not arg_q:
                    await resp_q("ℹ️ Uso: `/quitar <número o posición>` (Ejemplo: `/quitar 3` o `/quitar 2`).")
                    return
                if not cola_reproduccion and ruta_meditacion:
                    cola_reproduccion.append({
                        "ruta": ruta_meditacion,
                        "info": info_catalogo_hoy,
                        "titulo": (info_catalogo_hoy or {}).get("titulo", "Meditación")
                    })
                if not cola_reproduccion:
                    await resp_q("ℹ️ La lista de reproducción ya está vacía.")
                    return

                removido = None
                # 1. Intentar por posición exacta (1-based index) si el usuario puso posición (ej. 2)
                try:
                    pos = int(arg_q)
                    if 1 <= pos <= len(cola_reproduccion):
                        removido = cola_reproduccion.pop(pos - 1)
                except ValueError:
                    pass

                # 2. Si no fue por posición, buscar por número de audio (ej. #3 o #1094)
                if not removido:
                    idx_encontrado = None
                    for i_c, it_c in enumerate(cola_reproduccion):
                        num_it = str((it_c.get("info") or {}).get("numero") or "")
                        tit_it = str(it_c.get("titulo") or "").lower()
                        if num_it == str(arg_q).strip() or str(arg_q).lower() in tit_it:
                            idx_encontrado = i_c
                            break
                    if idx_encontrado is not None:
                        removido = cola_reproduccion.pop(idx_encontrado)

                if removido:
                    if len(cola_reproduccion) == 0:
                        ruta_meditacion = None
                        info_catalogo_hoy = None
                        indice_pista_actual = 0
                    else:
                        if indice_pista_actual >= len(cola_reproduccion):
                            indice_pista_actual = max(0, len(cola_reproduccion) - 1)
                        ruta_meditacion = cola_reproduccion[indice_pista_actual]["ruta"]
                        info_catalogo_hoy = cola_reproduccion[indice_pista_actual].get("info")

                    guardar_cola_hoy(cola_reproduccion)
                    tit_rem = removido.get("titulo") or (removido.get("info") or {}).get("titulo") or "Audio"
                    await resp_q(f"🗑️ **Audio removido:** «{tit_rem}».\n\n📋 Total restante en cola: **{len(cola_reproduccion)} pistas**.")
                    await actualizar_panel_progreso(forzar=True)
                else:
                    await resp_q(f"⚠️ No se encontró ningún audio con el número o posición «{arg_q}». Consulta `/cola` para ver la lista actual.")

            elif cmd_q in ("/encolar", "/agregar"):
                # Si no hay argumentos y es respuesta a un mensaje con audio
                if not arg_q and event.is_reply:
                    reply_msg = await event.get_reply_message()
                    if reply_msg and (
                        reply_msg.audio
                        or reply_msg.voice
                        or (
                            reply_msg.document
                            and (
                                (reply_msg.document.mime_type and "audio" in reply_msg.document.mime_type)
                                or any(getattr(a, "file_name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")) for a in getattr(reply_msg.document, "attributes", []))
                            )
                        )
                    ):
                        os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
                        n_arch = getattr(reply_msg.audio, "file_name", "") or getattr(reply_msg.voice, "file_name", "") or ""
                        if not n_arch and reply_msg.document:
                            for a in getattr(reply_msg.document, "attributes", []):
                                if getattr(a, "file_name", ""):
                                    n_arch = getattr(a, "file_name", "")
                        txt_raw_rep = reply_msg.raw_text or ""
                        info_cat = identificar_audio_catalogo(txt_raw_rep, n_arch)
                        if not info_cat and ("MARIO CARRILLO" in txt_raw_rep.upper() or "MARIO CARRILLO" in n_arch.upper()):
                            m_tit = re.search(r"«([^»]+)»", txt_raw_rep)
                            tit_m = m_tit.group(1).strip() if m_tit else n_arch.replace(".mp3", "")
                            info_cat = {
                                "numero": "",
                                "tipo": "MENSAJE",
                                "titulo": tit_m,
                                "maestro": "JESUS MARIO CARRILLO DURAN",
                                "es_mario": True,
                                "es_adicional": True,
                                "espera_post_meditacion_min": 30
                            }
                        tit_candidato = (info_cat or {}).get("titulo") or n_arch or f"Pista #{len(cola_reproduccion) + 1}"
                        # Evitar duplicados si ya está en la cola
                        ya_en_cola = any(
                            it.get("msg_id_origen") == reply_msg.id
                            or (tit_candidato and str(it.get("titulo", "")).strip().lower() == tit_candidato.strip().lower())
                            for it in cola_reproduccion
                        )
                        if ya_en_cola:
                            await resp_q(f"✅ **El audio ya está en la cola de reproducción:** «{tit_candidato}»\n📋 Total en cola: **{len(cola_reproduccion)} pistas**.")
                            return

                        idx_n = len(cola_reproduccion) + 1
                        r_dest = os.path.join(CARPETA_MEDITACIONES, f"meditacion_extra_{idx_n}_{reply_msg.id}.mp3")
                        await client.download_media(reply_msg, file=r_dest)
                        item_c = {
                            "ruta": r_dest,
                            "info": info_cat,
                            "titulo": tit_candidato,
                            "msg_id_origen": reply_msg.id
                        }
                        cola_reproduccion.append(item_c)
                        guardar_cola_hoy(cola_reproduccion)
                        if MEJORA_AUDIO:
                            asyncio.create_task(preparar_audio_eq(r_dest))
                        await resp_q(f"▶️ **Audio añadido a la cola de reproducción:** «{item_c['titulo']}»\n\n📋 Total en cola: **{len(cola_reproduccion)} pistas** (se reproducirá 30 min después de terminar la 1.ª reproducción).")
                        await actualizar_panel_progreso(forzar=True)
                        return

                if not arg_q:
                    await resp_q("ℹ️ Uso: `/encolar [audio] a las [hora]` (Ejemplo: `/encolar 15 a las 9:15pm` o `/encolar mensaje 606`). También puedes responder a cualquier audio con `/encolar`.")
                    return
                # Extraer posible hora programada (ej. "a las 9:15pm", "a las 21:15", "9:15 pm")
                hora_prog = None
                m_hora = re.search(r"(?:a\s+las\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?", arg_q, re.IGNORECASE)
                texto_busqueda = arg_q
                if m_hora:
                    h = int(m_hora.group(1))
                    m = int(m_hora.group(2))
                    ampm = (m_hora.group(3) or "").lower()
                    if ampm == "pm" and h < 12:
                        h += 12
                    elif ampm == "am" and h == 12:
                        h = 0
                    hora_prog = f"{h:02d}:{m:02d}"
                    texto_busqueda = arg_q[:m_hora.start()].strip() + " " + arg_q[m_hora.end():].strip()
                    texto_busqueda = texto_busqueda.strip()

                items_encontrados = identificar_todos_los_audios(texto_busqueda if texto_busqueda else arg_q)
                if not items_encontrados:
                    await resp_q(f"⚠️ No se encontró ningún audio en el catálogo para: «{arg_q}».")
                    return
                if not cola_reproduccion:
                    pista_3am_enc = await asyncio.to_thread(obtener_pista_oficial_3am)
                    if pista_3am_enc:
                        cola_reproduccion.append(pista_3am_enc)
                anadidos = []
                for it in items_encontrados:
                    t = it.get("tipo", "MEDITACION")
                    try:
                        n = int(it.get("numero"))
                    except (ValueError, TypeError):
                        n = None
                    if n:
                        if any(str((ex.get("info") or {}).get("numero") or "").strip() == str(n) and str((ex.get("info") or {}).get("tipo") or "MEDITACION").upper() == t.upper() for ex in cola_reproduccion):
                            anadidos.append(it)
                            continue
                        r_drive = obtener_o_descargar_audio(t, n)
                        if r_drive and os.path.exists(r_drive) and os.path.getsize(r_drive) > 5000:
                            it_copia = dict(it)
                            it_copia["es_adicional"] = True
                            item_c = {
                                "ruta": r_drive,
                                "info": it_copia,
                                "titulo": it_copia.get("titulo", f"{t} #{n}"),
                                "hora_programada": hora_prog
                            }
                            cola_reproduccion.append(item_c)
                            anadidos.append(it_copia)
                            if MEJORA_AUDIO:
                                asyncio.create_task(preparar_audio_eq(r_drive))
                if anadidos:
                    if not reproduccion_iniciada and len(cola_reproduccion) > 0:
                        ruta_meditacion = cola_reproduccion[0]["ruta"]
                        info_catalogo_hoy = cola_reproduccion[0].get("info")
                    guardar_cola_hoy(cola_reproduccion)
                    txt_anadidos = "\n".join(f"• **{x.get('tipo', 'Audio').capitalize()} #{x.get('numero')}:** «{x.get('titulo', '')}»" for x in anadidos)
                    str_h = f" ⏰ **Programado para:** {m_hora.group(0)}" if m_hora else ""
                    await resp_q(f"▶️ **Pistas añadidas a la cola de reproducción:**\n{txt_anadidos}{str_h}\n\n📋 Total en cola: **{len(cola_reproduccion)} pistas** (la Meditación Oficial de las 3:00 AM se mantiene de #1).")
                    await actualizar_panel_progreso(forzar=True)
                else:
                    await resp_q("⚠️ No se pudieron descargar los audios correspondientes desde Google Drive.")

        # Mantener la lista de turnos siempre visible al fondo si hay conversación activa en el chat
        @client.on(events.NewMessage(chats=entidad))
        async def mantener_turnos_al_fondo_por_chat(event):
            nonlocal mensajes_chat_recientes
            if event.out:
                return
            sender = await event.get_sender()
            
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
            sender_id = event.sender_id
            texto_raw = (event.raw_text or "").strip()
            texto = texto_raw.upper()

            es_audio_adicional_bot = (
                BOT_ID and sender_id == BOT_ID and (
                    "MENSAJE DEL MAESTRO JESUS MARIO CARRILLO" in texto
                    or "AUDIO ADICIONAL PREPARADO PARA SONAR" in texto
                )
            )
            if sender_id == me.id or (BOT_ID and sender_id == BOT_ID and not es_audio_adicional_bot):
                return
            if not es_audio_adicional_bot and not await es_admin_seguro(event, sender):
                return

            # Ignorar mensajes automáticos de bot o sistema para prevenir bucles
            if not es_audio_adicional_bot and any(texto_raw.startswith(p) for p in ("✅", "📢", "🕊️", "▶️", "🔍", "📋", "🧘✨", "🎙️", "ℹ️", "⚠️", "⛔", "[", "🔴", "⚪")):
                return
            if not es_audio_adicional_bot and any(k in texto for k in [
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
                    if not info_cat and ("MARIO CARRILLO" in texto or "MARIO CARRILLO" in nombre_archivo.upper() or es_audio_adicional_bot):
                        m_tit = re.search(r"«([^»]+)»", texto_raw)
                        tit_m = m_tit.group(1).strip() if m_tit else nombre_archivo.replace(".mp3", "")
                        info_cat = {
                            "numero": "",
                            "tipo": "MENSAJE",
                            "titulo": tit_m,
                            "maestro": "JESUS MARIO CARRILLO DURAN",
                            "es_mario": True,
                            "es_adicional": True,
                            "espera_post_meditacion_min": 30
                        }
                    txt_horario, lbl_tarea = determinar_fecha_y_etiqueta_tarea(event.raw_text or "")
                    es_para_hoy = "hoy" in txt_horario.lower() or es_audio_adicional_bot

                    if es_para_hoy:
                        if not cola_reproduccion:
                            pista_3am_ini = await asyncio.to_thread(obtener_pista_oficial_3am)
                            if pista_3am_ini:
                                cola_reproduccion.append(pista_3am_ini)
                        tit_cand = (info_cat or {}).get("titulo") or nombre_archivo or f"Audio #{len(cola_reproduccion) + 1}"
                        if any(
                            it.get("msg_id_origen") == target_msg.id
                            or (tit_cand and str(it.get("titulo", "")).strip().lower() == tit_cand.strip().lower())
                            for it in cola_reproduccion
                        ):
                            return
                        idx_nuevo = len(cola_reproduccion) + 1
                        nombre_f = f"meditacion_hoy_{idx_nuevo}_{target_msg.id}.mp3"
                        ruta = os.path.join(CARPETA_MEDITACIONES, nombre_f)
                        await client.download_media(target_msg, file=ruta)

                        if isinstance(info_cat, dict):
                            info_cat["es_adicional"] = True
                        item_cola = {
                            "ruta": ruta,
                            "info": info_cat,
                            "titulo": tit_cand,
                            "msg_id_origen": target_msg.id
                        }
                        cola_reproduccion.append(item_cola)

                        if not reproduccion_iniciada and len(cola_reproduccion) > 0:
                            ruta_meditacion = cola_reproduccion[0]["ruta"]
                            info_catalogo_hoy = cola_reproduccion[0].get("info")

                        if MEJORA_AUDIO:
                            asyncio.create_task(preparar_audio_eq(ruta))

                        guardar_cola_hoy(cola_reproduccion)
                        print(f"Nueva meditación recibida y guardada para hoy ({lbl_tarea}):", ruta)
                        await actualizar_panel_progreso(forzar=True)

                        if not es_audio_adicional_bot:
                            if info_cat:
                                txt_card = formatear_info_audio(info_cat)
                                await event.reply(f"✅ **Audio recibido y añadido a la lista de hoy (Pista #{len(cola_reproduccion)}):**\n\n{txt_card}\n\nLa Meditación Oficial de las 3:00 AM se mantiene de #1.")
                                avisar_con_bot(f"📢 **{lbl_tarea} registrada (Pista #{len(cola_reproduccion)}):**\n\n{txt_card}")
                            else:
                                await event.reply(f"✅ Meditación recibida para hoy (Pista #{len(cola_reproduccion)}). La Meditación Oficial de las 3:00 AM se mantiene de #1.")
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
                            await event.reply(f"✅ Meditación recibida para mañana ({txt_horario}). Se activará automáticamente mañana (la programación de la sala de hoy se mantiene intacta).*")
                            avisar_con_bot(f"📢 **{lbl_tarea} registrada:**\n\n{txt_card}")
                        else:
                            await event.reply(f"✅ Meditación recibida para mañana. Programada para reproducirse {txt_horario}.")

        # Escuchar comando /soyadmin
        @client.on(events.NewMessage(chats=entidad, pattern=r'(?i)^/soyadmin'))
        async def cmd_soyadmin(event):
            uid = event.sender_id
            r = None
            try:
                es_admin = await es_admin_seguro(event)
                if es_admin:
                    if uid:
                        admin_ids.add(uid)
                        try:
                            input_peer = await client.get_input_entity(uid)
                            await client(EditGroupCallParticipantRequest(call=input_call, participant=input_peer, muted=False))
                        except Exception:
                            pass
                    r = await event.reply("✅ Listo. He verificado tu condición de administrador. Tu micrófono está libre.")
                else:
                    r = await event.reply("❌ Telegram indica que no eres administrador.")
            except Exception as e:
                r = await event.reply(f"⚠️ Error al verificar permisos: {e}")

            # Auto-eliminar comando y respuesta a los 5 segundos (Opción 2)
            async def auto_eliminar_soyadmin():
                await asyncio.sleep(5)
                a_borrar = [m for m in (event.id, getattr(r, 'id', None)) if m]
                try:
                    await client.delete_messages(entidad, a_borrar)
                except Exception:
                    pass
            lanzar_tarea(auto_eliminar_soyadmin())

        @client.on(events.NewMessage(chats=entidad))
        async def comandos_naturales_admin(event):
            sender = await event.get_sender()
            if not await es_admin_seguro(event, sender):
                return
            sender_id = getattr(sender, "id", None) or getattr(event, "sender_id", None)
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
                nonlocal ruta_meditacion, info_catalogo_hoy, cola_reproduccion, indice_pista_actual, ultimo_error_reproduccion, reproduciendo_meditacion, token_reproduccion
                cancelar_espera_post_meditacion()
                if not cola_reproduccion and (not ruta_meditacion or not os.path.exists(ruta_meditacion)):
                    ruta_meditacion, info_catalogo_hoy, cola_reproduccion = await buscar_audio_meditacion(client, entidad, admin_ids)
                else:
                    try:
                        await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                    except Exception:
                        pass
                while indice_pista_actual in pistas_completadas and indice_pista_actual + 1 < len(cola_reproduccion):
                    indice_pista_actual += 1
                if cola_reproduccion and indice_pista_actual >= len(cola_reproduccion):
                    indice_pista_actual = len(cola_reproduccion) - 1
                if tgcalls and (cola_reproduccion or (ruta_meditacion and os.path.exists(ruta_meditacion))):
                    ok = await reproducir_meditacion(indice_pista_actual)
                    if ok:
                        await responder_nat(f"▶️ Reproduciendo Pista #{indice_pista_actual + 1} en la sala de voz...")
                    else:
                        detalle = f"\n*(Detalle: {ultimo_error_reproduccion})*" if ultimo_error_reproduccion else ""
                        await responder_nat(f"❌ Error al iniciar la reproducción de la meditación.{detalle}")
                else:
                    await responder_nat("⚠️ No se encontró ningún archivo de meditación de tarea disponible.")
            # Pausar meditación
            elif any(p in texto_raw for p in ["pausar meditacion", "pausa la meditacion", "pausar meditación", "pausa la meditación", "pausar audio", "pausa el audio"]):
                if tgcalls:
                    try:
                        await tgcalls.pause(destino)
                        marcar_pausa()
                        await responder_nat("⏸️ Meditación pausada por instrucción de administración.")
                    except Exception as e:
                        await responder_nat(f"Nota al pausar: {e}")
            # Reanudar meditación
            elif any(p in texto_raw for p in ["reanudar meditacion", "continua la meditacion", "reanudar meditación", "continuar meditación", "seguir meditación", "reanudar audio", "seguir con el audio"]):
                if tgcalls:
                    try:
                        await tgcalls.resume(destino)
                        marcar_reanudacion()
                        await responder_nat("▶️ Meditación reanudada por instrucción de administración.")
                    except Exception as e:
                        await responder_nat(f"Nota al reanudar: {e}")
            # Detener meditación
            elif any(p in texto_raw for p in ["detener meditacion", "parar meditacion", "detener meditación", "parar meditación", "parar audio", "detener audio"]):
                cancelar_espera_post_meditacion()
                token_reproduccion += 1
                reproduciendo_meditacion = False
                eq_estado["cambiando"] = False
                if tgcalls:
                    try:
                        await tgcalls.leave_call(destino)
                    except Exception as e:
                        print("Nota al detener:", e)
                await desbloquear_todos_los_participantes()
                await responder_nat("⏹️ Reproducción finalizada. Micrófonos restablecidos y desbloqueados.")
            # Siguiente audio en la cola de reproducción
            elif any(p in texto_raw for p in ["siguiente audio", "pasar al siguiente audio", "saltar audio", "siguiente meditacion", "siguiente meditación", "pasar audio"]):
                cancelar_espera_post_meditacion()
                try:
                    await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                except Exception:
                    pass
                if reproduciendo_meditacion:
                    pistas_completadas.add(indice_pista_actual)
                    target_idx = indice_pista_actual + 1
                else:
                    target_idx = indice_pista_actual + 1 if indice_pista_actual in pistas_completadas else indice_pista_actual
                    while target_idx in pistas_completadas and target_idx + 1 < len(cola_reproduccion):
                        target_idx += 1

                if target_idx < len(cola_reproduccion):
                    await responder_nat(f"⏭️ Saltando a la pista {target_idx + 1} de {len(cola_reproduccion)}...")
                    await reproducir_meditacion(target_idx)
                elif reproduciendo_meditacion:
                    token_reproduccion += 1
                    reproduciendo_meditacion = False
                    eq_estado["cambiando"] = False
                    if tgcalls:
                        await tgcalls.leave_call(destino)
                    await desbloquear_todos_los_participantes()
                    await responder_nat("⏹️ Reproducción finalizada y micrófonos desbloqueados.")
                else:
                    await responder_nat("ℹ️ No hay más pistas pendientes en la cola de hoy.")
            # Desbloquear micrófonos / Abrir sala
            elif any(p in texto_raw for p in ["abrir microfonos", "abrir micrófonos", "desmutear a todos", "desbloquear microfonos", "desbloquear micrófonos", "abrir la sala", "liberar microfonos", "liberar micrófonos"]):
                reproduciendo_meditacion = False
                segundos_inactividad_mic.clear()
                avisados_auto_mute.clear()
                if tgcalls:
                    try:
                        await tgcalls.leave_call(destino)
                    except Exception:
                        pass
                await desbloquear_todos_los_participantes()
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
                except Exception:
                    pass
                await responder_nat("🔓 Micrófonos desbloqueados para todos los participantes. Modo meditación desactivado.")
                avisar_con_bot("🔓 **Micrófonos abiertos:** El candado de silencio ha sido retirado para todos los asistentes.", es_efimero=False)
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
                    await actualizar_mensaje_turnos(forzar_al_fondo=True)
                    await responder_nat(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Tu micrófono está listo.")
                    avisar_con_bot(f"🎙️ **Turno de palabra:** ¡Adelante **{s_nom}**! Por favor abre tu micrófono para compartir.", es_efimero=True)
                    if not reproduciendo_meditacion:
                        lanzar_tarea(anunciar_turno_por_voz(s_nom))
            # Apagar / ocultar el cartel de LISTA DE TURNOS EN VIVO
            elif any(p in texto_raw for p in [
                "apagar lista de turnos", "apaga la lista de turnos", "apagar turnos", "apaga los turnos",
                "ocultar lista de turnos", "oculta la lista de turnos", "ocultar turnos", "oculta los turnos",
                "desactivar lista de turnos", "desactiva la lista de turnos", "desactivar turnos", "quitar lista de turnos",
                "quita la lista de turnos", "borrar lista de turnos"
            ]):
                _, msg_est = await cambiar_estado_lista_turnos(False)
                await responder_nat(msg_est)
            # Activar / mostrar el cartel de LISTA DE TURNOS EN VIVO
            elif any(p in texto_raw for p in [
                "activar lista de turnos", "activa la lista de turnos", "activar turnos", "activa los turnos",
                "mostrar lista de turnos", "muestra la lista de turnos", "mostrar turnos", "muestra los turnos",
                "encender lista de turnos", "enciende la lista de turnos", "encender turnos", "poner lista de turnos"
            ]):
                _, msg_est = await cambiar_estado_lista_turnos(True)
                await responder_nat(msg_est)
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

                # Oración: Sala libre sin restricciones técnicas (respeto voluntario del silencio sagrado)
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
                    print("🕊️ Oración: Micrófonos libres y sin candados técnicos en la sala.")
                except Exception:
                    pass

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

                try:
                    await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                    if cola_reproduccion:
                        ruta_meditacion = cola_reproduccion[0]["ruta"]
                        info_catalogo_hoy = cola_reproduccion[0].get("info")
                except Exception as e_sync_28:
                    print("Nota sincronizando cola a las 8:28 PM:", e_sync_28)

                extra_med_txt = ""
                if info_catalogo_hoy:
                    extra_med_txt = f": {info_catalogo_hoy['tipo']} #{info_catalogo_hoy['numero']} - «{info_catalogo_hoy['titulo']}» ({info_catalogo_hoy['maestro']})"

                texto_oracion = (
                    "🕊️ **MOMENTO DE ORACIÓN EN SILENCIO (3 MINUTOS)** 🕊️\n"
                    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                    "Entramos en nuestro espacio de oración y recogimiento comunitario.\n\n"
                    "🤫 **POR FAVOR GUARDEN SILENCIO:**\n"
                    "Durante estos 3 minutos mantengan sus micrófonos apagados para honrar la concentración y paz de todos.\n\n"
                    "⏰ **Cronograma del momento:**\n"
                    "• **8:28 PM – 8:31 PM:** Oración y recogimiento en silencio (3 min).\n"
                    f"• **8:32 PM:** Inicio de la Meditación diaria{extra_med_txt}."
                )
                avisar_con_bot(texto_oracion, reply_markup=keyboard_oracion, es_efimero=True)

                # Emitir en vivo el anuncio de voz de Toby y el pitido inicial de oración en la sala de voz
                async def emitir_secuencia_oracion():
                    try:
                        print("🕊️ Emitiendo locución de Toby para la oración comunitaria (8:28 PM)...")
                        await emitir_anuncio_tts("¡ATENCIÓN! A continuación empieza el momento de oración y recogimiento en silencio por 3 minutos. GRACIAS.")
                        await asyncio.sleep(0.8)
                    except Exception as e_an:
                        print("Nota emitiendo anuncio de oración:", e_an)
                    pitido_ini = obtener_pitido_inicial_oracion()
                    if pitido_ini:
                        print("🔔 Emitiendo campana inicial de oración...")
                        await reproducir_audio_efimero(pitido_ini)

                lanzar_tarea(emitir_secuencia_oracion())

            # 8:31 PM: Conclusión de los 3 minutos de oración y alerta 1 minuto antes de la meditación
            if hora_col == 20 and min_col == 31 and not aviso_meditacion_enviado:
                aviso_meditacion_enviado = True
                if aviso_oracion_enviado and not aviso_espera_enviado:
                    aviso_espera_enviado = True
                    oracion_activa_hoy = False

                    # Emitir en vivo el pitido final de oración concluyendo los 3 min
                    pitido_fin = obtener_pitido_final_oracion()
                    if pitido_fin:
                        await reproducir_audio_efimero(pitido_fin)

                    await desbloquear_todos_los_participantes()
                    prefijo = "✨ **Oración en silencio concluida.**\n\n"
                else:
                    prefijo = ""

                if not cola_reproduccion and (not ruta_meditacion or not os.path.exists(ruta_meditacion)):
                    try:
                        ruta_meditacion, info_catalogo_hoy, cola_reproduccion = await buscar_audio_meditacion(client, entidad, admin_ids)
                    except Exception as e:
                        print("Nota re-buscando audio a las 8:31 PM:", e)
                else:
                    try:
                        await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                        if cola_reproduccion:
                            ruta_meditacion = cola_reproduccion[0]["ruta"]
                            info_catalogo_hoy = cola_reproduccion[0].get("info")
                    except Exception as e_sync_31:
                        print("Nota sincronizando cola a las 8:31 PM:", e_sync_31)

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
                            f"👤 **Maestro:** {info_catalogo_hoy['maestro']}\n"
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
                else:
                    try:
                        await sincronizar_cola_con_render_y_grupo(client, entidad, cola_reproduccion)
                        if cola_reproduccion:
                            ruta_meditacion = cola_reproduccion[0]["ruta"]
                            info_catalogo_hoy = cola_reproduccion[0].get("info")
                    except Exception as e_sync_32:
                        print("Nota sincronizando cola a las 8:32 PM:", e_sync_32)
                if cola_reproduccion or (ruta_meditacion and os.path.exists(ruta_meditacion)):
                    reproduccion_iniciada = True
                    await reproducir_meditacion(0)

            # Verificación constante de audios con hora específica programada (ej. /encolar 15 a las 9:15pm)
            if not reproduciendo_meditacion and cola_reproduccion:
                hora_actual_str = f"{hora_col:02d}:{min_col:02d}"
                for idx_p, item_p in enumerate(cola_reproduccion):
                    h_prog = item_p.get("hora_programada")
                    if h_prog and h_prog == hora_actual_str:
                        print(f"⏰ Disparando audio programado para las {h_prog} (pista #{idx_p + 1})")
                        reproduccion_iniciada = True
                        await reproducir_meditacion(idx_p)
                        break

            try:
                call_info = await client(GetGroupCallRequest(call=input_call, limit=100))
            except RPCError as e:
                print("Llamada finalizada por un administrador o cerrada externamente:", type(e).__name__, e)
                cerrado_por_admin = True
                motivo_cierre = "admin"
                break
            except Exception as e:
                print("Error de conexión al consultar llamada:", e)
                recuperado = False
                for intento in range(5):
                    await asyncio.sleep(3)
                    try:
                        if not client.is_connected():
                            await client.connect()
                        call_info = await client(GetGroupCallRequest(call=input_call, limit=100))
                        recuperado = True
                        break
                    except Exception as e_rec:
                        print(f"Reintentando reconexión con Telegram ({intento + 1}/5):", e_rec)
                if not recuperado:
                    print("No se pudo restablecer la conexión con Telegram.")
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
                    print("⚠️ Detección de caída masiva o parpadeo general en la sala de Telegram.")

                participantes_conectados = uids_en_servidor

            # Mantener input_call permanentemente fresco en la caché de PyTgCalls
            if tgcalls and hasattr(tgcalls, "_app") and hasattr(tgcalls._app, "_bind_client") and hasattr(tgcalls._app._bind_client, "_cache"):
                try:
                    tgcalls._app._bind_client._cache.set_cache(destino, input_call)
                    if isinstance(destino, int):
                        tgcalls._app._bind_client._cache.set_cache(abs(destino), input_call)
                except Exception:
                    pass

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
                        print(f"⏳ la mano en Telegram y fue añadido a la lista de turnos.")
                        hubo_cambio_turnos = True

                # Moderación de micrófonos en vivo: clasificación de administradores por MÚLTIPLES señales
                es_adm = es_participante_admin(uid, nombre, p.peer)
                if not es_adm and uid not in checked_admins_cache:
                    checked_admins_cache.add(uid)
                    try:
                        perm = await client.get_permissions(entidad, uid)
                        if getattr(perm, 'is_admin', False) or getattr(perm, 'is_creator', False) or getattr(perm, 'manage_call', False):
                            admin_ids.add(uid)
                            es_adm = True
                            print(f"👑 Administrador detectado por permisos de Telegram: {nombre} ({uid}).")
                    except Exception:
                        checked_admins_cache.discard(uid)

                if uid == me.id and reproduciendo_meditacion and p_muted:
                    # Si es la cuenta del bot reproduciendo meditación y Telegram lo silencia, restaurarlo
                    try:
                        from telethon.tl.types import InputPeerSelf
                        await client(EditGroupCallParticipantRequest(call=input_call, participant=InputPeerSelf(), muted=False))
                        if tgcalls:
                            await tgcalls.unmute(destino)
                    except Exception:
                        pass

                # Registro de oradores activos para lista de turnos y métricas de participación
                if not p_muted:
                    if uid not in oradores_activos:
                        oradores_activos.add(uid)
                        hubo_cambio_turnos = True
                else:
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
                    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
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
                    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                    f"📅 Fecha: {fecha_hoy} | ⏰ Fin: {datetime.now(tz_col).strftime('%I:%M %p')}\n"
                    "✨ Gracias a todos por su participación en la sesión diaria.\n"
                    "📊 Los reportes y actas oficiales se publican a continuación."
                )
                await client.edit_message(entidad, msg_fijado, texto_concluido)
            except Exception:
                pass
            if hasattr(msg_fijado, "id"):
                ids_mensajes_efimeros.discard(msg_fijado.id)

        if msg_turnos:
            try:
                await client.edit_message(
                    entidad,
                    msg_turnos,
                    "🎙️ **LISTA DE TURNOS CERRADA**\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\nLa sala de voz ha concluido por el día de hoy."
                )
            except Exception:
                pass
            if hasattr(msg_turnos, "id"):
                ids_mensajes_efimeros.discard(msg_turnos.id)

        # 3. Finalización y Consolidación de Asistencia
        fin_llamada = datetime.now(tz_col)
        duracion_reunion_minutos = max(1, int(round((fin_llamada - inicio_llamada).total_seconds() / 60)))

        for uid, part in participantes.items():
            if part["activo_ahora"]:
                delta = (fin_llamada - part["ultimo_check"]).total_seconds()
                part["segundos_acumulados"] += max(0.0, delta)
                part["ultima_salida"] = fin_llamada
                part["activo_ahora"] = False

        # Desconectar reproductor de PyTgCalls, cancelar esperas de cola y cerrar sala
        cancelar_espera_post_meditacion()
        token_reproduccion += 1
        reproduciendo_meditacion = False
        eq_estado["cambiando"] = False
        if tarea_panel_progreso and not tarea_panel_progreso.done():
            tarea_panel_progreso.cancel()
        try:
            await cerrar_pantalla_emision_video()
        except Exception:
            pass
        if tgcalls:
            try:
                await tgcalls.leave_call(destino)
                await asyncio.sleep(2)
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
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
            "🏆 **PODIO DE PUNTUALIDAD (TOP 9):**",
        ]
        simbolos_podio = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
        if podio_puntuales:
            for idx, p in enumerate(podio_puntuales):
                tag = f"(@{p['username']})" if p["username"] else ""
                lineas_pub.append(f"{simbolos_podio[idx]} **{p['nombre']}** {tag} — {p['primera_entrada'].strftime('%I:%M:%S %p')}")
        else:
            lineas_pub.append("No se registraron participantes de la comunidad hoy.")

        lineas_pub.append("\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬")
        lineas_pub.append("🌟 **PUNTOS GANADOS HOY:**")
        puntos_comunidad = [p for p in asistentes_validos if p["id"] not in admin_ids and p.get("pts_hoy", 0) > 0]
        if puntos_comunidad:
            for p in puntos_comunidad:
                tag = f"(@{p['username']})" if p["username"] else ""
                icono_voz = "🎙️" if p["hablo"] else "🎧"
                estrella = "â­ " if p["porcentaje"] >= 80 else "• "
                aviso_medalla = f"\n   🎉 ¡Nueva medalla: {', '.join(p['nuevas_medallas'])}!" if p.get("nuevas_medallas") else ""
                lineas_pub.append(
                    f"{estrella}**{p['nombre']}** {tag} âž” **+{p['pts_hoy']} pts** {icono_voz}\n"
                    f"   [{p['desglose']}] — Racha: 🔥 {p['racha']} días ({p['rango']}){aviso_medalla}"
                )
        else:
            lineas_pub.append("No se registraron asistencias comunitarias que sumaran puntos hoy.")

        if es_fin_de_mes:
            lineas_pub.append("\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬")
            lineas_pub.append("👑 **🏆 CUADRO DE HONOR — CAMPEONES DEL MES 🏆** 👑")
            campeones_mes = sorted([u for u in usuarios_db.values() if int(u.get("id", 0)) not in admin_ids], key=lambda x: x.get("puntos_mes", 0), reverse=True)[:3]
            titulos = ["🥇 CAMPEÓN DEL MES", "🥈 SUBCAMPEÓN", "🥉 TERCER PUESTO"]
            for idx, c in enumerate(campeones_mes):
                lineas_pub.append(f"{titulos[idx]}: **{c['nombre']}** con {c.get('puntos_mes', 0)} pts")
            lineas_pub.append("✨ ¡Felicitaciones a los ganadores de la temporada!")

        lineas_pub.append("\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬")
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
                        txt_diagnostico_red = "\n\n📶 **Estabilidad de señal:** ¡Excelente! Tu conexión se mantuvo 100% fluida y sin interrupciones."
                    elif reconex == 1:
                        txt_calidad_senal = "🟡 **Buena (1 micro-corte breve)**"
                        txt_diagnostico_red = "\n\n💡 **Nota de conexión:** Registraste 1 micro-corte breve. Te sugerimos poner Telegram en _'Sin restricciones'_ en Batería para evitar que la pantalla suspenda la llamada."
                    else:
                        txt_calidad_senal = f"⚠️ **Inestable ({reconex} micro-desconexiones)**"
                        if hubo_caida_masiva_sala:
                            txt_diagnostico_red = (
                                f"\n\n📡 **Estabilidad de llamada:** Detectamos **{reconex} reconexiones** en tu sesión. "
                                "Notamos fluctuaciones generales en los servidores de Telegram hoy, por lo que la interrupción pudo deberse a la plataforma."
                            )
                        else:
                            txt_diagnostico_red = (
                                f"\n\n⚠️ **AUDITORÍA DE TU CONEXIÓN:**\n"
                                f"Registraste **{reconex} salidas de la sala** (mientras el resto de la comunidad se mantuvo estable).\n\n"
                                f"💡 **Consejos prácticos para mejorar tu próxima reunión:**\n"
                                f"1. 🔋 **Batería (Principal causa):** En tu celular ve a _Ajustes > Aplicaciones > Telegram > Batería_ y selecciona **'Sin restricciones'** (evita que el celular cierre la llamada al apagar la pantalla).\n"
                                f"2. 📶 **Señal:** Procura no alternar entre Wi-Fi y datos móviles durante la reunión.\n"
                                f"3. 🔁 **Llamadas Peer-to-peer:** En Telegram ve a _Ajustes > Privacidad y seguridad > Llamadas > Peer-to-peer_ y selecciona **'Nunca'**.\n"
                                f"4. 🧹 **Caché:** En Telegram ve a _Ajustes > Datos y almacenamiento > Uso de almacenamiento > Borrar caché_."
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
                        f"• Permanencia: **{p['minutos']} minutos** ({p['porcentaje']}% de la sesión)\n"
                        f"• Estabilidad de conexión: {txt_calidad_senal}\n"
                        f"• Participación de voz: {txt_uso_mic}\n"
                        f"{txt_meditacion_ind}"
                        f"• Puntos sumados hoy: **+{p['pts_hoy']} pts**\n"
                        f"  _{p['desglose']}_\n"
                        f"• Total acumulado: **{p['pts_mes']} pts este mes** (Histórico: {p['pts_totales']})\n"
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
                            f"📡 **Auditoría de conexión de tu llamada de hoy:**\n"
                            f"• Tiempo en sala: **{p['minutos']} minutos** ({p['porcentaje']}% de la sesión)\n"
                            f"• Desconexiones registradas: **{reconex} salidas de la sala**\n"
                            f"{txt_mic_fugaz}"
                            f"• Tu conexión fue inestable y no alcanzaste los 10 minutos mínimos para sumar puntos hoy.\n\n"
                            f"💡 **Consejos prácticos para mejorar tu próxima reunión:**\n"
                            f"1. 🔋 **Batería (Principal causa):** En tu celular ve a _Ajustes > Aplicaciones > Telegram > Batería_ y selecciona **'Sin restricciones'** (evita que el celular cierre la llamada al apagar la pantalla).\n"
                            f"2. 📶 **Señal:** Procura no alternar entre Wi-Fi y datos móviles durante la llamada.\n"
                            f"3. 🔁 **Llamadas Peer-to-peer:** En Telegram ve a _Ajustes > Privacidad y seguridad > Llamadas > Peer-to-peer_ y selecciona **'Nunca'**.\n"
                            f"4. 🧹 **Caché:** En Telegram ve a _Ajustes > Datos y almacenamiento > Uso de almacenamiento > Borrar caché_.\n\n"
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
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
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
                f"   • Permanencia: {p['minutos']} min ({p['porcentaje']}%) | Caídas: {p['reconexiones']}{caidas_tag}\n"
                f"   • Micrófono: {mic}{med_txt} | Hoy: +{p['pts_hoy']} pts (Mes: {p['pts_mes']} | Histórico: {p['pts_totales']})\n"
                f"   • Medallas: {meds_txt}"
            )

        if visitas_fugaces:
            lineas_priv.append("\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬")
            lineas_priv.append(f"⚠️ **VISITAS FUGACES (<{MIN_MINUTOS_ASISTENCIA} min):**")
            for p in visitas_fugaces:
                tag = f"@{p['username']}" if p['username'] else "Sin alias"
                caidas_f = f" | Caídas: {p['reconexiones']}" if p.get("reconexiones", 0) else ""
                seg_hablo = p.get("segundos_hablando", 0.0)
                voz_f = f" | 🎙️ {round(seg_hablo)}s" if seg_hablo > 0 else ""
                lineas_priv.append(f"⏳ {p['ultima_salida'].strftime('%I:%M:%S %p')})")

        lineas_priv.append(f"\n📎 Se generó el archivo de auditoría: `{ruta_csv}`")
        reporte_privado = "\n".join(lineas_priv)

        # 7. Generar Resumen con IA (Gemini) y Diarización de Oradores
        oradores_sesion = [
            p["nombre"] for p in participantes.values() if p.get("hablo")
        ]

        # Asegurar que PyTgCalls haya cerrado la sesión y ffmpeg haya vaciado sus buffers a disco
        if tgcalls:
            try:
                print("Finalizando grabación y cerrando sesión en PyTgCalls...")
                await tgcalls.leave_call(destino)
                await asyncio.sleep(1.5)
            except Exception as e_tg_stop:
                print("Nota cerrando sesión de PyTgCalls:", e_tg_stop)

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
            resumen_ia = "🛑 *La grabación de audio fue cancelada por la administración durante la sesión. Este informe se generó con base en los datos de participación sin almacenamiento de audio.*\n\n" + resumen_ia

        # Publicar Minuta Oficial en el Grupo
        txt_minuta_grupo = (
            f"📝 **MINUTA Y RESUMEN OFICIAL — LLAMADA {inicio_llamada.strftime('%d/%m/%Y')}**\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
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

        # Registrar reproducción oficial en log histórico y sincronizar estado (usando la Pista #1 oficial antes de vaciar la cola)
        try:
            from schedule_meditaciones import registrar_reproduccion_en_log_y_estado
            info_oficial_log = (cola_reproduccion[0].get("info") if cola_reproduccion and (cola_reproduccion[0].get("info") or {}).get("numero") else None) or info_catalogo_hoy
            if info_oficial_log and info_oficial_log.get("numero"):
                registrar_reproduccion_en_log_y_estado(info_oficial_log, fecha_hoy)
                info_catalogo_hoy = info_oficial_log
        except Exception as e_reg:
            print("Nota registrando reproduccion en log oficial:", e_reg)

        # ── LIMPIEZA TOTAL DE LA COLA AL CERRAR LA SALA ──
        # Borra cualquier audio que haya quedado encolado sin reproducirse para que a las 3:00 AM
        # del día siguiente se encole limpia y sin conflicto la Meditación Diaria oficial.
        try:
            cancelar_espera_post_meditacion()
            cola_reproduccion.clear()
            pistas_completadas.clear()
            for jf_clean in ("cola_hoy.json", "meta_hoy.json", "cola_manana.json"):
                r_jf = os.path.join(CARPETA_MEDITACIONES, jf_clean)
                if os.path.exists(r_jf):
                    try:
                        os.remove(r_jf)
                    except Exception:
                        pass
            if os.path.exists(CARPETA_MEDITACIONES):
                for fn_med in os.listdir(CARPETA_MEDITACIONES):
                    if fn_med.startswith(("meditacion_hoy", "meditacion_extra", "yt_extra_", "meditacion_manana")) or fn_med.endswith(("_gongs.mp3", "_video.mp4")):
                        try:
                            os.remove(os.path.join(CARPETA_MEDITACIONES, fn_med))
                        except Exception:
                            pass
            # Notificar también al servidor de Render para que vacíe su cola_hoy.json y temporales
            try:
                req_clean_r = urllib.request.Request(
                    "https://bot-meditaciones.onrender.com/limpiar_cola",
                    method="POST",
                    headers={"User-Agent": "LlamadaCierreSala"}
                )
                with urllib.request.urlopen(req_clean_r, timeout=8) as r_cl:
                    print(f"🧹 Cola de reproducción limpiada en Render al cerrar sala: HTTP {r_cl.status}")
            except Exception as e_cl_r:
                print(f"Nota limpiando cola en Render al cerrar sala: {e_cl_r}")
            print("🧹 Cola de reproducción local y audios no reproducidos eliminados exitosamente al cerrar la sala.")
        except Exception as e_clean_cola:
            print("Nota en limpieza final de cola:", e_clean_cola)

        try:
            if not client.is_connected():
                await client.connect()
            me = await client.get_me()
        except Exception as e_me_disc:
            print("Nota obteniendo me al finalizar:", e_me_disc)
            me = None
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
                        "🎙️ **Grabación de Audio:**\n"
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

        # Limpiar temporales de grabación cruda (preservando el audio oficial final en ruta_grabacion_completa)
        for s in segmentos_grabados:
            try:
                if s != ruta_grabacion_completa and os.path.exists(s):
                    os.remove(s)
                s_raw = s.rsplit(".", 1)[0] + ".raw"
                if os.path.exists(s_raw):
                    os.remove(s_raw)
            except Exception:
                pass
        for f_tmp in (ruta_grabacion_pre, ruta_grabacion_post):
            try:
                if os.path.exists(f_tmp):
                    os.remove(f_tmp)
                f_raw = f_tmp.rsplit(".", 1)[0] + ".raw"
                if os.path.exists(f_raw):
                    os.remove(f_raw)
            except Exception:
                pass

        if tarea_callbacks_bot and not tarea_callbacks_bot.done():
            tarea_callbacks_bot.cancel()

        # Limpieza de mensajes temporales al finalizar la llamada
        # Por defecto, NO borrar automáticamente avisos informativos ni ventanas de conclusión en 5 segundos.
        # Si se desea limpieza automática al cerrar, configurar AUTO_LIMPIAR_AL_CERRAR=1 con MINUTOS_ESPERA_LIMPIEZA (ej: 15).
        auto_limpiar = os.environ.get("AUTO_LIMPIAR_AL_CERRAR", "0") == "1"
        if auto_limpiar and ids_mensajes_efimeros:
            minutos_espera_limpieza = int(os.environ.get("MINUTOS_ESPERA_LIMPIEZA", "15"))
            segundos_espera_limpieza = max(60, minutos_espera_limpieza * 60)
            print(f"⏳ Sala concluida. Esperando {minutos_espera_limpieza} min para limpiar comandos temporales de la sala...")
            await asyncio.sleep(segundos_espera_limpieza)
            print(f"🧹 Limpiando comandos temporales ({len(ids_mensajes_efimeros)} mensajes)...")
            await limpiar_mensajes_temporales(client, entidad, ids_mensajes_efimeros)
        else:
            print("ℹ️ Limpieza automática al cerrar desactivada: Los avisos, resúmenes y reportes se conservan intactos en el grupo.")


if __name__ == "__main__":
    asyncio.run(main())
