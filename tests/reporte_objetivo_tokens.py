import sqlite3
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from buscador_biblioteca_v2 import buscar_v2
from normalizador_biblioteca import extraer_tokens_normalizados

DB_PATH = os.path.join("data", "biblioteca_v2.db")
conn = sqlite3.connect(DB_PATH)

with open("tests/preguntas_prueba.json", "r", encoding="utf-8") as f:
    preguntas = json.load(f)

# Las 10 preguntas analizadas
indices_seleccionados = [0, 1, 2, 3, 4, 10, 12, 13, 20, 21]
diez_preguntas = [preguntas[i] for i in indices_seleccionados]

print("=" * 90)
print("RECUENTO OBJETIVO DE TOKENS COINCIDENTES EN PUESTOS #1 A #5 (10 PREGUNTAS)")
print("=" * 90)

for q_idx, item in enumerate(diez_preguntas, 1):
    q = item["pregunta"]
    tema = item["tema"]
    tokens_query = extraer_tokens_normalizados(q)
    
    res = buscar_v2(conn, q, limit=5, max_por_video=2)
    
    print(f"\nPregunta #{q_idx}: \"{q}\"")
    print(f"Stems de la pregunta ({len(tokens_query)}): {tokens_query}")
    print(f"Total resultados que pasaron el filtro: {len(res)}")
    print("-" * 80)
    
    if not res:
        print("  (Sin resultados)")
        continue

    for rank, r in enumerate(res, 1):
        vid = r["video_id"]
        ini = r["inicio_segundos"]
        m = ini // 60
        s = ini % 60
        matched = r.get("tokens_coincidentes", [])
        num_m = len(matched)
        pct = (num_m / len(tokens_query)) * 100
        
        print(f"  Puesto #{rank}: [{vid}] ({m:02d}:{s:02d}) -> Coincidencias: {num_m}/{len(tokens_query)} ({pct:.0f}%) | Tokens: {matched}")

conn.close()
