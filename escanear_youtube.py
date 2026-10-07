import os
import json
import sqlite3
import subprocess
from datetime import datetime

CANALES = [
    "https://www.youtube.com/@jaimesutil2160/videos",
    "https://www.youtube.com/@mariocarrillo7892/videos",
    "https://www.youtube.com/@mariocarrillo7919/videos",
    "https://www.youtube.com/@ALANISO-2012/videos"
]

DB_PATH = os.path.join("data", "biblioteca_conocimiento_universal.db")
TEMP_DIR = os.path.join("data", "temp_subs")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS canales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    nombre TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canal_id INTEGER,
                    video_id TEXT UNIQUE,
                    titulo TEXT,
                    fecha_publicacion TEXT,
                    FOREIGN KEY(canal_id) REFERENCES canales(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS transcripciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT,
                    inicio_segundos INTEGER,
                    texto TEXT,
                    FOREIGN KEY(video_id) REFERENCES videos(video_id))''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_texto ON transcripciones(texto)''')
    conn.commit()
    return conn

def obtener_info_canal(url):
    print(f"\\nRecopilando videos del canal: {url}...")
    cmd = [
        "python", "-m", "yt_dlp",
        "--flat-playlist",
        "--dump-json",
        "--ignore-errors",
        url
    ]
    # Usar Popen para leer lA-nea por lA-nea directamente
    videos = []
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            line = line.strip()
            if not line: continue
            try:
                data = json.loads(line)
                if data.get("id"):
                    videos.append({
                        "video_id": data.get("id"),
                        "titulo": data.get("title", ""),
                        "uploader": data.get("uploader", url.split("@")[-1].split("/")[0])
                    })
            except Exception as e:
                pass
        proc.wait()
    except Exception as e:
        print(f"Error ejecutando yt-dlp: {e}")
    return videos

def procesar_canales():
    conn = init_db()
    c = conn.cursor()
    
    for url in CANALES:
        videos = obtener_info_canal(url)
        if not videos:
            continue
            
        nombre_canal = videos[0]["uploader"]
        c.execute("INSERT OR IGNORE INTO canales (url, nombre) VALUES (?, ?)", (url, nombre_canal))
        c.execute("SELECT id FROM canales WHERE url = ?", (url,))
        canal_id = c.fetchone()[0]
        
        for v in videos:
            c.execute("INSERT OR IGNORE INTO videos (canal_id, video_id, titulo) VALUES (?, ?, ?)", 
                      (canal_id, v["video_id"], v["titulo"]))
    
    conn.commit()
    conn.close()
    print("\\n[!] Fase 1 Completada: Todos los tA-tulos y canales estA¡n en la base de datos.")

if __name__ == "__main__":
    procesar_canales()
