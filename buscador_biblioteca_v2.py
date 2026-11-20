"""
Motor de búsqueda V2 para la Biblioteca del Conocimiento Universal.
Utiliza FTS5 con stemming Snowball, ranking BM25, estrategia AND->OR,
fusión de bloques contiguos, límite de 2 resultados por video y reconstrucción
de texto original desde la tabla transcripciones.
"""
import sqlite3
import os
import sys

from normalizador_biblioteca import extraer_tokens_normalizados

DB_V2_PATH = os.path.join("data", "biblioteca_v2.db")

def buscar_v2(conn, texto_pregunta: str, limit: int = 10, max_por_video: int = 2) -> list[dict]:
    """
    Ejecuta la búsqueda en FTS5 sobre biblioteca_v2.db.
    Devuelve lista de dicts:
      {
        "video_id": str,
        "titulo": str,
        "inicio_segundos": int,
        "inicio_link_segundos": int,  # inicio - 5 segundos para contexto
        "fin_segundos": int,
        "texto": str,
        "score_bm25": float
      }
    """
    tokens = extraer_tokens_normalizados(texto_pregunta, filtrar_stopwords=True)
    if not tokens:
        return []

    c = conn.cursor()

    # Precalcular Document Frequency (DF) de los tokens de la pregunta
    dfs = {}
    for tok in tokens:
        c.execute("SELECT count(*) FROM transcripciones_fts WHERE transcripciones_fts MATCH ?", (f'"{tok}"*',))
        dfs[tok] = c.fetchone()[0]

    # Identificar tokens específicos (DF <= 2500, es decir <= 2.8% de las ventanas)
    tokens_especificos = {tok for tok, df_val in dfs.items() if df_val <= 2500}

    # Regla de 1 solo token
    if len(tokens) == 1:
        if not tokens_especificos:
            # Es un término genérico (ej. 'tierra', 'hacer', 'vida', 'mundo')
            return []
        min_tokens_requeridos = 1
    else:
        # Regla 2+ tokens: al menos la mitad de los stems (mínimo 2)
        min_tokens_requeridos = max(2, (len(tokens) + 1) // 2)

    sql_base = """
        SELECT v2.id, v2.video_id, v.titulo, v2.inicio_segundos, v2.fin_segundos, fts.rank, v2.texto_stemmed
        FROM transcripciones_fts fts
        JOIN transcripciones_v2 v2 ON fts.rowid = v2.id
        JOIN videos v ON v2.video_id = v.video_id
        WHERE transcripciones_fts MATCH ?
        ORDER BY fts.rank
        LIMIT 60
    """

    # 1. Ejecutar AND
    query_and = " AND ".join([f'"{tok}"*' for tok in tokens])
    c.execute(sql_base, (query_and,))
    candidatos_and = c.fetchall()

    # 2. Ejecutar OR para tener pool de candidatos si AND no llena el límite
    query_or = " OR ".join([f'"{tok}"*' for tok in tokens])
    c.execute(sql_base, (query_or,))
    candidatos_or = c.fetchall()

    # Combinar candidatos: AND primero, luego OR sin duplicar IDs
    existentes_ids = set()
    candidatos_combinados = []
    for r in candidatos_and:
        existentes_ids.add(r[0])
        candidatos_combinados.append(r)
    for r in candidatos_or:
        if r[0] not in existentes_ids:
            existentes_ids.add(r[0])
            candidatos_combinados.append(r)

    # 3. Filtrar estrictamente:
    #    a) Debe contener al menos min_tokens_requeridos
    #    b) Con 2+ tokens, AL MENOS UNO de los tokens coincidentes debe ser ESPECÍFICO (DF <= 2500)
    candidatos_validados = []
    for row_id, vid, tit, ini, fin, rank_val, txt_stemmed in candidatos_combinados:
        palabras_doc = set(txt_stemmed.split())
        coincidentes = [tok for tok in tokens if any(w.startswith(tok) for w in palabras_doc)]
        
        if len(coincidentes) < min_tokens_requeridos:
            continue
            
        # Exigir al menos un token específico entre los coincidentes si hay tokens específicos en la pregunta
        if tokens_especificos:
            if not any(tok in tokens_especificos for tok in coincidentes):
                continue
        else:
            # Si la pregunta no tenía NINGÚN token específico (todos genéricos), no puede pasar
            continue

        candidatos_validados.append((row_id, vid, tit, ini, fin, rank_val, coincidentes))

    if not candidatos_validados:
        return []

    # 4. Fusión de bloques contiguos y tope por video
    resultados_agrupados = []
    conteo_por_video = {}

    for row_id, vid, tit, ini, fin, rank_val, coincidentes in candidatos_validados:
        fusionado = False
        for res in resultados_agrupados:
            if res["video_id"] == vid:
                if abs(ini - res["fin_segundos"]) <= 35 or abs(res["inicio_segundos"] - ini) <= 45:
                    res["inicio_segundos"] = min(res["inicio_segundos"], ini)
                    res["fin_segundos"] = max(res["fin_segundos"], fin)
                    res["inicio_link_segundos"] = max(0, res["inicio_segundos"] - 5)
                    res["score_bm25"] = min(res["score_bm25"], rank_val)
                    res["tokens_coincidentes"] = sorted(list(set(res["tokens_coincidentes"] + coincidentes)))
                    res["num_tokens_coincidentes"] = len(res["tokens_coincidentes"])
                    fusionado = True
                    break

        if fusionado:
            continue

        if conteo_por_video.get(vid, 0) >= max_por_video:
            continue

        conteo_por_video[vid] = conteo_por_video.get(vid, 0) + 1

        resultados_agrupados.append({
            "id": row_id,
            "video_id": vid,
            "titulo": tit,
            "inicio_segundos": ini,
            "inicio_link_segundos": max(0, ini - 5),
            "fin_segundos": fin,
            "texto": "",
            "score_bm25": rank_val,
            "tokens_coincidentes": coincidentes,
            "num_tokens_coincidentes": len(coincidentes)
        })

        if len(resultados_agrupados) >= limit:
            break

    # Reconstruir texto original legible desde la tabla transcripciones
    for res in resultados_agrupados:
        vid = res["video_id"]
        ini = res["inicio_segundos"]
        fin = res["fin_segundos"]
        
        c.execute("""
            SELECT texto FROM transcripciones
            WHERE video_id = ? AND inicio_segundos >= ? AND inicio_segundos <= ?
            ORDER BY inicio_segundos
        """, (vid, ini, fin))
        partes = [r[0] for r in c.fetchall()]
        if partes:
            res["texto"] = " ".join(partes)
        else:
            # Fallback a un rango más holgado
            c.execute("""
                SELECT texto FROM transcripciones
                WHERE video_id = ? AND inicio_segundos >= ? - 15 AND inicio_segundos <= ? + 15
                ORDER BY inicio_segundos
            """, (vid, ini, fin))
            res["texto"] = " ".join(r[0] for r in c.fetchall())

    return resultados_agrupados[:limit]
