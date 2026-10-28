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
#  Ancla Matemática Oficial del Calendario (Indestructible e Inquebrantable)
#  Base: Lunes 12 de Octubre de 2026 -> Meditación #1095 (Índice 5 de SECUENCIA)
# ----------------------------------------------------------------------
FECHA_ANCLA_BASE = datetime(2026, 10, 12, tzinfo=TZ_OFFSET).date()
INDICE_ANCLA_BASE = 5  # SECUENCIA[5] == 1095

def obtener_indice_para_fecha(fecha=None) -> int:
    """Calcula deterministamente el índice en SECUENCIA para una fecha dada (Colombia UTC-5)."""
    if fecha is None:
        fecha = _ahora_colombia().date()
    elif isinstance(fecha, datetime):
        fecha = fecha.date()
    delta = (fecha - FECHA_ANCLA_BASE).days
    return (INDICE_ANCLA_BASE + delta) % len(SECUENCIA)

def obtener_numero_meditacion_fecha(fecha=None) -> int:
    """Retorna el número oficial de meditación para una fecha dada según la secuencia matemática."""
    idx = obtener_indice_para_fecha(fecha)
    return SECUENCIA[idx]

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
        url_render = os.environ.get("RENDER_BOT_URL", "").replace("/tarea", "")
        if not url_render:
            return None
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
    """Carga el estado del cronograma de meditaciones de forma matemáticamente robusta.
    
    Jerarquía de resolución:
    1. Override explícito de administrador activo SOLO si coincide exactamente con la fecha de hoy.
       Si el override tiene fecha de un día anterior, se considera expirado y se elimina.
    2. Cálculo astronómico/calendario determinista desde la fecha ancla fija (2026-10-12 -> 1095).
       Garantiza que ningún reinicio de servidor en Render, despliegue o borrado de disco efímero
       desincronice el cronograma ni repita meditaciones pasadas.
    """
    estado = _cargar_json(STATE_FILE)
    ahora = _ahora_colombia()
    fecha_hoy_iso = ahora.strftime("%Y-%m-%d")
    
    # 1. Verificar override activo
    if isinstance(estado, dict) and estado.get("override"):
        fecha_override = estado.get("fecha_override") or estado.get("fecha_actualizacion")
        if fecha_override == fecha_hoy_iso and "indice" in estado:
            return estado
        else:
            print(f"ℹ️ Limpiando override expirado de fecha {fecha_override} (hoy es {fecha_hoy_iso})")
            estado["override"] = False
            estado.pop("siguiente_indice", None)
    
    # 2. Cálculo determinista por calendario (a prueba de fallos de disco o reinicios en Render)
    idx_hoy = obtener_indice_para_fecha(ahora.date())
    num_hoy = SECUENCIA[idx_hoy]
    idx_manana = (idx_hoy + 1) % len(SECUENCIA)
    num_manana = SECUENCIA[idx_manana]
    
    estado_calculado = {
        "fecha_actualizacion": fecha_hoy_iso,
        "indice": idx_hoy,
        "numero_programado": num_hoy,
        "siguiente_indice": idx_manana,
        "siguiente_numero": num_manana,
        "override": False,
        "descripcion": f"Calendario matemático: hoy #{num_hoy} (índice {idx_hoy}), mañana #{num_manana} (índice {idx_manana})"
    }
    _guardar_json(STATE_FILE, estado_calculado)
    return estado_calculado


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
        data["fecha_override"] = fecha_hoy
        data["descripcion"] = descripcion or f"Override explícito para siguiente ejecución: #{SECUENCIA[nuevo_indice % len(SECUENCIA)]} (índice {nuevo_indice})"
    _guardar_json(STATE_FILE, data)


