import sqlite3
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from tests.evaluar_linea_base import ejecutar_busqueda_actual
from buscador_biblioteca_v2 import buscar_v2

DB_V1_PATH = os.path.join("data", "biblioteca_conocimiento_universal.db")
DB_V2_PATH = os.path.join("data", "biblioteca_v2.db")
PREGUNTAS_PATH = os.path.join("tests", "preguntas_prueba.json")
RESULTADOS_PATH = os.path.join("tests", "resultados_comparativa.json")

def evaluar_comparativa():
    with open(PREGUNTAS_PATH, "r", encoding="utf-8") as f:
        preguntas = json.load(f)

    conn_v1 = sqlite3.connect(DB_V1_PATH)
    conn_v2 = sqlite3.connect(DB_V2_PATH)

    v1_top3 = 0
    v1_top10 = 0
    v2_top3 = 0
    v2_top10 = 0
    total = len(preguntas)

    filas_detalle = []

    for item in preguntas:
        p_id = item["id"]
        pregunta = item["pregunta"]
        exp_vid = item["video_id"]
        exp_ini = item["segundo_inicio"]
        exp_fin = item["segundo_fin"]
        tipo = item["tipo"]

        r_min = max(0, exp_ini - 30)
        r_max = exp_fin + 30

        # --- EVALUAR V1 (Actual) ---
        res_v1 = ejecutar_busqueda_actual(conn_v1, pregunta, limit=10)
        v1_hit3 = False
        v1_hit10 = False
        v1_pos = None

        for idx, (tit, seg, txt, vid) in enumerate(res_v1):
            if vid == exp_vid and (r_min <= seg <= r_max):
                if idx < 3: v1_hit3 = True
                if idx < 10:
                    v1_hit10 = True
                    v1_pos = idx + 1
                break

        if v1_hit3: v1_top3 += 1
        if v1_hit10: v1_top10 += 1

        # --- EVALUAR V2 (Nuevo FTS5 + BM25) ---
        res_v2 = buscar_v2(conn_v2, pregunta, limit=10, max_por_video=2)
        v2_hit3 = False
        v2_hit10 = False
        v2_pos = None

        for idx, r in enumerate(res_v2):
            vid = r["video_id"]
            seg = r["inicio_segundos"]
            fin = r["fin_segundos"]
            # Acierto si el video coincide y cae dentro del rango ±30s
            es_acierto = (vid == exp_vid) and (
                (r_min <= seg <= r_max) or 
                (abs(seg - exp_ini) <= 30) or
                (seg <= exp_fin and fin >= exp_ini)
            )
            if es_acierto:
                if idx < 3: v2_hit3 = True
                if idx < 10:
                    v2_hit10 = True
                    v2_pos = idx + 1
                break

        if v2_hit3: v2_top3 += 1
        if v2_hit10: v2_top10 += 1

        filas_detalle.append({
            "id": p_id,
            "pregunta": pregunta,
            "tipo": tipo,
            "esperado": f"{exp_vid} ({exp_ini}s)",
            "v1_top3": v1_hit3,
            "v1_top10": v1_hit10,
            "v1_pos": v1_pos,
            "v2_top3": v2_hit3,
            "v2_top10": v2_hit10,
            "v2_pos": v2_pos,
        })

    conn_v1.close()
    conn_v2.close()

    pct_v1_top3 = (v1_top3 / total) * 100
    pct_v1_top10 = (v1_top10 / total) * 100
    pct_v2_top3 = (v2_top3 / total) * 100
    pct_v2_top10 = (v2_top10 / total) * 100

    print("=" * 80)
    print("RESULTADOS DE BENCHMARK COMPARATIVO: MOTOR V1 vs MOTOR V2 (FTS5 + BM25)")
    print("=" * 80)
    print(f"Total de preguntas evaluadas: {total} (20 estándar parafraseadas + 10 vecinos)")
    print("-" * 80)
    print(f"MOTOR V1 (Actual - LIKE + AND):")
    print(f"  • Top 3:   {v1_top3}/{total} ({pct_v1_top3:.1f}%)")
    print(f"  • Top 10:  {v1_top10}/{total} ({pct_v1_top10:.1f}%)")
    print("-" * 80)
    print(f"MOTOR V2 (Nuevo - FTS5 + BM25 + Ventanas Solapadas):")
    print(f"  • Top 3:   {v2_top3}/{total} ({pct_v2_top3:.1f}%)")
    print(f"  • Top 10:  {v2_top10}/{total} ({pct_v2_top10:.1f}%)")
    print("=" * 80)

    # Detalle por categoría
    for t_nom in ["estandar", "vecinos"]:
        sub = [r for r in filas_detalle if r["tipo"] == t_nom]
        s_v1_10 = sum(1 for r in sub if r["v1_top10"])
        s_v2_10 = sum(1 for r in sub if r["v2_top10"])
        s_v2_3 = sum(1 for r in sub if r["v2_top3"])
        print(f"Categoría '{t_nom}' ({len(sub)} preguntas):")
        print(f"  V1 Top 10 = {s_v1_10}/{len(sub)} ({s_v1_10/len(sub)*100:.1f}%)  -->  V2 Top 10 = {s_v2_10}/{len(sub)} ({s_v2_10/len(sub)*100:.1f}%) [Top 3 = {s_v2_3/len(sub)*100:.1f}%]")

    print("=" * 80)

    # Guardar resultados
    with open(RESULTADOS_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "total": total,
            "v1_top3_pct": pct_v1_top3,
            "v1_top10_pct": pct_v1_top10,
            "v2_top3_pct": pct_v2_top3,
            "v2_top10_pct": pct_v2_top10,
            "detalle": filas_detalle
        }, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    evaluar_comparativa()
