import asyncio
import json
import os
import urllib.request

from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.functions.phone import DiscardGroupCallRequest, GetGroupCallRequest
from telethon.tl.types import Channel, Chat

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_SESSION"]
GRUPO = os.environ["TG_GROUP"]            # @usuario, o id numérico (-100...)
BOT_TOKEN = os.environ.get("BOT_TOKEN")   # opcional
CHAT_ID = os.environ.get("CHAT_ID", GRUPO)  # id del grupo para el bot
MIN_USUARIOS = int(os.environ.get("MIN_USUARIOS", "5"))


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

        # Obtener información completa del chat/canal para hallar la llamada activa
        if isinstance(entidad, Channel):
            full = await client(GetFullChannelRequest(entidad))
            full_chat = full.full_chat
        elif isinstance(entidad, Chat):
            full = await client(GetFullChatRequest(entidad.id))
            full_chat = full.full_chat
        else:
            print(f"Tipo de entidad no compatible: {type(entidad)}")
            return

        if not full_chat.call:
            print("No hay ningún chat de voz o videollamada activa en el grupo.")
            return

        try:
            call_info = await client(GetGroupCallRequest(call=full_chat.call, limit=1))
            participantes = call_info.call.participants_count
            print(f"Llamada activa encontrada. Participantes actuales: {participantes}")

            if participantes < MIN_USUARIOS:
                print(
                    f"Participantes ({participantes}) < {MIN_USUARIOS}. Procediendo a cerrar la sala..."
                )
                await client(DiscardGroupCallRequest(call=full_chat.call))
                print("Llamada cerrada con éxito.")
                avisar_con_bot(
                    f"🔒 La llamada diaria se ha cerrado automáticamente porque hay menos de {MIN_USUARIOS} personas conectadas tras 5 horas. ¡Buenas noches a todos!"
                )
            else:
                print(
                    f"Hay {participantes} personas conectadas (>= {MIN_USUARIOS}). La llamada continúa abierta."
                )

        except RPCError as e:
            print("Error RPC al interactuar con la llamada:", type(e).__name__, e)


if __name__ == "__main__":
    asyncio.run(main())
