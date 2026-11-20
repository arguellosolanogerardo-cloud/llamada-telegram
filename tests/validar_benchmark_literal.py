import sqlite3
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from tests.evaluar_linea_base import ejecutar_busqueda_actual

DB_PATH = os.path.join("data", "biblioteca_conocimiento_universal.db")
conn = sqlite3.connect(DB_PATH)

casos = [
    ("-0vhbQQErKo", 0, "amigos hermanos venezolanos"),
    ("-0vhbQQErKo", 21, "oposición gente miren"),
    ("-3KffrSkrKY", 5, "orgullosos contentos decirlo todo"),
    ("-3KoKTLPAqI", 2, "febrero 2000 26"),
    ("-3okIwyQQ0A", 4, "diciembre 2025 mario")
]

print("=" * 65)
print("VALIDACIÓN CON 5 BÚSQUEDAS COPIADAS LITERALMENTE DE FRAGMENTOS")
print("=" * 65)

aciertos_top3 = 0
aciertos_top10 = 0

for exp_vid, exp_seg, query in casos:
    res = ejecutar_busqueda_actual(conn, query, limit=10)
    hit_top3 = False
    hit_top10 = False
    pos = None

    for idx, (tit, seg, txt, vid) in enumerate(res):
        if vid == exp_vid and abs(seg - exp_seg) <= 30:
            if idx < 3: hit_top3 = True
            if idx < 10:
                hit_top10 = True
                pos = idx + 1
            break

    if hit_top3: aciertos_top3 += 1
    if hit_top10: aciertos_top10 += 1

    status = f"✅ ACIERTO (Posición #{pos})" if hit_top10 else "❌ FALLO"
    print(f"Pregunta: \"{query}\" (Esperado: {exp_vid} @ {exp_seg}s)")
    print(f"  Resultado: {status} | Total resultados devueltos: {len(res)}")

print("-" * 65)
print(f"Total Aciertos: Top 3 = {aciertos_top3}/5 ({aciertos_top3/5*100:.1f}%) | Top 10 = {aciertos_top10}/5 ({aciertos_top10/5*100:.1f}%)")
print("=" * 65)

conn.close()
