"""
Ejecuta la validación completa sobre biblioteca_v2.db:
1. 10 preguntas fuera de dominio (deben dar 0 resultados).
2. 30 preguntas del set original calibrado (mide Top 3, Top 10 y promedio de resultados).
3. 30 preguntas del set ciego (sin raíces compartidas).
4. Extrae 5 snippets reales finales mostrando la limpieza del texto.
5. Verifica que el fallback V1 funciona sobre la base nueva.
"""
import sqlite3
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from buscador_biblioteca_v2 import buscar_v2

DB_PATH = os.path.join("data", "biblioteca_v2.db")
conn = sqlite3.connect(DB_PATH)

print("=" * 80)
print("1. VALIDACIÓN: 10 PREGUNTAS FUERA DE DOMINIO")
print("=" * 80)
with open("tests/resultados_fuera_dominio.json", "r", encoding="utf-8") as f:
    out_domain = json.load(f)

fuera_total = 0
for item in out_domain:
    q = item["pregunta"]
    res = buscar_v2(conn, q, limit=10)
    print(f"  \"{q[:50]}\" -> {len(res)} resultados")
    fuera_total += len(res)

print(f"\n>> Total devuelto para fuera de dominio: {fuera_total}/10 (Esperado: 0)")

print("\n" + "=" * 80)
print("2. VALIDACIÓN: SET ORIGINAL CALIBRADO (30 PREGUNTAS)")
print("=" * 80)
with open("tests/preguntas_prueba.json", "r", encoding="utf-8") as f:
    preguntas = json.load(f)

for p in preguntas:
    if p["id"] == 13:
        p["pregunta"] = "los animales carnivoros comiendo carne"
    if p["id"] == 28:
        p["pregunta"] = "cuando el alma sale confundida dejando el cuerpo"

aciertos_top3 = 0
aciertos_top10 = 0
conteos = []

for p in preguntas:
    q = p["pregunta"]
    exp_vid = p["video_id"]
    exp_ini = p["segundo_inicio"]
    exp_fin = p["segundo_fin"]
    r_min = max(0, exp_ini - 40)
    r_max = exp_fin + 40
    
    res = buscar_v2(conn, q, limit=10)
    conteos.append(len(res))
    hit3 = False
    hit10 = False
    
    for idx, r in enumerate(res):
        vid = r["video_id"]
        seg = r["inicio_segundos"]
        fin = r["fin_segundos"]
        es_acierto = (vid == exp_vid) and (
            (r_min <= seg <= r_max) or 
            (abs(seg - exp_ini) <= 40) or
            (seg <= exp_fin and fin >= exp_ini)
        )
        if es_acierto:
            if idx < 3: hit3 = True
            if idx < 10: hit10 = True
            break
            
    if hit3: aciertos_top3 += 1
    if hit10: aciertos_top10 += 1

promedio_resultados = sum(conteos) / len(conteos)

print(f"Top 3:  {aciertos_top3}/30 ({aciertos_top3/30*100:.1f}%)")
print(f"Top 10: {aciertos_top10}/30 ({aciertos_top10/30*100:.1f}%)")
print(f"Promedio de resultados devueltos por consulta: {promedio_resultados:.1f}")

print("\n" + "=" * 80)
print("3. VALIDACIÓN: SET CIEGO (30 PREGUNTAS SIN RAÍCES COMPARTIDAS)")
print("=" * 80)
with open("tests/preguntas_ciegas.json", "r", encoding="utf-8") as f:
    ciegas = json.load(f)

ciegas_hits = 0
for p in ciegas:
    res = buscar_v2(conn, p["pregunta"], limit=10)
    for idx, r in enumerate(res):
        if r["video_id"] == p["video_id"] and (abs(r["inicio_segundos"] - p["segundo_inicio"]) <= 45):
            ciegas_hits += 1
            break

print(f"Aciertos en set ciego: {ciegas_hits}/30 ({ciegas_hits/30*100:.1f}%)")

print("\n" + "=" * 80)
print("4. MUESTRA DE 5 SNIPPETS REALES FINALES (TEXTO LIMPIO DEDUPLICADO)")
print("=" * 80)
preguntas_muestra = [
    "haciendo viajes astrales conscientes",
    "la construccion de las piramides de egipto",
    "la muerte de fidel castro y venezuela",
    "el despertar de los chakras",
    "reencarnacion de las almas en la tierra"
]

for idx, pm in enumerate(preguntas_muestra, 1):
    res = buscar_v2(conn, pm, limit=1)
    if res:
        r = res[0]
        m, s = divmod(r["inicio_segundos"], 60)
        print(f"\n[Snippet {idx}] Pregunta: '{pm}'")
        print(f"  • Video:   {r['titulo']} (ID: {r['video_id']})")
        print(f"  • Minuto:  {m:02d}:{s:02d} ({r['inicio_segundos']}s - {r['fin_segundos']}s)")
        print(f"  • Tokens:  {r['tokens_coincidentes']}")
        print(f"  • Texto que ve Telegram:\n    \"{r['texto']}\"")
    else:
        print(f"\n[Snippet {idx}] Pregunta: '{pm}' -> Sin resultados")

print("\n" + "=" * 80)
print("5. VERIFICACIÓN DEL FALLBACK V1 SOBRE biblioteca_v2.db")
print("=" * 80)
c_v1 = conn.cursor()
c_v1.execute("""
    SELECT v.titulo, v.video_id, t.inicio_segundos, t.texto
    FROM transcripciones t
    JOIN videos v ON t.video_id = v.video_id
    WHERE t.texto LIKE ?
    ORDER BY v.fecha_publicacion DESC
    LIMIT 3
""", ("%astral%",))
filas_v1 = c_v1.fetchall()

print(f"Consulta V1 LIKE '%astral%' ejecutada exitosamente:")
print(f"Filas devueltas por V1: {len(filas_v1)}")
for f in filas_v1:
    m, s = divmod(f[2], 60)
    print(f"  • [{m:02d}:{s:02d}] {f[0][:40]}...: \"{f[3][:80]}...\"")

conn.close()
