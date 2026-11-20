"""
Calibración y Evaluación Completa Multi-Dimensional Post-Indexación
==================================================================
Soporta: --dim all (ejecuta 768, 512 y 256 d) o --dim {256, 512, 768}

Métricas y Evaluaciones por Dimensión:
  1. Vectores Solos:
     - Similitud Top-1 y ranking del objetivo en Set Ciego (30 preguntas) y preguntas_reales.json.
     - Aciertos Top 3 y Top 10 con solapamiento temporal de intervalos.
     - Similitud Top-1 en Set Fuera de Dominio (30 preguntas OOD).
     - Percentiles P10, P25, P50, P75, P90 y calibración empírica de doble umbral (S_bajo, S_alto).
     - Distribución porcentual en bandas (< S_bajo, intermedia, >= S_alto).
  2. Búsqueda Híbrida RRF (Vectores + FTS5 con regla de tokens específicos):
     - Set Original (30 preguntas): verificación de no regresión (debe ser >= 27/30).
     - Set Ciego (30 preguntas): aciertos Top 3 y Top 10.
     - Set Fuera de Dominio (30 preguntas): verificación estricta de 0 resultados ([]).
     - Set Límite (10 preguntas): reporte observacional (vectorial, FTS5 e híbrido).

Nota: Se advierte explícitamente que los resultados con umbrales calibrados sobre
las mismas preguntas representan un techo optimista (in-sample).
"""

import os
import sys
import json
import sqlite3
import argparse
import numpy as np
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from buscador_biblioteca_v2 import buscar_v2

API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
DB_PATH = os.path.join("data", "biblioteca_v2.db")

def renormalizar_l2(matriz_o_vector: np.ndarray) -> np.ndarray:
    if matriz_o_vector.ndim == 1:
        norma = np.linalg.norm(matriz_o_vector)
        return matriz_o_vector / norma if norma > 0 else matriz_o_vector
    normas = np.linalg.norm(matriz_o_vector, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return matriz_o_vector / normas

def solapan_intervalos(ini1: int, fin1: int, ini2: int, fin2: int) -> bool:
    return (ini1 < fin2) and (fin1 > ini2)

def fts5_coincide(candidato_vec: dict, resultados_fts5: list) -> bool:
    v_vid = candidato_vec["video_id"]
    v_ini = candidato_vec["inicio_segundos"]
    v_fin = candidato_vec["fin_segundos"]
    for f in resultados_fts5:
        if f["video_id"] == v_vid and solapan_intervalos(v_ini, v_fin, f["inicio_segundos"], f["fin_segundos"]):
            return True
    return False

def ejecutar_busqueda_hibrida_rrf(
    conn: sqlite3.Connection,
    texto_query: str,
    vec_q: np.ndarray,
    matriz_vectores: np.ndarray,
    ventanas: list,
    s_bajo: float,
    s_alto: float,
    k_rrf: int = 60,
    limit: int = 5
) -> list[dict]:
    """
    Ejecuta búsqueda híbrida RRF combinando los Top-20 vectoriales con los Top-20 de FTS5.
    Aplica el doble umbral:
      - Solo vectorial: aceptado si sim >= S_alto.
      - Intermedio [S_bajo, S_alto): aceptado solo si FTS5 coincide.
      - Inferior < S_bajo: descartado si no está en FTS5.
      - Candidatos FTS5: aceptados si pasaron el filtro de token específico.
    """
    # 1. Candidatos FTS5 (con filtro de token específico de buscar_v2)
    candidatos_fts = buscar_v2(conn, texto_query, limit=20, max_por_video=2)

    # 2. Candidatos Vectoriales (Top 20 por similitud coseno)
    similitudes = np.dot(matriz_vectores, vec_q)
    top20_indices = np.argsort(-similitudes)[:20]

    # Mapeo de puntajes RRF
    rrf_scores = {}
    doc_info = {}

    for rank_v, idx_c in enumerate(top20_indices, 1):
        v = ventanas[idx_c]
        doc_key = f"{v['video_id']}_{v['inicio_segundos']}"
        sim_val = float(similitudes[idx_c])

        # Verificación de umbral para el candidato vectorial
        pasa_vectorial = False
        if sim_val >= s_alto:
            pasa_vectorial = True
        elif sim_val >= s_bajo:
            # Requiere corroboración FTS5
            if fts5_coincide(v, candidatos_fts):
                pasa_vectorial = True

        if pasa_vectorial:
            rrf_scores[doc_key] = rrf_scores.get(doc_key, 0.0) + (1.0 / (k_rrf + rank_v))
            doc_info[doc_key] = {
                "id": v["id"],
                "video_id": v["video_id"],
                "inicio_segundos": v["inicio_segundos"],
                "fin_segundos": v["fin_segundos"],
                "similitud_coseno": sim_val,
                "origen": "vector"
            }

    for rank_f, f in enumerate(candidatos_fts, 1):
        # Buscar si solapa con algún doc_key ya registrado
        solapado_key = None
        for dk, d_val in doc_info.items():
            if d_val["video_id"] == f["video_id"] and solapan_intervalos(d_val["inicio_segundos"], d_val["fin_segundos"], f["inicio_segundos"], f["fin_segundos"]):
                solapado_key = dk
                break

        if solapado_key:
            rrf_scores[solapado_key] += (1.0 / (k_rrf + rank_f))
            doc_info[solapado_key]["origen"] = "hibrido"
        else:
            doc_key = f"{f['video_id']}_{f['inicio_segundos']}"
            rrf_scores[doc_key] = rrf_scores.get(doc_key, 0.0) + (1.0 / (k_rrf + rank_f))
            doc_info[doc_key] = {
                "id": f.get("id", 0),
                "video_id": f["video_id"],
                "inicio_segundos": f["inicio_segundos"],
                "fin_segundos": f["fin_segundos"],
                "similitud_coseno": 0.0,
                "origen": "fts5"
            }

    # Ordenar por puntaje RRF descendente
    ordenados = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)
    resultados_finales = []
    conteo_vid = {}

    for k in ordenados:
        d = doc_info[k]
        vid = d["video_id"]
        if conteo_vid.get(vid, 0) >= 2:
            continue
        conteo_vid[vid] = conteo_vid.get(vid, 0) + 1
        d["rrf_score"] = round(rrf_scores[k], 6)
        resultados_finales.append(d)
        if len(resultados_finales) >= limit:
            break

    return resultados_finales

