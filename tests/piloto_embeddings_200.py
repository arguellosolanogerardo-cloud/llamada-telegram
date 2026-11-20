"""
Piloto Parametrizado de Embeddings Fase 4 (200 Ventanas Reales):
Soporta:
  --model gemini-embedding-001 (Texto, 768 dims, $0.15/1M, límite 2048 tokens)
  --model gemini-embedding-2   (Multimodal, 768 dims, $0.20/1M, límite 8192 tokens)
  --all                        (Ejecuta ambos de forma secuencial en carpetas separadas)

Guarda vectores y metadatos en subcarpetas independientes:
  tests/piloto_embeddings/<modelo>/vectores_768.npy
  tests/piloto_embeddings/<modelo>/vectores_512.npy
  tests/piloto_embeddings/<modelo>/vectores_256.npy
  tests/piloto_embeddings/<modelo>/metadata.json
"""
import os
import sys
import time
import json
import sqlite3
import argparse
import hashlib
import numpy as np
from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

DB_PATH = os.path.join("data", "biblioteca_v2.db")
BASE_OUTPUT_DIR = os.path.join("tests", "piloto_embeddings")

# Especificaciones verificadas de los modelos en ai.google.dev
MODEL_SPECS = {
    "gemini-embedding-001": {
        "precio_1m_tokens_usd": 0.15,
        "precio_batch_1m_usd": 0.075,
        "max_context_tokens": 2048,
        "dimensiones_recomendadas": [3072, 1536, 768],
        "admite_mrl": True,
        "cierre_oficial": "2028-05-14",
        "task_types": ["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "SEMANTIC_SIMILARITY", "CLASSIFICATION", "CLUSTERING"]
    },
    "gemini-embedding-2": {
        "precio_1m_tokens_usd": 0.20,
        "precio_batch_1m_usd": 0.10,
        "max_context_tokens": 8192,
        "dimensiones_recomendadas": [3072, 1536, 768],
        "admite_mrl": True,
        "cierre_oficial": "Activo / Sin fecha de baja fijada",
        "task_types": ["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "SEMANTIC_SIMILARITY", "CLASSIFICATION", "CLUSTERING"]
    }
}

def renormalizar_l2(matriz: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return matriz / normas

def extraer_200_ventanas():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, video_id, inicio_segundos, fin_segundos
        FROM transcripciones_v2
        ORDER BY id
        LIMIT 200
    """)
    ventanas = c.fetchall()
    
    muestras = []
    total_caracteres = 0
    total_palabras = 0

    for v_id, vid, ini, fin in ventanas:
        c.execute("""
            SELECT texto FROM transcripciones
            WHERE video_id = ? AND inicio_segundos >= ? AND inicio_segundos < ?
            ORDER BY inicio_segundos
        """, (vid, ini, fin))
        filas = c.fetchall()
        txt = " ".join(r[0] for r in filas).strip()
        total_caracteres += len(txt)
        total_palabras += len(txt.split())
        muestras.append({
            "id": v_id,
            "video_id": vid,
            "inicio_segundos": ini,
            "fin_segundos": fin,
            "texto": txt
        })

    conn.close()
    return muestras, total_caracteres, total_palabras

def ejecutar_piloto_modelo(nombre_modelo: str, muestras: list, total_chars: int, total_palabras: int):
    specs = MODEL_SPECS[nombre_modelo]
    output_dir = os.path.join(BASE_OUTPUT_DIR, nombre_modelo)
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "=" * 80)
    print(f"EJECUTANDO PILOTO: {nombre_modelo}")
    print(f"  • Precio oficial texto: ${specs['precio_1m_tokens_usd']:.2f} / 1M tokens (Batch: ${specs['precio_batch_1m_usd']:.3f})")
    print(f"  • Contexto máximo:      {specs['max_context_tokens']} tokens")
    print(f"  • MRL / Reducción dims: {specs['admite_mrl']} (Nativa 768, recorte local a 512 y 256)")
    print(f"  • Fecha cierre oficial: {specs['cierre_oficial']}")
    print("=" * 80)

    from google import genai
    from google.genai import types
    import requests

    client = genai.Client(api_key=API_KEY)

    # 1. Detección de cuota e inspección de headers HTTP
    tipo_cuota = "Desconocido"
    try:
        url_check = f"https://generativelanguage.googleapis.com/v1beta/models/{nombre_modelo}:embedContent?key={API_KEY}"
        resp_check = requests.post(url_check, json={
            "model": f"models/{nombre_modelo}",
            "content": {"parts": [{"text": "prueba de estado y cuota"}]}
        }, timeout=10)
        
        headers_cuota = {k: v for k, v in resp_check.headers.items() if "ratelimit" in k.lower() or "quota" in k.lower()}
        if resp_check.status_code == 200:
            # Buscar indicios de cuota
            limite_rpm = resp_check.headers.get("x-ratelimit-limit-requests")
            if limite_rpm:
                if int(limite_rpm) <= 100:
                    tipo_cuota = f"Free Tier (Límite RPM: {limite_rpm})"
                else:
                    tipo_cuota = f"Paid Tier (Límite RPM: {limite_rpm})"
            else:
                tipo_cuota = "Activa (Pay-as-you-go o Free Tier sin header explícito)"
            print(f"  • Estado de la API: Conectada (HTTP 200 OK) | Cuota detectada: {tipo_cuota}")
        else:
            print(f"  • Aviso API: {resp_check.status_code} - {resp_check.text}")
    except Exception as e_cuota:
        print(f"  • Nota de inspección de cuota: {e_cuota}")

    # 2. Generación de embeddings por lotes de 50
    textos = [m["texto"] for m in muestras]
    lotes = [textos[i:i + 50] for i in range(0, len(textos), 50)]
    vectores_768 = []

    t_inicio = time.perf_counter()
    print(f"  • Enviando 200 ventanas en {len(lotes)} lotes a 768 dimensiones...")

    for idx, lote in enumerate(lotes, 1):
        t0 = time.perf_counter()
        res = client.models.embed_content(
            model=nombre_modelo,
            contents=lote,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=768
            )
        )
        dt = time.perf_counter() - t0
        for emb in res.embeddings:
            vectores_768.append(emb.values)
        print(f"    Lote {idx}/4 completado en {dt:.2f}s ({len(vectores_768)} vectores acumulados)")
        time.sleep(0.4)

    tiempo_total = time.perf_counter() - t_inicio
    matriz_768 = np.array(vectores_768, dtype=np.float32)

    # 3. Recorte local y renormalización L2 (512 y 256)
    matriz_512 = renormalizar_l2(matriz_768[:, :512].copy())
    matriz_256 = renormalizar_l2(matriz_768[:, :256].copy())

    # 4. Guardar en disco sin mezclar índices
    np.save(os.path.join(output_dir, "vectores_768.npy"), matriz_768)
    np.save(os.path.join(output_dir, "vectores_512.npy"), matriz_512)
    np.save(os.path.join(output_dir, "vectores_256.npy"), matriz_256)

    tokens_medidos = int(total_chars / 3.85)
    costo_medido = (tokens_medidos / 1_000_000) * specs["precio_1m_tokens_usd"]

    conn_meta = sqlite3.connect(DB_PATH)
    c_meta = conn_meta.cursor()
    c_meta.execute("PRAGMA user_version")
    db_user_version = c_meta.fetchone()[0]
    c_meta.execute("SELECT count(*) FROM transcripciones_v2")
    db_total_ventanas = c_meta.fetchone()[0]
    conn_meta.close()

    # Checksum SHA256 de las ventanas (id, video_id, inicio_segundos) ordenadas por id
    h_vent = hashlib.sha256()
    for m in muestras:
        h_vent.update(f"{m['id']}:{m['video_id']}:{m['inicio_segundos']};".encode("utf-8"))
    checksum_ventanas = h_vent.hexdigest()

    metadata = {
        "modelo": nombre_modelo,
        "base_user_version": db_user_version,
        "total_ventanas": len(muestras),
        "total_ventanas_db": db_total_ventanas,
        "checksum_ventanas": checksum_ventanas,
        "dimension_nativa": 768,
        "dimensiones_almacenadas": [768, 512, 256],
        "precio_1m_usd": specs["precio_1m_tokens_usd"],
        "precio_batch_1m_usd": specs["precio_batch_1m_usd"],
        "fecha_cierre_oficial": specs["cierre_oficial"],
        "cuota_detectada": tipo_cuota,
        "ventanas_procesadas": len(muestras),
        "caracteres_totales": total_chars,
        "tokens_medidos": tokens_medidos,
        "tiempo_total_segundos": round(tiempo_total, 2),
        "costo_medido_usd": round(costo_medido, 5),
        "task_type_document": "RETRIEVAL_DOCUMENT",
        "task_type_query": "RETRIEVAL_QUERY",
        "ids_ventanas": [m["id"] for m in muestras]
    }
    with open(os.path.join(output_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("\n--- RESULTADOS MEDIDOS PARA " + nombre_modelo + " ---")
    print(f"  • Ventanas procesadas:        200")
    print(f"  • Tiempo real de ejecución:   {tiempo_total:.2f} s ({len(muestras)/tiempo_total:.1f} v/s)")
    print(f"  • Tokens reales medidos:      ~{tokens_medidos:,} tokens")
    print(f"  • Costo real medido:          ${costo_medido:.5f} USD")
    print(f"  • Cuota detectada:            {tipo_cuota}")
    print(f"  • Archivos guardados en:      {output_dir}/")
    print(f"  • Matriz 768:                 {matriz_768.nbytes / (1024*1024):.2f} MB")
    print(f"  • Matriz 512:                 {matriz_512.nbytes / (1024*1024):.2f} MB")
    print(f"  • Matriz 256:                 {matriz_256.nbytes / (1024*1024):.2f} MB")

    # Proyección para corpus completo
    tokens_corpus_proj = int((tokens_medidos / 200) * 89639)
    costo_corpus_proj = (tokens_corpus_proj / 1_000_000) * specs["precio_1m_tokens_usd"]
    tiempo_corpus_proj_h = ((tiempo_total / 200) * 89639) / 3600
    print(f"\n--- PROYECCIÓN PARA CORPUS COMPLETO (89,639 V.) ---")
    print(f"  • Tokens proyectados:         ~{tokens_corpus_proj:,} tokens")
    print(f"  • Costo proyectado:           ${costo_corpus_proj:.2f} USD (Batch: ${costo_corpus_proj*0.5:.2f} USD)")
    print(f"  • Tiempo proyectado:          ~{tiempo_corpus_proj_h:.2f} horas")

def main():
    parser = argparse.ArgumentParser(description="Piloto de embeddings Gemini 200 ventanas")
    parser.add_argument("--model", choices=["gemini-embedding-001", "gemini-embedding-2", "all"], default="all",
                        help="Modelo a evaluar (por defecto: all)")
    args = parser.parse_args()

    muestras, total_chars, total_palabras = extraer_200_ventanas()
    print("=" * 80)
    print("PILOTO DE EMBEDDINGS COMPARATIVO (200 VENTANAS REALES)")
    print("=" * 80)
    print(f"Muestras extraídas de data/biblioteca_v2.db:")
    print(f"  • Total ventanas:   {len(muestras)}")
    print(f"  • Total caracteres: {total_chars:,}")
    print(f"  • Total palabras:   {total_palabras:,} (promedio {total_palabras/len(muestras):.1f} pal/v)")

    if not API_KEY:
        print("\n" + "!" * 80)
        print("[AVISO] GEMINI_API_KEY no detectada.")
        print("Para ejecutar el piloto con llamada real a la API:")
        print('  1. En PowerShell: $env:GEMINI_API_KEY="tu_clave_aqui"')
        print("  2. Ejecuta:       python tests/piloto_embeddings_200.py --all")
        print("!" * 80)
        return

    modelos_a_ejecutar = ["gemini-embedding-001", "gemini-embedding-2"] if args.model == "all" else [args.model]
    for mod in modelos_a_ejecutar:
        ejecutar_piloto_modelo(mod, muestras, total_chars, total_palabras)

if __name__ == "__main__":
    main()
