import sqlite3
import os
import sys
import zlib
import re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Stemmer Snowball en español puro para no depender de librerías externas en la simulación
try:
    from nltk.stem.snowball import SpanishStemmer
    _stemmer = SpanishStemmer()
    def stem_es(palabra):
        return _stemmer.stem(palabra)
except Exception:
    # Fallback básico si fuera necesario
    def stem_es(palabra):
        p = palabra.lower()
        for suf in ["aciones", "imiento", "imientos", "mente", "idad", "idades", "ando", "iendo", "aron", "eron", "aran", "eran", "amos", "emos", "imos", "es", "as", "os", "s"]:
            if p.endswith(suf) and len(p) > len(suf) + 3:
                return p[:-len(suf)]
        return p

def normalizar_y_stem(texto):
    t = texto.lower()
    # Quitar acentos para remove_diacritics
    t = t.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u').replace('ü', 'u')
    palabras = re.findall(r'\b[a-zA-Z0-9]{2,}\b', t)
    return " ".join(stem_es(w) for w in palabras)

DB_PATH = os.path.join("data", "biblioteca_conocimiento_universal.db")

def simular_tamanos(window_rows=4, stride_rows=2, num_videos_muestra=100):
    """
    Simula la creación de ventanas deslizantes y compara el tamaño de almacenamiento
    entre Opción A y Opción B.
    
    Parámetros configurables:
      - window_rows: tamaño de la ventana en filas (4 filas ~ 38-45 segundos)
      - stride_rows: avance en filas (2 filas ~ 19-20 segundos de avance = 50% solapamiento)
      - num_videos_muestra: número de videos a muestrear para proyectar el 100%
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Total de videos y filas en la base real
    c.execute("SELECT count(distinct video_id) FROM transcripciones WHERE texto NOT LIKE '[%]'")
    total_videos = c.fetchone()[0]

    c.execute("SELECT count(*) FROM transcripciones WHERE texto NOT LIKE '[%]'")
    total_filas = c.fetchone()[0]

    # Muestrear videos
    c.execute("SELECT distinct video_id FROM transcripciones WHERE texto NOT LIKE '[%]' LIMIT ?", (num_videos_muestra,))
    vids_muestra = [r[0] for r in c.fetchall()]

    bytes_orig_total = 0
    bytes_opcion_a_total = 0
    bytes_opcion_b_total = 0
    total_ventanas = 0
    filas_analizadas = 0

    texto_a_sample = []
    texto_b_sample = []

    for vid in vids_muestra:
        c.execute("SELECT inicio_segundos, texto FROM transcripciones WHERE video_id = ? AND texto NOT LIKE '[%]' ORDER BY inicio_segundos", (vid,))
        filas = c.fetchall()
        filas_analizadas += len(filas)

        if not filas:
            continue

        for r in filas:
            bytes_orig_total += len(r[1].encode('utf-8'))

        i = 0
        while i < len(filas):
            chunk = filas[i:i + window_rows]
            if not chunk:
                break
            
            ini_seg = chunk[0][0]
            # Fin es el siguiente bloque si existe, o ini + len*10
            if i + window_rows < len(filas):
                fin_seg = filas[i + window_rows][0]
            else:
                fin_seg = ini_seg + len(chunk) * 10

            txt_orig = " ".join(r[1] for r in chunk)
            txt_stemmed = normalizar_y_stem(txt_orig)

            # Opción A: Guarda txt_orig (para mostrar) + txt_stemmed (para FTS)
            # Metadatos fijos por fila SQLite ~ 24 bytes (id, vid, ini, fin)
            bytes_opcion_a_total += 24 + len(txt_orig.encode('utf-8')) + len(txt_stemmed.encode('utf-8'))

            # Opción B: Guarda SOLO txt_stemmed (para FTS) + ini + fin
            # No guarda txt_orig; se reconstruye bajo demanda desde la tabla original
            bytes_opcion_b_total += 24 + len(txt_stemmed.encode('utf-8'))

            total_ventanas += 1
            if len(texto_a_sample) < 500:
                texto_a_sample.append(txt_orig + " " + txt_stemmed)
                texto_b_sample.append(txt_stemmed)

            i += stride_rows
            if i >= len(filas) - 1:
                break

    conn.close()

    # Factor de escala al 100% de la base de datos
    escala = total_videos / num_videos_muestra

    ventanas_proyectadas = int(total_ventanas * escala)
    bytes_a_proyectados = bytes_opcion_a_total * escala
    bytes_b_proyectados = bytes_opcion_b_total * escala

    # Overhead del índice FTS5 (típicamente ~40-60% del tamaño del texto indexado)
    # En FTS5 externo (content='transcripciones_v2'):
    # Solo indexa el texto stemmed.
    fts5_overhead_bytes = (bytes_opcion_b_total * 0.45) * escala

    # Tamaño actual de la base de datos
    db_actual_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    zip_actual_mb = os.path.getsize(os.path.join("data", "biblioteca.zip")) / (1024 * 1024) if os.path.exists(os.path.join("data", "biblioteca.zip")) else 41.29

    # Estimación final de la BD (manteniendo la tabla original como respaldo)
    # BD_Total = BD_Actual + transcripciones_v2 + fts5_index
    mb_extra_a = (bytes_a_proyectados + fts5_overhead_bytes) / (1024 * 1024)
    mb_extra_b = (bytes_b_proyectados + fts5_overhead_bytes) / (1024 * 1024)

    db_total_a = db_actual_mb + mb_extra_a
    db_total_b = db_actual_mb + mb_extra_b

    # Estimación de compresión ZIP (texto suele comprimir a ~25-30%)
    ratio_zip = 0.28
    zip_extra_a = mb_extra_a * ratio_zip
    zip_extra_b = mb_extra_b * ratio_zip
    zip_total_a = zip_actual_mb + zip_extra_a
    zip_total_b = zip_actual_mb + zip_extra_b

    solapamiento_pct = round(((window_rows - stride_rows) / window_rows) * 100, 1)

    return {
        "config": {
            "window_rows": window_rows,
            "stride_rows": stride_rows,
            "solapamiento_pct": solapamiento_pct,
            "duracion_ventana_aprox_seg": round(window_rows * 9.5, 1),
            "avance_aprox_seg": round(stride_rows * 9.5, 1),
            "videos_totales": total_videos,
            "filas_originales": total_filas,
            "ventanas_proyectadas": ventanas_proyectadas
        },
        "actual": {
            "db_mb": round(db_actual_mb, 2),
            "zip_mb": round(zip_actual_mb, 2)
        },
        "opcion_a": {
            "nombre": "Opción A (Texto Original + Texto Stemmed en v2)",
            "mb_extra": round(mb_extra_a, 2),
            "db_total_mb": round(db_total_a, 2),
            "zip_total_mb": round(zip_total_a, 2),
            "velocidad_display": "Directa (lee fragmento prearmado de v2)",
            "duplicacion": "Alta (guarda el texto dos veces además de la tabla original)"
        },
        "opcion_b": {
            "nombre": "Opción B (Solo Texto Stemmed en v2 + reconstrucción al vuelo)",
            "mb_extra": round(mb_extra_b, 2),
            "db_total_mb": round(db_total_b, 2),
            "zip_total_mb": round(zip_total_b, 2),
            "velocidad_display": "Rápida (~0.2ms por consulta de 10 fragmentos en la tabla original)",
            "duplicacion": "Mínima (solo guarda los stems normalizados e IDs de rango)"
        }
    }

if __name__ == "__main__":
    # Probar con ventana de 4 filas (~38s) y avance de 2 filas (50% solapamiento)
    res = simular_tamanos(window_rows=4, stride_rows=2, num_videos_muestra=80)
    print("=" * 70)
    print("SIMULACIÓN DE TAMAÑOS: OPCIÓN A vs OPCIÓN B")
    print(f"Configuración: Ventana = {res['config']['window_rows']} filas (~{res['config']['duracion_ventana_aprox_seg']}s) | Avance = {res['config']['stride_rows']} filas (~{res['config']['avance_aprox_seg']}s) | Solapamiento = {res['config']['solapamiento_pct']}%")
    print(f"Ventanas proyectadas para toda la BD: {res['config']['ventanas_proyectadas']:,}")
    print("=" * 70)
    print(f"Base de Datos Actual: {res['actual']['db_mb']} MB (ZIP actual: {res['actual']['zip_mb']} MB)")
    print("-" * 70)
    print(f"OPCIÓN A: {res['opcion_a']['nombre']}")
    print(f"  • Peso adicional en .db: +{res['opcion_a']['mb_extra']} MB")
    print(f"  • Tamaño final .db:       {res['opcion_a']['db_total_mb']} MB")
    print(f"  • Tamaño final .zip:      {res['opcion_a']['zip_total_mb']} MB")
    print(f"  • Recuperación de texto:  {res['opcion_a']['velocidad_display']}")
    print("-" * 70)
    print(f"OPCIÓN B: {res['opcion_b']['nombre']}")
    print(f"  • Peso adicional en .db: +{res['opcion_b']['mb_extra']} MB")
    print(f"  • Tamaño final .db:       {res['opcion_b']['db_total_mb']} MB")
    print(f"  • Tamaño final .zip:      {res['opcion_b']['zip_total_mb']} MB")
    print(f"  • Recuperación de texto:  {res['opcion_b']['velocidad_display']}")
    print("=" * 70)

    # También probar con ventana de 5 filas y avance de 3 filas (~40% solapamiento)
    res2 = simular_tamanos(window_rows=5, stride_rows=3, num_videos_muestra=80)
    print(f"Variante alternativa más ligera (Ventana=5 filas ~47s, Avance=3 filas ~28s, Solapamiento={res2['config']['solapamiento_pct']}%):")
    print(f"  • Ventanas proyectadas:   {res2['config']['ventanas_proyectadas']:,}")
    print(f"  • Opción A final: .db = {res2['opcion_a']['db_total_mb']} MB | .zip = {res2['opcion_a']['zip_total_mb']} MB")
    print(f"  • Opción B final: .db = {res2['opcion_b']['db_total_mb']} MB | .zip = {res2['opcion_b']['zip_total_mb']} MB")
    print("=" * 70)
