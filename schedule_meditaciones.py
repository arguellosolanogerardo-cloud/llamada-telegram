import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Asegurar codificación UTF-8 en stdout/stderr para Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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

# Zona horaria de Colombia (UTC-5)
TZ_OFFSET = timezone(timedelta(hours=-5))

def _ahora_colombia() -> datetime:
    return datetime.now(TZ_OFFSET)

def _cargar_json(ruta: Path) -> dict | list:
    if not ruta.exists():
        return {}
    with ruta.open("r", encoding="utf-8") as f:
        return json.load(f)

def _guardar_json(ruta: Path, data: dict | list) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Reemplazo atómico para evitar corrupción
    tmp.replace(ruta)

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
#  2. Estado de ejecución robusto con múltiples fuentes de verdad
# ----------------------------------------------------------------------

def _obtener_ultimo_numero_desde_log() -> int | None:
    """Lee el log de reproducciones para obtener el último número programado."""
    log = _cargar_json(LOG_FILE)
    if isinstance(log, list) and log:
        ultimo = log[-1]
        num = ultimo.get("numero")
        if isinstance(num, int) and num in SECUENCIA:
            return num
    return None


def _obtener_ultimo_numero_desde_telegram() -> int | None:
    """Intenta leer el último anuncio de tarea del bot en Telegram para
    reconstruir el estado si los archivos locales están desactualizados."""
    bot_token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP")
    if not bot_token or not chat_id:
        return None
    try:
        # Usar getUpdates o getChat history no es posible con Bot API,
        # pero podemos leer meta_hoy.json del endpoint del bot si existe
        url_render = os.environ.get("RENDER_BOT_URL", "").replace("/tarea", "")
        if not url_render:
            return None
        # Intentar leer estado desde el bot en Render
        req = urllib.request.Request(
            f"{url_render}/estado_meditacion",
            headers={"User-Agent": "ScheduleMeditaciones"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
            return data.get("ultimo_numero")
    except Exception:
        return None


def _indice_de_numero(numero: int) -> int | None:
    """Encuentra el índice en SECUENCIA para un número dado."""
    try:
        return SECUENCIA.index(numero)
    except ValueError:
        return None


def _cargar_estado() -> dict:
    """Carga el estado con validación cruzada contra el log de reproducciones.
    
    REGLA DE ORO: El log de reproducciones es la fuente de verdad definitiva.
    Si el state_meditaciones.json contradice el log, se corrige automáticamente.
    """
    estado = _cargar_json(STATE_FILE)
    ahora = _ahora_colombia()
    fecha_hoy = ahora.strftime("%Y-%m-%d")
    
    # 1. Verificar si el estado tiene la fecha de última actualización o un override explícito
    if isinstance(estado, dict) and "indice" in estado:
        # Si tiene bandera explícita de override/personalización del administrador, respetarla prioritariamente
        if estado.get("override"):
            return estado

        fecha_estado = estado.get("fecha_actualizacion", "")
        
        # Si ya se actualizó HOY, el estado es confiable
        if fecha_estado == fecha_hoy:
            return estado
        
        # Si se actualizó ayer o antes, verificar con el log
        indice_estado = estado["indice"]
        
        # El índice actual apunta al SIGUIENTE a programar.
        # Verificar: el número anterior (indice-1) debería ser el último del log
        if indice_estado > 0:
            numero_anterior = SECUENCIA[(indice_estado - 1) % len(SECUENCIA)]
        else:
            numero_anterior = SECUENCIA[-1]
        
        ultimo_log = _obtener_ultimo_numero_desde_log()
        
        if ultimo_log is not None and ultimo_log == numero_anterior:
            # Estado y log coinciden → estado es confiable
            return estado
        elif ultimo_log is not None:
            # ¡CONFLICTO! El log dice otro número → reconstruir desde el log
            indice_log = _indice_de_numero(ultimo_log)
            if indice_log is not None:
                nuevo_indice = (indice_log + 1) % len(SECUENCIA)
                print(f"⚠️ CORRECCIÓN DE ESTADO: state decía índice {indice_estado} "
                      f"(número {SECUENCIA[indice_estado % len(SECUENCIA)]}), "
                      f"pero el log dice que el último fue #{ultimo_log} "
                      f"→ corrigiendo a índice {nuevo_indice} "
                      f"(siguiente: #{SECUENCIA[nuevo_indice]})")
                estado = {
                    "indice": nuevo_indice,
                    "fecha_actualizacion": fecha_estado,
                    "correccion": f"Auto-corregido desde log: ultimo={ultimo_log}"
                }
                _guardar_json(STATE_FILE, estado)
                return estado
        
        # Si no hay log, confiar en el estado existente
        return estado
    
    # 2. Estado vacío o corrupto → reconstruir desde el log
    ultimo_log = _obtener_ultimo_numero_desde_log()
    if ultimo_log is not None:
        indice_log = _indice_de_numero(ultimo_log)
        if indice_log is not None:
            nuevo_indice = (indice_log + 1) % len(SECUENCIA)
            print(f"🔧 Estado reconstruido desde log: último=#{ultimo_log}, "
                  f"siguiente=#{SECUENCIA[nuevo_indice]} (índice {nuevo_indice})")
            estado = {"indice": nuevo_indice, "fecha_actualizacion": ""}
            _guardar_json(STATE_FILE, estado)
            return estado
    
    # 3. Intentar reconstruir desde Telegram
    ultimo_tg = _obtener_ultimo_numero_desde_telegram()
    if ultimo_tg is not None:
        indice_tg = _indice_de_numero(ultimo_tg)
        if indice_tg is not None:
            nuevo_indice = (indice_tg + 1) % len(SECUENCIA)
            print(f"🔧 Estado reconstruido desde Telegram: último=#{ultimo_tg}, "
                  f"siguiente=#{SECUENCIA[nuevo_indice]}")
            estado = {"indice": nuevo_indice, "fecha_actualizacion": ""}
            _guardar_json(STATE_FILE, estado)
            return estado
    
    # 4. Valor por defecto seguro
    # El 09/10/2026 se completó 1097 (índice 3: 1100, 1099, 1098, 1097)
    # La siguiente a programar es 1096 (índice 4)
    estado = {"indice": 4, "fecha_actualizacion": ""}
    _guardar_json(STATE_FILE, estado)
    return estado


def _actualizar_estado(nuevo_indice: int, override: bool = False, descripcion: str = "") -> None:
    fecha_hoy = _ahora_colombia().strftime("%Y-%m-%d")
    data = {
        "indice": nuevo_indice,
        "fecha_actualizacion": fecha_hoy,
        "numero_programado": SECUENCIA[nuevo_indice % len(SECUENCIA)],
        "timestamp": _ahora_colombia().isoformat()
    }
    if override:
        data["override"] = True
        data["descripcion"] = descripcion or f"Override explícito para siguiente ejecución: #{SECUENCIA[nuevo_indice % len(SECUENCIA)]} (índice {nuevo_indice})"
    _guardar_json(STATE_FILE, data)

# ----------------------------------------------------------------------
#  3. Función que será llamada cada día a las 03:00 AM
# ----------------------------------------------------------------------
def programar_meditacion_diaria() -> None:
    """Selecciona la siguiente meditación según el patrón alternante,
    actualiza meta_hoy.json, añade al log histórico y notifica al grupo.
    
    GARANTÍAS DE ROBUSTEZ:
    - Verifica que no se haya programado ya hoy (idempotente)
    - Reconstruye el estado desde el log si hay inconsistencias
    - Escribe fecha_iso para validación estricta en llamada.py
    - Escritura atómica de archivos JSON
    """
    ahora = _ahora_colombia()
    fecha_hoy_iso = ahora.strftime("%Y-%m-%d")
    fecha_hoy_display = ahora.strftime("%d/%m/%Y")
    
    # ── PROTECCIÓN ANTI-DUPLICADO ──
    # Verificar si ya se programó hoy mirando el log
    log = _cargar_json(LOG_FILE)
    if isinstance(log, list) and log:
        ultimo = log[-1]
        fecha_ultimo = ultimo.get("fecha", "")
        if fecha_ultimo.startswith(fecha_hoy_iso):
            print(f"⚠️ Ya se programó meditación hoy ({fecha_hoy_iso}): "
                  f"#{ultimo.get('numero')}. Omitiendo duplicado.")
            return
    
    # ── DETERMINAR SIGUIENTE MEDITACIÓN ──
    estado = _cargar_estado()
    indice = estado.get("indice", 4)
    if indice >= len(SECUENCIA):
        indice = 0
    numero = SECUENCIA[indice]
    
    # Si el estado especifica un siguiente_indice manual (ej: saltar directo a 1095 tras repetir 1097), usarlo
    es_salto_manual = False
    if "siguiente_indice" in estado and isinstance(estado["siguiente_indice"], int):
        siguiente_indice = estado["siguiente_indice"] % len(SECUENCIA)
        es_salto_manual = True
    else:
        siguiente_indice = (indice + 1) % len(SECUENCIA)

    print(f"📋 Programando meditación: índice={indice}, "
          f"número=#{numero}, siguiente=#{SECUENCIA[siguiente_indice]}")

    # ── OBTENER DATOS DEL CATÁLOGO ──
    info_cat = None
    try:
        from catalogo_audios import identificar_audio_catalogo
        info_cat = identificar_audio_catalogo(texto=f"meditacion {numero}")
    except Exception as e:
        print(f"Nota: No se pudo consultar catálogo: {e}")

    if not info_cat:
        info_cat = {
            "numero": numero,
            "tipo": "MEDITACION",
            "titulo": f"Meditación #{numero}",
            "fecha": ahora.strftime("%d/%m/%y"),
            "maestro": "Alaniso",
            "detectado_como": "MEDITACION",
        }

    # ── CAMPOS OBLIGATORIOS PARA VALIDACIÓN ESTRICTA ──
    info_cat["fecha_tarea_admin"] = fecha_hoy_display
    info_cat["fecha_iso"] = fecha_hoy_iso
    info_cat["indice_secuencia"] = indice
    info_cat["timestamp_programacion"] = ahora.isoformat()

    # ── GUARDAR meta_hoy.json (atómico) ──
    _guardar_json(META_HOY, info_cat)
    print(f"✅ meta_hoy.json actualizado: #{numero} para {fecha_hoy_display}")

    # ── AÑADIR AL LOG HISTÓRICO ──
    if not isinstance(log, list):
        log = []
    log.append({
        "fecha": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "numero": numero,
        "titulo": info_cat.get("titulo", f"Meditación #{numero}"),
        "indice": indice,
        "fecha_iso": fecha_hoy_iso,
    })
    # Mantener solo los últimos 365 registros
    if len(log) > 365:
        log = log[-365:]
    _guardar_json(LOG_FILE, log)

    # ── PERSISTIR NUEVO ÍNDICE ──
    desc = f"Salto directo programado a #{SECUENCIA[siguiente_indice]} (índice {siguiente_indice})" if es_salto_manual else ""
    _actualizar_estado(siguiente_indice, override=es_salto_manual, descripcion=desc)

    # ── SINCRONIZAR CON BOT EN RENDER ──
    try:
        url_render = os.environ.get("RENDER_BOT_URL", "").strip()
        if url_render:
            if not url_render.endswith("/tarea"):
                url_render = url_render.rstrip("/") + "/tarea"
            req_sync = urllib.request.Request(
                url_render,
                data=json.dumps({"info": info_cat}).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "ScheduleMeditaciones"}
            )
            with urllib.request.urlopen(req_sync, timeout=5) as r:
                print(f"Metadatos sincronizados con Render: HTTP {r.status}")
    except Exception as e_sync:
        print(f"Nota sincronizando con Render: {e_sync}")

    # ── PUBLICAR EN TELEGRAM ──
    try:
        from publicar_tarea import publicar_tarea_dia
        print(f"Publicando tarea diaria #{numero} en Telegram con audio oficial y anuncio...")
        publicar_tarea_dia(str(numero))
    except Exception as e_notif:
        print(f"⚠️ Error al notificar meditación en el grupo: {e_notif}")


# ----------------------------------------------------------------------
#  4. Iniciar el scheduler (se llama una sola vez al iniciar el bot)
# ----------------------------------------------------------------------
def iniciar_scheduler() -> None:
    """Crea y arranca el scheduler de APScheduler para 03:00 AM (UTC-5)."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        print("⚠️ APScheduler no disponible, scheduler no iniciado.")
        return
    
    scheduler = BackgroundScheduler(timezone=TZ_OFFSET)
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
