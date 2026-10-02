import asyncio
from datetime import datetime
import json
import os
import random
import urllib.request
from zoneinfo import ZoneInfo

from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.sessions import StringSession
from telethon.tl.functions.phone import CreateGroupCallRequest

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_SESSION"]
GRUPO = os.environ["TG_GROUP"]            # @usuario, o id numérico (-100...)
BOT_TOKEN = os.environ.get("BOT_TOKEN")   # opcional
CHAT_ID = os.environ.get("CHAT_ID", GRUPO)  # id del grupo para el bot
TITULO = os.environ.get("CALL_TITLE", "Llamada diaria")
AVISO = os.environ.get(
    "AVISO",
    "📞 ¡Empieza la llamada diaria! Entra al chat de voz del grupo.",
)


def hora_california() -> str:
    bogota = ZoneInfo("America/Bogota")
    california = ZoneInfo("America/Los_Angeles")
    hoy = datetime.now(bogota).replace(hour=19, minute=56, second=0, microsecond=0)
    return hoy.astimezone(california).strftime("%I:%M %p").lstrip("0").lower()


def avisar_con_bot(texto: str) -> None:
    if not BOT_TOKEN:
        return
    texto = texto.replace("{CA}", hora_california())
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    datos = json.dumps({"chat_id": CHAT_ID, "text": texto}).encode()
    req = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print("Aviso del bot enviado:", r.status)


async def main() -> None:
    async with TelegramClient(StringSession(SESSION), API_ID, API_HASH) as client:
        await client.get_dialogs()  # carga los chats para poder resolver el grupo
        try:
            destino = int(GRUPO)
        except ValueError:
            destino = GRUPO
        entidad = await client.get_entity(destino)

        try:
            await client(
                CreateGroupCallRequest(
                    peer=entidad,
                    random_id=random.randint(1, 2**31 - 1),
                    title=TITULO,
                )
            )
            print("Chat de voz creado.")
        except RPCError as e:
            # Por ejemplo, si ya hay un chat de voz activo
            print("No se pudo crear el chat de voz:", type(e).__name__, e)

    avisar_con_bot(AVISO)


asyncio.run(main())
