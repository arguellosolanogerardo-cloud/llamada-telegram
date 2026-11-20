"""
Script de reconstrucción y migración a biblioteca_v2.db:
- Deduplicación en el origen (transcripciones queda 100% limpia para Telegram y V1).
- Ventanas basadas en tiempo (~47 s duración, ~28 s avance, configurables).
- Índice FTS5 optimizado sobre transcripciones_v2.
- Generación de biblioteca_v2.zip y verificación de integridad.
"""
import sqlite3
import os
import sys
import time
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from normalizador_biblioteca import texto_a_stems

DB_ORIG = os.path.join("backup_crudo", "biblioteca_transcripciones_cruda_backup.db")
DB_V2 = os.path.join("data", "biblioteca_v2.db")
ZIP_V2 = os.path.join("data", "biblioteca_v2.zip")

# Parámetros configurables de tiempo (en segundos)
WINDOW_SECONDS = 47   # Duración de cada ventana
STEP_SECONDS = 28     # Avance entre ventanas (~40.4% de solapamiento)

def deduplicar_frases_intra_linea(texto: str) -> str:
    """
    Deduplica repeticiones dentro de una misma línea de subtítulo.
    - Colapsa palabras repetidas >= 3 veces ('para para para para' -> 'para').
    - Preserva repeticiones legítimas de 2 palabras ('muy muy bien', 'casi casi').
    - Colapsa frases repetidas consecutivas (k = 2 a 15 palabras).
    """
    palabras = texto.split()
    if not palabras:
        return ""
    
    # 1. Colapsar palabras individuales repetidas >= 3 veces
    limpias = []
    i = 0
    n = len(palabras)
    while i < n:
        w = palabras[i]
        j = i + 1
        while j < n and palabras[j].lower() == w.lower():
            j += 1
        rep = j - i
        if rep >= 3:
            limpias.append(w)
        elif rep == 2:
            limpias.append(w)
            limpias.append(palabras[i+1])
        else:
            limpias.append(w)
        i = j
        
    palabras = limpias
    
    # 2. Frases repetidas consecutivas (k de 2 a 15 palabras)
    n = len(palabras)
    resultado = []
    i = 0
    while i < n:
        match_k = 0
        max_k = min(15, (n - i) // 2)
        for k in range(max_k, 1, -1):
            if [w.lower() for w in palabras[i:i+k]] == [w.lower() for w in palabras[i+k:i+2*k]]:
                match_k = k
                break
        if match_k > 0:
            resultado.extend(palabras[i:i+match_k])
            i += 2 * match_k
            while i + match_k <= n and [w.lower() for w in palabras[i:i+match_k]] == [w.lower() for w in resultado[-match_k:]]:
                i += match_k
        else:
            resultado.append(palabras[i])
            i += 1
            
    return " ".join(resultado)

def deduplicar_stream_video(filas_video: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """
    Deduplica una secuencia de filas (inicio_segundos, texto) de un video:
    aplica deduplicación intra-línea y elimina solapamiento inicial con el final de la línea previa.
    """
    resultado = []
    palabras_previas = []

    for seg, txt in filas_video:
        txt_intra = deduplicar_frases_intra_linea(txt)
        palabras_act = txt_intra.split()
        if not palabras_act:
            continue

        if palabras_previas:
            max_ov = min(len(palabras_previas), len(palabras_act), 15)
            ov_k = 0
            for k in range(max_ov, 1, -1):
                if [w.lower() for w in palabras_previas[-k:]] == [w.lower() for w in palabras_act[:k]]:
                    ov_k = k
                    break
            if ov_k > 0:
                palabras_act = palabras_act[ov_k:]

        if palabras_act:
            txt_final = " ".join(palabras_act)
            resultado.append((seg, txt_final))
            palabras_previas.extend(palabras_act)
            if len(palabras_previas) > 40:
                palabras_previas = palabras_previas[-40:]

    return resultado

def migrar():
    t_inicio = time.time()
    print("=" * 75)
    print("INICIANDO RECONSTRUCCIÓN COMPLETA DE biblioteca_v2.db CON DEDUPLICACIÓN")
    print(f"Parámetros: Ventana = {WINDOW_SECONDS}s | Avance = {STEP_SECONDS}s | Solapamiento = {round(((WINDOW_SECONDS-STEP_SECONDS)/WINDOW_SECONDS)*100, 1)}%")
    print(f"Origen de datos crudos: {DB_ORIG}")
    print("=" * 75)

    if not os.path.exists(DB_ORIG):
        print(f"Error crítico: No existe el archivo de backup crudo {DB_ORIG}")
        return

    # Si existe un biblioteca_v2.db previo, eliminarlo para empezar limpio
    if os.path.exists(DB_V2):
        os.remove(DB_V2)

    conn_orig = sqlite3.connect(DB_ORIG)
    c_orig = conn_orig.cursor()

    conn_v2 = sqlite3.connect(DB_V2)
    # Optimizaciones para inserción masiva en SQLite
    conn_v2.execute("PRAGMA journal_mode = OFF")
    conn_v2.execute("PRAGMA synchronous = 0")
    conn_v2.execute("PRAGMA cache_size = 100000")
    c_v2 = conn_v2.cursor()

    # 1. Esquemas en v2
    print("1. Creando tablas en biblioteca_v2.db...")
    c_v2.execute("""
        CREATE TABLE canales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            nombre TEXT
        )
    """)
    c_v2.execute("""
        CREATE TABLE videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canal_id INTEGER,
            video_id TEXT UNIQUE,
            titulo TEXT,
            fecha_publicacion TEXT,
            FOREIGN KEY(canal_id) REFERENCES canales(id)
        )
    """)
    c_v2.execute("""
        CREATE TABLE transcripciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            inicio_segundos INTEGER,
            texto TEXT,
            FOREIGN KEY(video_id) REFERENCES videos(video_id)
        )
    """)
    c_v2.execute("""
        CREATE TABLE transcripciones_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            inicio_segundos INTEGER,
            fin_segundos INTEGER,
            texto_stemmed TEXT
        )
    """)
    c_v2.execute("""
        CREATE VIRTUAL TABLE transcripciones_fts USING fts5(
            texto_stemmed,
            content='transcripciones_v2',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        )
    """)

    # 2. Copiar canales
    print("2. Copiando canales...")
    c_orig.execute("SELECT id, url, nombre FROM canales")
    c_v2.executemany("INSERT INTO canales (id, url, nombre) VALUES (?, ?, ?)", c_orig.fetchall())

    # 3. Copiar videos
    print("3. Copiando videos...")
    c_orig.execute("SELECT id, canal_id, video_id, titulo, fecha_publicacion FROM videos")
    c_v2.executemany("INSERT INTO videos (id, canal_id, video_id, titulo, fecha_publicacion) VALUES (?, ?, ?, ?, ?)", c_orig.fetchall())

    # 4. Procesar videos: Deduplicar origen y generar ventanas por tiempo
    print("4. Deduplicando en el origen y generando ventanas temporales...")
    c_orig.execute("SELECT distinct video_id FROM transcripciones WHERE texto NOT LIKE '[%]'")
    vids = [r[0] for r in c_orig.fetchall()]
    total_vids = len(vids)

    batch_trans_clean = []
    batch_v2 = []
    batch_fts = []
    
    total_filas_clean = 0
    total_ventanas = 0
    row_v2_counter = 1

    for idx, vid in enumerate(vids):
        c_orig.execute("SELECT inicio_segundos, texto FROM transcripciones WHERE video_id = ? AND texto NOT LIKE '[%]' ORDER BY inicio_segundos", (vid,))
        filas_raw = c_orig.fetchall()
        if not filas_raw:
            continue

        # A. Deduplicación en el origen
        filas_clean = deduplicar_stream_video(filas_raw)
        if not filas_clean:
            continue

        for seg, txt in filas_clean:
            batch_trans_clean.append((vid, seg, txt))
            total_filas_clean += 1

        # B. Construcción de ventanas por tiempo (~47s duración, ~28s avance)
        t_min = filas_clean[0][0]
        t_max = filas_clean[-1][0]
        
        t_start = t_min
        idx_f = 0
        n_clean = len(filas_clean)

        while t_start <= t_max and idx_f < n_clean:
            if filas_clean[idx_f][0] >= t_start + WINDOW_SECONDS:
                t_start = filas_clean[idx_f][0]

            t_end = t_start + WINDOW_SECONDS
            
            # Recoger filas dentro del rango temporal [t_start, t_end)
            chunk_txt = []
            for s, txt in filas_clean:
                if s >= t_end:
                    break
                if s >= t_start:
                    chunk_txt.append(txt)

            if chunk_txt:
                txt_window = " ".join(chunk_txt)
                txt_stemmed = texto_a_stems(txt_window)

                batch_v2.append((row_v2_counter, vid, t_start, t_end, txt_stemmed))
                batch_fts.append((row_v2_counter, txt_stemmed))
                
                row_v2_counter += 1
                total_ventanas += 1

            t_start += STEP_SECONDS

        # Inserción en lotes de 5,000 registros para alta velocidad
        if len(batch_trans_clean) >= 5000:
            c_v2.executemany("INSERT INTO transcripciones (video_id, inicio_segundos, texto) VALUES (?, ?, ?)", batch_trans_clean)
            c_v2.executemany("INSERT INTO transcripciones_v2 (id, video_id, inicio_segundos, fin_segundos, texto_stemmed) VALUES (?, ?, ?, ?, ?)", batch_v2)
            c_v2.executemany("INSERT INTO transcripciones_fts (rowid, texto_stemmed) VALUES (?, ?)", batch_fts)
            conn_v2.commit()
            batch_trans_clean.clear()
            batch_v2.clear()
            batch_fts.clear()

        if (idx + 1) % 400 == 0 or (idx + 1) == total_vids:
            pct = ((idx + 1) / total_vids) * 100
            print(f"   Progreso: {idx + 1}/{total_vids} videos ({pct:.1f}%) | Filas limpias: {total_filas_clean:,} | Ventanas: {total_ventanas:,}")

    if batch_trans_clean:
        c_v2.executemany("INSERT INTO transcripciones (video_id, inicio_segundos, texto) VALUES (?, ?, ?)", batch_trans_clean)
        c_v2.executemany("INSERT INTO transcripciones_v2 (id, video_id, inicio_segundos, fin_segundos, texto_stemmed) VALUES (?, ?, ?, ?, ?)", batch_v2)
        c_v2.executemany("INSERT INTO transcripciones_fts (rowid, texto_stemmed) VALUES (?, ?)", batch_fts)
        conn_v2.commit()
        batch_trans_clean.clear()
        batch_v2.clear()
        batch_fts.clear()

    conn_orig.close()

    # 5. Crear índice para reconstrucción de texto eficiente
    print("5. Creando índice idx_trans_vid_sec en transcripciones limpias...")
    c_v2.execute("CREATE INDEX idx_trans_vid_sec ON transcripciones(video_id, inicio_segundos)")

    # 6. Optimización y VACUUM
    print("6. Optimizando base de datos con VACUUM...")
    conn_v2.execute("PRAGMA journal_mode = DELETE")
    conn_v2.execute("PRAGMA synchronous = NORMAL")
    conn_v2.commit()
    conn_v2.close()

    conn_v2 = sqlite3.connect(DB_V2)
    conn_v2.execute("VACUUM")

    # 7. Verificación de integridad y conteos
    print("7. Verificando integridad con PRAGMA integrity_check...")
    c_chk = conn_v2.cursor()
    c_chk.execute("PRAGMA integrity_check")
    integ = c_chk.fetchone()[0]

    c_chk.execute("SELECT count(*) FROM canales")
    canales_cnt = c_chk.fetchone()[0]

    c_chk.execute("SELECT count(*) FROM videos")
    videos_cnt = c_chk.fetchone()[0]

    c_chk.execute("SELECT count(*) FROM transcripciones")
    trans_clean_cnt = c_chk.fetchone()[0]

    c_chk.execute("SELECT count(*) FROM transcripciones_v2")
    trans_v2_cnt = c_chk.fetchone()[0]

    c_chk.execute("SELECT count(*) FROM transcripciones_fts")
    fts_cnt = c_chk.fetchone()[0]

    conn_v2.close()

    # 8. Empaquetado ZIP para Render
    print("8. Empaquetando en data/biblioteca_v2.zip...")
    if os.path.exists(ZIP_V2):
        os.remove(ZIP_V2)

    with zipfile.ZipFile(ZIP_V2, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(DB_V2, arcname="biblioteca_v2.db")

    size_db_mb = os.path.getsize(DB_V2) / (1024 * 1024)
    size_zip_mb = os.path.getsize(ZIP_V2) / (1024 * 1024)
    duracion = round(time.time() - t_inicio, 1)

    print("=" * 75)
    print("RECONSTRUCCIÓN FINALIZADA EXITOSAMENTE")
    print(f"Duración: {duracion} segundos")
    print(f"Integridad SQLite: {integ}")
    print(f"Conteos:")
    print(f"  • Canales:                  {canales_cnt}")
    print(f"  • Videos:                   {videos_cnt}")
    print(f"  • Transcripciones limpias:  {trans_clean_cnt:,}")
    print(f"  • Ventanas v2 temporales:   {trans_v2_cnt:,}")
    print(f"  • Documentos en FTS5:       {fts_cnt:,}")
    print(f"Tamaño en disco:")
    print(f"  • biblioteca_v2.db:         {size_db_mb:.2f} MB")
    print(f"  • biblioteca_v2.zip:        {size_zip_mb:.2f} MB")
    print("=" * 75)

if __name__ == "__main__":
    migrar()
