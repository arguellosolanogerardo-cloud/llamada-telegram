import os
import requests
import time

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("GRUPO_CHAT_ID", "-1002235941847")

def enviar_aviso():
    # Mensaje de preparaciA3n idAentico al de bot_comandos.py
    texto = (
        "⏳ **AVISO DE PREPARACIÓN (30 MINUTOS)** ⏳\\n\\n"
        "La sala de lectura se abrirá en exactamente 30 minutos.\\n\\n"
        "**Pasos recomendados:**\\n"
        "1️⃣ Busca un lugar tranquilo.\\n"
        "2️⃣ Prepara tus audífonos.\\n"
        "3️⃣ Verifica que tu micrófono esté apagado antes de entrar.\\n\\n"
        "¡Nos vemos en breve! 🎧✨"
    )
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        print(response.text)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    if BOT_TOKEN:
        enviar_aviso()
    else:
        print("Falta BOT_TOKEN")
