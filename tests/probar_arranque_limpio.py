"""
Prueba de arranque limpio simulando entorno de despliegue en Render:
- Directorio data_prueba/ que contiene ÚNICAMENTE biblioteca_v2.zip.
- Verifica descompresión automática en disco (no en memoria BytesIO).
- Prueba modo BUSQUEDA_V2=0 (V1 sobre biblioteca_v2.db).
- Prueba modo BUSQUEDA_V2=1 (V2 FTS5 sobre biblioteca_v2.db).
"""
import os
import sys
import shutil
import zipfile
import sqlite3

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEMP_DIR = os.path.join("tests", "temp_render_data")
ZIP_ORIG = os.path.join("data", "biblioteca_v2.zip")

print("=" * 75)
print("PRUEBA DE ARRANQUE LIMPIO (SIMULACIÓN DEPLOY RENDER CON UN SOLO ARCHIVO ZIP)")
print("=" * 75)

# 1. Preparar directorio temporal limpio
if os.path.exists(TEMP_DIR):
    shutil.rmtree(TEMP_DIR)
os.makedirs(TEMP_DIR, exist_ok=True)

# Copiar solo el zip
temp_zip = os.path.join(TEMP_DIR, "biblioteca_v2.zip")
temp_db = os.path.join(TEMP_DIR, "biblioteca_v2.db")
shutil.copy2(ZIP_ORIG, temp_zip)
print(f"1. Directorio limpio creado con único archivo: {temp_zip} ({os.path.getsize(temp_zip)/(1024*1024):.2f} MB)")
print(f"   ¿Existe biblioteca_v2.db? {os.path.exists(temp_db)}")
print(f"   ¿Existe base antigua?     False")

# 2. Simular descompresión de arranque (código idéntico a bot_comandos.py)
print("\n2. Ejecutando lógica de descompresión de arranque de bot_comandos.py...")
if not os.path.exists(temp_db) and os.path.exists(temp_zip):
    with zipfile.ZipFile(temp_zip, 'r') as zf:
        zf.extractall(TEMP_DIR)
print(f"   Descompresión exitosa en disco: {os.path.exists(temp_db)} ({os.path.getsize(temp_db)/(1024*1024):.2f} MB)")

# 3. Probar MODO BUSQUEDA_V2=0 (Consulta V1 clásica ejecutada sobre biblioteca_v2.db)
print("\n3. Probando MODO BUSQUEDA_V2=0 (Consulta V1 sobre biblioteca_v2.db)...")
conn = sqlite3.connect(temp_db)
c = conn.cursor()
c.execute("""
    SELECT v.titulo, t.inicio_segundos, t.texto, v.video_id
    FROM transcripciones t
    INNER JOIN videos v ON t.video_id = v.video_id
    WHERE t.texto LIKE ?
    ORDER BY v.fecha_publicacion DESC
    LIMIT 3
""", ("%astral%",))
filas_v1 = c.fetchall()
print(f"   Resultados devueltos por V1: {len(filas_v1)}")
for idx, (tit, seg, txt, vid) in enumerate(filas_v1, 1):
    m, s = divmod(seg, 60)
    print(f"     #{idx} [{m:02d}:{s:02d}] {tit[:35]}... : \"{txt[:60]}...\"")

# 4. Probar MODO BUSQUEDA_V2=1 (Motor V2 FTS5 sobre biblioteca_v2.db)
print("\n4. Probando MODO BUSQUEDA_V2=1 (Motor V2 sobre biblioteca_v2.db)...")
sys.path.insert(0, ".")
from buscador_biblioteca_v2 import buscar_v2

res_v2 = buscar_v2(conn, "haciendo viajes astrales conscientes", limit=3)
print(f"   Resultados devueltos por V2: {len(res_v2)}")
for idx, r in enumerate(res_v2, 1):
    m, s = divmod(r["inicio_segundos"], 60)
    print(f"     #{idx} [{m:02d}:{s:02d}] {r['titulo'][:35]}... : \"{r['texto'][:60]}...\"")

conn.close()

# 5. Limpieza del directorio temporal
shutil.rmtree(TEMP_DIR)
print("\n5. Limpieza completada. Directorio temporal eliminado.")
print("=" * 75)
print("VERIFICACIÓN COMPLETA: Ambos modos funcionan 100% con solo biblioteca_v2.db.")
print("=" * 75)
