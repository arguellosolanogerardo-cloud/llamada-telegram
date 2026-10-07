import os
import sqlite3
import subprocess
import glob
import re
import json
import time
from datetime import datetime

DB_PATH = os.path.join("data", "biblioteca_conocimiento_universal.db")
TEMP_DIR = os.path.join("data", "temp_subs")
ESTADO_PATH = os.path.join("data", "estado_descarga.json")
LOG_ERRORES = os.path.join("data", "imprevistos_descarga.txt")

def parse_vtt_time(time_str):
    partes = time_str.split('.')[0].split(':')
    segundos = 0
    if len(partes) == 3:
        segundos = int(partes[0]) * 3600 + int(partes[1]) * 60 + int(partes[2])
    elif len(partes) == 2:
        segundos = int(partes[0]) * 60 + int(partes[1])
    return segundos

def limpiar_texto(texto):
    texto = re.sub(r'<[^>]+>', '', texto)
    return texto.replace('\\n', ' ').strip()

def procesar_vtt(archivo_vtt):
    try:
        with open(archivo_vtt, 'r', encoding='utf-8') as f:
            lineas = f.readlines()
    except Exception:
        return []
    chunks = []
    chunk_actual = {"inicio": 0, "texto": []}
    patron_tiempo = re.compile(r'(\d+:\d+:\d+\.\d+|\d+:\d+\.\d+)\s*-->\s*')
    
    for i in range(len(lineas)):
        linea = lineas[i].strip()
        if not linea: continue
        match = patron_tiempo.search(linea)
        if match:
            segundos = parse_vtt_time(match.group(1))
            texto_lineas = []
            j = i + 1
            while j < len(lineas) and not patron_tiempo.search(lineas[j]):
                if lineas[j].strip() and not lineas[j].startswith('WEBVTT') and not lineas[j].startswith('Kind:') and not lineas[j].startswith('Language:'):
                    texto_lineas.append(limpiar_texto(lineas[j]))
                j += 1
            texto_bloque = " ".join(texto_lineas).strip()
            if texto_bloque:
                if not chunk_actual["texto"]:
                    chunk_actual["inicio"] = segundos
                if not chunk_actual["texto"] or chunk_actual["texto"][-1] != texto_bloque:
                    chunk_actual["texto"].append(texto_bloque)
                if segundos - chunk_actual["inicio"] > 45 or len(" ".join(chunk_actual["texto"]).split()) > 60:
                    chunks.append({"inicio": chunk_actual["inicio"], "texto": " ".join(chunk_actual["texto"])})
                    chunk_actual = {"inicio": 0, "texto": []}
    if chunk_actual["texto"]:
        chunks.append({"inicio": chunk_actual["inicio"], "texto": " ".join(chunk_actual["texto"])})
    return chunks

def registrar_error(vid, url, mensaje):
    with open(LOG_ERRORES, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR en {vid} ({url}): {mensaje}\\n")

def actualizar_estado(procesados, total, inicio_time, imprevistos, url_actual):
    porcentaje = (procesados / total) * 100 if total > 0 else 100
    tiempo_transcurrido = time.time() - inicio_time
    velocidad = procesados / tiempo_transcurrido if tiempo_transcurrido > 0 else 0
    restantes = total - procesados
    tiempo_restante = restantes / velocidad if velocidad > 0 else 0
    
    m, s = divmod(int(tiempo_restante), 60)
    h, m = divmod(m, 60)
    eta = f"{h}h {m}m {s}s"
    
    estado = {
        "porcentaje": round(porcentaje, 2),
        "completados": procesados,
        "total": total,
        "tiempo_estimado_restante": eta,
        "errores": imprevistos,
        "procesando_actualmente": url_actual,
        "ultima_actualizacion": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, indent=4)
    
    # Barra visual en terminal
    barra = "#" * int(porcentaje / 5) + "-" * (20 - int(porcentaje / 5))
    print(f"\\r[{barra}] {porcentaje:.1f}% | {procesados}/{total} | ETA: {eta} | Errores: {imprevistos} ", end="", flush=True)

def descargar_todo():
    os.makedirs(TEMP_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT v.id, v.video_id FROM videos v LEFT JOIN transcripciones t ON v.video_id = t.video_id WHERE t.id IS NULL''')
    pendientes = c.fetchall()
    
    if not pendientes:
        print("\\n¡Todas las transcripciones han sido procesadas!")
        return

    total = len(pendientes)
    print(f"Iniciando descarga masiva de {total} transcripciones. Esto tomarA¡ tiempo...\\n")
    
    inicio_time = time.time()
    procesados = 0
    imprevistos = 0
    
    for db_id, vid in pendientes:
        url = f"https://www.youtube.com/watch?v={vid}"
        actualizar_estado(procesados, total, inicio_time, imprevistos, url)
        
        for f in glob.glob(os.path.join(TEMP_DIR, "*")):
            os.remove(f)
            
        cmd = ["python", "-m", "yt_dlp", "--write-auto-subs", "--write-subs", "--skip-download", "--sub-langs", "es", "--sub-format", "vtt", "-o", os.path.join(TEMP_DIR, "%(id)s.%(ext)s"), url]
        res = subprocess.run(cmd, capture_output=True, text=True)
        
        if res.returncode != 0 and "ERROR" in res.stderr:
            imprevistos += 1
            registrar_error(vid, url, res.stderr.split("\\n")[0])
            c.execute("INSERT INTO transcripciones (video_id, inicio_segundos, texto) VALUES (?, ?, ?)", (vid, 0, "[Error en descarga]"))
            conn.commit()
            procesados += 1
            continue
            
        vtt_files = glob.glob(os.path.join(TEMP_DIR, "*.vtt"))
        if not vtt_files:
            c.execute("INSERT INTO transcripciones (video_id, inicio_segundos, texto) VALUES (?, ?, ?)", (vid, 0, "[Sin subtA-tulos disponibles]"))
            conn.commit()
        else:
            chunks = procesar_vtt(vtt_files[0])
            if not chunks:
                c.execute("INSERT INTO transcripciones (video_id, inicio_segundos, texto) VALUES (?, ?, ?)", (vid, 0, "[SubtA-tulos vacA-os]"))
            else:
                for chunk in chunks:
                    c.execute("INSERT INTO transcripciones (video_id, inicio_segundos, texto) VALUES (?, ?, ?)", (vid, chunk["inicio"], chunk["texto"]))
            conn.commit()
            
        procesados += 1
        
    actualizar_estado(procesados, total, inicio_time, imprevistos, "Terminado")
    conn.close()
    print("\\n\\n[!] Proceso de construcciA3n de la Biblioteca finalizado.")

if __name__ == "__main__":
    descargar_todo()
