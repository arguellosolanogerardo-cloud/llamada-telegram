"""Ejecuta esto UNA vez en tu PC para obtener la cadena de sesión (TG_SESSION).
Requisitos: pip install telethon
"""
from telethon import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("api_id: "))
api_hash = input("api_hash: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    # Pedirá tu teléfono (con +57...) y el código que te llega a Telegram
    print("\nTU TG_SESSION (guárdala como secreto, NO la compartas):\n")
    print(client.session.save())
