import sqlite3
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = os.path.join("data", "biblioteca_conocimiento_universal.db")
PREGUNTAS_PATH = os.path.join("tests", "preguntas_prueba.json")
RESULTADOS_PATH = os.path.join("tests", "resultados_linea_base.json")

def ejecutar_busqueda_actual(conn, texto, limit=10):
    """Implementa exactamente la lógica de búsqueda actual de responder_consulta_biblioteca en bot_comandos.py"""
    t_limpio = texto.lower()
    for drop_w in ["biblioteca", "conocimiento", "universal", "toby", "asistente", "busca", "buscame",
                     "donde", "habla", "sobre", "que dice", "qué dice", "en la", "de la", "del",
                     "dime", "cuéntame", "cuentame", "explica", "explicame", "explícame",
                     "pregunta", "encuentra", "hay", "los", "las", "con", "por", "para",
                     "una", "uno", "que", "qué", "quién", "quien", "cómo", "como", "cuál", "cual",
                     "enseñanza", "enseñanzas", "video", "videos", "tema"]:
        t_limpio = t_limpio.replace(drop_w, " ")
    palabras = [p for p in t_limpio.strip().split() if len(p) > 2]

    if not palabras:
        return []

    c = conn.cursor()
    conditions = []
    params = []
    for p in palabras:
        if len(p) > 3:
            conditions.append("t.texto LIKE ?")
            params.append(f"%{p}%")
    if not conditions:
        conditions = ["t.texto LIKE ?"]
        params = [f"%{' '.join(palabras)}%"]

    query = "SELECT v.titulo, t.inicio_segundos, t.texto, v.video_id FROM transcripciones t INNER JOIN videos v ON t.video_id = v.video_id WHERE "
    query += " AND ".join(conditions) + f" LIMIT {limit}"
    
    try:
        c.execute(query, params)
        return c.fetchall()
    except Exception as e:
        print("Error en búsqueda:", e)
        return []

def evaluar():
    with open(PREGUNTAS_PATH, "r", encoding="utf-8") as f:
        preguntas = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    
    resultados_eval = []
    aciertos_top3 = 0
    aciertos_top10 = 0
    total = len(preguntas)

    for item in preguntas:
        p_id = item["id"]
        pregunta = item["pregunta"]
        exp_vid = item["video_id"]
        exp_ini = item["segundo_inicio"]
        exp_fin = item["segundo_fin"]
        tipo = item["tipo"]

        # Rango con margen de ±30 segundos
        rango_min = max(0, exp_ini - 30)
        rango_max = exp_fin + 30

        resultados_raw = ejecutar_busqueda_actual(conn, pregunta, limit=10)

        hit_top3 = False
        hit_top10 = False
        pos_acierto = None

        for idx, (tit, seg, txt, vid) in enumerate(resultados_raw):
            es_video_correcto = (vid == exp_vid)
            en_rango_tiempo = (rango_min <= seg <= rango_max)
            
            if es_video_correcto and en_rango_tiempo:
                if idx < 3 and not hit_top3:
                    hit_top3 = True
                if idx < 10 and not hit_top10:
                    hit_top10 = True
                    pos_acierto = idx + 1
                break

        if hit_top3:
            aciertos_top3 += 1
        if hit_top10:
            aciertos_top10 += 1

        resultados_eval.append({
            "id": p_id,
            "pregunta": pregunta,
            "tipo": tipo,
            "esperado": f"{exp_vid} ({exp_ini}-{exp_fin}s)",
            "total_resultados_devueltos": len(resultados_raw),
            "hit_top3": hit_top3,
            "hit_top10": hit_top10,
            "posicion": pos_acierto
        })

    conn.close()

    pct_top3 = (aciertos_top3 / total) * 100
    pct_top10 = (aciertos_top10 / total) * 100

    print("=" * 60)
    print("MEDICIÓN DE LÍNEA BASE (BUSCADOR ACTUAL - LIKE + AND)")
    print("=" * 60)
    print(f"Total de preguntas evaluadas: {total}")
    print(f"Aciertos Top 3:  {aciertos_top3}/{total} ({pct_top3:.1f}%)")
    print(f"Aciertos Top 10: {aciertos_top10}/{total} ({pct_top10:.1f}%)")
    print("=" * 60)

    # Detalle por tipo
    for t_nombre in ["estandar", "vecinos"]:
        sub = [r for r in resultados_eval if r["tipo"] == t_nombre]
        sub_top3 = sum(1 for r in sub if r["hit_top3"])
        sub_top10 = sum(1 for r in sub if r["hit_top10"])
        print(f"Tipo '{t_nombre}' ({len(sub)} preguntas): Top 3 = {sub_top3}/{len(sub)} ({sub_top3/len(sub)*100:.1f}%) | Top 10 = {sub_top10}/{len(sub)} ({sub_top10/len(sub)*100:.1f}%)")

    with open(RESULTADOS_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "total": total,
            "aciertos_top3": aciertos_top3,
            "porcentaje_top3": pct_top3,
            "aciertos_top10": aciertos_top10,
            "porcentaje_top10": pct_top10,
            "detalle": resultados_eval
        }, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    evaluar()
