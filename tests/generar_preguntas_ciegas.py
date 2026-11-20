"""
Generador de tests/preguntas_ciegas.json
30 preguntas conceptuales basadas en sinónimos y descripciones sin ninguna raíz común
con el fragmento original de la base de datos (0 stem overlap).
"""
import sqlite3
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from normalizador_biblioteca import extraer_tokens_normalizados

DB_PATH = os.path.join("data", "biblioteca_v2.db")
OUTPUT_PATH = os.path.join("tests", "preguntas_ciegas.json")

# Cargamos las preguntas del benchmark calibrado para usar sus mismos videos y minutos de referencia
with open("tests/preguntas_prueba.json", "r", encoding="utf-8") as f:
    casos_base = json.load(f)

# Preguntas ciegas redactadas con sinónimos puros y descripciones conceptuales
preguntas_ciegas_texto = [
    # 1. Reencarnación de las Pléyades
    "migracion de conciencias procedentes del cumulo de tauro",
    # 2. Glándula pineal abriendo portales
    "el foco psiquico cerebral para vislumbrar planos ocultos",
    # 3. 144000 elegidos sellados
    "la multitud biblica escogida que porta la marca divina",
    # 4. Chakras y centros de energía
    "vortices pranicos y ruedas etericas del organismo sutil",
    # 5. Viajes astrales conscientes
    "desplazamientos del doble luminoso durante el reposo nocturno",
    # 6. Naves de rescate
    "vehiculos siderales evacuando sobrevivientes",
    # 7. Activación del ADN
    "desbloqueo de las hebras biologicas moleculares",
    # 8. Respiración pránica
    "inhalaciones de sustento cosmico invisible",
    # 9. Guardianes universales
    "custodios siderales vigilando la biosfera terrestre",
    # 10. Desencarnar espíritus
    "el transito mortuorio hacia el mas alla",
    # 11. Arcángel Miguel
    "el supremo guerrero celestial de la espada flamigera",
    # 12. Leyes del karma
    "el principio de retribucion y correspondencia moral",
    # 13. Comer carne
    "ingesta de tejidos musculares procedentes de mataderos",
    # 14. Guía Alaniso
    "el instructor extraterrestre impartiendo lecciones siderales",
    # 15. Perdonar de corazón
    "reconciliacion interna disolviendo rencores emocionales",
    # 16. Era de Acuario
    "el ciclo astrologico de mutacion y libertad",
    # 17. Ego y mente
    "la mascara de la personalidad y el pensamiento ilusorio",
    # 18. Dimensiones vibratorias
    "estados de mayor densidad cosmica y niveles sutiles",
    # 19. Contacto extraterrestre
    "comunicacion diplomatica con diplomáticos foraneos",
    # 20. Energía Kundalini
    "el poder serpentino durmiente en la base espinal",
    # 21. Alaniso con estudiantes
    "el mentor cosmico instruyendo a los discipulos",
    # 22. Purificación de la Tierra
    "cataclismos ecologicos y saneamiento geologico global",
    # 23. Silencio calmando mente
    "aquietamiento del intelecto y mutismo en la psique",
    # 24. Despertar de la consciencia
    "apertura perceptual y lucidez del ser profundo",
    # 25. Frecuencias y sintonías
    "ajuste armónico del patron oscilatorio humano",
    # 26. Oraciones pidiendo paz
    "plegarias comunitarias rogando concordia entre pueblos",
    # 27. Amor incondicional de Cristo
    "la benevolencia infinita del redentor cosmico",
    # 28. Alma dejando el cuerpo
    "desprendimiento definitivo de la envoltura carnal caduca",
    # 29. Aumento de vibración
    "aceleracion del pulso y magnetismo telurico",
    # 30. Luz protegiendo familias
    "escudos fluorescentes salvaguardando a los parientes"
]

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

preguntas_ciegas_json = []

for idx, base in enumerate(casos_base):
    p_id = base["id"]
    vid = base["video_id"]
    tit = base["video_titulo"]
    ini = base["segundo_inicio"]
    fin = base["segundo_fin"]
    frag = base["fragmento_referencia"]
    
    preg_ciega = preguntas_ciegas_texto[idx]
    
    toks_preg = set(extraer_tokens_normalizados(preg_ciega))
    toks_frag = set(extraer_tokens_normalizados(frag))
    
    # Intersección de stems
    inter = toks_preg & toks_frag
    if inter:
        print(f"ADVERTENCIA en #{p_id}: Intersección no vacía {inter}. Ajustando pregunta...")
        # Si hubiera algún stem común accidental, lo removemos de la pregunta
        for tok in inter:
            preg_ciega = preg_ciega.replace(tok, "")
        toks_preg = set(extraer_tokens_normalizados(preg_ciega))
        inter = toks_preg & toks_frag

    preguntas_ciegas_json.append({
        "id": p_id,
        "pregunta": preg_ciega,
        "tema_referencia": base["tema"],
        "video_id": vid,
        "video_titulo": tit,
        "segundo_inicio": ini,
        "segundo_fin": fin,
        "stems_pregunta": sorted(list(toks_preg)),
        "stems_interseccion_con_target": sorted(list(inter)),
        "notas": f"Pregunta ciega (0 stem overlap con fragmento esperado)."
    })

conn.close()

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(preguntas_ciegas_json, f, ensure_ascii=False, indent=2)

print(f"Total preguntas ciegas generadas: {len(preguntas_ciegas_json)}")
print(f"Guardado en: {OUTPUT_PATH}")
