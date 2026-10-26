import os
import sys
import time
import json
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

# Asegurar que el directorio raíz del proyecto esté en sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from radar_youtube import CANALES_RADAR, extraer_videos_web
from bot_comandos import descargar_audio_youtube_robusto

def log_c(msg: str):
    t = datetime.now(ZoneInfo("America/Bogota")).strftime("%H:%M:%S")
    print(f"[{t}] [CENTINELA] {msg}", flush=True)

def verificar_y_sincronizar_nuevos():
    carp_med = os.path.join(BASE_DIR, "data", "meditaciones")
    os.makedirs(carp_med, exist_ok=True)
    
    nuevos_procesados = []
    for canal in CANALES_RADAR:
        try:
            videos = extraer_videos_web(canal["url"])
            for v in videos[:5]: # Revisar los 5 más recientes
                vid = v.get("video_id")
                tit = v.get("titulo", "")
                if not vid:
                    continue
                
                mp3_path = os.path.join(carp_med, f"yt_clean_{vid}.mp3")
                if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) < 1000:
                    log_c(f"Detectado video sin MP3 pre-cargado: {vid} («{tit}»)...")
                    archivo, fuente = descargar_audio_youtube_robusto(vid, tit)
                    if archivo and os.path.exists(archivo) and os.path.getsize(archivo) > 1000:
                        log_c(f"✅ Descargado y remasterizado con éxito: {archivo}")
                        nuevos_procesados.append(vid)
                    else:
                        log_c(f"❌ No se pudo descargar: {vid}")
        except Exception as e:
            log_c(f"Error revisando canal {canal.get('nombre')}: {e}")

    if nuevos_procesados:
        log_c(f"Sincronizando {len(nuevos_procesados)} nuevos audios y radar_vistos con GitHub...")
        try:
            # Actualizar radar_vistos.json para que Render nunca duplique anuncios tras el deploy
            ruta_vistos = os.path.join(BASE_DIR, "data", "radar_vistos.json")
            vistos = []
            if os.path.exists(ruta_vistos):
                try:
                    with open(ruta_vistos, "r", encoding="utf-8") as f:
                        vistos = json.load(f)
                except Exception:
                    pass
            for v_id in nuevos_procesados:
                if v_id not in vistos:
                    vistos.append(v_id)
            with open(ruta_vistos, "w", encoding="utf-8") as f:
                json.dump(vistos, f, indent=2)

            subprocess.run(["git", "add", "data/meditaciones/yt_clean_*.mp3", "data/radar_vistos.json"], cwd=BASE_DIR, check=True)
            subprocess.run(
                ["git", "commit", "-m", "fix(youtube): sincronizar audios y registrar en radar_vistos para evitar duplicados"],
                cwd=BASE_DIR,
                check=True
            )
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=BASE_DIR, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=BASE_DIR, check=True)
            log_c("🚀 ¡Audios y radar_vistos sincronizados y desplegados exitosamente a Render!")
        except Exception as e_git:
            log_c(f"Error sincronizando con git: {e_git}")

def main():
    log_c("Iniciando Centinela Local de YouTube (monitoreo activo cada 30 segundos)...")
    while True:
        try:
            verificar_y_sincronizar_nuevos()
        except Exception as e:
            log_c(f"Error en ciclo de centinela: {e}")
        time.sleep(30)

if __name__ == "__main__":
    main()