def evaluar_dimension(
    dim: int,
    matriz_vectores: np.ndarray,
    ventanas: list,
    conn: sqlite3.Connection,
    client,
    modelo: str,
    cache_query_vectors_768: dict
) -> dict:
    print("\n" + "═" * 85)
    print(f"EVALUACIÓN Y CALIBRACIÓN COMPLETA PARA DIMENSIÓN {dim} d")
    print("═" * 85)

    def get_vec_q(q_text: str) -> np.ndarray:
        if q_text not in cache_query_vectors_768:
            from google.genai import types
            res = client.models.embed_content(
                model=modelo,
                contents=[q_text],
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=768
                )
            )
            v768 = np.array(res.embeddings[0].values, dtype=np.float32)
            cache_query_vectors_768[q_text] = renormalizar_l2(v768)

        v_base = cache_query_vectors_768[q_text]
        if dim == 768:
            return v_base
        return renormalizar_l2(v_base[:dim].copy())

    # 1. Medir distribución OOD (30 preguntas fuera de dominio)
    with open("tests/preguntas_fuera_dominio.json", "r", encoding="utf-8") as f:
        preguntas_ood = json.load(f)

    sims_top1_ood = []
    for p in preguntas_ood:
        vec_q = get_vec_q(p["pregunta"])
        sims = np.dot(matriz_vectores, vec_q)
        sims_top1_ood.append(float(np.max(sims)))

    p_ood = np.percentile(sims_top1_ood, [10, 25, 50, 75, 90, 100])
    s_alto = float(max(p_ood[4] + 0.03, p_ood[5]))
    s_bajo = float(p_ood[2])  # mediana de OOD

    # 2. Medir Set Ciego (30 preguntas)
    with open("tests/preguntas_ciegas.json", "r", encoding="utf-8") as f:
        preguntas_ciegas = json.load(f)

    sims_top1_ciegas = []
    ranks_vec_ciegas = []
    aciertos_hibrido_ciegas_top3 = 0
    aciertos_hibrido_ciegas_top10 = 0

    for p in preguntas_ciegas:
        q = p["pregunta"]
        exp_vid = p["video_id_esperado"]
        exp_ini = p["inicio_segundos_esperado"]
        exp_fin = p["fin_segundos_esperado"]

        vec_q = get_vec_q(q)
        sims = np.dot(matriz_vectores, vec_q)
        sims_top1_ciegas.append(float(np.max(sims)))

        # Ranking vectorial puro
        idx_sort = np.argsort(-sims)
        rank_v = 999999
        for r_pos, idx_c in enumerate(idx_sort, 1):
            cand = ventanas[idx_c]
            if cand["video_id"] == exp_vid and solapan_intervalos(cand["inicio_segundos"], cand["fin_segundos"], exp_ini, exp_fin):
                rank_v = r_pos
                break
        ranks_vec_ciegas.append(rank_v)

        # Evaluación Híbrida RRF
        res_hib = ejecutar_busqueda_hibrida_rrf(conn, q, vec_q, matriz_vectores, ventanas, s_bajo, s_alto, limit=10)
        encontrado_hib_pos = None
        for pos_h, rh in enumerate(res_hib, 1):
            if rh["video_id"] == exp_vid and solapan_intervalos(rh["inicio_segundos"], rh["fin_segundos"], exp_ini, exp_fin):
                encontrado_hib_pos = pos_h
                break
        if encontrado_hib_pos and encontrado_hib_pos <= 3:
            aciertos_hibrido_ciegas_top3 += 1
        if encontrado_hib_pos and encontrado_hib_pos <= 10:
            aciertos_hibrido_ciegas_top10 += 1

    p_ciegas = np.percentile(sims_top1_ciegas, [10, 25, 50, 75, 90])

    # 3. Medir Set Original (30 preguntas calibradas) con Híbrido RRF (No regresión >= 27/30)
    with open("tests/preguntas_prueba.json", "r", encoding="utf-8") as f:
        preguntas_orig = json.load(f)

    aciertos_orig_top3 = 0
    aciertos_orig_top10 = 0

    for p in preguntas_orig:
        q = p["pregunta"]
        exp_vid = p["video_id_esperado"]
        exp_ini = p["inicio_segundos_esperado"]
        exp_fin = p["fin_segundos_esperado"]

        vec_q = get_vec_q(q)
        res_hib = ejecutar_busqueda_hibrida_rrf(conn, q, vec_q, matriz_vectores, ventanas, s_bajo, s_alto, limit=10)
        pos_encontrado = None
        for pos_h, rh in enumerate(res_hib, 1):
            if rh["video_id"] == exp_vid and solapan_intervalos(rh["inicio_segundos"], rh["fin_segundos"], exp_ini, exp_fin):
                pos_encontrado = pos_h
                break
        if pos_encontrado and pos_encontrado <= 3:
            aciertos_orig_top3 += 1
        if pos_encontrado and pos_encontrado <= 10:
            aciertos_orig_top10 += 1

    # 4. Medir Fuera de Dominio con Híbrido RRF (Debe dar 0 devueltos)
    falsos_positivos_ood_hibrido = 0
    for p in preguntas_ood:
        vec_q = get_vec_q(p["pregunta"])
        res_hib = ejecutar_busqueda_hibrida_rrf(conn, p["pregunta"], vec_q, matriz_vectores, ventanas, s_bajo, s_alto, limit=5)
        if len(res_hib) > 0:
            falsos_positivos_ood_hibrido += 1

    # 5. Medir Preguntas Reales si existen
    aciertos_reales_vec_top3 = None
    aciertos_reales_vec_top10 = None
    if os.path.exists("tests/preguntas_reales.json"):
        with open("tests/preguntas_reales.json", "r", encoding="utf-8") as f:
            preguntas_reales = json.load(f)
        if preguntas_reales:
            ranks_reales = []
            for p in preguntas_reales:
                q = p["pregunta"]
                exp_vid = p.get("video_id_esperado")
                exp_ini = p.get("inicio_segundos_esperado", 0)
                exp_fin = p.get("fin_segundos_esperado", 0)
                vec_q = get_vec_q(q)
                sims = np.dot(matriz_vectores, vec_q)
                idx_sort = np.argsort(-sims)
                rank_v = 999999
                for r_pos, idx_c in enumerate(idx_sort, 1):
                    cand = ventanas[idx_c]
                    if exp_vid and cand["video_id"] == exp_vid and solapan_intervalos(cand["inicio_segundos"], cand["fin_segundos"], exp_ini, exp_fin):
                        rank_v = r_pos
                        break
                ranks_reales.append(rank_v)
            aciertos_reales_vec_top3 = sum(1 for r in ranks_reales if r <= 3)
            aciertos_reales_vec_top10 = sum(1 for r in ranks_reales if r <= 10)

    # Distribución en bandas del Set Ciego y OOD
    def clasificar_banda(s):
        if s >= s_alto:
            return "ALTA"
        elif s >= s_bajo:
            return "INTERMEDIA"
        return "BAJA"

    bandas_ciegas = [clasificar_banda(s) for s in sims_top1_ciegas]
    bandas_ood = [clasificar_banda(s) for s in sims_top1_ood]

    # Reporte por consola
    print(f"--- 1. UMBRALES CALIBRADOS (Dimensión: {dim} d) ---")
    print(f"  • S_alto (Aceptación vectorial pura):   {s_alto:.4f}")
    print(f"  • S_bajo (Piso corroboración FTS5):     {s_bajo:.4f}")
    print(f"  • Percentiles Top-1 OOD:    P10={p_ood[0]:.4f} | Mediana={p_ood[2]:.4f} | P90={p_ood[4]:.4f} | Max={p_ood[5]:.4f}")
    print(f"  • Percentiles Top-1 Ciegas: P10={p_ciegas[0]:.4f} | Mediana={p_ciegas[2]:.4f} | P90={p_ciegas[4]:.4f}")

    print(f"\n--- 2. DISTRIBUCIÓN EN BANDAS ---")
    print(f"  • Set Ciego (30 preg.):      Alta={bandas_ciegas.count('ALTA')} ({bandas_ciegas.count('ALTA')/30*100:.1f}%) | Intermedia={bandas_ciegas.count('INTERMEDIA')} ({bandas_ciegas.count('INTERMEDIA')/30*100:.1f}%) | Baja={bandas_ciegas.count('BAJA')} ({bandas_ciegas.count('BAJA')/30*100:.1f}%)")
    print(f"  • Fuera de Dominio (30 p.):  Alta={bandas_ood.count('ALTA')} ({bandas_ood.count('ALTA')/30*100:.1f}%) | Intermedia={bandas_ood.count('INTERMEDIA')} ({bandas_ood.count('INTERMEDIA')/30*100:.1f}%) | Baja={bandas_ood.count('BAJA')} ({bandas_ood.count('BAJA')/30*100:.1f}%)")

    vec_ciegas_top3 = sum(1 for r in ranks_vec_ciegas if r <= 3)
    vec_ciegas_top10 = sum(1 for r in ranks_vec_ciegas if r <= 10)

    print(f"\n--- 3. RENDIMIENTO BENCHMARK (Dimensión: {dim} d) ---")
    print(f"  • [VECTORES SOLOS] Set Ciego (30 preg.):")
    print(f"      Top 3:  {vec_ciegas_top3}/30 ({vec_ciegas_top3/30*100:.1f}%)")
    print(f"      Top 10: {vec_ciegas_top10}/30 ({vec_ciegas_top10/30*100:.1f}%)")
    if aciertos_reales_vec_top10 is not None:
        print(f"  • [VECTORES SOLOS] Preguntas Reales:")
        print(f"      Top 3:  {aciertos_reales_vec_top3}")
        print(f"      Top 10: {aciertos_reales_vec_top10}")

    print(f"  • [HÍBRIDO RRF] Set Ciego (30 preg.):")
    print(f"      Top 3:  {aciertos_hibrido_ciegas_top3}/30 ({aciertos_hibrido_ciegas_top3/30*100:.1f}%)")
    print(f"      Top 10: {aciertos_hibrido_ciegas_top10}/30 ({aciertos_hibrido_ciegas_top10/30*100:.1f}%)")

    print(f"  • [HÍBRIDO RRF] Set Original (30 preg. - Control de Regresión):")
    print(f"      Top 3:  {aciertos_orig_top3}/30 ({aciertos_orig_top3/30*100:.1f}%)")
    print(f"      Top 10: {aciertos_orig_top10}/30 ({aciertos_orig_top10/30*100:.1f}%) -> {'CUMPLE (>= 27/30)' if aciertos_orig_top10 >= 27 else 'FALLA REGRESIÓN'}")

    print(f"  • [HÍBRIDO RRF] Fuera de Dominio (30 preg. - Filtro de Falsos Positivos):")
    print(f"      Devolvieron resultados: {falsos_positivos_ood_hibrido}/30 -> {'100% PERFECTO ([])' if falsos_positivos_ood_hibrido == 0 else 'HAY FALSOS POSITIVOS'}")

    return {
        "dimension": dim,
        "umbrales": {"s_alto": round(s_alto, 4), "s_bajo": round(s_bajo, 4)},
        "percentiles_ood": [round(float(x), 4) for x in p_ood],
        "percentiles_ciegas": [round(float(x), 4) for x in p_ciegas],
        "bandas_ciegas_pct": {
            "alta": round(bandas_ciegas.count('ALTA')/30*100, 1),
            "intermedia": round(bandas_ciegas.count('INTERMEDIA')/30*100, 1),
            "baja": round(bandas_ciegas.count('BAJA')/30*100, 1)
        },
        "vectores_solos_ciegas": {"top3": vec_ciegas_top3, "top10": vec_ciegas_top10},
        "hibrido_ciegas": {"top3": aciertos_hibrido_ciegas_top3, "top10": aciertos_hibrido_ciegas_top10},
        "hibrido_original": {"top3": aciertos_orig_top3, "top10": aciertos_orig_top10},
        "hibrido_ood_falsos_positivos": falsos_positivos_ood_hibrido
    }

