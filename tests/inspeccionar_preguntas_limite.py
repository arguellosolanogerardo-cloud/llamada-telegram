"""
Inspección observacional de las preguntas límite en FTS5 (versión larga vs versión corta natural).
Reporta qué fragmentos devuelve el motor actual sin emitir pasar/fallar.
"""
import json
import sqlite3
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from buscador_biblioteca_v2 import buscar_v2

conn = sqlite3.connect("data/biblioteca_v2.db")

with open("tests/preguntas_limite.json", "r", encoding="utf-8") as f:
    preguntas = json.load(f)

print("=" * 85)
print("REPORTE OBSERVACIONAL DE PREGUNTAS LÍMITE (FTS5 CON PREGUNTAS CORTAS NATURALES)")
print("=" * 85)

for p in preguntas:
    p_id = p["id"]
    cat = p["categoria"]
    q_larga = p["pregunta_larga"]
    q_corta = p["pregunta_corta"]
    t_canal = p["termino_canal"]
    
    res_corta = buscar_v2(conn, q_corta, limit=3)
    
    print(f"\n#{p_id:02d} [{cat}]")
    print(f"  Consulta corta: \"{q_corta}\" | Contexto en canal: {t_canal}")
    print(f"  Total devueltos por FTS5: {len(res_corta)}")
    
    if not res_corta:
        print("    -> Sin resultados devueltos por FTS5")
    else:
        for idx, r in enumerate(res_corta, 1):
            ini = r["inicio_segundos"]
            fin = r["fin_segundos"]
            m_i, s_i = ini // 60, ini % 60
            m_f, s_f = fin // 60, fin % 60
            txt = r["texto"][:140].replace("\n", " ").strip()
            print(f"    [{idx}] Video {r['video_id']} ({m_i:02d}:{s_i:02d} - {m_f:02d}:{s_f:02d}): \"{txt}...\"")

conn.close()
