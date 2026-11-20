import sqlite3
import json
import time
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from buscador_biblioteca_v2 import buscar_v2

DB_PATH = os.path.join("data", "biblioteca_v2.db")

with open("tests/preguntas_prueba.json", "r", encoding="utf-8") as f:
    set_calibradas = json.load(f)

with open("tests/preguntas_ciegas.json", "r", encoding="utf-8") as f:
    set_ciegas = json.load(f)

todas_las_60 = [p["pregunta"] for p in set_calibradas] + [p["pregunta"] for p in set_ciegas]

conn = sqlite3.connect(DB_PATH)

latencias_ms = []

# Warm-up (1 consulta)
_ = buscar_v2(conn, "alaniso guardianes", limit=5)

for p in todas_las_60:
    t0 = time.perf_counter()
    _ = buscar_v2(conn, p, limit=10, max_por_video=2)
    t1 = time.perf_counter()
    latencias_ms.append((t1 - t0) * 1000.0)

conn.close()

latencias_ms.sort()
total = len(latencias_ms)
promedio = sum(latencias_ms) / total
min_lat = latencias_ms[0]
max_lat = latencias_ms[-1]
p50 = latencias_ms[int(total * 0.50)]
p90 = latencias_ms[int(total * 0.90)]
p95 = latencias_ms[int(total * 0.95)]

print("=" * 80)
print(f"MEDICIÓN DE LATENCIA DEL MOTOR V2 SOBRE {total} CONSULTAS REALES")
print("=" * 80)
print(f"  • Latencia Promedio: {promedio:.2f} ms")
print(f"  • Mediana (p50):     {p50:.2f} ms")
print(f"  • Percentil 90 (p90): {p90:.2f} ms")
print(f"  • Percentil 95 (p95): {p95:.2f} ms")
print(f"  • Mínima:            {min_lat:.2f} ms")
print(f"  • Máxima:            {max_lat:.2f} ms")
print("=" * 80)

with open("tests/resultados_latencia.json", "w", encoding="utf-8") as f:
    json.dump({
        "total_consultas": total,
        "promedio_ms": promedio,
        "p50_ms": p50,
        "p90_ms": p90,
        "p95_ms": p95,
        "min_ms": min_lat,
        "max_ms": max_lat,
        "todas_latencias_ms": latencias_ms
    }, f, indent=2)
