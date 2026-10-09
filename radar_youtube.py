import os
import json
import time
import urllib.request
import re
import html
import threading
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


CANALES_RADAR = [
    {
        "id": "UCms8TOzGiu0Ozj-QmpwstQw",
        "nombre": "ALANISO 2012",
        "handle": "@ALANISO-2012",
        "url": "https://www.youtube.com/@ALANISO-2012/videos"
    },
    {
        "id": "UCjEjDB1gZMGh0QegLjN1o7w",
        "nombre": "Maestro Mario Carrillo",
        "handle": "@mariocarrillo7919",
        "url": "https://www.youtube.com/@mariocarrillo7919/videos"
    }
]

RADAR_DB_PATH = os.path.join("data", "radar_vistos.json")


def cargar_vistos() -> list:
    if os.path.exists(RADAR_DB_PATH):
        try:
            with open(RADAR_DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(x) for x in data]
        except Exception as e:
            print("Nota leyendo radar_vistos:", e)
    return []


def guardar_vistos(vistos: list) -> None:
    try:
        os.makedirs(os.path.dirname(RADAR_DB_PATH), exist_ok=True)
        unicos = []
        for x in vistos:
            if x not in unicos:
                unicos.append(x)
        with open(RADAR_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(unicos[-100:], f, indent=2)
    except Exception as e:
        print("Nota guardando radar_vistos:", e)


def extraer_entradas_xml(xml_texto: str) -> list:
    entradas = []
    for entry in re.findall(r'<entry>(.*?)</entry>', xml_texto, re.DOTALL):
        vid_m = re.search(r'<yt:videoId>(.*?)</yt:videoId>', entry)
        title_m = re.search(r'<title>(.*?)</title>', entry)
        link_m = re.search(r'<link rel="alternate" href="(.*?)"/>', entry)
        pub_m = re.search(r'<published>(.*?)</published>', entry)
        if vid_m and title_m:
            vid = vid_m.group(1).strip()
            link = link_m.group(1).strip() if link_m else f"https://www.youtube.com/watch?v={vid}"
            pub_str = pub_m.group(1).strip() if pub_m else ""
            dt_pub = None
            if pub_str:
                try:
                    dt_pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    pass
            entradas.append({
                "video_id": vid,
                "titulo": html.unescape(title_m.group(1).strip()),
                "link": link,
                "published_str": pub_str,
                "published_dt": dt_pub
            })
    return entradas


def chequear_canales(bot_enviar_mensaje_func, chat_id_grupo) -> int:
    """Revisa los feeds RSS de YouTube y anuncia nuevos videos. Retorna cantidad de videos anunciados."""
    vistos = cargar_vistos()
    es_primera_vez = len(vistos) == 0
    nuevos_vistos = list(vistos)
    ahora_utc = datetime.now(timezone.utc)
    target_chat = chat_id_grupo or os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP") or -1002963691819
    anunciados = 0

    for canal in CANALES_RADAR:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={canal['id']}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=12) as resp:
                xml_texto = resp.read().decode('utf-8', errors='ignore')

            entradas = extraer_entradas_xml(xml_texto)
            for datos in entradas:
                vid = datos["video_id"]
                dt_pub = datos["published_dt"]

                if vid in vistos or vid in nuevos_vistos:
                    continue

                segundos_antiguedad = (ahora_utc - dt_pub).total_seconds() if dt_pub else 999999
                es_reciente = segundos_antiguedad < 86400  # publicado en las últimas 24h

                # En primera ejecución: no spamear videos de hace más de 24 horas
                if es_primera_vez and not es_reciente:
                    nuevos_vistos.append(vid)
                    continue

                # Marcar como visto
                nuevos_vistos.append(vid)

                # Formatear fecha para Colombia
                fecha_txt = ""
                if dt_pub:
                    try:
                        dt_col = dt_pub.astimezone(ZoneInfo("America/Bogota"))
                        fecha_txt = dt_col.strftime("%d/%m/%Y a las %I:%M %p")
                    except Exception:
                        fecha_txt = dt_pub.strftime("%d/%m/%Y")
                else:
                    fecha_txt = "Hace unos momentos"

                texto_anuncio = (
                    f"🔔 **¡NUEVO VIDEO PUBLICADO EN YOUTUBE!** 🐼\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📺 **Canal:** {canal['nombre']}\n"
                    f"✨ **Título:** «{datos['titulo']}»\n"
                    f"🗓️ **Publicado:** {fecha_txt}\n\n"
                    f"🔗 **Ver en YouTube:**\n{datos['link']}"
                )

                teclado = {
                    "inline_keyboard": [
                        [{"text": "🎧 Obtener Audio MP3", "callback_data": f"ytmp3_{vid}"}],
                        [{"text": "📅 Programar como Tarea", "callback_data": f"yttarea_{vid}"}]
                    ]
                }

                print(f"📡 Radar YouTube: Anunciando nuevo video de {canal['nombre']} ({vid}): «{datos['titulo']}»")
                if bot_enviar_mensaje_func:
                    bot_enviar_mensaje_func(target_chat, texto_anuncio, reply_markup=teclado)
                    anunciados += 1
                time.sleep(1)
        except Exception as e:
            print(f"⚠️ Error revisando radar {canal['nombre']}: {e}")

    guardar_vistos(nuevos_vistos)
    return anunciados


def radar_loop(bot_enviar_mensaje_func, chat_id_grupo):
    # Primera revisión al arrancar
    try:
        chequear_canales(bot_enviar_mensaje_func, chat_id_grupo)
    except Exception as e:
        print(f"⚠️ Error en primera revisión del radar: {e}")

    while True:
        try:
            time.sleep(90)  # Cada 90 segundos (1.5 minutos)
            chequear_canales(bot_enviar_mensaje_func, chat_id_grupo)
        except Exception as e:
            print(f"⚠️ Error en loop radar YouTube: {e}")
            time.sleep(30)


def iniciar_radar(bot_enviar_mensaje_func, chat_id_grupo):
    t = threading.Thread(target=radar_loop, args=(bot_enviar_mensaje_func, chat_id_grupo), daemon=True)
    t.start()
    print("📡 Radar de YouTube iniciado en segundo plano (ALANISO 2012 y Mario Carrillo, sondeo cada 90s).")
