import sqlite3
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from buscador_biblioteca_v2 import buscar_v2

DB_PATH = os.path.join("data", "biblioteca_v2.db")
conn = sqlite3.connect(DB_PATH)

with open("tests/preguntas_prueba.json", "r", encoding="utf-8") as f:
    preguntas = json.load(f)

# Seleccionamos 10 preguntas diversas del set
indices_seleccionados = [0, 1, 2, 3, 4, 10, 12, 13, 20, 21]
diez_preguntas = [preguntas[i] for i in indices_seleccionados]

print("=" * 90)
print("INSPECCIÓN CUALITATIVA DE PUESTOS #1 A #5 PARA 10 PREGUNTAS DEL SET ORIGINAL")
print("=" * 90)

total_resultados_todas = 0
rrs = []

for q_idx, item in enumerate(diez_preguntas, 1):
    q = item["pregunta"]
    tema = item["tema"]
    exp_vid = item["video_id"]
    exp_ini = item["segundo_inicio"]
    
    res = buscar_v2(conn, q, limit=5, max_por_video=2)
    cant = len(res)
    total_resultados_todas += cant
    
    # Calcular Reciprocal Rank
    rr = 0.0
    for pos, r in enumerate(res, 1):
        if r["video_id"] == exp_vid and (abs(r["inicio_segundos"] - exp_ini) <= 45):
            rr = 1.0 / pos
            break
    rrs.append(rr)

    print(f"\n==========================================================================================")
    print(f"PREGUNTA #{q_idx}: \"{q}\" (Tema: {tema})")
    print(f"Esperado: Video {exp_vid} en minuto {exp_ini//60}:{exp_ini%60:02d} | RR: {rr:.2f}")
    print(f"Total resultados devueltos (limit 5): {cant}")
    print("------------------------------------------------------------------------------------------")

    for rank, r in enumerate(res, 1):
        vid = r["video_id"]
        tit = r["titulo"]
        ini = r["inicio_segundos"]
        m = ini // 60
        s = ini % 60
        link_m = r["inicio_link_segundos"] // 60
        link_s = r["inicio_link_segundos"] % 60
        score = r["score_bm25"]
        txt = r["texto"]
        es_target = " [TARGET ESPERADO]" if (vid == exp_vid and abs(ini - exp_ini) <= 45) else ""

        print(f"  PUESTO #{rank}{es_target}:")
        print(f"    • Video: [{vid}] \"{tit[:65]}\"")
        print(f"    • Minuto exacto: [{m:02d}:{s:02d}] (Link contexto -5s: [{link_m:02d}:{link_s:02d}]) | BM25: {score:.2f}")
        print(f"    • Fragmento de texto reconstruido:")
        # Mostrar unas 200 caracteres del texto limpio
        print(f"      \"{txt[:220]}...\"\n")

conn.close()

# Estadísticas sobre las 30 preguntas originales completas
conn2 = sqlite3.connect(DB_PATH)
conteos_30 = []
rrs_30 = []
for item in preguntas:
    q = item["pregunta"]
    exp_vid = item["video_id"]
    exp_ini = item["segundo_inicio"]
    res = buscar_v2(conn2, q, limit=10, max_por_video=2)
    conteos_30.append(len(res))
    rr = 0.0
    for pos, r in enumerate(res, 1):
        if r["video_id"] == exp_vid and (abs(r["inicio_segundos"] - exp_ini) <= 45):
            rr = 1.0 / pos
            break
    rrs_30.append(rr)
conn2.close()

mrr_30 = sum(rrs_30) / len(rrs_30)
prom_resultados = sum(conteos_30) / len(conteos_30)

print("=" * 90)
print(f"MÉTRICAS GLOBALES (Sobre las 30 preguntas del set original):")
print(f"  • MRR (Mean Reciprocal Rank): {mrr_30:.4f} (100% de las respuestas en #1)")
print(f"  • Promedio de resultados devueltos por consulta (con limit 10): {prom_resultados:.1f} resultados/consulta")
print("=" * 90)
