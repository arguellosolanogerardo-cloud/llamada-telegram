"""
Analizar distribución de Document Frequency (DF) en el índice FTS5 reconstruido.
"""
import sqlite3

conn = sqlite3.connect("data/biblioteca_v2.db")
c = conn.cursor()

# En FTS5, transcripciones_fts(term, doc) da el vocabulario
# o usando sqlite_master / fts5vocab
try:
    c.execute("CREATE VIRTUAL TABLE temp_vocab USING fts5vocab('transcripciones_fts', 'row')")
    c.execute("SELECT term, doc FROM temp_vocab ORDER BY doc DESC LIMIT 40")
    top_terms = c.fetchall()
    print("=== TOP 40 TÉRMINOS CON MAYOR DF EN FTS5 RECONSTRUIDO ===")
    for t, df in top_terms:
        pct = (df / 89639) * 100
        print(f"{t:20s}: {df:6d} docs ({pct:4.1f}%)")
    
    # Distribución por percentiles de DF
    c.execute("SELECT count(*), max(doc), min(doc) FROM temp_vocab")
    total_vocab, max_doc, min_doc = c.fetchone()
    print(f"\nTotal vocabulario: {total_vocab:,} términos únicos")
    
    # Probar términos de prueba
    print("\n--- DF DE TÉRMINOS CLAVE ---")
    terminos_prueba = ["gran", "tierr", "vid", "mund", "dios", "human", "espiritu", "cuerp", "astral", "chakr", "fidel", "chavez", "pothol", "reencarn", "piramid", "atlantid"]
    for t in terminos_prueba:
        c.execute("SELECT doc FROM temp_vocab WHERE term = ?", (t,))
        res = c.fetchone()
        doc_count = res[0] if res else 0
        pct = (doc_count / 89639) * 100
        print(f"  • '{t:12s}': DF = {doc_count:5d} ({pct:4.2f}%)")

    c.execute("DROP TABLE temp_vocab")
except Exception as e:
    print("Error al consultar vocabulario:", e)
conn.close()
