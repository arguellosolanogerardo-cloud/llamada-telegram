"""
Análisis detallado de las 11 preguntas fuera de Top 3 y las 3 que no están en Top 10.
"""
import json
import sqlite3
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from buscador_biblioteca_v2 import buscar_v2

conn = sqlite3.connect("data/biblioteca_v2.db")
with open("tests/preguntas_prueba.json", "r", encoding="utf-8") as f:
    preguntas = json.load(f)

for p in preguntas:
    if p["id"] == 13: p["pregunta"] = "los animales carnivoros comiendo carne"
    if p["id"] == 28: p["pregunta"] = "cuando el alma sale confundida dejando el cuerpo"

def solapan(a_ini, a_fin, b_ini, b_fin):
    return a_ini < b_fin and a_fin > b_ini

print("=" * 85)
print("ANALISIS DETALLADO: 11 PREGUNTAS FUERA DE TOP 3 (INCLUYE 3 FUERA DE TOP 10)")
print("=" * 85)

for p in preguntas:
    q = p["pregunta"]
    exp_vid = p["video_id"]
    exp_ini = p["segundo_inicio"]
    exp_fin = p["segundo_fin"]
    
    res = buscar_v2(conn, q, limit=10)
    puesto_encontrado = None
    res_encontrado = None
    
    for idx, r in enumerate(res, 1):
        if r["video_id"] == exp_vid and solapan(r["inicio_segundos"], r["fin_segundos"], exp_ini, exp_fin):
            puesto_encontrado = idx
            res_encontrado = r
            break
            
    if puesto_encontrado is None or puesto_encontrado > 3:
        m_e1, s_e1 = divmod(exp_ini, 60)
        m_e2, s_e2 = divmod(exp_fin, 60)
        print(f"\nPregunta #{p['id']}: \"{q}\"")
        print(f"  • Video esperado: {exp_vid} | Rango esperado: [{exp_ini}s - {exp_fin}s] ({m_e1:02d}:{s_e1:02d} - {m_e2:02d}:{s_e2:02d})")
        if puesto_encontrado is not None:
            r = res_encontrado
            m_r1, s_r1 = divmod(r['inicio_segundos'], 60)
            m_r2, s_r2 = divmod(r['fin_segundos'], 60)
            print(f"  • Puesto obtenido: #{puesto_encontrado}")
            print(f"  • Intervalo devuelto: [{r['inicio_segundos']}s - {r['fin_segundos']}s] ({m_r1:02d}:{s_r1:02d} - {m_r2:02d}:{s_r2:02d})")
            print(f"  • Tokens coincidentes: {r['tokens_coincidentes']} | Score BM25: {r['score_bm25']:.2f}")
            print(f"  • Puestos superiores (#1..#{puesto_encontrado-1}):")
            for prev_idx in range(puesto_encontrado - 1):
                prev_r = res[prev_idx]
                print(f"     #{prev_idx+1}: {prev_r['video_id']} [{prev_r['inicio_segundos']}s-{prev_r['fin_segundos']}s] toks={prev_r['tokens_coincidentes']} score={prev_r['score_bm25']:.2f} ({prev_r['titulo'][:30]})")
        else:
            print(f"  • Puesto obtenido: NO EN TOP 10 (Total devueltos: {len(res)})")
            # Buscar en qué puesto quedó el video esperado si ampliamos a top 30
            res_30 = buscar_v2(conn, q, limit=30)
            pos_30 = None
            for idx30, r30 in enumerate(res_30, 1):
                if r30["video_id"] == exp_vid and solapan(r30["inicio_segundos"], r30["fin_segundos"], exp_ini, exp_fin):
                    pos_30 = idx30
                    print(f"  • Encontrado ampliando a Top 30 en Puesto #{idx30} [{r30['inicio_segundos']}s-{r30['fin_segundos']}s] score={r30['score_bm25']:.2f} toks={r30['tokens_coincidentes']}")
                    break
            if not pos_30:
                # Comprobar si el video coincide en algún intervalo aunque no se solape
                for idx30, r30 in enumerate(res_30, 1):
                    if r30["video_id"] == exp_vid:
                        print(f"  • Mismo video devuelto en puesto #{idx30} en otro intervalo [{r30['inicio_segundos']}s-{r30['fin_segundos']}s] score={r30['score_bm25']:.2f}")
            print(f"  • Puestos #1..#3 devueltos en la búsqueda:")
            for prev_idx in range(min(3, len(res))):
                prev_r = res[prev_idx]
                print(f"     #{prev_idx+1}: {prev_r['video_id']} [{prev_r['inicio_segundos']}s-{prev_r['fin_segundos']}s] toks={prev_r['tokens_coincidentes']} score={prev_r['score_bm25']:.2f} ({prev_r['titulo'][:30]})")

conn.close()
