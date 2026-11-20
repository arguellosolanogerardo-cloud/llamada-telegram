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
OUTPUT_PATH = os.path.join("tests", "resultados_fuera_dominio.json")

preguntas_inexistentes = [
    "receta para cocinar lasaña boloñesa al horno con queso parmesano",
    "minería de criptomonedas y bitcoin usando tarjetas gráficas gpu",
    "reparación y calibración del carburador de un motor automotriz v8",
    "algoritmos de computación cuántica y entrelazamiento de qubits",
    "final de la liga de campeones de la uefa champions league de fútbol",
    "excavaciones paleontológicas y fósiles de dinosaurios tiranosaurios",
    "instalación de paneles solares fotovoltaicos en tejados residenciales",
    "preparación de cóctel margarita con tequila blanco y zumo de lima",
    "compilación del kernel monolítico de linux con drivers pci express",
    "arquitectura de procesadores risc-v y diseño de circuitos verilog fpga"
]

conn = sqlite3.connect(DB_PATH)

resultados_lista = []

print("=" * 85)
print("EVALUACIÓN DE PREGUNTAS SOBRE TEMAS INEXISTENTES (OUT-OF-DOMAIN)")
print("=" * 85)

for idx, p in enumerate(preguntas_inexistentes, 1):
    tokens = extraer_tokens_normalizados(p)
    res = buscar_v2(conn, p, limit=10)
    
    cant = len(res)
    mejor_score = res[0]["score_bm25"] if res else None
    peor_score = res[-1]["score_bm25"] if res else None
    
    print(f"\nPregunta #{idx}: \"{p}\"")
    print(f"  • Tokens normalizados ({len(tokens)}): {tokens}")
    print(f"  • Resultados devueltos por V2: {cant}")
    
    if res:
        print(f"  • Score BM25 Mejor: {mejor_score:.2f} | Peor: {peor_score:.2f}")
        for r_idx, r in enumerate(res[:3], 1):
            print(f"     #{r_idx}: [{r['video_id']}] (min {r['inicio_segundos']//60}:{r['inicio_segundos']%60:02d}) BM25: {r['score_bm25']:.2f}")
            print(f"         Título: {r['titulo'][:50]}")
            print(f"         Snippet: \"{r['texto'][:80]}...\"")
    else:
        print("  • Ningún resultado devuelto (0 coincidencias).")

    resultados_lista.append({
        "id": idx,
        "pregunta": p,
        "tokens": tokens,
        "total_resultados": cant,
        "mejor_score_bm25": mejor_score,
        "peor_score_bm25": peor_score,
        "primer_resultado": {
            "video_id": res[0]["video_id"],
            "titulo": res[0]["titulo"],
            "minuto": f"{res[0]['inicio_segundos']//60}:{res[0]['inicio_segundos']%60:02d}",
            "snippet": res[0]["texto"][:120],
            "score_bm25": res[0]["score_bm25"]
        } if res else None
    })

conn.close()

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(resultados_lista, f, ensure_ascii=False, indent=2)

print("\n" + "=" * 85)
