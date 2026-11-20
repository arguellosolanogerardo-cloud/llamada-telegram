import sqlite3
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from normalizador_biblioteca import extraer_tokens_normalizados

conn = sqlite3.connect("data/biblioteca_v2.db")
c = conn.cursor()

queries = ["dinosaurios", "kundalini", "mormones"]

for q in queries:
    tokens = extraer_tokens_normalizados(q, filtrar_stopwords=True)
    tok = tokens[0]
    
    # 1. Total en corpus FTS5
    c.execute("SELECT count(*) FROM transcripciones_fts WHERE transcripciones_fts MATCH ?", (f'"{tok}"*',))
    total_fts = c.fetchone()[0]
    
    # 2. Pool inicial de SQL (LIMIT 60)
    sql = """
        SELECT v2.id, v2.video_id, v2.inicio_segundos, v2.fin_segundos, fts.rank, v2.texto_stemmed
        FROM transcripciones_fts fts
        JOIN transcripciones_v2 v2 ON fts.rowid = v2.id
        WHERE transcripciones_fts MATCH ?
        ORDER BY fts.rank
        LIMIT 60
    """
    c.execute(sql, (f'"{tok}"*',))
    pool_sql = c.fetchall()
    
    # 3. Filtro de tokens
    candidatos_validados = []
    for r in pool_sql:
        palabras = set(r[5].split())
        if any(w.startswith(tok) for w in palabras):
            candidatos_validados.append(r)
            
    # 4. Fusión contigua
    agrupados = []
    conteo_video = {}
    fusionados_count = 0
    tope_video_count = 0
    
    for r in candidatos_validados:
        vid, ini, fin = r[1], r[2], r[3]
        fusionado = False
        for res in agrupados:
            if res["video_id"] == vid:
                if abs(ini - res["fin_segundos"]) <= 35 or abs(res["inicio_segundos"] - ini) <= 45:
                    res["inicio_segundos"] = min(res["inicio_segundos"], ini)
                    res["fin_segundos"] = max(res["fin_segundos"], fin)
                    fusionado = True
                    fusionados_count += 1
                    break
        if fusionado:
            continue
            
        if conteo_video.get(vid, 0) >= 2:
            tope_video_count += 1
            continue
            
        conteo_video[vid] = conteo_video.get(vid, 0) + 1
        agrupados.append({"video_id": vid, "inicio_segundos": ini, "fin_segundos": fin})
        
    print(f"=== Consulta: \"{q}\" (stem: \"{tok}\") ===")
    print(f"  1. Total ventanas con el stem en todo el corpus: {total_fts}")
    print(f"  2. Pool inicial SQL (ORDER BY rank LIMIT 60):    {len(pool_sql)}")
    print(f"  3. Pasan filtro de token específico:             {len(candidatos_validados)}")
    print(f"  4. Ventanas fusionadas (contiguas/solapadas):    {fusionados_count}")
    print(f"  5. Descartados por tope de 2 por video:          {tope_video_count}")
    print(f"  6. Resultados únicos agrupados disponibles:      {len(agrupados)}")
    print(f"  7. Devueltos cuando limit=3:                     {min(3, len(agrupados))}")
    print(f"  8. Devueltos cuando limit=10:                    {min(10, len(agrupados))}")
    print()

conn.close()
