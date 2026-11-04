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
HISTORIAL_PUB_FILE = DATA_DIR / "registro_publicaciones_3am.json"
MAX_PUBLICACIONES_POR_DIA = 1
_SCHEDULER_INSTANCE = None
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

def obtener_conteo_publicaciones_hoy(fecha_iso: str = None) -> int:
    """Devuelve la cantidad de veces que se ha publicado la tarea en Telegram en el día indicado (máximo 1)."""
    if not fecha_iso:
        fecha_iso = _ahora_colombia().strftime("%Y-%m-%d")
    conteo = 0
    historial = _cargar_json(HISTORIAL_PUB_FILE)
    if isinstance(historial, dict):
        entry = historial.get(fecha_iso)
        if isinstance(entry, dict):
            conteo = int(entry.get("veces_publicado", 0))
        elif isinstance(entry, int):
            conteo = entry

    # Respaldo contra reinicios en Render: Si el historial marca 0 pero meta_hoy.json ya marca publicado_telegram hoy
    if conteo == 0 and META_HOY.exists():
        try:
            meta = _cargar_json(META_HOY)
            if isinstance(meta, dict) and meta.get("publicado_telegram") is True:
                f_meta = meta.get("fecha_iso") or meta.get("fecha_tarea_admin")
                f_disp = _ahora_colombia().strftime("%d/%m/%Y")
                if f_meta in (fecha_iso, f_disp):
                    conteo = 1
        except Exception:
            pass

    # Respaldo remoto: Si localmente el conteo es 0, consultar al bot en Render si está configurada la URL
    if conteo == 0:
        try:
            url_render = os.environ.get("RENDER_BOT_URL", "").strip()
            if not url_render:
                url_render = "https://bot-meditaciones.onrender.com"
            url_api = url_render.rstrip("/") + "/estado_cola"
            req_c = urllib.request.Request(url_api, headers={"User-Agent": "ScheduleMeditaciones"})
            with urllib.request.urlopen(req_c, timeout=3) as resp:
                data_render = json.loads(resp.read().decode())
                if isinstance(data_render, dict) and (data_render.get("publicado_telegram") or data_render.get("veces_publicado", 0) > 0):
                    f_rend = data_render.get("fecha_iso")
                    if not f_rend or f_rend == fecha_iso:
                        conteo = max(1, int(data_render.get("veces_publicado", 1)))
        except Exception:
            pass

    return conteo

