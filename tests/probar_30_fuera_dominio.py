import json
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from buscador_biblioteca_v2 import buscar_v2

conn = sqlite3.connect("data/biblioteca_v2.db")
with open("tests/preguntas_fuera_dominio.json", "r", encoding="utf-8") as f:
    preguntas = json.load(f)

total_devueltos = 0
for p in preguntas:
    q = p["pregunta"]
    res = buscar_v2(conn, q, limit=10)
    total_devueltos += len(res)
    if len(res) > 0:
        print(f"Aviso en #{p['id']} ({p['categoria']}): {q} -> {len(res)} res")

print(f"Total devueltos en las 30 preguntas fuera de dominio: {total_devueltos} (Esperado: 0)")
if total_devueltos == 0:
    print(">> FILTRADO 100% PERFECTO: Ninguna de las 30 preguntas generó falsos positivos.")
conn.close()
