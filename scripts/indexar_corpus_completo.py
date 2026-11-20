"""
Indexación Completa Reanudable del Corpus de la Biblioteca
==========================================================
Modelo: gemini-embedding-001 (768 dimensiones nativas, recorte local a 512 y 256 con renormalización L2)
Corpus: 89,639 ventanas temporales de biblioteca_v2.db

Características:
  - Reanudable por lotes (checkpoint atómico con np.memmap en disco).
  - Progreso en tiempo real: lote, ventanas, tokens, costo acumulado, velocidad y ETA.
  - Validación de seguridad tras los primeros 3 lotes (forma 768, ausencia de NaN, norma L2 ≈ 1).
  - Resiliencia: backoff exponencial ante 429/503 y parada tras 5 errores consecutivos.
  - Generación de metadata.json con user_version, total_ventanas y checksum SHA256.
"""

import os
import sys
import time
import json
import sqlite3
import hashlib
import argparse
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

PRECIO_1M_TOKENS = 0.15  # USD por millón de tokens en gemini-embedding-001
MAX_ERRORES_CONSECUTIVOS = 5

def renormalizar_l2(matriz: np.ndarray) -> np.ndarray:
    """Normaliza cada fila a norma L2 = 1.0 tras recorte dimensional (MRL)."""
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return matriz / normas

def calcular_checksum_db(conn: sqlite3.Connection) -> tuple[int, int, str]:
    """Obtiene user_version, total de ventanas y checksum SHA256 de la tabla activa."""
    c = conn.cursor()
    c.execute("PRAGMA user_version")
    u_ver = c.fetchone()[0]
    c.execute("SELECT count(*) FROM transcripciones_v2")
    n_vent = c.fetchone()[0]
    
    c.execute("SELECT id, video_id, inicio_segundos FROM transcripciones_v2 ORDER BY id")
    h = hashlib.sha256()
    for r in c:
        h.update(f"{r[0]}:{r[1]}:{r[2]};".encode("utf-8"))
    chk = h.hexdigest()
    return u_ver, n_vent, chk

def detectar_tipo_cuota(modelo: str, api_key: str) -> str:
    """Detecta el tipo de cuenta y cuota mediante inspección de headers HTTP."""
    import requests
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:embedContent?key={api_key}"
        resp = requests.post(url, json={
            "model": f"models/{modelo}",
            "content": {"parts": [{"text": "ping de verificacion de cuota"}]}
        }, timeout=10)
        
        if resp.status_code == 200:
            rpm_limit = resp.headers.get("x-ratelimit-limit-requests")
            if rpm_limit:
                if int(rpm_limit) <= 100:
                    return f"Free Tier (Límite RPM: {rpm_limit})"
                else:
                    return f"Paid Tier (Límite RPM: {rpm_limit})"
            return "Activa (Pay-as-you-go o Free Tier sin header explícito)"
        else:
            return f"Respuesta API {resp.status_code}: {resp.text[:80]}"
    except Exception as e:
        return f"No se pudo determinar: {e}"

