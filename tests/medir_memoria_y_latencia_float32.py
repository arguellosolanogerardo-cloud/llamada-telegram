"""
Medición de latencia y memoria RAM para matrices de embeddings en float32:
- Evalúa dimensiones 256, 512 y 768 sobre el total real de 89,639 ventanas.
- Mide memoria RSS en megabytes y porcentaje del límite de 512 MB de Render.
- Mide latencia de producto punto en float32 (matriz completa vs escaneo por bloques de 10,000).
"""
import os
import sys
import time
import psutil
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOTAL_VENTANAS = 89639
RENDER_RAM_LIMIT_MB = 512.0

proc = psutil.Process()

print("=" * 80)
print("BENCHMARK DE MEMORIA Y LATENCIA EN FLOAT32 (89,639 VECTORES)")
print(f"Límite de memoria en Render: {RENDER_RAM_LIMIT_MB} MB")
print("=" * 80)

# Memoria base del proceso Python
ram_base = proc.memory_info().rss / (1024 * 1024)
print(f"Memoria RAM base del proceso: {ram_base:.2f} MB\n")

resultados = {}

for dim in [256, 512, 768]:
    # 1. Medir tamaño en bytes exacto
    bytes_teoricos = TOTAL_VENTANAS * dim * 4 # 4 bytes por float32
    mb_matriz = bytes_teoricos / (1024 * 1024)
    
    # 2. Generar matriz float32 en memoria y medir RAM real consumida
    matriz = np.random.randn(TOTAL_VENTANAS, dim).astype(np.float32)
    # Normalizar L2 para simular vectores unitarios reales
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    matriz /= normas
    
    ram_con_matriz = proc.memory_info().rss / (1024 * 1024)
    ram_usada_matriz = ram_con_matriz - ram_base
    pct_ram_render = (ram_con_matriz / RENDER_RAM_LIMIT_MB) * 100
    
    # Vector de consulta
    q = np.random.randn(dim).astype(np.float32)
    q /= np.linalg.norm(q)
    
    # 3. Medir latencia con matriz completa en memoria
    # Calentamiento
    _ = np.dot(matriz[:100], q)
    
    t0 = time.perf_counter()
    scores = np.dot(matriz, q)
    top10_idx = np.argpartition(scores, -10)[-10:]
    top10_sorted = top10_idx[np.argsort(-scores[top10_idx])]
    latencia_completa_ms = (time.perf_counter() - t0) * 1000
    
    # 4. Medir latencia con escaneo por bloques de 10,000 (para bajo consumo)
    chunk_size = 10000
    t0_chunk = time.perf_counter()
    mejores_globales = []
    for i in range(0, TOTAL_VENTANAS, chunk_size):
        sub_mat = matriz[i:i + chunk_size]
        sub_scores = np.dot(sub_mat, q)
        k = min(10, len(sub_scores))
        part = np.argpartition(sub_scores, -k)[-k:]
        for idx in part:
            mejores_globales.append((sub_scores[idx], i + idx))
    mejores_globales.sort(key=lambda x: x[0], reverse=True)
    top10_chunk = mejores_globales[:10]
    latencia_chunk_ms = (time.perf_counter() - t0_chunk) * 1000

    del matriz
    del scores

    resultados[dim] = {
        "mb_matriz": mb_matriz,
        "ram_total_proceso_mb": ram_con_matriz,
        "pct_render": pct_ram_render,
        "latencia_full_ms": latencia_completa_ms,
        "latencia_chunk_ms": latencia_chunk_ms
    }
    
    print(f"--- Dimensión {dim} (float32) ---")
    print(f"  • Peso físico matriz:        {mb_matriz:6.2f} MB")
    print(f"  • RAM total bot + matriz:    {ram_con_matriz:6.2f} MB ({pct_ram_render:4.1f}% de 512 MB)")
    print(f"  • Margen libre en Render:    {RENDER_RAM_LIMIT_MB - ram_con_matriz:6.2f} MB")
    print(f"  • Latencia scan completo:    {latencia_completa_ms:6.2f} ms")
    print(f"  • Latencia scan por bloques: {latencia_chunk_ms:6.2f} ms\n")

print("=" * 80)
print("RESUMEN COMPARATIVO:")
print(f"{'Dimensión':<12} | {'Peso Matriz':<14} | {'RAM Total':<12} | {'% Render':<10} | {'Latencia Full':<15} | {'Latencia Bloques'}")
print("-" * 80)
for dim, d in resultados.items():
    print(f"{dim:<12} | {d['mb_matriz']:6.2f} MB      | {d['ram_total_proceso_mb']:6.2f} MB   | {d['pct_render']:5.1f}%    | {d['latencia_full_ms']:6.2f} ms        | {d['latencia_chunk_ms']:6.2f} ms")
print("=" * 80)
