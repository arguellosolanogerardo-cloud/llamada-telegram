import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler

# ----------------------------------------------------------------------
#  Configuración de rutas (ajusta si cambias la ubicación)
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MEDIT_DIR = DATA_DIR / "meditaciones"

META_HOY = MEDIT_DIR / "meta_hoy.json"
LOG_FILE = DATA_DIR / "reproducciones_log.json"
STATE_FILE = DATA_DIR / "state_meditaciones.json"
# ----------------------------------------------------------------------

def _cargar_json(ruta: Path) -> dict:
    if not ruta.exists():
        return {}
    with ruta.open("r", encoding="utf-8") as f:
        return json.load(f)

def _guardar_json(ruta: Path, data: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ----------------------------------------------------------------------
#  1. Generar la sucesión completa de números según el patrón pedido
# ----------------------------------------------------------------------
def _generar_secuencia() -> list[int]:
    seq = []
    # Grupo 1: 1100 → 1091 (descendente, 10 meditaciónes)
    seq += list(range(1100, 1090, -1))
    # Grupo 2: 21 → 30 (ascendente)
    seq += list(range(21, 31))
    # Grupo 3: 1090 → 1081 (descendente)
    seq += list(range(1090, 1080, -1))
    # Grupo 4: 31 → 40 (ascendente)
    seq += list(range(31, 41))
    # Repetir hasta cubrir todas las 1113 meditaciones
    full = []
    while len(full) < 1113:
        full += seq
    return full[:1113]

SECUENCIA = _generar_secuencia()

# ----------------------------------------------------------------------
#  2. Estado de ejecución (índice actual en la secuencia)
# ----------------------------------------------------------------------
def _cargar_estado() -> dict:
    estado = _cargar_json(STATE_FILE)
    if not estado:
        estado = {"indice": 0}
        _guardar_json(STATE_FILE, estado)
    return estado

def _actualizar_estado(nuevo_indice: int) -> None:
    _guardar_json(STATE_FILE, {"indice": nuevo_indice})

# ----------------------------------------------------------------------
#  3. Función que será llamada cada día a las 03:00
# ----------------------------------------------------------------------
def programar_meditacion_diaria() -> None:
    """Selecciona la siguiente meditación según el patrón,
    actualiza meta_hoy.json y registra el evento."""
    estado = _cargar_estado()
    indice = estado["indice"]
    numero = SECUENCIA[indice]
    siguiente_indice = (indice + 1) % len(SECUENCIA)

    # a) Guardar en meta_hoy.json (formato que ya usa el bot)
    meta = {
        "numero": numero,
        "tipo": "MEDITACION",
        "titulo": f"Meditación #{numero}",
        "fecha": datetime.now(timezone.utc).strftime("%d/%m/%y"),
        "maestro": "Alaniso",
        "detectado_como": "MEDITACION",
        "fecha_tarea_admin": datetime.now().strftime("%d/%m/%Y"),
    }
    _guardar_json(META_HOY, meta)

    # b) Añadir al log histórico
    log = _cargar_json(LOG_FILE)
    if not isinstance(log, list):
        log = []
    log.append({
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "numero": numero,
        "titulo": meta["titulo"],
    })
    _guardar_json(LOG_FILE, log)

    # c) Persistir nuevo índice
    _actualizar_estado(siguiente_indice)

    # d) Notificar al grupo (usa tu helper de envío si existe)
    try:
        from bot_comandos import enviar_mensaje  # Ajusta al nombre real
        mensaje = (
            f"🧘 Meditación **#{numero}** programada para hoy (03:00 AM).\n"
            f"👤 Maestro: Alaniso\n"
            f"📅 Grabación: {meta['fecha']}"
        )
        enviar_mensaje(mensaje)
    except Exception:
        pass

# ----------------------------------------------------------------------
#  4. Iniciar el scheduler (se llama una sola vez al iniciar el bot)
# ----------------------------------------------------------------------
def iniciar_scheduler() -> None:
    """Crea y arranca el scheduler de APScheduler."""
    scheduler = BackgroundScheduler(timezone=timezone(timedelta(hours=-5)))  # UTC‑5
    scheduler.add_job(programar_meditacion_diaria, "cron", hour=3, minute=0, id="meditacion_diaria")
    scheduler.start()

# ----------------------------------------------------------------------
#  5. Ejecutar al iniciar el bot (prueba rápida)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Ejecutar inmediatamente para pruebas
    programar_meditacion_diaria()