def registrar_publicacion_exitosa(fecha_iso: str = None, msg_id: int | str = None, num: int = None) -> int:
    """Registra una publicación exitosa en Telegram para hoy e incrementa el contador (tope de 1)."""
    ahora = _ahora_colombia()
    if not fecha_iso:
        fecha_iso = ahora.strftime("%Y-%m-%d")
    historial = _cargar_json(HISTORIAL_PUB_FILE)
    if not isinstance(historial, dict):
        historial = {}

    entry = historial.get(fecha_iso, {})
    if not isinstance(entry, dict):
        entry = {"veces_publicado": int(entry) if isinstance(entry, int) else 0}

    conteo = int(entry.get("veces_publicado", 0))
    msg_ids = entry.get("msg_ids", [])
    if not isinstance(msg_ids, list):
        msg_ids = []
    timestamps = entry.get("timestamps", [])
    if not isinstance(timestamps, list):
        timestamps = []

    # DEDUPLICACION 1: Si este msg_id ya fue registrado hoy, ignorar incremento duplicado
    if msg_id and str(msg_id) in [str(m) for m in msg_ids]:
        return conteo

    # DEDUPLICACION 2: Si se registro el mismo numero hace menos de 60 segundos, ignorar incremento
    if timestamps and num is not None and entry.get("numero") == num:
        try:
            ultimo_ts = datetime.fromisoformat(timestamps[-1])
            if (ahora - ultimo_ts).total_seconds() < 60:
                if msg_id and str(msg_id) not in [str(m) for m in msg_ids]:
                    msg_ids.append(msg_id)
                    entry["msg_ids"] = msg_ids
                    _guardar_json(HISTORIAL_PUB_FILE, historial)
                return conteo
        except Exception:
            pass

    conteo += 1
    timestamps.append(ahora.isoformat())
    if msg_id and str(msg_id) not in [str(m) for m in msg_ids]:
        msg_ids.append(msg_id)

    entry["veces_publicado"] = conteo
    if num is not None:
        entry["numero"] = num
    entry["timestamps"] = timestamps
    entry["msg_ids"] = msg_ids
    entry["ultima_publicacion"] = ahora.strftime("%Y-%m-%d %H:%M:%S")

    historial[fecha_iso] = entry
    # Purgar registros antiguos (> 60 días)
    if len(historial) > 60:
        for k in sorted(historial.keys())[:-60]:
            historial.pop(k, None)

    _guardar_json(HISTORIAL_PUB_FILE, historial)
    print(f"📊 [3AM] Publicación registrada para {fecha_iso}: {conteo}/{MAX_PUBLICACIONES_POR_DIA} realizadas.")
    return conteo

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
    
    # ── CONTROL ESTRICTO DE HORARIO (SOLO MADRUGADA 03:00 - 04:30 AM SALVO FORZADO) ──
    en_ventana_madrugada = (ahora.hour == 3 or (ahora.hour == 4 and ahora.minute <= 30))
    if not forzar and not en_ventana_madrugada:
        print(f"ℹ️ [3AM] Intento de publicación automática fuera de horario ({ahora.strftime('%H:%M')}). "
              f"Las publicaciones automáticas solo se permiten entre 03:00 AM y 04:30 AM. Omitiendo.")
        return

    # ── CONTROL ESTRICTO DE PUBLICACIÓN (MÁXIMO 1 VEZ AL DÍA) ──
    conteo_hoy = obtener_conteo_publicaciones_hoy(fecha_hoy_iso)
    if not forzar and conteo_hoy >= MAX_PUBLICACIONES_POR_DIA:
        print(f"ℹ️ [3AM] La tarea de hoy ({fecha_hoy_iso}) ya ha sido publicada {conteo_hoy} veces "
              f"(límite máximo permitido: {MAX_PUBLICACIONES_POR_DIA}). Omitiendo duplicado.")
        return
    
    # ── DETERMINAR SIGUIENTE MEDITACIÓN ──
    estado = _cargar_estado()
    indice = estado.get("indice", 5)
    if indice >= len(SECUENCIA):
        indice = 0
    numero = SECUENCIA[indice]
    siguiente_indice = (indice + 1) % len(SECUENCIA)

    print(f"📋 Programando meditación: índice={indice}, "
          f"número=#{numero}, siguiente=#{SECUENCIA[siguiente_indice]} "
          f"(Publicación {conteo_hoy + 1}/{MAX_PUBLICACIONES_POR_DIA} del día)")

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
    try:
        from centinela_youtube import pre_renderizar_video_meditacion_hoy
        pre_renderizar_video_meditacion_hoy()
    except Exception as e_pr:
        print(f"Nota pre-renderizado 3 AM: {e_pr}")
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

    # ── PUBLICAR EN TELEGRAM (HASTA 2 VECES MÁXIMO) ──
    try:
        from publicar_tarea import publicar_tarea_dia
        print(f"Publicando tarea diaria #{numero} en Telegram con audio oficial y anuncio...")
        res_pub = publicar_tarea_dia(str(numero))
        if res_pub:
            nuevo_conteo = obtener_conteo_publicaciones_hoy(fecha_hoy_iso)
            print(f"[OK] Tarea diaria #{numero} publicada exitosamente (Publicación {nuevo_conteo}/{MAX_PUBLICACIONES_POR_DIA} de hoy).")
    except Exception as e_notif:
        print(f"⚠️ Error al notificar meditación en el grupo: {e_notif}")


# ----------------------------------------------------------------------
#  4. Catch-up automático con límite estricto de 2 publicaciones
# ----------------------------------------------------------------------
_CATCHUP_LOCK = False

