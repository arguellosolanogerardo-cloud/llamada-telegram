import sqlite3
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = os.path.join("data", "biblioteca_conocimiento_universal.db")
OUTPUT_PATH = os.path.join("tests", "preguntas_prueba.json")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 20 Temas Estándar con palabras clave presentes en un mismo fragmento,
# pero con la PREGUNTA PARAFRASEADA (sinónimos, plurales, conjugaciones diferentes)
candidatos_estandar = [
    ("144000 elegidos", ["144"], "quiénes son los elegidos de los ciento cuarenta y cuatro mil"),
    ("llama violeta", ["violeta"], "cómo transmutar las energías densas con el rayo violeta"),
    ("reencarnacion de almas", ["reencarn"], "cómo experimentan las almas sus múltiples vidas sucesivas"),
    ("glandula pineal", ["pineal"], "técnicas para estimular el tercer ojo y la visión interior"),
    ("centros energeticos", ["chacra"], "armonización de los vórtices de energía en el cuerpo"),
    ("viaje astral", ["astral"], "experiencias de desdoblamiento del cuerpo sutil mientras dormimos"),
    ("hermanos pleyadianos", ["pleyad"], "mensajes transmitidos por las civilizaciones de las pléyades"),
    ("quinta dimension", ["dimensi"], "síntomas energéticos del salto vibratorio dimensional"),
    ("avistamiento de naves", ["nave"], "presencia de naves extraterrestres custodiando el planeta"),
    ("activacion del adn", ["adn"], "modificaciones genéticas y activación de filamentos estelares"),
    ("respiracion pranica", ["prana"], "absorción de energía vital a través de respiraciones conscientes"),
    ("guardianes cosmicos", ["guardian"], "la protección de los guardianes del universo sobre la tierra"),
    ("transicion de la muerte", ["desencarn"], "el desprendimiento del espíritu al momento de fallecer"),
    ("arcangel miguel", ["miguel"], "invocación del arcángel miguel para protección espiritual"),
    ("ley del karma", ["karma"], "las consecuencias kármicas de nuestras acciones pasadas"),
    ("alimentacion consciente", ["carne"], "beneficios espirituales de abandonar el consumo de animales"),
    ("mensajes de alaniso", ["alaniso"], "enseñanzas espirituales transmitidas por el maestro alaniso"),
    ("perdon del corazon", ["perdon"], "sanación emocional mediante el acto del perdón"),
    ("era de acuario", ["acuario"], "los cambios planetarios que trae la nueva era cósmica"),
    ("trascender el ego", ["ego"], "cómo desidentificarse de los apegos mentales y del ego"),
]

preguntas = []
id_cnt = 1

for tema, kws, preg in candidatos_estandar:
    where = " AND ".join(["texto LIKE ?" for _ in kws])
    params = [f"%{k}%" for k in kws]
    c.execute(f"""
        SELECT t.id, t.video_id, v.titulo, t.inicio_segundos, t.texto 
        FROM transcripciones t 
        JOIN videos v ON t.video_id = v.video_id 
        WHERE t.texto NOT LIKE '[%]' AND {where}
        ORDER BY t.id LIMIT 1
    """, params)
    row = c.fetchone()
    if row:
        t_id, v_id, tit, sec, txt = row
        preguntas.append({
            "id": id_cnt,
            "pregunta": preg,
            "tema": tema,
            "tipo": "estandar",
            "video_id": v_id,
            "video_titulo": tit,
            "segundo_inicio": sec,
            "segundo_fin": sec + 30,
            "fragmento_referencia": txt[:160].strip(),
            "notas": "Concepto clave en un único bloque; pregunta parafraseada (sinónimos/plurales)."
        })
        id_cnt += 1

# 10 Temas Vecinos: Palabras clave separadas entre bloques contiguos (t1 y t2)
# Preguntas de 3 o más palabras donde los términos aparecen en bloques vecinos
candidatos_vecinos = [
    ("meditacion y profundidad", "meditaci", "profund", "alcanzar estados elevados de recogimiento meditativo"),
    ("planeta tierra y transformacion", "planeta", "tierra", "cambios profundos en el planeta tierra y la humanidad"),
    ("maestros y sabiduria", "maestro", "sabidur", "enseñanzas de sabiduría de los maestros espirituales"),
    ("amor y luz divina", "luz", "amor", "irradiar frecuencias de luz y amor divino"),
    ("silencio y calma", "silencio", "calma", "encontrar calma mediante el silencio mental y la paz"),
    ("despertar y transformacion", "despertar", "transform", "procesos de transformación interna durante el despertar espiritual"),
    ("oracion y union", "oraci", "uni", "la fuerza espiritual de la oración en unión comunitaria"),
    ("energia y vibracion", "energ", "vibrac", "elevar la energía y la vibración del cuerpo sutil"),
    ("hermanos y universo", "hermano", "universo", "mensajes de los hermanos del universo para la humanidad"),
    ("paz y corazon", "paz", "coraz", "cultivar la paz profunda en el corazón espiritual")
]

for tema, w1, w2, preg in candidatos_vecinos:
    c.execute("""
        SELECT t1.id, t1.video_id, v.titulo, t1.inicio_segundos, t1.texto, t2.inicio_segundos, t2.texto
        FROM transcripciones t1
        JOIN transcripciones t2 ON t1.video_id = t2.video_id AND t2.id = t1.id + 1
        JOIN videos v ON t1.video_id = v.video_id
        WHERE t1.texto NOT LIKE '[%]' AND t2.texto NOT LIKE '[%]'
          AND t1.texto LIKE ? AND t2.texto LIKE ?
          AND t1.texto NOT LIKE ? AND t2.texto NOT LIKE ?
        ORDER BY t1.id LIMIT 1
    """, (f"%{w1}%", f"%{w2}%", f"%{w2}%", f"%{w1}%"))
    row = c.fetchone()
    if row:
        t1_id, v_id, tit, sec1, txt1, sec2, txt2 = row
        preguntas.append({
            "id": id_cnt,
            "pregunta": preg,
            "tema": tema,
            "tipo": "vecinos",
            "video_id": v_id,
            "video_titulo": tit,
            "segundo_inicio": sec1,
            "segundo_fin": sec2 + 25,
            "fragmento_referencia": f"{txt1.strip()} // [BLOQUE SIGUIENTE]: {txt2.strip()}",
            "notas": f"Palabras clave divididas entre bloque {sec1}s ('{w1}') y bloque {sec2}s ('{w2}'). En el buscador AND actual devuelve 0 aciertos."
        })
        id_cnt += 1

conn.close()

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(preguntas, f, ensure_ascii=False, indent=2)

print(f"Total preguntas generadas: {len(preguntas)} (Estándar: {sum(1 for p in preguntas if p['tipo']=='estandar')}, Vecinos: {sum(1 for p in preguntas if p['tipo']=='vecinos')})")
print(f"Archivo guardado: {OUTPUT_PATH}")
