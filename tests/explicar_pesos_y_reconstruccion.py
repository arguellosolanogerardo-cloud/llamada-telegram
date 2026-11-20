import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

conn = sqlite3.connect("data/biblioteca_v2.db")
c = conn.cursor()

c.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'index')")
objs = c.fetchall()
print("Objetos en biblioteca_v2.db:")
for o in objs:
    print(" ", o)

print("\nConteos de filas:")
for t in ['canales', 'videos', 'transcripciones', 'transcripciones_v2', 'transcripciones_fts']:
    c.execute(f"SELECT count(*) FROM {t}")
    print(f"  Tabla {t}: {c.fetchone()[0]:,} filas")

# Probar la reconstrucción exacta para 3 ventanas aleatorias
print("\nVerificación de Reconstrucción de Texto desde tabla transcripciones:")
c.execute("""
    SELECT v2.id, v2.video_id, v.titulo, v2.inicio_segundos, v2.fin_segundos, v2.texto_stemmed
    FROM transcripciones_v2 v2
    JOIN videos v ON v2.video_id = v.video_id
    WHERE v2.id IN (1, 5000, 50000)
""")
rows = c.fetchall()

for row in rows:
    v2_id, vid, tit, ini, fin, stemmed = row
    print(f"\n--- Ventana ID {v2_id} | Video {vid} ({ini}s - {fin}s) ---")
    print(f"Título: {tit}")
    print(f"Stemmed en FTS5 (primeros 100 car.): {stemmed[:100]}...")
    
    c.execute("""
        SELECT inicio_segundos, texto
        FROM transcripciones
        WHERE video_id = ? AND inicio_segundos >= ? AND inicio_segundos <= ?
        ORDER BY inicio_segundos
    """, (vid, ini, fin))
    partes = c.fetchall()
    print(f"Filas encontradas en tabla 'transcripciones': {len(partes)}")
    for p in partes:
        print(f"   [{p[0]}s]: {p[1][:60]}...")
    reconstruido = " ".join([p[1] for p in partes])
    print(f"Texto Reconstruido ({len(reconstruido)} chars):")
    print(f"   \"{reconstruido[:140]}...\"")

conn.close()
