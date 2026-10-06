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
    ChannelParticipantCreator,
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


async def avisar_al_dueno(client, owner_id: int, texto: str) -> None:
    """Envía el resumen en privado al dueño (a sus mensajes privados/guardados) y mediante el bot."""
    if not owner_id:
        return

    # 1. Enviar directamente a través de Telegram al dueño o a 'Mensajes Guardados'
    try:
        await client.send_message(owner_id, texto)
        print("Resumen enviado al dueño por privado/guardados en Telegram.")
    except Exception as e:
        print("No se pudo enviar mensaje directo por sesión:", e)

    # 2. Intentar también por el bot si el dueño tiene chat iniciado con él
    if BOT_TOKEN:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            datos = json.dumps({"chat_id": owner_id, "text": texto}).encode()
            req = urllib.request.Request(
                url, data=datos, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                print("Resumen enviado al dueño mediante el bot:", r.status)
        except Exception:
            pass  # Es normal si el dueño aún no ha iniciado conversación privada con el bot


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
        me = await client.get_me()
        owner_id = me.id if me else None
        if me:
            admin_ids.add(me.id)
        if hasattr(entidad, "id"):
            admin_ids.add(entidad.id)

        try:
            if isinstance(entidad, (Channel, Chat)):
                async for admin in client.iter_participants(
                    entidad, filter=ChannelParticipantsAdmins
                ):
                    admin_ids.add(admin.id)
                    if isinstance(getattr(admin, "participant", None), ChannelParticipantCreator):
                        owner_id = admin.id
                print(f"Administradores detectados y protegidos: {len(admin_ids)}. Dueño ID: {owner_id}")
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
        conteo_ventanas_bot = 0
        total_revisados = 0

        # Iterar en orden cronológico (reverse=True) para que el primer video visto sea el original
        async for msg in client.iter_messages(entidad, reverse=True):
            if not msg or msg.id is None:
                continue

            # Si hay límite de días y el mensaje es anterior, continuar hasta llegar a la fecha
            if fecha_limite and msg.date < fecha_limite:
                continue

            total_revisados += 1

            # Proteger mensajes fijados (pinned) y mensajes de servicio
            if getattr(msg, "pinned", False) or getattr(msg, "action", None):
                continue

            bot_id = int(BOT_TOKEN.split(":")[0]) if (BOT_TOKEN and ":" in BOT_TOKEN) else None
            es_ventana_bot = False
            # Detectar ventanas del robot (mensajes con botones interactivos o enviados por el bot)
            if getattr(msg, "reply_markup", None) is not None:
                es_ventana_bot = True
            elif bot_id and (msg.sender_id == bot_id or getattr(msg, "via_bot_id", None) == bot_id):
                es_ventana_bot = True

            if not es_ventana_bot:
                if getattr(msg, "out", False):
                    continue
                if msg.sender_id and msg.sender_id in admin_ids:
                    continue

            texto = msg.raw_text or ""
            debe_borrar = False
            motivo = ""

            # Regla 0: Ventanas y notificaciones del bot
            if es_ventana_bot:
                debe_borrar = True
                conteo_ventanas_bot += 1
                motivo = "Ventana/Notificación del Bot"

            # Regla A: Stickers y GIFs
            elif msg.sticker or es_gif(msg):
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
        print(f" - Ventanas/Notificaciones del Bot: {conteo_ventanas_bot}")
        print(f" - YouTube repetidos: {conteo_youtube_duplicados}")
        print(f" - Saludos: {conteo_saludos}")
        print(f" - Stickers / GIFs: {conteo_stickers_gifs}")

        # 3. Eliminar los mensajes en lotes de 100
        if not ids_a_borrar:
            print("No se encontraron mensajes para eliminar. El grupo está limpio.")
            if owner_id:
                await avisar_al_dueno(
                    client,
                    owner_id,
                    f"🧹 **Reporte de Limpieza (Solo para el Dueño):**\n"
                    f"El grupo fue analizado ({total_revisados} mensajes) y ya se encuentra completamente limpio. No hubo nada que borrar."
                )
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
            f"🧹 **Reporte Privado de Limpieza (Solo para el Dueño):**\n"
            f"• Mensajes eliminados: {total_borrados}\n"
            f"• Ventanas/Avisos del bot borrados: {conteo_ventanas_bot}\n"
            f"• Videos de YouTube repetidos borrados: {conteo_youtube_duplicados}\n"
            f"• Saludos acumulados borrados: {conteo_saludos}\n"
            f"• Stickers y GIFs eliminados: {conteo_stickers_gifs}\n"
            f"• Total mensajes analizados: {total_revisados}\n"
            f"✨ El grupo se mantiene limpio y no recibió ningún aviso público."
        )
        if owner_id:
            await avisar_al_dueno(client, owner_id, resumen)


if __name__ == "__main__":
    asyncio.run(main())
