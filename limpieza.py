import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import re
import unicodedata
import urllib.request

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.sessions import StringSession
from telethon.tl.types import (
    Channel,
    ChannelParticipantsAdmins,
    Chat,
    DocumentAttributeAnimated,
)

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_SESSION"]
GRUPO = os.environ["TG_GROUP"]
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", GRUPO)

# Días hacia atrás a revisar: 0 = todo el historial del grupo
DIAS_HISTORIAL = int(os.environ.get("DIAS_HISTORIAL", "0"))

# Regex para extraer ID de videos de YouTube (estándar, shorts, lives, youtu.be)
YT_REGEX = re.compile(
    r"(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|shorts\/|live\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})",
    re.IGNORECASE,
)

# Saludos y frases vacías típicas
SALUDOS = {
    "hola",
    "hola a todos",
    "hola grupo",
    "buenos dias",
    "buen dia",
    "buen dia a todos",
    "buenas tardes",
    "buenas noches",
    "buenas",
    "saludos",
    "saludos a todos",
    "saludos grupo",
    "bendiciones",
    "bendiciones a todos",
    "feliz dia",
    "feliz noche",
    "bienvenidos",
}


def normalizar_texto(texto: str) -> str:
    """Remueve tildes, signos de puntuación y emojis para evaluar saludos."""
    if not texto:
        return ""
    limpio = unicodedata.normalize("NFKD", texto).encode("ASCII", "ignore").decode("utf-8")
    return re.sub(r"[^a-z0-9\s]", "", limpio.lower()).strip()


def es_gif(mensaje) -> bool:
    """Detecta si el mensaje es un GIF o animación."""
    if getattr(mensaje, "gif", False):
        return True
    if mensaje.document:
        if any(isinstance(attr, DocumentAttributeAnimated) for attr in mensaje.document.attributes):
            return True
        if mensaje.document.mime_type in ("image/gif", "video/mp4") and any(
            isinstance(attr, DocumentAttributeAnimated) for attr in mensaje.document.attributes
        ):
            return True
    return False


def avisar_con_bot(texto: str) -> None:
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    datos = json.dumps({"chat_id": CHAT_ID, "text": texto}).encode()
    req = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("Aviso del bot enviado:", r.status)
    except Exception as e:
        print("Error al enviar aviso con el bot:", e)


async def main() -> None:
    async with TelegramClient(StringSession(SESSION), API_ID, API_HASH) as client:
        await client.get_dialogs()
        try:
            destino = int(GRUPO)
        except ValueError:
            destino = GRUPO

        entidad = await client.get_entity(destino)

        # 1. Obtener IDs de administradores para nunca borrar sus mensajes
        admin_ids = set()
        try:
            if isinstance(entidad, (Channel, Chat)):
                async for admin in client.iter_participants(
                    entidad, filter=ChannelParticipantsAdmins
                ):
                    admin_ids.add(admin.id)
                print(f"Administradores detectados y protegidos: {len(admin_ids)}")
        except Exception as e:
            print("Aviso: No se pudo obtener lista completa de administradores:", e)

        # 2. Configurar rango de fechas si no es escaneo total
        fecha_limite = None
        if DIAS_HISTORIAL > 0:
            fecha_limite = datetime.now(timezone.utc) - timedelta(days=DIAS_HISTORIAL)
            print(f"Modo ventana temporal: Revisando últimos {DIAS_HISTORIAL} días (desde {fecha_limite.strftime('%Y-%m-%d %H:%M UTC')})...")
        else:
            print("Modo escaneo total: Revisando la totalidad del historial del grupo...")

        youtube_vistos = set()
        ids_a_borrar = []
        conteo_youtube_duplicados = 0
        conteo_saludos = 0
        conteo_stickers_gifs = 0
        total_revisados = 0

        # Iterar en orden cronológico (reverse=True) para que el primer video visto sea el original
        async for msg in client.iter_messages(entidad, reverse=True):
            if not msg or msg.id is None:
                continue

            # Si hay límite de días y el mensaje es anterior, continuar hasta llegar a la fecha
            if fecha_limite and msg.date < fecha_limite:
                continue

            total_revisados += 1

            # Proteger mensajes fijados (pinned) y de administradores
            if getattr(msg, "pinned", False):
                continue
            if msg.sender_id and msg.sender_id in admin_ids:
                continue

            texto = msg.raw_text or ""
            debe_borrar = False
            motivo = ""

            # Regla A: Stickers y GIFs
            if msg.sticker or es_gif(msg):
                debe_borrar = True
                conteo_stickers_gifs += 1
                motivo = "Sticker/GIF"

            # Regla B: Saludos vacíos
            elif texto:
                texto_normalizado = normalizar_texto(texto)
                if texto_normalizado in SALUDOS:
                    debe_borrar = True
                    conteo_saludos += 1
                    motivo = "Saludo"

            # Regla C: Videos repetidos de YouTube
            if not debe_borrar and texto:
                coincidencias_yt = YT_REGEX.findall(texto)
                if coincidencias_yt:
                    for yt_id in coincidencias_yt:
                        if yt_id in youtube_vistos:
                            debe_borrar = True
                            conteo_youtube_duplicados += 1
                            motivo = f"YouTube duplicado ({yt_id})"
                            break
                        else:
                            youtube_vistos.add(yt_id)

            if debe_borrar:
                ids_a_borrar.append(msg.id)

        print(f"Mensajes totales analizados: {total_revisados}")
        print(f"Mensajes marcados para borrar: {len(ids_a_borrar)}")
        print(f" - YouTube repetidos: {conteo_youtube_duplicados}")
        print(f" - Saludos: {conteo_saludos}")
        print(f" - Stickers / GIFs: {conteo_stickers_gifs}")

        # 3. Eliminar los mensajes en lotes de 100
        if not ids_a_borrar:
            print("No se encontraron mensajes para eliminar. El grupo está limpio.")
            return

        print(f"Iniciando borrado en lotes de {len(ids_a_borrar)} mensajes...")
        lote_tamano = 100
        total_borrados = 0

        for i in range(0, len(ids_a_borrar), lote_tamano):
            lote = ids_a_borrar[i : i + lote_tamano]
            try:
                await client.delete_messages(entidad, lote)
                total_borrados += len(lote)
                await asyncio.sleep(1.2)  # Pausa de seguridad para evitar FloodWait
            except FloodWaitError as e:
                print(f"Telegram FloodWait: esperando {e.seconds} segundos...")
                await asyncio.sleep(e.seconds + 1)
                await client.delete_messages(entidad, lote)
                total_borrados += len(lote)
            except RPCError as e:
                print(f"Error al borrar lote: {type(e).__name__} - {e}")

        print(f"Limpieza completada con éxito. Total eliminados: {total_borrados}")

        resumen = (
            f"🧹 **Mantenimiento del Grupo completado:**\n"
            f"• Mensajes eliminados: {total_borrados}\n"
            f"• Videos repetidos borrados: {conteo_youtube_duplicados}\n"
            f"• Saludos acumulados: {conteo_saludos}\n"
            f"• Stickers y GIFs: {conteo_stickers_gifs}\n"
            f"✨ El historial del grupo ha quedado descongestionado."
        )
        avisar_con_bot(resumen)


if __name__ == "__main__":
    asyncio.run(main())