def verificar_y_ejecutar_catchup(forzar: bool = False) -> bool:
    """Verifica y ejecuta la publicacion respetando el limite maximo estricto de 2 veces al dia.
    Ventana permitida:
    - Madrugada (03:00 a 03:59 AM hora Colombia)
    - O cuando se recibe trigger externo de respaldo y aun hay 0 publicaciones realizadas hoy (hasta las 05:00 AM)
    - Si ya se publico hoy (conteo >= 1) y estamos fuera de la hora 3 AM, se omite de forma segura.
    - Si conteo >= MAX_PUBLICACIONES_POR_DIA, NUNCA se publica automaticamente.
    """
    global _CATCHUP_LOCK
    if _CATCHUP_LOCK:
        return False

    try:
        ahora = _ahora_colombia()
        fecha_hoy_iso = ahora.strftime("%Y-%m-%d")
        fecha_hoy_display = ahora.strftime("%d/%m/%Y")
        numero_esperado = obtener_numero_meditacion_fecha(ahora.date())

        conteo = obtener_conteo_publicaciones_hoy(fecha_hoy_iso)
        if conteo >= MAX_PUBLICACIONES_POR_DIA:
            print(f"ℹ️ [3AM] Tarea de hoy ({fecha_hoy_display}) ya alcanzo el limite de {conteo}/{MAX_PUBLICACIONES_POR_DIA} publicaciones. Omitiendo.")
            return False

        en_ventana_madrugada = (ahora.hour == 3 or (ahora.hour == 4 and ahora.minute <= 30))
        if not forzar and not en_ventana_madrugada:
            print(f"ℹ️ Fuera de ventana de madrugada ({ahora.strftime('%H:%M')}). No se dispara catchup automático a deshoras.")
            return False

        _CATCHUP_LOCK = True
        try:
            print(f"⏰ [3AM] Disparando publicación de hoy #{numero_esperado} (intento {conteo + 1}/{MAX_PUBLICACIONES_POR_DIA})...")
            programar_meditacion_diaria(forzar=forzar)
            nuevo_conteo = obtener_conteo_publicaciones_hoy(fecha_hoy_iso)
            return nuevo_conteo > conteo
        finally:
            _CATCHUP_LOCK = False
    except Exception as e_catchup:
        print(f"⚠️ Error en verificar_y_ejecutar_catchup: {e_catchup}")
        _CATCHUP_LOCK = False
        return False


# ----------------------------------------------------------------------
#  5. Iniciar el scheduler (se llama una sola vez al iniciar el bot)
# ----------------------------------------------------------------------
def iniciar_scheduler() -> None:
    """Configura la publicación diaria a las 03:00 AM (UTC-5) y un segundo intento a las 03:15 AM
    (con tope máximo absoluto de 1 publicación al día)."""
    global _SCHEDULER_INSTANCE
    ahora = _ahora_colombia()
    # Si el bot arranca dentro de la hora de 03:00 AM, verificar catch-up
    if ahora.hour == 3:
        import threading
        threading.Thread(target=verificar_y_ejecutar_catchup, kwargs={"forzar": False}, daemon=True).start()

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        print("⚠️ APScheduler no disponible, scheduler no iniciado.")
        return

    scheduler = BackgroundScheduler(timezone=TZ_OFFSET)
    # 1. Disparo principal a las 03:00 AM
    scheduler.add_job(
        programar_meditacion_diaria,
        "cron",
        hour=3,
        minute=0,
        id="meditacion_diaria_0300",
        replace_existing=True,
        misfire_grace_time=1800,  # 30 minutos de tolerancia (03:00 a 03:30 AM)
        coalesce=True
    )
    # 2. Segundo intento de respaldo a las 03:15 AM (siempre respetando tope de 2)
    scheduler.add_job(
        programar_meditacion_diaria,
        "cron",
        hour=3,
        minute=15,
        id="meditacion_diaria_0315",
        replace_existing=True,
        misfire_grace_time=1800,
        coalesce=True
    )
    scheduler.start()
    _SCHEDULER_INSTANCE = scheduler
    print("⏰ Scheduler configurado: Publicación diaria a las 03:00 AM y 03:15 AM (máx 1 vez/día)")

# ----------------------------------------------------------------------
#  6. Ejecutar directamente para pruebas
# ----------------------------------------------------------------------
if __name__ == "__main__":
    programar_meditacion_diaria()
