"""
Inspección profunda de cada término de las 30 preguntas fuera de dominio en el corpus.
Busca coincidencias individuales y compuestas para detectar posibles solapamientos.
"""
import json
import sqlite3
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from normalizador_biblioteca import extraer_tokens_normalizados

conn = sqlite3.connect("data/biblioteca_v2.db")
c = conn.cursor()

with open("tests/preguntas_fuera_dominio.json", "r", encoding="utf-8") as f:
    preguntas = json.load(f)

print("=" * 85)
print("INSPECCIÓN DE TÉRMINOS FUERA DE DOMINIO EN EL CORPUS DE biblioteca_v2.db")
print("=" * 85)

solapamientos_detectados = []

for p in preguntas:
    p_id = p["id"]
    cat = p["categoria"]
    q = p["pregunta"]
    tokens = extraer_tokens_normalizados(q, filtrar_stopwords=True)
    
    # Frecuencia de cada token individual en FTS5
    freqs = {}
    for tok in tokens:
        c.execute("SELECT count(*) FROM transcripciones_fts WHERE transcripciones_fts MATCH ?", (f'"{tok}"*',))
        freqs[tok] = c.fetchone()[0]
        
    # Verificar si alguna ventana contiene 2 o más tokens a la vez
    if len(tokens) >= 2:
        query_and = " AND ".join([f'"{tok}"*' for tok in tokens[:2]])
        c.execute("SELECT count(*) FROM transcripciones_fts WHERE transcripciones_fts MATCH ?", (query_and,))
        and_pairs = c.fetchone()[0]
    else:
        and_pairs = 0

    print(f"\n#{p_id:02d} [{cat}] \"{q}\"")
    print(f"    Tokens y Frecuencias (DF en 89,639 ventanas):")
    for tok, df in freqs.items():
        print(f"      • '{tok}': {df} ventanas")
        
    # Alerta si hay términos espirituales con alta presencia que puedan contaminar
    if "espiritual_cercano" in cat:
        # Detectar si hay tokens específicos que colisionan con enseñanzas del canal
        colisiones = [tok for tok, df in freqs.items() if df > 500]
        if colisiones:
            print(f"    ⚠️ ALERTA DE SOLAPAMIENTO: Tokens con alto DF en el canal: {colisiones}")
            solapamientos_detectados.append((p_id, cat, q, colisiones, freqs))

conn.close()