def registrar_reproduccion_en_log_y_estado(info_cat: dict, fecha_str: str = "") -> None:
    """Registra en reproducciones_log.json y sincroniza state_meditaciones.json
    al finalizar la llamada oficial diaria. Llamado desde llamada.py."""
    ahora = _ahora_colombia()
    fecha_iso = ahora.strftime("%Y-%m-%d")
    numero = info_cat.get("numero") if isinstance(info_cat, dict) else None
    if not numero:
        return
    
    # 1. Actualizar log
    log = _cargar_json(LOG_FILE)
    if not isinstance(log, list):
        log = []
    # Deduplicar si ya existe entrada para hoy
    log = [it for it in log if not str(it.get("fecha", "")).startswith(fecha_iso)]
    log.append({
        "fecha": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "numero": int(numero),
        "titulo": info_cat.get("titulo", f"Meditación #{numero}"),
        "indice": _indice_de_numero(int(numero)),
        "fecha_iso": fecha_iso,
    })
    if len(log) > 365:
        log = log[-365:]
    _guardar_json(LOG_FILE, log)
    
    # 2. Actualizar state para el día siguiente
    idx_actual = _indice_de_numero(int(numero))
    idx_sig = (idx_actual + 1) % len(SECUENCIA) if idx_actual is not None else obtener_indice_para_fecha(ahora.date() + timedelta(days=1))
    
    st = {
        "fecha_actualizacion": fecha_iso,
        "indice": idx_sig,
        "numero_programado": SECUENCIA[idx_sig],
        "ultimo_reproducido": int(numero),
        "override": False,
        "descripcion": f"Completada #{numero} el {fecha_iso}. Siguiente programada: #{SECUENCIA[idx_sig]} (índice {idx_sig})"
    }
    _guardar_json(STATE_FILE, st)
    print(f"✅ Registro oficial guardado: #{numero} completada, siguiente #{SECUENCIA[idx_sig]}")


# ----------------------------------------------------------------------
#  3. Función que será llamada cada día a las 03:00 AM
# ----------------------------------------------------------------------
def programar_meditacion_diaria(forzar: bool = False) -> None:
    """Selecciona la siguiente meditación según el patrón alternante,
    actualiza meta_hoy.json, añade al log histórico y notifica al grupo.
    
    GARANTÍAS DE ROBUSTEZ:
    - Verificación matemática por fecha ancla calendario
    - Idempotente: evita duplicar si ya se programó la correcta
    - Detección y autocorrección si meta_hoy.json tenía un número desfasado
    - Escritura atómica de archivos JSON
    """
    ahora = _ahora_colombia()
    fecha_hoy_iso = ahora.strftime("%Y-%m-%d")
    fecha_hoy_display = ahora.strftime("%d/%m/%Y")
    
    numero_esperado = obtener_numero_meditacion_fecha(ahora.date())
    
    # ── PROTECCIÓN ANTI-DUPLICADO ──
    meta = _cargar_json(META_HOY)
    if not forzar and isinstance(meta, dict):
        f_meta = meta.get("fecha_iso") or meta.get("fecha_tarea_admin")
        num_meta = meta.get("numero")
        if (f_meta == fecha_hoy_iso or f_meta == fecha_hoy_display) and num_meta == numero_esperado:
            print(f"ℹ️ Ya está programada correctamente la meditación #{num_meta} para hoy ({fecha_hoy_iso}). Omitiendo duplicado.")
            return
    
    # ── DETERMINAR SIGUIENTE MEDITACIÓN ──
    estado = _cargar_estado()
    indice = estado.get("indice", 5)
    if indice >= len(SECUENCIA):
        indice = 0
    numero = SECUENCIA[indice]
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

    # ── LIMPIAR CUALQUIER COLA O AUDIO NO REPRODUCIDO DEL DÍA ANTERIOR ──
    try:
        MEDIT_DIR.mkdir(parents=True, exist_ok=True)
        for jf in ("cola_hoy.json", "cola_manana.json"):
            p_jf = MEDIT_DIR / jf
            if p_jf.exists():
                p_jf.unlink(missing_ok=True)
        for f_old in MEDIT_DIR.iterdir():
            if f_old.is_file() and f_old.name.startswith(("meditacion_hoy", "meditacion_extra", "yt_extra_", "meditacion_manana")) and f_old.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg", ".mp4"):
                try:
                    f_old.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception as e_clean_3am:
        print(f"Nota limpiando cola previa a las 3 AM: {e_clean_3am}")

    # ── GUARDAR meta_hoy.json y cola_hoy.json limpia (atómico) ──
    _guardar_json(META_HOY, info_cat)
    _guardar_json(MEDIT_DIR / "cola_hoy.json", {
        "fecha": fecha_hoy_display,
        "cola": [{
            "ruta": str((MEDIT_DIR / "meditacion_hoy.mp3").resolve()),
            "info": info_cat,
            "titulo": f"Meditación #{numero} - {info_cat.get('titulo', '')}".strip(" -")
        }]
    })
    print(f"✅ meta_hoy.json y cola_hoy.json inicializados limpios: #{numero} para {fecha_hoy_display}")

    # ── AÑADIR AL LOG HISTÓRICO ──
    log = _cargar_json(LOG_FILE)
    if not isinstance(log, list):
        log = []
    log = [entry for entry in log if not str(entry.get("fecha", "")).startswith(fecha_hoy_iso)]
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
    _actualizar_estado(siguiente_indice, override=False, descripcion=f"Programada #{numero} para hoy. Siguiente: #{SECUENCIA[siguiente_indice]}")

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
#  4. Catch-up automático y Watchdog para tareas atrasadas
# ----------------------------------------------------------------------
_CATCHUP_LOCK = False