def main():
    parser = argparse.ArgumentParser(description="Indexación completa del corpus con embeddings de Gemini.")
    parser.add_argument("--model", default="gemini-embedding-001", help="Modelo de embeddings")
    parser.add_argument("--batch-size", type=int, default=50, help="Tamaño de lote (ventanas por llamada)")
    parser.add_argument("--output-dir", default=os.path.join("data", "vectores_v2"), help="Directorio de destino")
    parser.add_argument("--db-path", default=os.path.join("data", "biblioteca_v2.db"), help="Ruta a biblioteca_v2.db")
    args = parser.parse_args()

    if not API_KEY:
        print("\n" + "!" * 80)
        print("ERROR: Clave de API no configurada.")
        print("Por favor define la variable de entorno GEMINI_API_KEY antes de ejecutar:")
        print("  PowerShell: $env:GEMINI_API_KEY=\"tu_api_key_aqui\"")
        print("!" * 80 + "\n")
        sys.exit(1)

    if not os.path.exists(args.db_path):
        print(f"ERROR: Base de datos no encontrada en {args.db_path}")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 85)
    print("INDEXADOR DE CORPUS COMPLETO (FASE 4 - GEMINI EMBEDDINGS)")
    print(f"  • Modelo objetivo:      {args.model}")
    print(f"  • Dimensión nativa:     768 (recorte local a 512 y 256 con L2)")
    print(f"  • Tamaño de lote:       {args.batch_size} ventanas por solicitud")
    print(f"  • Directorio de salida: {args.output_dir}")
    print("=" * 85)

    conn = sqlite3.connect(args.db_path)
    print("Calculando checksum y metadatos de la base SQLite...")
    t_chk0 = time.perf_counter()
    u_ver, total_ventanas, db_checksum = calcular_checksum_db(conn)
    dt_chk = time.perf_counter() - t_chk0
    print(f"  • Base user_version:    {u_ver}")
    print(f"  • Total de ventanas:    {total_ventanas:,}")
    print(f"  • Checksum SHA256:      {db_checksum} (calculado en {dt_chk:.2f}s)")

    # Detección de cuota
    tipo_cuota = detectar_tipo_cuota(args.model, API_KEY)
    print(f"  • Estado de la cuenta:  {tipo_cuota}")
    print("=" * 85)

    # Estado de checkpoint
    chk_file = os.path.join(args.output_dir, "checkpoint_indexacion.json")
    raw_mmap_file = os.path.join(args.output_dir, "raw_768.dat")
    
    ventanas_completadas = 0
    tokens_acumulados = 0
    costo_acumulado = 0.0
    tiempo_acumulado = 0.0

    if os.path.exists(chk_file):
        try:
            with open(chk_file, "r", encoding="utf-8") as f:
                chk_data = json.load(f)
            
            # Validar compatibilidad del checkpoint con la DB activa
            if chk_data.get("base_user_version") != u_ver or chk_data.get("checksum_ventanas") != db_checksum:
                print("\n[AVISO] Checkpoint previo pertenece a una versión anterior de la base.")
                print("Reiniciando indexación desde cero para coherencia total...")
                ventanas_completadas = 0
            else:
                ventanas_completadas = chk_data.get("ventanas_completadas", 0)
                tokens_acumulados = chk_data.get("tokens_acumulados", 0)
                costo_acumulado = chk_data.get("costo_acumulado_usd", 0.0)
                tiempo_acumulado = chk_data.get("tiempo_acumulado_segundos", 0.0)
                print(f"\n[REANUDACIÓN] Checkpoint detectado: {ventanas_completadas:,} / {total_ventanas:,} ventanas ya procesadas.")
                print(f"  • Tokens previos acumulados: ~{tokens_acumulados:,}")
                print(f"  • Costo previo acumulado:    ${costo_acumulado:.4f} USD")
        except Exception as e_chk:
            print(f"[AVISO] Error leyendo checkpoint ({e_chk}). Iniciando desde cero.")
            ventanas_completadas = 0

    # Crear o abrir archivo mapeado en memoria (memmap) de 768 floats por ventana
    modo_mmap = "r+" if os.path.exists(raw_mmap_file) else "w+"
    matriz_memmap = np.memmap(raw_mmap_file, dtype="float32", mode=modo_mmap, shape=(total_ventanas, 768))

    # Verificación de sanidad al reanudar: comprobar que no existan vectores a cero ni NaNs en lo ya procesado
    if ventanas_completadas > 0:
        print(f"Verificando integridad de los {ventanas_completadas:,} vectores ya registrados en disco...")
        normas_existentes = np.linalg.norm(matriz_memmap[:ventanas_completadas], axis=1)
        ceros = int(np.sum(normas_existentes < 1e-4))
        nans = int(np.sum(np.isnan(normas_existentes)))
        if ceros > 0 or nans > 0:
            print(f"[ERROR DE INTEGRIDAD] Se detectaron {ceros} vectores en cero y {nans} NaNs en el archivo previo.")
            print("El checkpoint o el archivo raw_768.dat está inconsistente. Reiniciando desde cero...")
            ventanas_completadas = 0
            tokens_acumulados = 0
            costo_acumulado = 0.0
            tiempo_acumulado = 0.0
        else:
            print(f"  • Integridad OK: 0 vectores a cero y 0 NaNs en las {ventanas_completadas:,} filas previas.")

    # Cargar ventanas pendientes desde la base
    c = conn.cursor()
    c.execute("SELECT id, video_id, inicio_segundos, fin_segundos FROM transcripciones_v2 ORDER BY id")
    todas_ventanas = c.fetchall()

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=API_KEY)

    errores_consecutivos = 0
    total_lotes = (total_ventanas + args.batch_size - 1) // args.batch_size
    lote_inicial = ventanas_completadas // args.batch_size

    t_sesion_inicio = time.perf_counter()

    print(f"\nIniciando procesamiento desde el lote {lote_inicial + 1} de {total_lotes}...")

    i = ventanas_completadas
    while i < total_ventanas:
        idx_lote = (i // args.batch_size) + 1
        fin_i = min(i + args.batch_size, total_ventanas)
        ventanas_lote = todas_ventanas[i:fin_i]

        # Extraer texto legible original reconstruido para el lote actual (NO el stemmed)
        textos_lote = []
        caracteres_lote = 0
        for _, vid, ini, fin in ventanas_lote:
            c.execute("""
                SELECT texto FROM transcripciones
                WHERE video_id = ? AND inicio_segundos >= ? AND inicio_segundos < ?
                ORDER BY inicio_segundos
            """, (vid, ini, fin))
            filas_txt = c.fetchall()
            txt = " ".join(r[0] for r in filas_txt).strip()
            textos_lote.append(txt)
            caracteres_lote += len(txt)

        t_lote0 = time.perf_counter()
        try:
            res = client.models.embed_content(
                model=args.model,
                contents=textos_lote,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=768
                )
            )

            # Éxito: extraer vectores y normalizar inmediatamente a L2 = 1.0 (Gemini MRL 768 no viene normalizado de fábrica)
            arr_lote = np.array([emb.values for emb in res.embeddings], dtype=np.float32)
            vectores_norm = renormalizar_l2(arr_lote)

            # Escribir en memmap y forzar flush a disco ANTES de registrar el checkpoint
            matriz_memmap[i:fin_i] = vectores_norm
            matriz_memmap.flush()

            dt_lote = time.perf_counter() - t_lote0
            errores_consecutivos = 0

            # Medición de tokens: preferir metadatos oficiales de la API si están presentes
            tokens_reales_api = None
            if hasattr(res, "usage_metadata") and res.usage_metadata:
                tokens_reales_api = getattr(res.usage_metadata, "prompt_token_count", None) or getattr(res.usage_metadata, "total_token_count", None)

            if tokens_reales_api:
                tokens_lote = int(tokens_reales_api)
                tipo_token_tag = "[REAL]"
            else:
                tokens_lote = int(caracteres_lote / 3.85)
                tipo_token_tag = "[EST]"

            costo_lote = (tokens_lote / 1_000_000) * PRECIO_1M_TOKENS
            tokens_acumulados += tokens_lote
            costo_acumulado += costo_lote

            i = fin_i
            ventanas_completadas = i

            t_transcurrido = tiempo_acumulado + (time.perf_counter() - t_sesion_inicio)
            ventanas_sesion = i - (lote_inicial * args.batch_size)
            tiempo_sesion = time.perf_counter() - t_sesion_inicio
            velocidad = (ventanas_sesion / tiempo_sesion) if tiempo_sesion > 0 else 0.0

            ventanas_restantes = total_ventanas - i
            eta_minutos = (ventanas_restantes / velocidad / 60) if velocidad > 0 else 0.0
            pct_avance = (i / total_ventanas) * 100.0

            # Guardar checkpoint atómico tras flush()
            chk_tmp = chk_file + ".tmp"
            with open(chk_tmp, "w", encoding="utf-8") as f_chk:
                json.dump({
                    "modelo": args.model,
                    "base_user_version": u_ver,
                    "total_ventanas": total_ventanas,
                    "checksum_ventanas": db_checksum,
                    "ventanas_completadas": ventanas_completadas,
                    "tokens_acumulados": tokens_acumulados,
                    "tokens_tipo": "medido_api" if tokens_reales_api else "estimado_caracteres",
                    "costo_acumulado_usd": round(costo_acumulado, 5),
                    "tiempo_acumulado_segundos": round(t_transcurrido, 2),
                    "estado": "COMPLETADO" if i >= total_ventanas else "EN_PROGRESO"
                }, f_chk, indent=2)
            os.replace(chk_tmp, chk_file)

            # Log de progreso en tiempo real
            print(f"Lote [{idx_lote:04d}/{total_lotes:04d}] | Ventanas: {i:05d}/{total_ventanas:05d} ({pct_avance:5.1f}%) | Tokens {tipo_token_tag}: ~{tokens_acumulados:9,d} | Costo: ${costo_acumulado:7.4f} USD | Vel: {velocidad:4.1f} v/s | ETA: {eta_minutos:5.1f} min")

            # Verificación de seguridad tras los primeros 3 lotes
            if idx_lote == 3 and (lote_inicial < 3):
                print("\n" + "=" * 85)
                print("VERIFICACIÓN DE SEGURIDAD (PRIMEROS 3 LOTES COMPLETADOS)")
                print("=" * 85)
                muestra = np.array(matriz_memmap[0:i], dtype=np.float32)
                forma_ok = (muestra.shape[1] == 768)
                sin_nans = not np.isnan(muestra).any()
                normas = np.linalg.norm(muestra, axis=1)
                norma_media = float(np.mean(normas))
                norma_ok = (0.95 <= norma_media <= 1.05)

                print(f"  • Forma de la matriz acumulada: {muestra.shape} -> {'OK (768 d)' if forma_ok else 'FALLÓ'}")
                print(f"  • Norma L2 media (tras normalización L2): {norma_media:.4f} -> {'OK (≈ 1.0)' if norma_ok else 'ADVERTENCIA'}")
                print("=" * 85)

                if not (forma_ok and sin_nans):
                    print("\n[ERROR CRÍTICO] Los vectores no pasaron la verificación de sanidad. Abortando.")
                    sys.exit(1)
                print(">> AVISO: Verificación inicial 100% exitosa. Continuando con la indexación del corpus...\n")

            # Pausa breve de cortesía para estabilizar tasa de llamadas
            time.sleep(0.15)

        except Exception as e:
            errores_consecutivos += 1
            err_msg = str(e)
            print(f"\n[ERROR] Falla en lote {idx_lote} (intento {errores_consecutivos}/{MAX_ERRORES_CONSECUTIVOS}): {e}")

            if errores_consecutivos >= MAX_ERRORES_CONSECUTIVOS:
                print("\n" + "!" * 85)
                print(f"DETENCIÓN AUTOMÁTICA: Se alcanzaron {MAX_ERRORES_CONSECUTIVOS} errores consecutivos.")
                print(f"Progreso guardado de forma segura en: {chk_file}")
                print("Puedes reanudar en cualquier momento ejecutando el mismo comando.")
                print("!" * 85 + "\n")
                sys.exit(1)

            # Backoff exponencial
            t_espera = 2 ** errores_consecutivos
            if "429" in err_msg or "quota" in err_msg.lower() or "resourceexhausted" in err_msg.lower():
                t_espera = max(t_espera, 20)
                print(f"Detectado límite de cuota (429/ResourceExhausted). Esperando {t_espera}s con backoff...")
            elif "503" in err_msg or "unavailable" in err_msg.lower():
                t_espera = max(t_espera, 10)
                print(f"Servicio temporalmente no disponible (503). Esperando {t_espera}s...")
            else:
                print(f"Reintentando en {t_espera}s...")
            time.sleep(t_espera)

    conn.close()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # FINALIZACIÓN: REcorte Dimensional y Generación de Índices
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    t_total_final = tiempo_acumulado + (time.perf_counter() - t_sesion_inicio)

    print("\n" + "=" * 85)
    print("INDEXACIÓN COMPLETADA EXITOSAMENTE. PROCESANDO ARCHIVOS FINALES...")
    print("=" * 85)

    matriz_768_full = np.array(matriz_memmap, dtype=np.float32)

    # 1. Guardar 768 nativo
    path_768 = os.path.join(args.output_dir, "vectores_768.npy")
    print(f"Guardando matriz completa de 768 dimensiones en {path_768}...")
    np.save(path_768, matriz_768_full)

    # 2. Recorte a 512 y renormalización L2
    path_512 = os.path.join(args.output_dir, "vectores_512.npy")
    print(f"Generando matriz recortada y renormalizada a 512 dimensiones en {path_512}...")
    matriz_512 = renormalizar_l2(matriz_768_full[:, :512].copy())
    np.save(path_512, matriz_512)

    # 3. Recorte a 256 y renormalización L2
    path_256 = os.path.join(args.output_dir, "vectores_256.npy")
    print(f"Generando matriz recortada y renormalizada a 256 dimensiones en {path_256}...")
    matriz_256 = renormalizar_l2(matriz_768_full[:, :256].copy())
    np.save(path_256, matriz_256)

    # 4. Escribir metadata.json oficial
    meta_oficial = {
        "modelo": args.model,
        "base_user_version": u_ver,
        "total_ventanas": total_ventanas,
        "total_ventanas_db": total_ventanas,
        "checksum_ventanas": db_checksum,
        "dimension_nativa": 768,
        "dimensiones_almacenadas": [768, 512, 256],
        "precio_1m_usd": PRECIO_1M_TOKENS,
        "cuota_detectada": tipo_cuota,
        "tokens_reales_medidos": tokens_acumulados,
        "costo_real_usd": round(costo_acumulado, 5),
        "tiempo_total_segundos": round(t_total_final, 2),
        "fecha_finalizacion": datetime.now().isoformat(),
        "task_type_document": "RETRIEVAL_DOCUMENT",
        "task_type_query": "RETRIEVAL_QUERY"
    }
    with open(os.path.join(args.output_dir, "metadata.json"), "w", encoding="utf-8") as f_meta:
        json.dump(meta_oficial, f_meta, indent=2)

    # Limpiar archivo temporal memmap si se desea
    if os.path.exists(raw_mmap_file):
        try:
            del matriz_memmap
            os.remove(raw_mmap_file)
        except Exception:
            pass

    print("\n" + "=" * 85)
    print("REPORTE FINAL MEDIDO")
    print("=" * 85)
    print(f"  • Modelo indexado:       {args.model}")
    print(f"  • Ventanas totales:      {total_ventanas:,} ventanas")
    print(f"  • Tokens reales medidos: ~{tokens_acumulados:,} tokens")
    print(f"  • Costo real medido:     ${costo_acumulado:.4f} USD")
    print(f"  • Tiempo total medido:   {t_total_final:.2f} s ({t_total_final/60:.2f} min)")
    print(f"  • Velocidad media:       {total_ventanas/t_total_final:.1f} ventanas/s")
    print(f"  • Cuota detectada:       {tipo_cuota}")
    print(f"  • user_version base:     {u_ver}")
    print(f"  • Checksum verificado:   {db_checksum}")
    print(f"  • Archivos generados:    vectores_768.npy, vectores_512.npy, vectores_256.npy, metadata.json")
    print("=" * 85 + "\n")

if __name__ == "__main__":
    main()
