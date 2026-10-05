import os
import sys
import json
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from catalogo_audios import identificar_audio_catalogo, formatear_info_audio, cargar_catalogo

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP")
RUTA_PUNTOS = os.path.join("data", "puntos.json")


def obtener_info_bot() -> str:
    if not BOT_TOKEN:
        return ""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        req = urllib.request.Request(url, headers={"User-Agent": "PublicarTareaBot"})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode())
            if res.get("ok"):
                return res["result"].get("username", "")
    except Exception:
        pass
    return ""


def enviar_mensaje(chat_id: int | str, texto: str, reply_markup: dict = None) -> bool:
    if not BOT_TOKEN:
        print("BOT_TOKEN no configurado.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    datos = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        print(f"Error enviando mensaje a {chat_id}:", e)
        return False


def generar_anuncio_tarea(info: dict, fecha_str: str = None) -> str:
    if not fecha_str:
        tz_col = ZoneInfo("America/Bogota")
        fecha_str = datetime.now(tz_col).strftime("%d/%m/%Y")

    tipo_raw = str(info.get("tipo", "")).upper()
    tipo = "Meditación" if "MEDITACI" in tipo_raw else "Mensaje"
    num = info.get("numero", "")
    titulo = info.get("titulo", "")
    maestro = info.get("maestro", "Guía Espiritual")
    fecha_orig = info.get("fecha", "")

    return (
        f"🕊️ **TAREA DEL DÍA {fecha_str}—**🕊️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Comunidad, hoy {fecha_str} trabajaremos con la siguiente práctica:\n\n"
        f"🧘 **{tipo} #{num}:** «{titulo}»\n"
        f"👤 **Maestro / Guía:** {maestro}\n"
        f"🗓️ **Grabación original:** {fecha_orig}\n\n"
        f"⏰ **Cronograma de esta noche {fecha_str} :**\n"
        f"• **7:56 PM:** Apertura de la sala de voz en Telegram.\n"
        f"• **8:24 PM:** Oración y recogimiento en silencio (5 min).\n"
        f"• **8:29 PM:** Pausa de respiración consciente (3 min).\n"
        f"• **8:32 PM:** Reproducción en vivo de la {tipo.lower()}.\n\n"
        f"🎧 *El audio ya fue publicado en el grupo para su estudio previo.*"
    )


def armar_teclado_audio(chat_id: int | str, msg_id_audio: int | str = None, bot_user: str = "") -> dict:
    clean_id = str(chat_id).replace("-100", "")
    url_audio = None
    if msg_id_audio:
        url_audio = f"https://t.me/c/{clean_id}/{msg_id_audio}"
    elif str(chat_id).startswith("-100"):
        url_audio = f"https://t.me/c/{clean_id}"
    elif str(chat_id).startswith("@"):
        url_audio = f"https://t.me/{str(chat_id).lstrip('@')}"

    botones = []
    if url_audio:
        botones.append([{"text": "🎧 ESCUCHAR / VER AUDIO EN EL GRUPO 👆", "url": url_audio}])
    if bot_user:
        botones.append([{"text": "📥 RECIBIR AUDIO EN MI TELEGRAM PRIVADO 🎧", "url": f"https://t.me/{bot_user}?start=audio"}])
    elif not url_audio:
        botones.append([{"text": "🎧 ESCUCHAR AUDIO EN EL GRUPO 🎧", "url": "https://t.me"}])

    return {"inline_keyboard": botones}


def publicar_tarea_dia(parametro: str, msg_id_audio: int | str = None) -> dict | None:
    """Identifica el audio por número o texto y envía el anuncio oficial al grupo y privados."""
    info = identificar_audio_catalogo(texto=parametro)
    if not info:
        print(f"No se encontró información en el catálogo para: {parametro}")
        return None

    tz_col = ZoneInfo("America/Bogota")
    fecha_hoy_str = datetime.now(tz_col).strftime("%d/%m/%Y")

    # Guardar metadatos del día
    os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
    ruta_meta = os.path.join("data", "meditaciones", "meta_hoy.json")
    try:
        with open(ruta_meta, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando meta_hoy:", e)

    texto_anuncio = generar_anuncio_tarea(info, fecha_hoy_str)
    bot_username = obtener_info_bot()
    teclado = armar_teclado_audio(CHAT_ID, msg_id_audio, bot_username) if CHAT_ID else None

    # 1. Enviar al Grupo Principal con botón interactivo al audio
    if CHAT_ID:
        ok_grupo = enviar_mensaje(CHAT_ID, texto_anuncio, reply_markup=teclado)
        if ok_grupo:
            print(f"Anuncio de la tarea #{info['numero']} publicado en el grupo {CHAT_ID} con botón de audio.")
        else:
            print(f"No se pudo publicar en el grupo {CHAT_ID}.")
    else:
        print("Variable CHAT_ID o TG_GROUP no configurada.")

    # 2. Enviar por separado a cada miembro registrado
    if os.path.exists(RUTA_PUNTOS):
        try:
            with open(RUTA_PUNTOS, "r", encoding="utf-8") as f:
                db_puntos = json.load(f)
            usuarios = db_puntos.get("usuarios", {})
            enviados_priv = 0
            for uid, datos in usuarios.items():
                if str(uid) == str(CHAT_ID):
                    continue
                texto_priv = (
                    f"🕊️ **TAREA DEL DÍA {fecha_hoy_str}** 🕊️\n"
                    f"Hola **{datos.get('nombre', 'Compañero')}**, hoy trabajaremos con:\n\n"
                    f"🧘 **{info.get('tipo', 'MEDITACION').title()} #{info['numero']}:** «{info['titulo']}»\n"
                    f"👤 **Guía:** {info['maestro']} | 🗓️ **Grabación:** {info['fecha']}\n\n"
                    f"⏰ Te esperamos puntual a las 7:56 PM para la apertura de la sala."
                )
                teclado_priv = armar_teclado_audio(CHAT_ID, msg_id_audio, bot_username)
                if enviar_mensaje(uid, texto_priv, reply_markup=teclado_priv):
                    enviados_priv += 1
            print(f"Notificación privada enviada a {enviados_priv} miembros con botón al audio.")
        except Exception as e:
            print("Nota enviando a privados:", e)

    return info


if __name__ == "__main__":
    param = sys.argv[1] if len(sys.argv) > 1 else "20"
    msg_id = sys.argv[2] if len(sys.argv) > 2 else None
    publicar_tarea_dia(param, msg_id)
