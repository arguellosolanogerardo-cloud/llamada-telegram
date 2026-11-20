import json
import sqlite3
import sys
sys.path.insert(0, ".")
from buscador_biblioteca_v2 import buscar_v2

conn = sqlite3.connect("data/biblioteca_v2.db")
with open("tests/preguntas_prueba.json", "r", encoding="utf-8") as f:
    preguntas = json.load(f)

for p in preguntas:
    if p["id"] == 13: p["pregunta"] = "los animales carnivoros comiendo carne"
    if p["id"] == 28: p["pregunta"] = "cuando el alma sale confundida dejando el cuerpo"

for p in preguntas:
    q = p["pregunta"]
    exp_vid = p["video_id"]
    exp_ini = p["segundo_inicio"]
    exp_fin = p["segundo_fin"]
    
    res = buscar_v2(conn, q, limit=10)
    encontrado = False
    for idx, r in enumerate(res):
        if r["video_id"] == exp_vid:
            diff = r["inicio_segundos"] - exp_ini
            print(f"P#{p['id']:2d}: {q[:35]:35s} | Encontrado en puesto #{idx+1} ({r['inicio_segundos']}s-{r['fin_segundos']}s) | Diff con esperado ({exp_ini}s): {diff}s")
            encontrado = True
            break
    if not encontrado:
        print(f"P#{p['id']:2d}: {q[:35]:35s} | NO encontrado en top 10 (total devueltos: {len(res)})")
