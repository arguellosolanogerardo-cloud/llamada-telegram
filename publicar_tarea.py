import os
import sys
import json
import urllib.request
from catalogo_audios import identificar_audio_catalogo, formatear_info_audio, cargar_catalogo

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP")
RUTA_PUNTOS = os.path.join("data", "puntos.json")


def enviar_mensaje(chat_id: int | str, texto: str) -> bool:
    if not BOT_TOKEN:
        print("BOT_TOKEN no configurado.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown",
    }
    datos = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        print(f"Error enviando mensaje a {chat_id}:", e)
        return False


def generar_anuncio_tarea(info: dict) -> str:
    tipo = info.get("tipo", "MEDITACION").title()
    num = info.get("numero", "")
    titulo = info.get("titulo", "")
    maestro = info.get("maestro", "Guía Espiritual")
    fecha = info.get("fecha", "")

    return (
        f"🕊️ **TAREA ESPIRITUAL DEL DÍA — CATÁLOGO OFICIAL** 🕊️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Comunidad, hoy trabajaremos con la siguiente práctica:\n\n"
        f"🧘 **{tipo} #{num}:** «{titulo}»\n"
        f"👤 **Maestro / Guía:** {maestro}\n"
        f"🗓️ **Grabación original:** {fecha}\n\n"
        f"⏰ **Cronograma de esta noche:**\n"
        f"• **7:56 PM:** Apertura de la sala de voz en Telegram.\n"
        f"• **8:24 PM:** Oración y recogimiento en silencio (5 min).\n"
        f"• **8:29 PM:** Pausa de respiración consciente (3 min).\n"
        f"• **8:32 PM:** Reproducción en vivo de la {tipo.lower()}.\n\n"
        f"🎧 *El audio ya fue publicado en el grupo para su estudio previo.*"
    )


def publicar_tarea_dia(parametro: str) -> dict | None:
    """Identifica el audio por número o texto y envía el anuncio oficial al grupo y privados."""
    info = identificar_audio_catalogo(texto=parametro)
    if not info:
        print(f"No se encontró información en el catálogo para: {parametro}")
        return None

    # Guardar metadatos del día
    os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
    ruta_meta = os.path.join("data", "meditaciones", "meta_hoy.json")
    try:
        with open(ruta_meta, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando meta_hoy:", e)

    texto_anuncio = generar_anuncio_tarea(info)

    # 1. Enviar al Grupo Principal
    if CHAT_ID:
        ok_grupo = enviar_mensaje(CHAT_ID, texto_anuncio)
        if ok_grupo:
            print(f"Anuncio de la tarea #{info['numero']} publicado en el grupo {CHAT_ID}.")
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
                    f"🕊️ **TAREA ESPIRITUAL DEL DÍA**\n"
                    f"Hola **{datos.get('nombre', 'Compañero')}**, hoy en la reunión de las 7:56 PM trabajaremos:\n\n"
                    f"🧘 **{info.get('tipo', 'MEDITACION').title()} #{info['numero']}:** «{info['titulo']}»\n"
                    f"👤 **Guía:** {info['maestro']} | 🗓️ **Fecha:** {info['fecha']}\n\n"
                    f"¡Te esperamos puntual esta noche a las 7:56 PM!"
                )
                if enviar_mensaje(uid, texto_priv):
                    enviados_priv += 1
            print(f"Notificación privada enviada a {enviados_priv} miembros.")
        except Exception as e:
            print("Nota enviando a privados:", e)

    return info


if __name__ == "__main__":
    param = sys.argv[1] if len(sys.argv) > 1 else "20"
    publicar_tarea_dia(param)
