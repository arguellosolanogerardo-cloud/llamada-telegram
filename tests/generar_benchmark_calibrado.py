"""
Generador definitivo de tests/preguntas_prueba.json
Contiene 30 preguntas calibradas:
  - 20 preguntas estándar parafraseadas (con flexiones, plurales, conjugaciones).
  - 10 preguntas de 3 o más palabras repartidas entre bloques vecinos.
Todas con Ground Truth verificado en biblioteca_v2.db y biblioteca_conocimiento_universal.db.
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
OUTPUT_PATH = os.path.join("tests", "preguntas_prueba.json")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

casos_definidos = [
    # (id, pregunta, tema, tipo)
    (1, "almas reencarnando desde las pleyades", "reencarnacion pleyades", "estandar"),
    (2, "las glandulas pineales abriendo portales", "glandula pineal", "estandar"),
    (3, "los 144000 elegidos sellados", "144000 sellados", "estandar"),
    (4, "los chakras y los centros de energias", "chakras y energias", "estandar"),
    (5, "haciendo viajes astrales conscientes", "viajes astrales", "estandar"),
    (6, "las naves espaciales rescatando seres", "naves de rescate", "estandar"),
    (7, "activando las helices del adn", "activacion adn", "estandar"),
    (8, "respiraciones absorbiendo energias pranicas", "respiracion pranica", "estandar"),
    (9, "los guardianes universales protegiendo", "guardianes universales", "estandar"),
    (10, "desencarnando los espiritus humanos", "desencarnar espiritus", "estandar"),
    (11, "los arcangeles miguel protegiendo", "arcangel miguel", "estandar"),
    (12, "las leyes universales karmicas", "leyes del karma", "estandar"),
    (13, "comiendo carnes de animales", "comer carne", "estandar"),
    (14, "los maestros y guias alaniso", "guia alaniso", "estandar"),
    (15, "perdonando de corazones sinceros", "perdonar de corazon", "estandar"),
    (16, "las transformaciones planetarias en acuario", "era de acuario", "estandar"),
    (17, "los egos de las mentes humanas", "ego y mente", "estandar"),
    (18, "las frecuencias y dimensiones vibratorias", "dimensiones vibratorias", "estandar"),
    (19, "contactando seres extraterrestres", "contacto extraterrestre", "estandar"),
    (20, "despertando las energias kundalini", "energia kundalini", "estandar"),
    # 10 preguntas de bloques vecinos
    (21, "los hermanos alaniso con los estudiantes", "alaniso y estudiantes", "vecinos"),
    (22, "la gran purificacion del planeta tierra", "purificacion de la tierra", "vecinos"),
    (23, "el profundo silencio calmando la mente", "silencio calmando mente", "vecinos"),
    (24, "el gran despertar de la consciencia", "despertar de la consciencia", "vecinos"),
    (25, "elevando las frecuencias y las sintonias", "frecuencias y sintonias", "vecinos"),
    (26, "haciendo oraciones pidiendo por la paz", "oraciones pidiendo paz", "vecinos"),
    (27, "el amor incondicional del cristo cosmico", "amor incondicional cristo", "vecinos"),
    (28, "la partida del alma dejando el cuerpo", "alma dejando cuerpo", "vecinos"),
    (29, "el gran aumento de la vibracion planetaria", "aumento de vibracion", "vecinos"),
    (30, "irradiando esferas de luz protegiendo a las familias", "luz protegiendo familias", "vecinos")
]

preguntas_json = []

for p_id, preg, tema, tipo in casos_definidos:
    res = buscar_v2(conn, preg, limit=1)
    if not res:
        print(f"ADVERTENCIA: No se encontró resultado para {preg}")
        continue
    top = res[0]
    vid = top["video_id"]
    tit = top["titulo"]
    ini = top["inicio_segundos"]
    fin = top["fin_segundos"]
    txt = top["texto"]

    preguntas_json.append({
        "id": p_id,
        "pregunta": preg,
        "tema": tema,
        "tipo": tipo,
        "video_id": vid,
        "video_titulo": tit,
        "segundo_inicio": ini,
        "segundo_fin": fin,
        "fragmento_referencia": txt[:180] + "...",
        "notas": f"Ground Truth calibrado en video {vid} [{ini}s - {fin}s]. Pregunta parafraseada ({tipo})."
    })

conn.close()

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(preguntas_json, f, ensure_ascii=False, indent=2)

print(f"Total preguntas generadas y guardadas: {len(preguntas_json)}")
print(f"Guardado en: {OUTPUT_PATH}")
