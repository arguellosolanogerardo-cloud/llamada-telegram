import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler

# ----------------------------------------------------------------------
#  Configuración de rutas
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MEDIT_DIR = DATA_DIR / "meditaciones"

META_HOY = MEDIT_DIR / "meta_hoy.json"
LOG_FILE = DATA_DIR / "reproducciones_log.json"
STATE_FILE = DATA_DIR / "state_meditaciones.json"
# ----------------------------------------------------------------------

def _cargar_json(ruta: Path) -> dict | list:
    if not ruta.exists():
        return {}
    with ruta.open("r", encoding="utf-8") as f:
        return json.load(f)

def _guardar_json(ruta: Path, data: dict | list) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ----------------------------------------------------------------------
#  1. Generar la sucesión completa de números según el patrón pedido:
#     - Bloques de 10 descendentes: 1100..1091, 1090..1081, 1080..1071...
#     - Bloques de 10 ascendentes:  21..30, 31..40, 41..50...
#     Alternando sucesivamente hasta cubrir todas las meditaciones.
# ----------------------------------------------------------------------
def _generar_secuencia() -> list[int]:
    secuencia = []
    top_actual = 1100
    bottom_actual = 21
    vistos = set()

    while top_actual >= bottom_actual:
        # Bloque descendente de 10
        for _ in range(10):
            if top_actual >= bottom_actual and top_actual not in vistos:
                secuencia.append(top_actual)
                vistos.add(top_actual)
                top_actual -= 1

        # Bloque ascendente de 10
        for _ in range(10):
            if bottom_actual <= top_actual and bottom_actual not in vistos:
                secuencia.append(bottom_actual)
                vistos.add(bottom_actual)
                bottom_actual += 1

    return secuencia

SECUENCIA = _generar_secuencia()

# ----------------------------------------------------------------------
#  2. Estado de ejecución (índice actual en la secuencia)
# ----------------------------------------------------------------------
def _cargar_estado() -> dict:
    estado = _cargar_json(STATE_FILE)
    if not isinstance(estado, dict) or "indice" not in estado:
        # El 09/10/2026 se completó 1097 (índice 3: 1100, 1099, 1098, 1097)
        # La siguiente a programar es 1096 (índice 4)
        estado = {"indice": 4}
        _guardar_json(STATE_FILE, estado)
    return estado

def _actualizar_estado(nuevo_indice: int) -> None:
    _guardar_json(STATE_FILE, {"indice": nuevo_indice})

# ----------------------------------------------------------------------
#  3. Función que será llamada cada día a las 03:00 AM
# ----------------------------------------------------------------------
def programar_meditacion_diaria() -> None:
    """Selecciona la siguiente meditación según el patrón alternante,
    actualiza meta_hoy.json, añade al log histórico y notifica al grupo."""
    estado = _cargar_estado()
    indice = estado.get("indice", 4)
    if indice >= len(SECUENCIA):
        indice = 0
    numero = SECUENCIA[indice]
    siguiente_indice = (indice + 1) % len(SECUENCIA)

    # a) Obtener datos oficiales del catálogo si están disponibles
    info_cat = None
    try:
        from bot_comandos import identificar_audio_catalogo
        info_cat = identificar_audio_catalogo(texto=f"meditacion {numero}")
    except Exception as e:
        print(f"Nota: No se pudo consultar catálogo: {e}")

    if not info_cat:
        info_cat = {
            "numero": numero,
            "tipo": "MEDITACION",
            "titulo": f"Meditación #{numero}",
            "fecha": datetime.now(timezone.utc).strftime("%d/%m/%y"),
            "maestro": "Alaniso",
            "detectado_como": "MEDITACION",
        }

    info_cat["fecha_tarea_admin"] = datetime.now().strftime("%d/%m/%Y")

    # Guardar en meta_hoy.json
    _guardar_json(META_HOY, info_cat)

    # b) Añadir al log histórico
    log = _cargar_json(LOG_FILE)
    if not isinstance(log, list):
        log = []
    log.append({
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "numero": numero,
        "titulo": info_cat.get("titulo", f"Meditación #{numero}"),
    })
    _guardar_json(LOG_FILE, log)

    # c) Persistir nuevo índice para el siguiente día
    _actualizar_estado(siguiente_indice)

    # d) Publicar en el grupo oficial de Telegram con anuncio y botones
    try:
        from bot_comandos import enviar_mensaje, CHAT_ID
        from publicar_tarea import generar_anuncio_tarea, armar_teclado_audio

        anuncio = generar_anuncio_tarea(info_cat)
        teclado = armar_teclado_audio(CHAT_ID, numero_tarea=numero, tipo_tarea="MEDITACION")

        if CHAT_ID:
            enviar_mensaje(CHAT_ID, anuncio, reply_markup=teclado)
            print(f"✅ Meditación #{numero} programada y anunciada en el grupo con éxito.")
    except Exception as e_notif:
        print(f"⚠️ Error al notificar meditación en el grupo: {e_notif}")

# ----------------------------------------------------------------------
#  4. Iniciar el scheduler (se llama una sola vez al iniciar el bot)
# ----------------------------------------------------------------------
def iniciar_scheduler() -> None:
    """Crea y arranca el scheduler de APScheduler para 03:00 AM (UTC-5)."""
    scheduler = BackgroundScheduler(timezone=timezone(timedelta(hours=-5)))
    scheduler.add_job(
        programar_meditacion_diaria,
        "cron",
        hour=3,
        minute=0,
        id="meditacion_diaria",
        replace_existing=True
    )
    scheduler.start()
    print("⏰ Scheduler configurado: Meditaciones diarias a las 03:00 AM (Bogotá/UTC-5)")

# ----------------------------------------------------------------------
#  5. Ejecutar directamente para pruebas
# ----------------------------------------------------------------------
if __name__ == "__main__":
    programar_meditacion_diaria()