def main():
    parser = argparse.ArgumentParser(description="Calibración y evaluación de embeddings.")
    parser.add_argument("--dim", default="all", help="Dimensión: 'all', '768', '512' o '256'")
    parser.add_argument("--vectors-dir", default=os.path.join("data", "vectores_v2"), help="Directorio de vectores")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: Clave GEMINI_API_KEY no definida en entorno.")
        sys.exit(1)

    meta_path = os.path.join(args.vectors_dir, "metadata.json")
    if not os.path.exists(meta_path):
        print(f"ERROR: No se encontró {meta_path}. Ejecuta primero indexar_corpus_completo.py.")
        sys.exit(1)

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    modelo = meta.get("modelo", "gemini-embedding-001")

    dims_a_probar = [768, 512, 256] if args.dim.lower() == "all" else [int(args.dim)]

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, video_id, inicio_segundos, fin_segundos FROM transcripciones_v2 ORDER BY id")
    filas_v2 = c.fetchall()
    ventanas = [{"id": r[0], "video_id": r[1], "inicio_segundos": r[2], "fin_segundos": r[3], "idx": idx} for idx, r in enumerate(filas_v2)]

    from google import genai
    client = genai.Client(api_key=API_KEY)

    cache_queries = {}
    resultados_totales = {}

    for d in dims_a_probar:
        mat_path = os.path.join(args.vectors_dir, f"vectores_{d}.npy")
        if not os.path.exists(mat_path):
            print(f"Aviso: {mat_path} no existe en disco. Omitiendo dimensión {d}.")
            continue
        mat = np.load(mat_path)
        res_dim = evaluar_dimension(d, mat, ventanas, conn, client, modelo, cache_queries)
        resultados_totales[str(d)] = res_dim

    conn.close()

    # Guardar en archivo
    out_file = "tests/resultados_calibracion_completa.json"
    with open(out_file, "w", encoding="utf-8") as f_out:
        json.dump(resultados_totales, f_out, indent=2)

    print("\n" + "=" * 85)
    print("RESUMEN CONSOLIDADO Y ADVERTENCIA METODOLÓGICA")
    print("=" * 85)
    print(">> Resultados guardados en tests/resultados_calibracion_completa.json")
    print(">> [ADVERTENCIA METODOLÓGICA]: Los umbrales calibrados sobre el mismo conjunto")
    print("   representan un TECHO OPTIMISTA (in-sample). En producción real con usuarios,")
    print("   la distribución empírica presentará variabilidad.")
    print("=" * 85 + "\n")

if __name__ == "__main__":
    main()
