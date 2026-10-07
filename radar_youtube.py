import os
import json
import time
import urllib.request
import re
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

CANALES_RADAR = [
    {"id": "UCms8TOzGiu0Ozj-QmpwstQw", "nombre": "ALANISO 2012"},
    {"id": "UCjEjDB1gZMGh0QegLjN1o7w", "nombre": "Mario Carrillo"}
]

RADAR_DB_PATH = os.path.join("data", "radar_vistos.json")

def cargar_vistos():
    if os.path.exists(RADAR_DB_PATH):
        try:
            with open(RADAR_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return []

def guardar_vistos(vistos):
    with open(RADAR_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(vistos, f)

def extraer_datos_xml(xml_texto):
    # Buscamos el primer entry que representa el Aoltimo video
    entry_match = re.search(r'<entry>(.*?)</entry>', xml_texto, re.DOTALL)
    if not entry_match: return None
    entry = entry_match.group(1)
    
    video_id_match = re.search(r'<yt:videoId>(.*?)</yt:videoId>', entry)
    title_match = re.search(r'<title>(.*?)</title>', entry)
    link_match = re.search(r'<link rel="alternate" href="(.*?)"/>', entry)
    
    if video_id_match and title_match and link_match:
        return {
            "video_id": video_id_match.group(1),
            "titulo": title_match.group(1),
            "link": link_match.group(1)
        }
    return None

def chequear_canales(bot_enviar_mensaje_func, chat_id_grupo):
    vistos = cargar_vistos()
    nuevos_vistos = list(vistos)
    hay_nuevos = False
    
    for canal in CANALES_RADAR:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={canal['id']}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            xml_texto = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
            datos = extraer_datos_xml(xml_texto)
            if datos:
                vid = datos["video_id"]
                # Si es la primera vez que corre, no mandamos spam, solo guardamos
                if not vistos:
                    nuevos_vistos.append(vid)
                    hay_nuevos = True
                elif vid not in vistos and vid not in nuevos_vistos:
                    # ES UN VIDEO NUEVO!
                    nuevos_vistos.append(vid)
                    hay_nuevos = True
                    
                    # Preparar anuncio
                    thumb_url = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                    texto_anuncio = (
                        f"🔔 **¡Nueva enseñanza publicada!**\\n\\n"
                        f"📺 **Canal:** {canal['nombre']}\\n"
                        f"✨ **Título:** {datos['titulo']}\\n\\n"
                        f"Puedes ver el video completo aquA-:\\n{datos['link']}"
                    )
                    
                    teclado = {
                        "inline_keyboard": [
                            [{"text": "🎧 Obtener Audio MP3", "callback_data": f"ytmp3_{vid}"}],
                            [{"text": "📅 Programar para la Sala", "callback_data": f"yttarea_{vid}"}]
                        ]
                    }
                    
                    # Enviar mensaje con foto (usando la funciA3n generica si soporta mandar fotos, o mandando texto)
                    bot_enviar_mensaje_func(chat_id_grupo, texto_anuncio, reply_markup=teclado)
        except Exception as e:
            print(f"Error revisando radar {canal['nombre']}: {e}")
            
    if hay_nuevos:
        # Mantener solo los Aoltimos 50 para no hacer un archivo enorme
        guardar_vistos(nuevos_vistos[-50:])

def radar_loop(bot_enviar_mensaje_func, chat_id_grupo):
    while True:
        try:
            chequear_canales(bot_enviar_mensaje_func, chat_id_grupo)
        except Exception as e:
            print(f"Error en loop radar: {e}")
        time.sleep(900) # Revisa cada 15 minutos

def iniciar_radar(bot_enviar_mensaje_func, chat_id_grupo):
    t = threading.Thread(target=radar_loop, args=(bot_enviar_mensaje_func, chat_id_grupo), daemon=True)
    t.start()
    print("Radar de YouTube iniciado en segundo plano.")