def verificar_y_ejecutar_catchup(forzar: bool = False) -> bool:
    """Verifica si ya son las 03:00 AM o más (hora Colombia) y si la tarea diaria
    de hoy ya fue programada y publicada. Si no fue publicada, la ejecuta de inmediato (catch-up).
    Retorna True si ejecutó catch-up, False si ya estaba publicada o aún no son las 3 AM."""
    global _CATCHUP_LOCK
    if _CATCHUP_LOCK:
        print("ℹ️ [CATCH-UP] Ya hay una ejecución de catch-up en curso. Omitiendo concurrencia.")
        return False

    try:
        ahora = _ahora_colombia()
        # La tarea diaria se programa oficialmente a partir de las 03:00 AM
        if ahora.hour < 3 and not forzar:
            return False

        fecha_hoy_iso = ahora.strftime("%Y-%m-%d")
        fecha_hoy_display = ahora.strftime("%d/%m/%Y")
        numero_esperado = obtener_numero_meditacion_fecha(ahora.date())

        meta = _cargar_json(META_HOY)
        ya_programada = False
        if isinstance(meta, dict):
            f_meta = meta.get("fecha_iso") or meta.get("fecha_tarea_admin")
            num_meta = meta.get("numero")
            if (f_meta == fecha_hoy_iso or f_meta == fecha_hoy_display) and num_meta == numero_esperado:
                ya_programada = True

        if not ya_programada or forzar:
            _CATCHUP_LOCK = True
            try:
                print(f"🚨 [CATCH-UP ACTIVADO] Son las {ahora.strftime('%H:%M:%S')} y la tarea #{numero_esperado} de hoy ({fecha_hoy_iso}) NO estaba publicada. Publicando inmediatamente...")
                programar_meditacion_diaria(forzar=forzar)
                return True
            finally:
                _CATCHUP_LOCK = False
        else:
            return False
    except Exception as e_catchup:
        print(f"⚠️ Error en verificar_y_ejecutar_catchup: {e_catchup}")
        _CATCHUP_LOCK = False
        return False


# ----------------------------------------------------------------------
#  5. Iniciar el scheduler (se llama una sola vez al iniciar el bot)
# ----------------------------------------------------------------------
def iniciar_scheduler() -> None:
    """Crea y arranca el scheduler de APScheduler para 03:00 AM (UTC-5)
    con tolerancia amplia a misfire (12h) y watchdog catch-up cada 10 min."""
    import threading

    # 1. Al iniciar el bot, verificar de inmediato si la tarea de hoy está pendiente
    threading.Thread(target=verificar_y_ejecutar_catchup, daemon=True).start()

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        print("⚠️ APScheduler no disponible, scheduler no iniciado.")
        return

    scheduler = BackgroundScheduler(timezone=TZ_OFFSET)
    # Tarea principal a las 03:00 AM con misfire_grace_time de 12 horas (43200 s)
    scheduler.add_job(
        programar_meditacion_diaria,
        "cron",
        hour=3,
        minute=0,
        id="meditacion_diaria",
        replace_existing=True,
        misfire_grace_time=43200,
        coalesce=True
    )
    # Watchdog periódico cada 10 minutos para detectar omisiones si el servidor despertó tarde
    scheduler.add_job(
        verificar_y_ejecutar_catchup,
        "interval",
        minutes=10,
        id="watchdog_tarea_catchup",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True
    )
    scheduler.start()
    print("⏰ Scheduler configurado: Meditaciones diarias a las 03:00 AM (Bogotá/UTC-5) + Watchdog Catch-Up cada 10 min")

# ----------------------------------------------------------------------
#  6. Ejecutar directamente para pruebas
# ----------------------------------------------------------------------
if __name__ == "__main__":
    programar_meditacion_diaria()
