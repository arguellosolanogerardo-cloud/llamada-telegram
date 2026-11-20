import sqlite3
import os
import sys
import shutil
import re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ORIG_DB = os.path.join("data", "biblioteca_conocimiento_universal.db")
TEMP_DB = os.path.join("data", "temp_test_copy.db")

print("=" * 65)
print("1. EVALUANDO ELIMINACIÓN DE idx_texto EN COPIA DE PRUEBA")
print("=" * 65)

# Crear copia para no tocar el original
if os.path.exists(TEMP_DB):
    os.remove(TEMP_DB)

print("Copiando base de datos para pruebas...")
shutil.copyfile(ORIG_DB, TEMP_DB)

size_inicial = os.path.getsize(TEMP_DB) / (1024 * 1024)
print(f"Tamaño inicial de la copia: {size_inicial:.2f} MB")

conn = sqlite3.connect(TEMP_DB)
c = conn.cursor()

# Verificar índices existentes
c.execute("SELECT name, tbl_name FROM sqlite_master WHERE type = 'index'")
indices = c.fetchall()
print("Índices encontrados:", indices)

# Eliminar idx_texto y ejecutar VACUUM
c.execute("DROP INDEX IF EXISTS idx_texto")
conn.commit()
conn.close()

# Reabrir para VACUUM
conn = sqlite3.connect(TEMP_DB)
conn.execute("VACUUM")
conn.close()

size_sin_indice = os.path.getsize(TEMP_DB) / (1024 * 1024)
ahorro_mb = size_inicial - size_sin_indice
pct_ahorro = (ahorro_mb / size_inicial) * 100

print(f"Tamaño tras eliminar idx_texto y ejecutar VACUUM: {size_sin_indice:.2f} MB")
print(f"Ahorro de espacio por eliminar idx_texto: {ahorro_mb:.2f} MB ({pct_ahorro:.1f}%)")
print("=" * 65)

print("\n" + "=" * 65)
print("2. MEDICIÓN REAL DE FTS5 SOBRE MUESTRA DEL 5%")
print("=" * 65)

# Stemmer Snowball
try:
    from nltk.stem.snowball import SpanishStemmer
    _stemmer = SpanishStemmer()
    def stem_es(palabra):
        return _stemmer.stem(palabra)
except Exception:
    def stem_es(palabra):
        return palabra

def normalizar_y_stem(texto):
    t = texto.lower()
    t = t.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u').replace('ü', 'u')
    palabras = re.findall(r'\b[a-zA-Z0-9]{2,}\b', t)
    return " ".join(stem_es(w) for w in palabras)

conn = sqlite3.connect(TEMP_DB)
c = conn.cursor()

# Total de videos
c.execute("SELECT count(distinct video_id) FROM transcripciones WHERE texto NOT LIKE '[%]'")
total_videos = c.fetchone()[0]

# Muestra del 5%
muestra_videos_count = int(total_videos * 0.05)
print(f"Total videos: {total_videos} | Muestra 5%: {muestra_videos_count} videos")

c.execute("SELECT distinct video_id FROM transcripciones WHERE texto NOT LIKE '[%]' LIMIT ?", (muestra_videos_count,))
muestra_vids = [r[0] for r in c.fetchall()]

# Crear tabla transcripciones_v2_sample (Opción B: solo texto_stemmed + inicio + fin)
c.execute("""
    CREATE TABLE IF NOT EXISTS transcripciones_v2_sample (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT,
        inicio_segundos INTEGER,
        fin_segundos INTEGER,
        texto_stemmed TEXT
    )
""")

# Crear FTS5 virtual table con remove_diacritics 2
c.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS transcripciones_fts_sample USING fts5(
        texto_stemmed,
        content='transcripciones_v2_sample',
        content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    )
""")

# Ventanas de 5 filas, avance de 3 filas (~40% solapamiento)
window_rows = 5
step_rows = 3
total_ventanas_muestra = 0

for vid in muestra_vids:
    c.execute("SELECT inicio_segundos, texto FROM transcripciones WHERE video_id = ? AND texto NOT LIKE '[%]' ORDER BY inicio_segundos", (vid,))
    filas = c.fetchall()
    if not filas:
        continue

    i = 0
    while i < len(filas):
        chunk = filas[i:i + window_rows]
        if not chunk:
            break
        
        ini_seg = chunk[0][0]
        if i + window_rows < len(filas):
            fin_seg = filas[i + window_rows][0]
        else:
            fin_seg = ini_seg + len(chunk) * 10

        txt_orig = " ".join(r[1] for r in chunk)
        txt_stemmed = normalizar_y_stem(txt_orig)

        c.execute("""
            INSERT INTO transcripciones_v2_sample (video_id, inicio_segundos, fin_segundos, texto_stemmed)
            VALUES (?, ?, ?, ?)
        """, (vid, ini_seg, fin_seg, txt_stemmed))
        row_id = c.lastrowid

        # Insertar en FTS5
        c.execute("""
            INSERT INTO transcripciones_fts_sample (rowid, texto_stemmed)
            VALUES (?, ?)
        """, (row_id, txt_stemmed))

        total_ventanas_muestra += 1
        i += step_rows
        if i >= len(filas) - 1:
            break

conn.commit()
conn.close()

# Medir tamaño tras insertar la muestra del 5%
size_con_muestra = os.path.getsize(TEMP_DB) / (1024 * 1024)
mb_muestra = size_con_muestra - size_sin_indice
proyeccion_100_mb = mb_muestra * 20  # Escalar de 5% a 100%
ventanas_totales_proy = total_ventanas_muestra * 20

print(f"Ventanas procesadas en muestra 5%: {total_ventanas_muestra}")
print(f"Peso medido en disco para muestra 5% (tabla v2 + índice FTS5): {mb_muestra:.2f} MB")
print(f"Proyección al 100% (todas las ventanas v2 + FTS5): +{proyeccion_100_mb:.2f} MB")
print(f"Ventanas proyectadas para toda la base: {ventanas_totales_proy:,}")

# Tamaño final estimado para la base nueva:
# Base_Final = (Base_Inicial - ahorro_idx_texto) + proyeccion_v2_y_fts5
base_final_proyectada_mb = (size_inicial - ahorro_mb) + proyeccion_100_mb

print("-" * 65)
print(f"RESUMEN FINAL DE PESO (Opción B: Ventana 5 / Avance 3):")
print(f"  • Base original actual:               {size_inicial:.2f} MB")
print(f"  • Ahorro al quitar idx_texto:         -{ahorro_mb:.2f} MB")
print(f"  • Peso de transcripciones_v2 + FTS5:  +{proyeccion_100_mb:.2f} MB")
print(f"  • Base final estimada en disco (.db): {base_final_proyectada_mb:.2f} MB")
print(f"  • Archivo ZIP estimado (.zip):        ~{base_final_proyectada_mb * 0.23:.2f} MB")
print("=" * 65)

# Limpiar archivo temporal
if os.path.exists(TEMP_DB):
    try:
        os.remove(TEMP_DB)
        print("Copia temporal eliminada correctamente.")
    except Exception as e:
        print("Nota eliminando copia temporal:", e)
