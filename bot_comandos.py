import os
import zipfile
import json
import sqlite3
import hashlib
import shutil

# Ruta unificada oficial de la base de datos de la Biblioteca (despliegue único)
DB_BIBLIO_PATH = os.path.join("data", "biblioteca_v2.db")
ZIP_BIBLIO_PATH = os.path.join("data", "biblioteca_v2.zip")

# Limpieza de archivo temporal huérfano dejado por cortes abruptos previos en Render
_db_tmp_orphan = DB_BIBLIO_PATH + ".tmp"
if os.path.exists(_db_tmp_orphan):
    try:
        print(f"[Biblioteca Startup] Eliminando archivo temporal huérfano: {_db_tmp_orphan}...")
        os.remove(_db_tmp_orphan)
        print("[Biblioteca Startup] Temporal huérfano eliminado con éxito.")
    except Exception as _e_clean:
        print(f"[Biblioteca Startup] Advertencia al eliminar temporal huérfano: {_e_clean}")

# Descompresión atómica y control de versión automático al arrancar en Render
if os.path.exists(ZIP_BIBLIO_PATH):
    debe_descomprimir = False
    v_zip = 0
    if not os.path.exists(DB_BIBLIO_PATH):
        print("[Biblioteca Startup] Base no encontrada en disco. Descomprimiendo...")
        debe_descomprimir = True
    else:
        # 1. Comparar fecha de modificación
        if os.path.getmtime(ZIP_BIBLIO_PATH) > os.path.getmtime(DB_BIBLIO_PATH):
            print("[Biblioteca Startup] Archivo zip más reciente que la base en disco. Actualizando...")
            debe_descomprimir = True
        else:
            # 2. Comparar versión interna (version.json en zip vs PRAGMA user_version en DB)
            try:
                with zipfile.ZipFile(ZIP_BIBLIO_PATH, 'r') as zf:
                    if "version.json" in zf.namelist():
                        v_zip = int(json.loads(zf.read("version.json").decode("utf-8")).get("version", 0))
                conn_chk = sqlite3.connect(DB_BIBLIO_PATH)
                c_chk = conn_chk.cursor()
                c_chk.execute("PRAGMA user_version")
                v_db = c_chk.fetchone()[0]
                conn_chk.close()
                if v_zip > 0 and v_db != v_zip:
                    print(f"[Biblioteca Startup] Discrepancia de versión: DB={v_db} vs ZIP={v_zip}. Actualizando...")
                    debe_descomprimir = True
            except Exception as e_v:
                print(f"[Biblioteca Startup] Error comprobando versiones: {e_v}")

    if debe_descomprimir:
        db_tmp = DB_BIBLIO_PATH + ".tmp"
        try:
            print("[Biblioteca Startup] Extrayendo a archivo temporal para descompresión atómica...")
            with zipfile.ZipFile(ZIP_BIBLIO_PATH, 'r') as zip_ref:
                with zip_ref.open("biblioteca_v2.db") as source, open(db_tmp, "wb") as target:
                    shutil.copyfileobj(source, target)
                if "version.json" in zip_ref.namelist():
                    zip_ref.extract("version.json", "data")

            # Verificación estricta antes del reemplazo
            print("[Biblioteca Startup] Verificando integridad y versión de la base temporal...")
            conn_verif = sqlite3.connect(db_tmp)
            c_verif = conn_verif.cursor()
            c_verif.execute("PRAGMA quick_check")
            chk_status = c_verif.fetchone()[0]
            c_verif.execute("PRAGMA user_version")
            v_extraida = c_verif.fetchone()[0]
            conn_verif.close()

            if chk_status != "ok":
                raise ValueError(f"Integridad SQLite corrupta en archivo temporal: {chk_status}")
            if v_zip > 0 and v_extraida > 0 and v_extraida != v_zip:
                raise ValueError(f"user_version extraída ({v_extraida}) no coincide con version.json ({v_zip})")

            # Reemplazo atómico
            os.replace(db_tmp, DB_BIBLIO_PATH)
            print(f"[Biblioteca Startup] Reemplazo atómico exitoso. Base activa user_version={v_extraida}.")
        except Exception as e_atomic:
            print(f"[Biblioteca Startup] ERROR en descompresión atómica: {e_atomic}. La base previa sigue intacta.")
            if os.path.exists(db_tmp):
                try:
                    os.remove(db_tmp)
                except Exception:
                    pass

import asyncio
import json
import os
import re
import time
import urllib.request
import urllib.parse
import threading
import requests
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler

from ia_resumen import buscar_en_minutas, obtener_minuta
# Ensure stdout can handle Unicode emojis on Windows terminals
import sys
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Función de registro del consumo real de memoria RSS para monitoreo en Render
def log_rss_memoria(etiqueta: str = ""):
    """Registra en log el consumo real de memoria RSS (psutil o resource) en Render."""
    try:
        import psutil
        rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        print(f"[Memoria RSS] {etiqueta}: {rss_mb:.2f} MB")
        return rss_mb
    except Exception:
        try:
            import resource
            rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            print(f"[Memoria RSS] {etiqueta}: {rss_mb:.2f} MB")
            return rss_mb
        except Exception:
            return None

log_rss_memoria("Arranque inicial de bot_comandos")

# Validación exhaustiva de compatibilidad del índice vectorial en arranque
def validar_indice_vectorial(dir_vectores: str = os.path.join("data", "vectores_v2")) -> bool:
    """
    Verifica que el índice vectorial en disco sea 100% compatible con la base SQLite activa.
    Valida en metadata.json:
      1. Nombre de modelo ('modelo')
      2. Dimensiones ('dimension_nativa', 'dimensiones_almacenadas')
      3. user_version ('base_user_version' vs PRAGMA user_version)
      4. Conteo de ventanas ('total_ventanas' vs COUNT(*) en transcripciones_v2)
      5. Checksum SHA256 ('checksum_ventanas' de id:video_id:inicio ordenado)
    Si hay discrepancia, archivo faltante o corrupción, emite aviso y cae limpiamente a FTS5.
    """
    meta_path = os.path.join(dir_vectores, "metadata.json")
    if not os.path.exists(meta_path):
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        modelo = meta.get("modelo")
        dim_nat = meta.get("dimension_nativa")
        dims_alm = meta.get("dimensiones_almacenadas")
        v_idx = meta.get("base_user_version")
        w_idx = meta.get("total_ventanas") or meta.get("total_ventanas_db")
        chk_idx = meta.get("checksum_ventanas")

        if not modelo or not dim_nat or not dims_alm:
            print("[Vectores Startup] ADVERTENCIA: Metadatos vectoriales incompletos (modelo o dimensiones ausentes). Fallback FTS5.")
            return False

        if not os.path.exists(DB_BIBLIO_PATH):
            print("[Vectores Startup] Base SQLite no existe en disco. Fallback FTS5.")
            return False

        conn = sqlite3.connect(DB_BIBLIO_PATH)
        c = conn.cursor()
        c.execute("PRAGMA user_version")
        v_db = c.fetchone()[0]
        c.execute("SELECT count(*) FROM transcripciones_v2")
        w_db = c.fetchone()[0]

        if v_idx != v_db:
            conn.close()
            print(f"[Vectores Startup] ADVERTENCIA: Discrepancia de user_version (DB={v_db} vs Vectores={v_idx}). Fallback FTS5.")
            return False

        if w_idx != w_db:
            conn.close()
            print(f"[Vectores Startup] ADVERTENCIA: Discrepancia en número de ventanas (DB={w_db} vs Vectores={w_idx}). Fallback FTS5.")
            return False

        # Validación estricta de Checksum SHA256 si está presente en metadatos
        if chk_idx:
            c.execute("SELECT id, video_id, inicio_segundos FROM transcripciones_v2 ORDER BY id")
            h = hashlib.sha256()
            for r in c:
                h.update(f"{r[0]}:{r[1]}:{r[2]};".encode("utf-8"))
            chk_db = h.hexdigest()
            conn.close()
            if chk_idx != chk_db:
                print(f"[Vectores Startup] ADVERTENCIA: Checksum de ventanas no coincide (DB={chk_db[:8]}... vs Vectores={chk_idx[:8]}...). Fallback FTS5.")
                return False
        else:
            conn.close()

        print(f"[Vectores Startup] Índice vectorial 100% verificado: modelo={modelo}, dims={dims_alm}, user_version={v_db}, ventanas={w_db}. OK.")
        return True
    except Exception as e_vidx:
        print(f"[Vectores Startup] Error validando índice vectorial ({e_vidx}). Fallback FTS5.")
        return False

# Registro de diagnóstico de SQLite y FTS5 al arrancar
try:
    print(f"[SQLite Startup] Versión de SQLite del sistema: {sqlite3.sqlite_version}")
    _db_v2_check = os.path.join("data", "biblioteca_v2.db")
    if os.path.exists(_db_v2_check):
        _conn_diag = sqlite3.connect(_db_v2_check)
        _c_diag = _conn_diag.cursor()
        _c_diag.execute("SELECT count(*) FROM transcripciones_fts WHERE transcripciones_fts MATCH 'alanis*'")
        _cnt_diag = _c_diag.fetchone()[0]
        _conn_diag.close()
        print(f"[SQLite Startup] Consulta de prueba FTS5 en biblioteca_v2.db OK: {_cnt_diag} registros encontrados.")
    else:
        print("[SQLite Startup] biblioteca_v2.db no está presente aún; FTS5 se activará al existir el archivo.")
except Exception as _e_diag:
    print(f"[SQLite Startup] Advertencia al verificar FTS5: {_e_diag}")

from catalogo_audios import identificar_audio_catalogo, formatear_info_audio, identificar_todos_los_audios, formatear_cola_audios
from publicar_tarea import generar_anuncio_tarea, armar_teclado_audio, extraer_fecha_de_texto, obtener_info_bot
from drive_manager import obtener_o_descargar_audio, buscar_audio_en_drive

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()
BOT_ID = int(BOT_TOKEN.split(":")[0]) if (BOT_TOKEN and ":" in BOT_TOKEN) else None
CHAT_ID = (os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP") or "").strip()
TG_API_ID = (os.environ.get("TG_API_ID") or "").strip()
TG_API_HASH = (os.environ.get("TG_API_HASH") or "").strip()
TG_SESSION = (os.environ.get("TG_SESSION") or "").strip()
GITHUB_TOKEN = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()

RUTA_PUNTOS = os.path.join("data", "puntos.json")
RUTA_AUDIOS_REGISTRADOS = os.path.join("data", "meditaciones", "audios_registrados.json")
RUTA_MSGS_BOT = os.path.join("data", "mensajes_bot_grupo.json")
RUTA_USUARIOS_SIN_PRIVADO = os.path.join("data", "usuarios_sin_privado.json")
URL_RAW_GITHUB = "https://raw.githubusercontent.com/arguellosolanogerardo-cloud/llamada-telegram/main/data/puntos.json"

COLA_LOGS = []
_TAREA_FLOTANTE = {"msg_id": None, "contador": 0, "texto": "", "reply_markup": None, "chat_id": None}
_CACHE_RESPUESTAS_BIBLIO = {}


def cargar_usuarios_sin_privado() -> set:
    if os.path.exists(RUTA_USUARIOS_SIN_PRIVADO):
        try:
            with open(RUTA_USUARIOS_SIN_PRIVADO, "r", encoding="utf-8") as f:
                return set(str(x) for x in json.load(f))
        except Exception:
            pass
    return set()


def marcar_usuario_sin_privado(uid: int | str) -> None:
    if not uid:
        return
    try:
        os.makedirs(os.path.dirname(RUTA_USUARIOS_SIN_PRIVADO), exist_ok=True)
        s = cargar_usuarios_sin_privado()
        uid_str = str(uid)
        if uid_str not in s:
            s.add(uid_str)
            with open(RUTA_USUARIOS_SIN_PRIVADO, "w", encoding="utf-8") as f:
                json.dump(sorted(list(s)), f, indent=2)
    except Exception:
        pass


def marcar_usuario_con_privado(uid: int | str) -> None:
    if not uid:
        return
    try:
        s = cargar_usuarios_sin_privado()
        uid_str = str(uid)
        if uid_str in s:
            s.remove(uid_str)
            with open(RUTA_USUARIOS_SIN_PRIVADO, "w", encoding="utf-8") as f:
                json.dump(sorted(list(s)), f, indent=2)
    except Exception:
        pass


def log_debug(msg: str) -> None:
    timestamp = datetime.now(ZoneInfo("America/Bogota")).strftime("%H:%M:%S")
    linea = f"[{timestamp}] {msg}"
    print(linea)
    COLA_LOGS.append(linea)
    if len(COLA_LOGS) > 100:
        COLA_LOGS.pop(0)


def cargar_audios_registrados() -> dict:
    if os.path.exists(RUTA_AUDIOS_REGISTRADOS):
        try:
            with open(RUTA_AUDIOS_REGISTRADOS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _obtener_ffmpeg_bin() -> str | None:
    import shutil
    f_sys = shutil.which("ffmpeg")
    if f_sys and os.path.exists(f_sys) and os.path.getsize(f_sys) > 1000:
        return f_sys
    try:
        import imageio_ffmpeg
        f_img = imageio_ffmpeg.get_ffmpeg_exe()
        if f_img and os.path.exists(f_img):
            try:
                import stat
                os.chmod(f_img, os.stat(f_img).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except Exception:
                pass
            return f_img
    except Exception:
        pass
    return None


def descargar_audio_youtube_robusto(vid_target: str, titulo_pista: str = "") -> str | None:
    """Descarga o recupera el audio de un video de YouTube de forma ultra-robusta:
    1. Verifica si ya existe en caché local de meditaciones.
    2. Si corresponde al catálogo de meditaciones/mensajes, lo descarga directamente desde Google Drive.
    3. Si no, usa yt-dlp con múltiples clientes de fallback (ios, web, android, mweb, tv) y formatos livianos.
    4. Garantiza conversión a MP3 y control de tamaño (<50MB para Telegram).
    """
    if not vid_target:
        return None

    vid_target = str(vid_target).strip()
    carp_med = os.path.join("data", "meditaciones")
    os.makedirs(carp_med, exist_ok=True)
    cache_oficial = os.path.join(carp_med, f"yt_dl_{vid_target}.mp3")

    # 1. Caché existente
    if os.path.exists(cache_oficial) and os.path.getsize(cache_oficial) > 1000:
        return cache_oficial

    tmp_mp3 = os.path.join("data", f"ytmp3_{vid_target}.mp3")
    if os.path.exists(tmp_mp3) and os.path.getsize(tmp_mp3) > 1000:
        try:
            shutil.copy2(tmp_mp3, cache_oficial)
        except Exception:
            pass
        return cache_oficial

    # Obtener título si no fue provisto
    if not titulo_pista:
        try:
            from radar_youtube import obtener_info_oembed, obtener_titulo_video
            info_oe = obtener_info_oembed(vid_target)
            titulo_pista = info_oe.get("title", "").strip() or obtener_titulo_video(vid_target) or f"Audio {vid_target}"
        except Exception:
            titulo_pista = f"Audio {vid_target}"

    # 2. Respaldo directo desde Google Drive si está en el catálogo oficial
    try:
        info_cat = identificar_audio_catalogo(titulo_pista)
        if info_cat and info_cat.get("numero") and info_cat.get("tipo"):
            ruta_drive = obtener_o_descargar_audio(info_cat["tipo"], info_cat["numero"])
            if ruta_drive and os.path.exists(ruta_drive) and os.path.getsize(ruta_drive) > 1000:
                try:
                    shutil.copy2(ruta_drive, cache_oficial)
                    print(f"✅ Audio {vid_target} ({titulo_pista}) obtenido exitosamente desde Google Drive.")
                    return cache_oficial
                except Exception:
                    return ruta_drive
    except Exception as e_cat:
        print(f"Nota buscando en catálogo Drive para {vid_target}: {e_cat}")

    # 3. Descarga desde YouTube con yt-dlp multi-cliente
    ff_bin = _obtener_ffmpeg_bin()
    tmp_out_tmpl = os.path.join("data", f"ytmp3_{vid_target}.%(ext)s")
    url_yt = f"https://www.youtube.com/watch?v={vid_target}"

    # Intento 1: Multi-cliente (ios primero para evitar PO Token y SABR)
    cmd1 = [
        sys.executable, "-m", "yt_dlp",
        "--extractor-args", "youtube:player_client=ios,web,android,mweb,tv",
        "-f", "ba/ba*/b[ext=mp4]/b/18/best",
        "-x", "--audio-format", "mp3",
        "--audio-quality", "4",
        "--no-playlist",
        "--no-check-certificates",
        "--socket-timeout", "30",
        "--retries", "3"
    ]
    if ff_bin:
        cmd1.extend(["--ffmpeg-location", ff_bin])
    cmd1.extend(["--output", tmp_out_tmpl, url_yt])

    exito = False
    try:
        r1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=180)
        if r1.returncode == 0:
            exito = True
        else:
            print(f"Aviso yt-dlp intento 1 ({vid_target}): {r1.stderr[:200] if r1.stderr else ''}")
    except Exception as e1:
        print(f"Error yt-dlp intento 1 ({vid_target}): {e1}")

    # Intento 2: Fallback estándar de yt-dlp
    if not exito and not os.path.exists(tmp_mp3):
        cmd2 = [
            sys.executable, "-m", "yt_dlp",
            "-f", "ba/ba*/b[ext=mp4]/b/18/best",
            "-x", "--audio-format", "mp3",
            "--audio-quality", "4",
            "--no-playlist",
            "--no-check-certificates",
            "--socket-timeout", "30"
        ]
        if ff_bin:
            cmd2.extend(["--ffmpeg-location", ff_bin])
        cmd2.extend(["--output", tmp_out_tmpl, url_yt])
        try:
            r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=180)
            if r2.returncode == 0:
                exito = True
        except Exception as e2:
            print(f"Error yt-dlp intento 2 ({vid_target}): {e2}")

    # Intento 3: Descarga directa de stream crudo sin -x (independiente de ffprobe)
    if not os.path.exists(tmp_mp3):
        import glob
        matches_pre = glob.glob(os.path.join("data", f"ytmp3_{vid_target}.*"))
        if not any(os.path.getsize(m) > 1000 for m in matches_pre):
            cmd3 = [
                sys.executable, "-m", "yt_dlp",
                "-f", "ba/ba*/b[ext=mp4]/b/18/best",
                "--no-playlist",
                "--no-check-certificates",
                "--socket-timeout", "30",
                "--output", tmp_out_tmpl,
                url_yt
            ]
            try:
                subprocess.run(cmd3, capture_output=True, text=True, timeout=180)
            except Exception as e3:
                print(f"Error yt-dlp intento 3 ({vid_target}): {e3}")

    # 4. Localizar y convertir archivo descargado
    import glob
    archivo_final = None
    if os.path.exists(tmp_mp3) and os.path.getsize(tmp_mp3) > 1000:
        archivo_final = tmp_mp3
    else:
        matches = glob.glob(os.path.join("data", f"ytmp3_{vid_target}.*"))
        for m in matches:
            if m.endswith((".mp3", ".m4a", ".webm", ".opus", ".mp4", ".ogg")) and os.path.getsize(m) > 1000:
                if not m.endswith(".mp3") and ff_bin:
                    try:
                        r_c = subprocess.run(
                            [ff_bin, "-y", "-i", m, "-vn", "-acodec", "libmp3lame", "-b:a", "96k", "-ar", "44100", tmp_mp3],
                            capture_output=True, timeout=120
                        )
                        if os.path.exists(tmp_mp3) and os.path.getsize(tmp_mp3) > 1000:
                            archivo_final = tmp_mp3
                            try:
                                os.remove(m)
                            except Exception:
                                pass
                            break
                    except Exception as e_conv:
                        print(f"Error convirtiendo manual {m}: {e_conv}")
                archivo_final = m
                break

    if not archivo_final or not os.path.exists(archivo_final) or os.path.getsize(archivo_final) <= 1000:
        return None

    # 5. Control de tamaño para Telegram Bot API (límite estricto 50 MB)
    tam_mb = os.path.getsize(archivo_final) / (1024 * 1024)
    if tam_mb > 49.0 and ff_bin:
        archivo_comp = os.path.join("data", f"ytmp3_{vid_target}_comp.mp3")
        try:
            subprocess.run(
                [ff_bin, "-y", "-i", archivo_final, "-vn", "-acodec", "libmp3lame", "-b:a", "48k", "-ac", "1", archivo_comp],
                capture_output=True, timeout=120
            )
            if os.path.exists(archivo_comp) and os.path.getsize(archivo_comp) > 1000:
                try:
                    os.remove(archivo_final)
                except Exception:
                    pass
                archivo_final = archivo_comp
        except Exception as e_comp:
            print(f"Error comprimiendo audio grande: {e_comp}")

    # 6. Copiar a caché permanente oficial
    try:
        shutil.copy2(archivo_final, cache_oficial)
        return cache_oficial
    except Exception:
        return archivo_final



def guardar_audio_registrado(info_cat: dict, file_id: str = None, msg_id: int | str = None) -> None:
    if not info_cat:
        return
    try:
        os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
        db = cargar_audios_registrados()
        tipo = str(info_cat.get("tipo", "MEDITACION")).upper()
        num = str(info_cat.get("numero", "")).strip()
        vid = str(info_cat.get("video_id", "")).strip()
        registro = dict(info_cat)
        if file_id:
            registro["file_id"] = file_id
        if msg_id:
            registro["msg_id_audio"] = msg_id
        claves = []
        if num:
            claves.extend([f"{tipo}_{num}", num])
        if vid:
            claves.append(f"YT_{vid}")
        for k in claves:
            if k:
                db[k] = registro
        with open(RUTA_AUDIOS_REGISTRADOS, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando audio registrado:", e)


def cargar_msgs_bot() -> list:
    if os.path.exists(RUTA_MSGS_BOT):
        try:
            with open(RUTA_MSGS_BOT, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def registrar_msg_bot(mid: int | str) -> None:
    if not mid:
        return
    try:
        os.makedirs(os.path.dirname(RUTA_MSGS_BOT), exist_ok=True)
        msgs = cargar_msgs_bot()
        m_int = int(mid)
        if m_int not in msgs:
            msgs.append(m_int)
        msgs = msgs[-300:]
        with open(RUTA_MSGS_BOT, "w", encoding="utf-8") as f:
            json.dump(msgs, f)
    except Exception:
        pass


def eliminar_mensaje(chat_id: int | str, message_id: int | str) -> bool:
    if not BOT_TOKEN or not chat_id or not message_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
        datos = json.dumps({"chat_id": chat_id, "message_id": int(message_id)}).encode()
        req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return True
    except Exception:
        return False


def limpiar_sala_notificaciones(chat_id: int | str) -> int:
    """Borra notificaciones y ventanas creadas por el robot en la sala."""
    log_debug(f"Iniciando limpiar_sala_notificaciones para chat {chat_id}")
    borrados = 0
    # 1. Borrar mensajes registrados del bot
    msgs = cargar_msgs_bot()
    log_debug(f"Mensajes registrados en json: {len(msgs)}")
    if msgs:
        for mid in list(msgs):
            if eliminar_mensaje(chat_id, mid):
                borrados += 1
                time.sleep(0.05)
        try:
            with open(RUTA_MSGS_BOT, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception:
            pass

    # 2. Si cuenta con credenciales Telethon (TG_SESSION), realizar escaneo profundo
    log_debug(f"Verificando Telethon: TG_SESSION={bool(TG_SESSION)}, TG_API_ID={bool(TG_API_ID)}, TG_API_HASH={bool(TG_API_HASH)}")
    if TG_SESSION and TG_API_ID and TG_API_HASH:
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession

            async def _scan_telethon():
                cant_tel = 0
                async with TelegramClient(StringSession(TG_SESSION), int(TG_API_ID), TG_API_HASH) as client:
                    try:
                        dest = int(chat_id)
                    except ValueError:
                        dest = chat_id
                    entidad = await client.get_entity(dest)
                    me = await client.get_me()
                    my_id = me.id if me else None
                    bot_id = int(BOT_TOKEN.split(":")[0]) if (BOT_TOKEN and ":" in BOT_TOKEN) else None
                    ids_del = []
                    async for m in client.iter_messages(entidad, limit=150):
                        es_bot = False
                        if getattr(m, "out", False) or (my_id and m.sender_id == my_id):
                            es_bot = True
                        elif bot_id and (m.sender_id == bot_id or getattr(m, "via_bot_id", None) == bot_id):
                            es_bot = True
                        elif getattr(m, "reply_markup", None) is not None:
                            # Solo bots pueden tener inline keyboards en un grupo
                            es_bot = True
                        elif getattr(m, "sender", None) and getattr(m.sender, "bot", False):
                            es_bot = True

                        if es_bot:
                            ids_del.append(m.id)

                    log_debug(f"Telethon encontro {len(ids_del)} mensajes de bot/ventanas para borrar.")
                    if ids_del:
                        for k in range(0, len(ids_del), 100):
                            await client.delete_messages(entidad, ids_del[k:k+100])
                        cant_tel = len(ids_del)
                return cant_tel

            cant_tel = asyncio.run(_scan_telethon())
            borrados += cant_tel
            log_debug(f"Limpieza Telethon completada: {cant_tel} mensajes eliminados.")
        except Exception as e:
            log_debug(f"Nota en limpieza Telethon: {e}")

    # 3. Disparar workflow de limpieza en GitHub Actions si GITHUB_TOKEN está presente
    if GITHUB_TOKEN:
        try:
            url_gh = "https://api.github.com/repos/arguellosolanogerardo-cloud/llamada-telegram/actions/workflows/limpieza.yml/dispatches"
            payload_gh = json.dumps({"ref": "main", "inputs": {"modo_profundo": True}}).encode()
            req_gh = urllib.request.Request(
                url_gh,
                data=payload_gh,
                headers={
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "BotComandos",
                    "Content-Type": "application/json"
                }
            )
            with urllib.request.urlopen(req_gh, timeout=10) as r:
                log_debug(f"Workflow de limpieza GitHub Actions disparado: {r.status}")
        except Exception as e:
            log_debug(f"Nota disparando GitHub Actions: {e}")

    log_debug(f"Total mensajes borrados por limpiar_sala_notificaciones: {borrados}")
    return borrados


_ULTIMO_SCAN_RADAR = 0.0


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/logs":
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            diag_txt = (
                f"=== ESTADO BOT ===\n"
                f"TG_SESSION_CONFIGURADO: {bool(TG_SESSION)}\n"
                f"TG_API_ID_CONFIGURADO: {bool(TG_API_ID)}\n"
                f"TG_API_HASH_CONFIGURADO: {bool(TG_API_HASH)}\n"
                f"GITHUB_TOKEN_CONFIGURADO: {bool(GITHUB_TOKEN)}\n"
                f"CHAT_ID: {CHAT_ID}\n"
                f"MSGS_BOT_REGISTRADOS: {len(cargar_msgs_bot())}\n"
                f"=== ULTIMOS LOGS ({len(COLA_LOGS)}) ===\n" +
                "\n".join(COLA_LOGS[-60:])
            )
            self.wfile.write(diag_txt.encode("utf-8"))
            return
        if self.path.startswith("/diag"):
            try:
                allowed_types = urllib.parse.quote(json.dumps(["message", "edited_message", "callback_query"]))
                url_rst = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?limit=1&timeout=0&allowed_updates={allowed_types}"
                urllib.request.urlopen(urllib.request.Request(url_rst, headers={"User-Agent": "BotComandosHealth"}), timeout=5)
            except Exception:
                pass
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as r:
                    res = json.loads(r.read().decode())
                texto = f"Token_Start: {BOT_TOKEN[:8] if BOT_TOKEN else 'None'} | Bot: {res}"
            except Exception as e:
                texto = f"Token_Start: {BOT_TOKEN[:8] if BOT_TOKEN else 'None'} | Error: {e}"
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(texto.encode("utf-8"))
            return
        if self.path in ("/aviso", "/aviso_previo", "/recordatorio"):
            m_id = enviar_aviso_preparacion_sala()
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message_id": m_id}).encode())
            return
        if self.path in ("/radar", "/escanear", "/scan"):
            try:
                global _ULTIMO_SCAN_RADAR
                ahora_ts = time.time()
                if (ahora_ts - _ULTIMO_SCAN_RADAR) < 45:
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "anunciados": 0, "cooldown": True}).encode())
                    return
                _ULTIMO_SCAN_RADAR = ahora_ts
                from radar_youtube import chequear_canales
                cant = chequear_canales(enviar_mensaje, CHAT_ID, bot_enviar_foto_func=enviar_foto)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "anunciados": cant}).encode())
                return
            except Exception as e_rad:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e_rad)}).encode())
                return
        if self.path.startswith("/estado_cola"):
            try:
                tz_col = ZoneInfo("America/Bogota")
                ahora_c = datetime.now(tz_col)
                if ahora_c.hour < 4:
                    ahora_c -= timedelta(days=1)
                fecha_h = ahora_c.strftime("%d/%m/%Y")
                info_h = obtener_info_tarea_hoy() or {}
                cola_h = []
                r_cola = os.path.join("data", "meditaciones", "cola_hoy.json")
                if os.path.exists(r_cola):
                    try:
                        with open(r_cola, "r", encoding="utf-8") as fc:
                            dc = json.load(fc)
                            if isinstance(dc, dict) and dc.get("fecha") == fecha_h:
                                cola_h = dc.get("cola", [])
                    except Exception:
                        pass
                payload_resp = {
                    "status": "ok",
                    "fecha": fecha_h,
                    "info_hoy": info_h,
                    "cola_hoy": cola_h,
                    "audios_registrados": cargar_audios_registrados()
                }
                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(payload_resp, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e_ec:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e_ec)}).encode())
                return
        if self.path.startswith("/limpiar_cola"):
            try:
                limpiar_cola_y_temporales_render()
                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "cleaned": True}).encode("utf-8"))
                return
            except Exception as e_lc:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e_lc)}).encode())
                return
        if self.path.startswith("/ipc_panel"):
            try:
                ipc_f = os.path.join("data", "control_panel_ipc.json")
                datos_ipc = {}
                if os.path.exists(ipc_f):
                    with open(ipc_f, "r", encoding="utf-8") as fi:
                        datos_ipc = json.load(fi)
                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(datos_ipc, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e_ip:
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({}).encode())
                return
        if self.path.startswith("/programar_yt"):
            try:
                parsed_q = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(parsed_q.query)
                vid_q = (qs.get("vid") or [""])[0].strip()
                if not vid_q:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": "Falta parametro vid"}).encode())
                    return
                threading.Thread(
                    target=procesar_programacion_yttarea,
                    args=(vid_q, 8204833441, CHAT_ID),
                    daemon=True
                ).start()
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "vid": vid_q, "chat_id": CHAT_ID}).encode())
                return
            except Exception as e_pyt:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e_pyt)}).encode())
                return
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot Comandos OK")

    def do_POST(self):
        if self.path.startswith("/limpiar_cola"):
            try:
                limpiar_cola_y_temporales_render()
                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "cleaned": True}).encode("utf-8"))
                return
            except Exception as e_lc:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e_lc)}).encode())
                return
        if self.path in ("/radar", "/escanear", "/scan"):
            try:
                global _ULTIMO_SCAN_RADAR
                ahora_ts = time.time()
                if (ahora_ts - _ULTIMO_SCAN_RADAR) < 45:
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "anunciados": 0, "cooldown": True}).encode())
                    return
                _ULTIMO_SCAN_RADAR = ahora_ts
                from radar_youtube import chequear_canales
                cant = chequear_canales(enviar_mensaje, CHAT_ID, bot_enviar_foto_func=enviar_foto)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "anunciados": cant}).encode())
                return
            except Exception as e_rad:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e_rad)}).encode())
                return
        if self.path in ("/aviso", "/aviso_previo", "/recordatorio"):
            m_id = enviar_aviso_preparacion_sala()
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message_id": m_id}).encode())
            return
        if self.path in ("/tarea", "/set_tarea"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                datos = json.loads(body)
                info = datos.get("info")
                msg_id_audio = datos.get("msg_id_audio")
                if info:
                    if msg_id_audio:
                        info["msg_id_audio"] = msg_id_audio
                    carp_m = os.path.join("data", "meditaciones")
                    os.makedirs(carp_m, exist_ok=True)
                    # Si es una meditación oficial nueva (no audio adicional de Mario), limpiar cualquier cola previa
                    if not info.get("es_mario") and not info.get("es_adicional"):
                        limpiar_cola_y_temporales_render(conservar_meta=True)
                        fecha_t = info.get("fecha_tarea_admin") or datetime.now(ZoneInfo("America/Bogota")).strftime("%d/%m/%Y")
                        r_mp3 = info.get("audio_path") or os.path.join(carp_m, "meditacion_hoy.mp3")
                        t_nom = "Meditación" if "MEDITACI" in str(info.get("tipo", "MEDITACION")).upper() else "Mensaje"
                        num_s = info.get("numero", "")
                        pista_unica = {
                            "ruta": os.path.abspath(r_mp3),
                            "info": info,
                            "titulo": f"{t_nom} #{num_s} - {info.get('titulo', '')}".strip(" -#")
                        }
                        with open(os.path.join(carp_m, "cola_hoy.json"), "w", encoding="utf-8") as fc:
                            json.dump({"fecha": fecha_t, "cola": [pista_unica]}, fc, ensure_ascii=False, indent=2)
                    ruta_meta = os.path.join(carp_m, "meta_hoy.json")
                    with open(ruta_meta, "w", encoding="utf-8") as f:
                        json.dump(info, f, ensure_ascii=False, indent=2)
                    guardar_audio_registrado(info, file_id=info.get("file_id"), msg_id=msg_id_audio)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
                return
            except Exception as e:
                print("Error en do_POST /tarea:", e)
                self.send_response(500)
                self.end_headers()
                return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def limpiar_cola_y_temporales_render(conservar_meta: bool = False) -> None:
    """Borra la cola de reproducción y cualquier audio temporal no reproducido al cerrar la sala o cambiar de día."""
    carp_m = os.path.join("data", "meditaciones")
    os.makedirs(carp_m, exist_ok=True)
    archivos_json = ["cola_hoy.json", "cola_manana.json"]
    if not conservar_meta:
        archivos_json.append("meta_hoy.json")
    for jf in archivos_json:
        rj = os.path.join(carp_m, jf)
        if os.path.exists(rj):
            try:
                os.remove(rj)
            except Exception:
                pass
    ipc_f = os.path.join("data", "control_panel_ipc.json")
    if os.path.exists(ipc_f):
        try:
            os.remove(ipc_f)
        except Exception:
            pass
    try:
        for fn in os.listdir(carp_m):
            if fn.startswith(("meditacion_hoy", "meditacion_extra", "yt_extra_", "meditacion_manana")) and fn.endswith((".mp3", ".m4a", ".wav", ".ogg", ".mp4")):
                try:
                    os.remove(os.path.join(carp_m, fn))
                except Exception:
                    pass
    except Exception:
        pass
    print("🧹 Cola de reproducción y audios temporales limpiados en Render.")


def iniciar_servidor_health():
    port = int(os.environ.get("PORT", 8000))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        server.serve_forever()
    except Exception as e:
        print("Nota servidor health check:", e)



def obtener_rango(puntos: int) -> str:
    if puntos >= 1800:
        return "💎 Diamante"
    if puntos >= 750:
        return "🥇 Oro"
    if puntos >= 250:
        return "🥈 Plata"
    return "🥉 Bronce"


def cargar_puntos() -> dict:
    if os.path.exists(RUTA_PUNTOS):
        try:
            with open(RUTA_PUNTOS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("Nota leyendo puntos locales:", e)

    # Fallback si se ejecuta en servidor externo sin clon del repo
    try:
        req = urllib.request.Request(URL_RAW_GITHUB, headers={"User-Agent": "BotComandos"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print("Nota consultando puntos desde GitHub:", e)

    return {"version": 2, "usuarios": {}}


_ADMIN_IDS_CACHE = {}
_ADMIN_IDS_TIMESTAMP = {}


def obtener_admin_ids(target_chat=None) -> set:
    target = target_chat or CHAT_ID
    ahora = time.time()
    t_str = str(target) if target else "default"
    if t_str in _ADMIN_IDS_CACHE and (ahora - _ADMIN_IDS_TIMESTAMP.get(t_str, 0) < 300):
        return _ADMIN_IDS_CACHE[t_str]

    admins = set()
    # Administradores oficiales permanentes conocidos
    ADMINS_OFICIALES_FIJOS = {8204833441, 8278899029, 8916842088, 8384683142, 1779560581, 6902578190, 8953593022}
    for hard_admin in ADMINS_OFICIALES_FIJOS:
        admins.add(hard_admin)
    # Identificadores de administradores anónimos en Telegram
    admins.add(1087968824)  # @GroupAnonymousBot
    if target:
        try:
            admins.add(int(target))
        except (ValueError, TypeError):
            pass

    env_admins = os.environ.get("ADMIN_IDS", "") or os.environ.get("ADMIN_ID", "")
    for aid_str in env_admins.replace(",", " ").split():
        if aid_str.strip().isdigit():
            admins.add(int(aid_str.strip()))

    if BOT_TOKEN and target:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatAdministrators?chat_id={target}"
            req = urllib.request.Request(url, headers={"User-Agent": "BotComandos"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
                if data.get("ok"):
                    for item in data.get("result", []):
                        u = item.get("user", {})
                        if u.get("id"):
                            admins.add(int(u["id"]))
        except Exception as e:
            print("Nota obteniendo getChatAdministrators:", e)

    _ADMIN_IDS_CACHE[t_str] = admins
    _ADMIN_IDS_TIMESTAMP[t_str] = ahora
    return admins


def es_mensaje_de_admin(msg: dict, chat_id: int | str) -> bool:
    """Verifica si un mensaje proviene de un administrador o del dueño (incluye administradores anónimos o que envían como el grupo/canal)."""
    from_user = msg.get("from", {})
    user_id = from_user.get("id")

    # Rechazar cualquier bot como administrador (a menos que sea el bot anónimo oficial de Telegram)
    if from_user.get("is_bot") and user_id != 1087968824 and from_user.get("username") != "GroupAnonymousBot":
        return False
    if BOT_ID and user_id == BOT_ID:
        return False

    # 1. Si el mensaje se envió a nombre del grupo o canal
    sender_chat = msg.get("sender_chat")
    if sender_chat:
        sc_id = sender_chat.get("id")
        if sc_id and (str(sc_id) == str(chat_id) or (CHAT_ID and str(sc_id) == str(CHAT_ID))):
            return True

    # 2. Si el remitente es el bot anónimo oficial de Telegram (@GroupAnonymousBot)
    if user_id == 1087968824 or from_user.get("username") == "GroupAnonymousBot":
        return True

    # 3. Verificar si el usuario está en la lista de administradores del grupo
    if user_id:
        admins_set = obtener_admin_ids(chat_id)
        if user_id in admins_set:
            return True

    return False


def generar_texto_miperfil(user_id: int, db_puntos: dict, user_nombre: str = "", es_admin: bool = False) -> str:
    if es_admin:
        nombre = user_nombre or "Administrador"
        return (
            f"👑 **PERFIL DE MODERACIÓN: {nombre}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ **Rol:** Administrador / Moderador de la Sala\n\n"
            "ℹ️ *Los administradores y moderadores están exentos del sistema de puntos y no participan en los rankings ni podios de puntualidad, garantizando una competencia justa y transparente para toda la comunidad.*"
        )

    usuarios = db_puntos.get("usuarios", {})
    u = usuarios.get(str(user_id))
    if not u:
        nombre = user_nombre or "Compañero"
        return (
            f"👤 **Perfil de Asistencia:** {nombre}\n\n"
            f"Aún no registras asistencias válidas en las llamadas.\n"
            f"¡Únete hoy a las 7:56 PM para ganar tus primeros puntos y subir de rango!"
        )
    nombre = u.get("nombre", user_nombre or "Usuario")
    pts_mes = u.get("puntos_mes", u.get("puntos_totales", 0))
    pts_tot = u.get("puntos_totales", 0)
    rango = obtener_rango(pts_tot)
    racha = u.get("racha_actual", 0)
    asistencias_mes = u.get("asistencias_mes", 0)
    asistencias_tot = u.get("asistencias_totales", 0)
    medallas = u.get("medallas", [])
    txt_medallas = "\n• " + "\n• ".join(medallas) if medallas else "Ninguna aún"

    return (
        f"👤 **FICHA DE USUARIO: {nombre}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎖️ **Rango actual:** {rango}\n"
        f"🏆 **Puntos del mes:** {pts_mes} pts\n"
        f"⭐ **Puntos históricos:** {pts_tot} pts\n"
        f"🔥 **Racha actual:** {racha} días consecutivos\n"
        f"📅 **Asistencias:** {asistencias_mes} este mes ({asistencias_tot} en total)\n\n"
        f"🏅 **Medallas obtenidas:**{txt_medallas}"
    )


def generar_texto_ranking(db_puntos: dict, admin_ids: set = None) -> str:
    usuarios = db_puntos.get("usuarios", {})
    if not usuarios:
        return "🏆 **Ranking Mensual:** Aún no hay registros de asistencia este mes."

    if admin_ids is None:
        admin_ids = obtener_admin_ids()

    usuarios_filtrados = [
        u for u in usuarios.values()
        if int(u.get("id", 0)) not in admin_ids
    ]
    if not usuarios_filtrados:
        return "🏆 **Ranking Mensual:** Aún no hay registros de participantes de la comunidad este mes."

    top = sorted(usuarios_filtrados, key=lambda x: x.get("puntos_mes", x.get("puntos_totales", 0)), reverse=True)[:10]
    lineas = [
        "🏆 **TOP 10 DE ASISTENCIA Y PUNTOS (ESTE MES)** 🏆",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    medallas_top = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
    for i, u in enumerate(top):
        pts = u.get("puntos_mes", u.get("puntos_totales", 0))
        rango = obtener_rango(u.get("puntos_totales", 0))
        medallas = " ".join([m.split()[0] for m in u.get("medallas", [])])
        lineas.append(f"{medallas_top[i]} {rango} **{u['nombre']}** — {pts} pts {medallas}".strip())

    lineas.append("\n💡 Escribe `/puntos` para ver tus estadísticas personales.")
    return "\n".join(lineas)


def generar_texto_reglas() -> str:
    return (
        "📜 **SISTEMA DE PUNTOS Y REGLAS DE LA COMUNIDAD**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Cada noche a las 7:56 PM se abre la llamada diaria. ¡Participa y suma puntos!\n\n"
        "⏰ **PUNTUALIDAD:**\n"
        "• Entrar en los primeros 5 min: **+25 pts**\n"
        "• Entrar entre min 5 y 10: **+15 pts**\n\n"
        "🌟 **PERMANENCIA:**\n"
        "• Asistencia completa (>= 80% de la sesión): **+50 pts**\n"
        "• Asistencia parcial: **+20 a +35 pts**\n\n"
        "🎙️ **MICRÓFONO / VOZ:**\n"
        "• Hablar y aportar activamente: **+20 pts**\n\n"
        "🧘 **MEDITACIÓN DIARIA (8:32 PM):**\n"
        "• Participar en la meditación: **+30 pts**\n\n"
        "🔥 **RACHAS:**\n"
        "• Asistir días seguidos: **+5 pts extra por día consecutivo**\n\n"
        "🏅 **MEDALLAS ESPECIALES:**\n"
        "• 🛡️ *Puntualidad de Hierro:* 5 días seguidos en el podio (Top 9 de puntualidad).\n"
        "• 🎙️ *Voz de la Comunidad:* Hablar en 7 llamadas consecutivas.\n"
        "• 🧘 *Mente Serena:* Completar 10 meditaciones en el mes.\n"
        "• 👑 *Centinela:* Asistir a más del 90% de las reuniones del mes.\n\n"
        "👑 **ADMINISTRADORES Y MODERADORES:**\n"
        "• Los administradores y moderadores están exentos del sistema de puntos y no entran en el ranking ni en el podio de puntualidad, garantizando una competencia justa para todos los miembros de la comunidad.\n\n"
        "✋ **TURNOS Y PARTICIPACIÓN:**\n"
        "• Escribe `/turno` en el grupo o levanta la mano ✋ en la sala para coordinar la palabra en orden.\n"
        "• Micrófonos 100% libres y sin cortes automáticos: cada participante gestiona su micrófono de forma responsable.\n\n"
        "📝 **MINUTAS Y ACTAS CON IA:**\n"
        "• Escribe `/resumen` para leer la minuta oficial de la última sesión.\n"
        "• Escribe `/buscar <palabra>` para encontrar temas tratados en llamadas anteriores.\n"
        "• Escribe `/acta [fecha]` para consultar el documento formal.\n\n"
        "👑 **GRABACIÓN (SOLO ADMINS):**\n"
        "• `/estadograbacion` — Consultar estado actual.\n"
        "• `/pausargrabacion` — Pausar la grabación (ej. tema confidencial).\n"
        "• `/reanudargrabacion` — Reanudar la grabación.\n"
        "• `/detenergrabacion` — Cancelar y borrar grabación de hoy.\n\n"
        "💎 **RANGOS:** Bronce (<250) | Plata (250+) | Oro (750+) | Diamante (1800+)\n"
        "¡Los 3 primeros del mes reciben mención de honor!"
    )


def enviar_mensaje(chat_id: int | str, texto: str, reply_to_message_id: int = None, reply_markup: dict = None, link_preview_options: dict = None) -> int | None:
    if not BOT_TOKEN:
        print("BOT_TOKEN no configurado.")
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown",
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if link_preview_options is not None:
        payload["link_preview_options"] = link_preview_options
    else:
        # Forzar vista previa de medios grandes por defecto si el mensaje contiene enlaces
        payload["link_preview_options"] = {
            "is_disabled": False,
            "prefer_large_media": True,
            "show_above_text": False
        }

    datos = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res_data = json.loads(r.read().decode())
            m_id = res_data.get("result", {}).get("message_id")
            if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                registrar_msg_bot(m_id)
            return m_id
    except urllib.error.HTTPError as e_http:
        _cod = e_http.code
        err_body = ""
        try:
            err_body = e_http.read().decode('utf-8', errors='ignore')
        except Exception:
            pass

        # 403 Forbidden o 400 Bad Request por chat no iniciado / bot bloqueado
        es_inaccesible = False
        if _cod == 403:
            es_inaccesible = True
        elif _cod == 400:
            err_lower = err_body.lower()
            if any(k in err_lower for k in ["chat not found", "initiate conversation", "user not found", "bot was blocked", "chat_id is empty", "user_is_blocked"]):
                es_inaccesible = True

        if es_inaccesible:
            marcar_usuario_sin_privado(chat_id)
            log_debug(f"ℹ️ Usuario {chat_id} inaccesible en privado (omitido).")
            return None

        print(f"Error enviando mensaje a {chat_id}: HTTP {_cod} {err_body[:100]}")
        import sys; sys.stdout.flush()

        # Si el error es de formato (Markdown inválido), reintentar sin parse_mode
        if "parse_mode" in payload and any(k in err_body.lower() for k in ["can't parse entities", "parse_mode", "entity"]):
            del payload["parse_mode"]
            datos = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json; charset=utf-8"})
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    res_data = json.loads(r.read().decode())
                    m_id = res_data.get("result", {}).get("message_id")
                    if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                        registrar_msg_bot(m_id)
                    return m_id
            except Exception as e2:
                print(f"Error re-enviando sin formato a {chat_id}:", e2)
                sys.stdout.flush()
        return None
    except Exception as e:
        print(f"Error enviando mensaje a {chat_id}:", e)
        import sys; sys.stdout.flush()
        return None


def enviar_foto(chat_id: int | str, ruta_foto: str, caption: str = "", reply_markup: dict = None) -> int | None:
    if not BOT_TOKEN or not ruta_foto:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {
        "chat_id": str(chat_id),
        "caption": caption,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    # Si es URL remota (ej: miniatura de YouTube)
    if ruta_foto.startswith("http://") or ruta_foto.startswith("https://"):
        data["photo"] = ruta_foto
        try:
            r = requests.post(url, data=data, timeout=30)
            res = r.json()
            if res.get("ok"):
                m_id = res.get("result", {}).get("message_id")
                if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                    registrar_msg_bot(m_id)
                log_debug(f"Foto remota enviada exitosamente a {chat_id}: msg_id={m_id}")
                return m_id
            log_debug(f"Telegram rechazó foto remota ({chat_id}): {res}")
            # Si el rechazo fue por entidades de Markdown inválidas, reintentar sin formato
            if "parse_mode" in data and any(k in str(res).lower() for k in ["can't parse entities", "parse_mode", "entity"]):
                del data["parse_mode"]
                r2 = requests.post(url, data=data, timeout=30)
                res2 = r2.json()
                if res2.get("ok"):
                    m_id = res2.get("result", {}).get("message_id")
                    if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                        registrar_msg_bot(m_id)
                    log_debug(f"Foto remota enviada exitosamente sin formato a {chat_id}: msg_id={m_id}")
                    return m_id
        except Exception as e_url:
            log_debug(f"Error enviando foto remota a {chat_id}: {e_url}")
        return None

    # Si es archivo local
    if not os.path.exists(ruta_foto):
        return None

    try:
        with open(ruta_foto, "rb") as f:
            files = {"photo": (os.path.basename(ruta_foto), f, "image/png")}
            r = requests.post(url, data=data, files=files, timeout=35)
            res = r.json()
            if res.get("ok"):
                m_id = res.get("result", {}).get("message_id")
                if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                    registrar_msg_bot(m_id)
                log_debug(f"Foto enviada exitosamente a {chat_id}: msg_id={m_id}")
                return m_id
            log_debug(f"Telegram rechazó foto ({chat_id}): {res}")
            if "parse_mode" in data and any(k in str(res).lower() for k in ["can't parse entities", "parse_mode", "entity"]):
                del data["parse_mode"]
                f.seek(0)
                files2 = {"photo": (os.path.basename(ruta_foto), f, "image/png")}
                r2 = requests.post(url, data=data, files=files2, timeout=35)
                res2 = r2.json()
                if res2.get("ok"):
                    m_id = res2.get("result", {}).get("message_id")
                    if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                        registrar_msg_bot(m_id)
                    log_debug(f"Foto local enviada exitosamente sin formato a {chat_id}: msg_id={m_id}")
                    return m_id
    except Exception as e:
        log_debug(f"Error enviando foto a {chat_id}: {e}")
    return None


def generar_banner_aviso_previo(ruta_salida: str, info_tarea: dict = None) -> str | None:
    """Genera una tarjeta gráfica de alta resolución en color vívido para el aviso de preparación."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        width, height = 1080, 680
        img = Image.new("RGB", (width, height), color=(15, 23, 42))
        draw = ImageDraw.Draw(img)

        # 1. Fondo degradado de alta gama (Azul cósmico profundo)
        for y in range(height):
            r = int(14 + (28 - 14) * (y / height))
            g = int(20 + (16 - 20) * (y / height))
            b = int(48 + (72 - 48) * (y / height))
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # 2. Borde exterior neón brillante con doble marco
        draw.rounded_rectangle([(16, 16), (width - 16, height - 16)], radius=24, outline=(99, 102, 241), width=3)
        draw.rounded_rectangle([(22, 22), (width - 22, height - 22)], radius=20, outline=(56, 189, 248), width=2)

        # 3. Fuentes compatibles
        font_badge = font_title = font_body = font_bold = font_tarea = None
        for fn in ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]:
            try:
                font_badge = ImageFont.truetype(fn, 34)
                font_title = ImageFont.truetype(fn, 24)
                font_bold = ImageFont.truetype(fn, 21)
                font_tarea = ImageFont.truetype(fn, 19)
                font_body = ImageFont.truetype("segoeui.ttf" if "segoe" in fn else fn, 20)
                break
            except Exception:
                continue
        if not font_badge:
            font_badge = font_title = font_bold = font_body = font_tarea = ImageFont.load_default()

        # 4. Header Badge llamativo (Violeta vibrante con resplandor)
        draw.rounded_rectangle([(45, 38), (width - 45, 128)], radius=18, fill=(67, 24, 255), outline=(147, 197, 253), width=2)
        draw.text((75, 58), "AVISO: SALA DE VOZ EN 30 MINUTOS (7:56 PM)", fill=(255, 255, 255), font=font_badge)

        # 5. Caja de Tarea del Día (Dorado / Ámbar brillante)
        y_caja_start = 148
        if info_tarea:
            draw.rounded_rectangle([(45, y_caja_start), (width - 45, y_caja_start + 65)], radius=14, fill=(120, 53, 15), outline=(245, 158, 11), width=2)
            tipo = info_tarea.get('tipo', 'Meditación').capitalize()
            num = info_tarea.get('numero', '')
            tit = info_tarea.get('titulo', '')
            maestro = info_tarea.get('maestro', '')
            txt_med = f"Sesión de Hoy: {tipo} #{num} - «{tit}» ({maestro})"
            if len(txt_med) > 85:
                txt_med = txt_med[:82] + "..."
            draw.text((70, y_caja_start + 20), txt_med, fill=(254, 243, 199), font=font_tarea)
            y_caja_start += 80

        # 6. Cuadro interior de preparación (Fondo oscuro con borde Cian neón)
        caja_h = 345 if info_tarea else 420
        draw.rounded_rectangle([(45, y_caja_start), (width - 45, y_caja_start + caja_h)], radius=18, fill=(30, 41, 59), outline=(56, 189, 248), width=2)

        draw.text((75, y_caja_start + 22), "CONSEJOS IMPORTANTES ANTES DE ENTRAR A LA SALA:", fill=(56, 189, 248), font=font_title)

        tips = [
            ("1", "Batería:", "Carga tu celular al menos al 50% o déjalo conectado."),
            ("2", "Conexión:", "Usa Wi-Fi o datos estables y evita cambiar de red."),
            ("3", "Android:", "Pon Telegram en 'Sin restricciones' de batería y candado."),
            ("4", "Audio:", "Ten listos tus audífonos para disfrutar la meditación.")
        ]

        y_pos = y_caja_start + 72
        sep = 62 if info_tarea else 78
        for num, tit, desc in tips:
            draw.rounded_rectangle([(75, y_pos), (115, y_pos + 38)], radius=10, fill=(37, 99, 235))
            draw.text((88, y_pos + 7), num, fill=(255, 255, 255), font=font_bold)
            draw.text((130, y_pos + 7), tit, fill=(251, 191, 36), font=font_bold)
            try:
                ancho_tit = draw.textlength(tit, font=font_bold)
            except Exception:
                ancho_tit = len(tit) * 12
            x_desc = 140 + int(ancho_tit)
            draw.text((x_desc, y_pos + 8), desc, fill=(241, 245, 249), font=font_body)
            y_pos += sep

        # 7. Footer
        draw.text((75, height - 52), "Comunidad La Verdad Os Hará Libres  •  Apertura en directo a las 7:56 PM", fill=(148, 163, 184), font=font_body)

        os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
        img.save(ruta_salida, "PNG")
        return ruta_salida
    except Exception as e:
        log_debug(f"Nota generando banner con Pillow: {e}")
        return None


_LOCK_AVISO = threading.Lock()
_FECHA_ULTIMO_AVISO_AUTO: str | None = None


def enviar_aviso_preparacion_sala(target_chat_id=None, forzar=False) -> int | None:
    """Envía el aviso previo. Sin `forzar`, solo se envía una vez por día (Colombia)."""
    global _FECHA_ULTIMO_AVISO_AUTO
    cid = target_chat_id or CHAT_ID
    if not cid:
        log_debug("Aviso previo: CHAT_ID no configurado")
        return None

    fecha_hoy = datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d")
    with _LOCK_AVISO:
        if not forzar and _FECHA_ULTIMO_AVISO_AUTO == fecha_hoy:
            log_debug("Aviso previo ya enviado hoy; se omite duplicado")
            return None
        m_id = _enviar_aviso_preparacion_sala_impl(cid)
        if m_id:
            if not forzar: _FECHA_ULTIMO_AVISO_AUTO = fecha_hoy
        return m_id


def obtener_info_tarea_hoy() -> dict | None:
    """
    Obtiene la información oficial de la tarea programada para HOY de forma robusta.
    1. Si meta_hoy.json existe y su fecha coincide con HOY (DD/MM/AAAA o AAAA-MM-DD), y coincide con el cronograma oficial o override admin, lo usa.
    2. Si meta_hoy.json tiene fecha de un día anterior u otro número, calcula la meditación matemática oficial de hoy.
    3. Consulta cola_hoy.json para hoy si hay una lista de audios programada.
    4. Sincroniza meta_hoy.json para asegurar consistencia atómica.
    """
    tz_col = ZoneInfo("America/Bogota")
    ahora = datetime.now(tz_col)
    if ahora.hour < 4:
        ahora -= timedelta(days=1)
    hoy_str = ahora.strftime("%d/%m/%Y")
    hoy_iso = ahora.strftime("%Y-%m-%d")

    try:
        from schedule_meditaciones import obtener_numero_meditacion_fecha
        num_oficial = obtener_numero_meditacion_fecha(ahora.date())
    except Exception:
        num_oficial = 1095

    info_valida = None

    # 1. Intentar leer meta_hoy.json SOLO si su fecha coincide con HOY
    ruta_meta = os.path.join("data", "meditaciones", "meta_hoy.json")
    if os.path.exists(ruta_meta):
        try:
            with open(ruta_meta, "r", encoding="utf-8") as fm:
                meta = json.load(fm)
            f_meta = meta.get("fecha_tarea_admin") or meta.get("fecha_iso")
            if f_meta and (f_meta == hoy_str or f_meta == hoy_iso):
                # Validar que el número sea el oficial o provenga de un override explícito
                if meta.get("numero") == num_oficial or meta.get("admin_override"):
                    info_valida = meta
        except Exception:
            pass

    # 2. Si meta_hoy.json no es de hoy, no existe o tenía un número incorrecto, usar cálculo oficial por calendario
    if not info_valida:
        info_valida = identificar_audio_catalogo(texto=f"meditacion {num_oficial}")
        if info_valida:
            info_valida["fecha_tarea_admin"] = hoy_str
            info_valida["fecha_iso"] = hoy_iso

    # 3. Revisar si hay audio físico meditacion_hoy.mp3
    if not info_valida:
        ruta_med = os.path.join("data", "meditaciones", "meditacion_hoy.mp3")
        if os.path.exists(ruta_med) and os.path.getsize(ruta_med) > 0:
            info_valida = identificar_audio_catalogo(nombre_archivo=os.path.basename(ruta_med))
            if info_valida:
                info_valida["fecha_tarea_admin"] = hoy_str
                info_valida["fecha_iso"] = hoy_iso

    # 4. Revisar si existe cola_hoy.json para hoy con audios programados / adicionales
    ruta_cola = os.path.join("data", "meditaciones", "cola_hoy.json")
    if os.path.exists(ruta_cola):
        try:
            with open(ruta_cola, "r", encoding="utf-8") as fc:
                dc = json.load(fc)
            f_cola = dc.get("fecha") if isinstance(dc, dict) else None
            if f_cola == hoy_str:
                items_c = dc.get("cola", []) if isinstance(dc, dict) else (dc if isinstance(dc, list) else [])
                validos_c = [it.get("info") for it in items_c if isinstance(it, dict) and it.get("info")]
                if validos_c:
                    # Si la cola solo tiene un audio adicional (ej. Maestro Mario) y falta la meditación oficial de hoy, anteponerla
                    if info_valida and not info_valida.get("es_mario"):
                        num_base = str(info_valida.get("numero", "")).strip()
                        if num_base and not any(str(v.get("numero", "")).strip() == num_base for v in validos_c):
                            base_copia = dict(info_valida)
                            base_copia.pop("cola_audios", None)
                            validos_c.insert(0, base_copia)
                    if len(validos_c) > 1:
                        if not info_valida:
                            info_valida = dict(validos_c[0])
                        info_valida["cola_audios"] = validos_c
        except Exception:
            pass

    # 5. Si logramos resolver info_valida, sincronizar meta_hoy.json para hoy
    if info_valida:
        try:
            os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
            info_guardar = dict(info_valida)
            info_guardar["fecha_tarea_admin"] = hoy_str
            info_guardar["fecha_iso"] = hoy_iso
            with open(ruta_meta, "w", encoding="utf-8") as fm:
                json.dump(info_guardar, fm, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return info_valida


def _enviar_aviso_preparacion_sala_impl(cid) -> int | None:

    # Obtener tarea del día si está disponible
    info_tarea = obtener_info_tarea_hoy()

    txt_med_bloque = ""
    if info_tarea and info_tarea.get("numero"):
        tipo = info_tarea.get("tipo", "Meditación").capitalize()
        num = info_tarea.get("numero")
        tit = info_tarea.get("titulo", "")
        maestro = info_tarea.get("maestro", "")
        txt_med_bloque = f"🧘 **Sesión de Hoy:** {tipo} #{num} — «{tit}» ({maestro})\n"

    # Texto con cuadro de cita / blockquote de Telegram
    caption = (
        "🔔 **RECORDATORIO: SALA DE VOZ EN 30 MINUTOS** ⏰\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🕗 **Apertura de sala:** 7:56 PM Colombia\n"
        f"{txt_med_bloque}"
        "> 📋 **CONSEJOS IMPORTANTES ANTES DE ENTRAR:**\n"
        "> \n"
        "> 🔋 **Batería:** Carga tu dispositivo al menos al 50% o conéctalo.\n"
        "> 📶 **Conexión:** Usa Wi-Fi o datos estables (evita cambiar de red durante la llamada).\n"
        "> ⚙️ **Android:** Ajusta Telegram en *\"Sin restricciones\"* en Batería y fíjalo con candado en apps recientes.\n"
        "> 🔁 **Estabilidad:** Si se cae seguido: *Ajustes > Privacidad > Llamadas > Peer-to-peer > \"Nunca\"*.\n"
        "> 🎧 **Espacio y Audio:** Prepara tus audífonos y busca un lugar tranquilo para la sesión.\n\n"
        "✨ *¡Nos encontramos puntuales a las 7:56 PM para compartir juntos!*"
    )

    bot_u = obtener_info_bot()
    inline_kb = []
    if bot_u:
        inline_kb.append([
            {"text": "🧘 Ver Tarea del Día", "url": f"https://t.me/{bot_u}?start=meditacion"},
            {"text": "🏆 Ranking Mensual", "url": f"https://t.me/{bot_u}?start=ranking"}
        ])
        inline_kb.append([
            {"text": "📜 Reglas de Asistencia y Puntos", "url": f"https://t.me/{bot_u}?start=reglas"}
        ])
    reply_markup = {"inline_keyboard": inline_kb} if inline_kb else None

    # Intentar generar la tarjeta gráfica en color vívido
    ruta_banner = os.path.join("data", "meditaciones", "banner_aviso_previo.png")
    ruta_gen = generar_banner_aviso_previo(ruta_banner, info_tarea=info_tarea)

    m_id = None
    if ruta_gen and os.path.exists(ruta_gen):
        m_id = enviar_foto(cid, ruta_gen, caption=caption, reply_markup=reply_markup)

    # Si falló la foto, enviar mensaje de texto formateado con el cuadro
    if not m_id:
        m_id = enviar_mensaje(cid, caption, reply_markup=reply_markup)

    if m_id:
        log_debug(f"Aviso de preparación enviado con éxito a {cid}: msg_id={m_id}")
    else:
        log_debug(f"❌ Aviso de preparación FALLÓ (foto y texto) para {cid}")
    return m_id


def enviar_audio(chat_id: int | str, ruta_audio: str, caption: str = "", title: str = "Meditación Diaria", performer: str = "Comunidad", reply_markup: dict = None) -> tuple[bool, int | None, str | None]:
    if not BOT_TOKEN or not ruta_audio:
        return False, None, None

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"

    # Si es un file_id de Telegram (no existe como archivo local en disco)
    if not os.path.exists(ruta_audio):
        payload = {
            "chat_id": str(chat_id),
            "audio": str(ruta_audio),
            "caption": caption,
            "parse_mode": "Markdown",
            "title": title,
            "performer": performer,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        try:
            r = requests.post(url, data=payload, timeout=25)
            res = r.json()
            if not res.get("ok") and "parse_mode" in payload:
                payload_fb = dict(payload)
                del payload_fb["parse_mode"]
                r = requests.post(url, data=payload_fb, timeout=25)
                res = r.json()
            if res.get("ok"):
                res_m = res.get("result", {})
                m_id = res_m.get("message_id")
                if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                    registrar_msg_bot(m_id)
                f_id = (res_m.get("audio") or res_m.get("document") or {}).get("file_id") or ruta_audio
                log_debug(f"Audio enviado vía file_id a {chat_id}: msg_id={m_id}")
                return True, m_id, f_id
            log_debug(f"Telegram rechazó audio file_id ({chat_id}): {res}")
            return False, None, None
        except Exception as e:
            log_debug(f"Error enviando audio por file_id a {chat_id}: {e}")
            return False, None, None

    # Si es archivo local en disco
    data = {
        "chat_id": str(chat_id),
        "caption": caption,
        "parse_mode": "Markdown",
        "title": title,
        "performer": performer,
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    try:
        t_inicio = time.time()
        tam_mb = round(os.path.getsize(ruta_audio) / (1024 * 1024), 2)
        nombre_subida = os.path.basename(ruta_audio)
        if title and title != "Meditación Diaria":
            limpio = re.sub(r'[\\/*?:"<>|]', "", title).strip()
            if limpio:
                nombre_subida = f"{limpio}.mp3"
        log_debug(f"Iniciando subida de audio local a {chat_id} ({nombre_subida}, {tam_mb} MB)...")
        with open(ruta_audio, "rb") as f:
            files = {"audio": (nombre_subida, f, "audio/mpeg")}
            r = requests.post(url, data=data, files=files, timeout=180)
            res = r.json()
            if not res.get("ok") and "parse_mode" in data:
                data_fb = dict(data)
                del data_fb["parse_mode"]
                f.seek(0)
                files_fb = {"audio": (nombre_subida, f, "audio/mpeg")}
                r = requests.post(url, data=data_fb, files=files_fb, timeout=180)
                res = r.json()
            if res.get("ok"):
                res_m = res.get("result", {})
                m_id = res_m.get("message_id")
                if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                    registrar_msg_bot(m_id)
                f_id = (res_m.get("audio") or res_m.get("document") or {}).get("file_id")
                dur = round(time.time() - t_inicio, 1)
                log_debug(f"Audio subido con éxito a {chat_id} en {dur}s: msg_id={m_id}, file_id={f_id}")
                return True, m_id, f_id
            log_debug(f"Telegram rechazó audio local ({chat_id}): {res}")
            return False, None, None
    except Exception as e:
        log_debug(f"Error enviando audio local a {chat_id}: {e}")
        return False, None, None


def copiar_mensaje(chat_id: int | str, from_chat_id: int | str, message_id: int | str, caption: str = "") -> bool:
    if not BOT_TOKEN or not from_chat_id or not message_id:
        return False
    m_id = int(str(message_id).strip()) if str(message_id).strip().isdigit() else message_id
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
    payload = {
        "chat_id": chat_id,
        "from_chat_id": from_chat_id,
        "message_id": m_id,
    }
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "Markdown"
    datos = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode())
            if res.get("ok"):
                c_id = res.get("result", {}).get("message_id")
                if c_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                    registrar_msg_bot(c_id)
                print(f"Audio copiado de {from_chat_id}:{m_id} a {chat_id}")
                return True
    except Exception as e:
        print(f"Nota copyMessage {from_chat_id}:{m_id} -> {chat_id}:", e)

    # Fallback con forwardMessage
    try:
        url_fwd = f"https://api.telegram.org/bot{BOT_TOKEN}/forwardMessage"
        payload_fwd = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": m_id,
        }
        req_fwd = urllib.request.Request(url_fwd, data=json.dumps(payload_fwd).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req_fwd, timeout=15) as rf:
            res_fwd = json.loads(rf.read().decode())
            if res_fwd.get("ok"):
                f_id = res_fwd.get("result", {}).get("message_id")
                if f_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                    registrar_msg_bot(f_id)
                print(f"Audio reenviado a {chat_id}")
                return True
    except Exception as ef:
        print(f"Nota forwardMessage {from_chat_id}:{m_id} -> {chat_id}:", ef)

    return False


def entregar_audio_meditacion(chat_id: int | str, info_cat: dict, msg_id_reply: int | str = None, user_id_privado: int | str = None) -> None:
    if not info_cat:
        info_cat = obtener_info_tarea_hoy()

    if not info_cat:
        enviar_mensaje(
            chat_id,
            "🧘 **Meditación Diaria:**\nAún no hay un audio de meditación disponible para hoy. Puedes consultar el catálogo escribiendo `/meditacion [número]` o `/mensaje [número]`.",
            reply_to_message_id=msg_id_reply
        )
        return

    # Si hay una cola con múltiples audios programados, entregar cada uno en orden
    cola_audios = info_cat.get("cola_audios")
    if cola_audios and isinstance(cola_audios, list) and len(cola_audios) > 1:
        for sub_info in cola_audios:
            if isinstance(sub_info, dict):
                sub_copy = dict(sub_info)
                sub_copy.pop("cola_audios", None)
                entregar_audio_meditacion(chat_id, sub_copy, msg_id_reply=msg_id_reply, user_id_privado=user_id_privado)
        return

    tipo_nombre = info_cat.get('tipo', 'Meditación').title()
    num = str(info_cat.get('numero', '')).strip()
    titulo = info_cat.get('titulo', '')
    maestro = info_cat.get('maestro', 'Comunidad')
    fecha = info_cat.get("fecha_original") or info_cat.get("fecha", "")
    vid_cat = str(info_cat.get("video_id", "")).strip()
    es_mario_cat = bool(info_cat.get("es_mario") or "MARIO CARRILLO" in maestro.upper() or "MARIO CARRILLO" in str(titulo).upper())

    if es_mario_cat:
        caption = (
            f"🧘 **MENSAJE DEL MAESTRO JESUS MARIO CARRILLO DURAN**\n"
            f"📌 **Título:** «{titulo}»\n"
            f"👤 **Maestro:** JESUS MARIO CARRILLO DURAN\n"
            f"🗓️ **Grabación original:** {fecha}\n\n"
            "🎧 Audio adicional programado para sonar 30 minutos después de finalizar la primera meditación."
        )
        title = f"Mensaje - {titulo}"
        performer = "JESUS MARIO CARRILLO DURAN"
    else:
        caption = (
            f"🧘 **{tipo_nombre} #{num}**\n"
            f"📌 **Título:** «{titulo}»\n"
            f"👤 **Maestro:** {maestro}\n"
            f"🗓️ **Grabación original:** {fecha}\n\n"
            "🎧 Audio para tu práctica en diferido."
        )
        title = f"{tipo_nombre} #{num} - {titulo}"
        performer = maestro

    bot_u = obtener_info_bot()
    clean_tipo = "mensaje" if "MENSAJE" in tipo_nombre.upper() else "meditacion"
    param_audio = f"audio_{clean_tipo}_{num}" if num else "audio"
    teclado_grupo = {"inline_keyboard": [[{"text": "📥 RECIBIR AUDIO EN MI TELEGRAM PRIVADO 🎧", "url": f"https://t.me/{bot_u}?start={param_audio}"}]]} if (int(chat_id) < 0 and bot_u) else None

    def enviar_copia_privada(ref_audio):
        if user_id_privado and str(user_id_privado) != str(chat_id) and int(user_id_privado) > 0:
            try:
                enviar_audio(user_id_privado, ref_audio, caption=caption, title=title, performer=performer)
            except Exception:
                pass

    # 1. Buscar en fuentes de audio disponibles
    # A) file_id directo en info_cat
    audio_file_id = info_cat.get("file_id")

    # B) file_id en la tarea oficial de hoy (solo si no es un audio adicional sin número)
    meta_hoy = obtener_info_tarea_hoy() or {}

    if not audio_file_id and meta_hoy and not es_mario_cat and not vid_cat:
        if not num or str(meta_hoy.get("numero", "")).strip() == num:
            audio_file_id = meta_hoy.get("file_id")

    # C) file_id en base de datos de audios registrados
    db_audios = cargar_audios_registrados()
    if not audio_file_id and db_audios:
        reg = None
        if vid_cat:
            reg = db_audios.get(f"YT_{vid_cat}")
        if not reg and num:
            reg = db_audios.get(f"{tipo_nombre.upper()}_{num}") or db_audios.get(num)
        if reg:
            audio_file_id = reg.get("file_id")

    # Intentar enviar vía file_id si lo tenemos
    if audio_file_id:
        ok, m_id, f_id = enviar_audio(chat_id, audio_file_id, caption=caption, title=title, performer=performer, reply_markup=teclado_grupo)
        if ok:
            enviar_copia_privada(audio_file_id)
            return

    # D) Buscar archivo local en disco
    ruta_local = None
    audio_path_cat = info_cat.get("audio_path")
    if audio_path_cat and os.path.exists(audio_path_cat) and os.path.getsize(audio_path_cat) > 1000:
        ruta_local = audio_path_cat
    elif vid_cat:
        for cand_yt in [
            os.path.join("data", "meditaciones", f"yt_dl_{vid_cat}.mp3"),
            os.path.join("data", "meditaciones", "meditacion_hoy_2.mp3"),
        ]:
            if os.path.exists(cand_yt) and os.path.getsize(cand_yt) > 1000:
                ruta_local = cand_yt
                break
    else:
        ruta_med_hoy = os.path.join("data", "meditaciones", "meditacion_hoy.mp3")
        if (not num or (meta_hoy and str(meta_hoy.get("numero", "")).strip() == num)) and os.path.exists(ruta_med_hoy) and os.path.getsize(ruta_med_hoy) > 0:
            ruta_local = ruta_med_hoy
        else:
            for f_name in [f"meditacion_{num}.mp3", f"mensaje_{num}.mp3", f"{num}.mp3"]:
                candidato = os.path.join("data", "meditaciones", f_name)
                if os.path.exists(candidato) and os.path.getsize(candidato) > 0:
                    ruta_local = candidato
                    break

    if ruta_local:
        ok, m_id, f_id = enviar_audio(chat_id, ruta_local, caption=caption, title=title, performer=performer, reply_markup=teclado_grupo)
        if ok:
            if f_id:
                guardar_audio_registrado(info_cat, file_id=f_id, msg_id=m_id)
            enviar_copia_privada(f_id or ruta_local)
            return

    # E) Intentar copiar mensaje directamente desde el grupo oficial si conocemos el msg_id
    msg_id_audio = info_cat.get("msg_id_audio")
    if not msg_id_audio and meta_hoy and not es_mario_cat and (not num or str(meta_hoy.get("numero", "")).strip() == num):
        msg_id_audio = meta_hoy.get("msg_id_audio")
    if not msg_id_audio and db_audios:
        reg = db_audios.get(f"YT_{vid_cat}") if vid_cat else (db_audios.get(f"{tipo_nombre.upper()}_{num}") or db_audios.get(num))
        if reg:
            msg_id_audio = reg.get("msg_id_audio")

    origen_grupo = CHAT_ID or meta_hoy.get("chat_id_grupo")
    if msg_id_audio and origen_grupo:
        if copiar_mensaje(chat_id, origen_grupo, msg_id_audio, caption=caption):
            enviar_copia_privada(audio_file_id)
            return

    # F) Descargar automáticamente desde Google Drive!
    if num and num.isdigit():
        t_nombre = "Meditación" if "MEDITACI" in str(tipo_nombre).upper() else ("Mensaje" if "MENSAJE" in str(tipo_nombre).upper() else tipo_nombre)
        enviar_mensaje(chat_id, f"🔍 Buscando audio para {t_nombre} #{num}...", reply_to_message_id=msg_id_reply)
        ruta_drive = obtener_o_descargar_audio(tipo_nombre, int(num))
        if ruta_drive:
            ok, m_id, f_id = enviar_audio(chat_id, ruta_drive, caption=caption, title=title, performer=performer, reply_markup=teclado_grupo)
            if ok:
                if f_id:
                    guardar_audio_registrado(info_cat, file_id=f_id, msg_id=m_id)
                enviar_copia_privada(f_id or ruta_drive)
                return

    # G) Si aún no está cargado el archivo en ninguna fuente
    txt_cat = (
        f"🧘 **CATÁLOGO OFICIAL DE AUDIOS**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 **{tipo_nombre} #{num}:** «{titulo}»\n"
        f"👤 **Maestro:** {maestro}\n"
        f"🗓️ **Fecha de grabación original:** {fecha}\n\n"
        f"ℹ️ El archivo .mp3 correspondiente aún no se encuentra registrado en el almacenamiento del bot ni en la carpeta de Google Drive.\n\n"
        f"💡 **Para administradores:** Puedes enviar o reenviar el archivo de audio directamente a este chat privado para vincularlo a la meditación #{num}."
    )
    enviar_mensaje(chat_id, txt_cat, reply_to_message_id=msg_id_reply)


def enviar_documento(chat_id: int | str, ruta_doc: str, caption: str = "") -> None:
    if not BOT_TOKEN or not os.path.exists(ruta_doc):
        return
    boundary = "----WebKitFormBoundaryDoc7MA4YWxk"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"

    try:
        with open(ruta_doc, "rb") as f:
            file_bytes = f.read()

        body = bytearray()
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode())
        if caption:
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode())

        filename = os.path.basename(ruta_doc)
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\nContent-Type: application/pdf\r\n\r\n".encode())
        body.extend(file_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            url,
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            res_doc = json.loads(r.read().decode())
            d_id = res_doc.get("result", {}).get("message_id")
            if d_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                registrar_msg_bot(d_id)
            print(f"Documento enviado a {chat_id}:", r.status)
    except Exception as e:
        print(f"Error enviando documento a {chat_id}:", e)


def responder_consulta_biblioteca(chat_id: int | str, texto: str, msg_id_reply: int | str = None, from_u: dict = None) -> bool:
    """Busca exclusivamente en la base de datos de transcripciones de YouTube (Biblioteca)."""
    t_limpio = texto.lower()
    for drop_w in ["biblioteca", "conocimiento", "universal", "toby", "asistente", "busca", "buscame",
                     "donde", "habla", "sobre", "que dice", "qué dice", "en la", "de la", "del",
                     "dime", "cuéntame", "cuentame", "explica", "explicame", "explícame",
                     "pregunta", "encuentra", "hay", "los", "las", "con", "por", "para",
                     "una", "uno", "que", "qué", "quién", "quien", "cómo", "como", "cuál", "cual",
                     "enseñanza", "enseñanzas", "video", "videos", "tema"]:
        t_limpio = t_limpio.replace(drop_w, " ")
    palabras = [p for p in t_limpio.strip().split() if len(p) > 2]
    
    if not palabras:
        enviar_mensaje(chat_id, "📚 Para consultar la **Biblioteca Conocimiento Universal**, escribe qué tema deseas buscar. Ejemplo:\n*«Toby busca en la biblioteca sobre los 144.000»*", reply_to_message_id=msg_id_reply)
        return True

    enviar_mensaje(chat_id, "🔍 *Buscando en la Biblioteca Conocimiento Universal...*", reply_to_message_id=msg_id_reply)

    # Registrar auditoría
    try:
        os.makedirs("data", exist_ok=True)
        auditoria_path = os.path.join("data", "auditoria_consultas.json")
        consultas = []
        if os.path.exists(auditoria_path):
            try:
                with open(auditoria_path, "r", encoding="utf-8") as f_aud:
                    consultas = json.load(f_aud)
            except Exception:
                pass
        consultas.append({
            "fecha": datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d %H:%M:%S"),
            "usuario_id": (from_u or {}).get("id"),
            "nombre": (from_u or {}).get("first_name", "Usuario"),
            "pregunta": texto
        })
        with open(auditoria_path, "w", encoding="utf-8") as f_aud:
            json.dump(consultas, f_aud, indent=4, ensure_ascii=False)
    except Exception:
        pass

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # MOTOR DE BÚSQUEDA BIBLIOTECA (Base unificada: biblioteca_v2.db)
    # V2 controlado por variable de entorno BUSQUEDA_V2 (OFF por defecto: "0")
    # Si BUSQUEDA_V2=0 o si V2 falla, ejecuta automáticamente V1 sobre la misma base
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    db_activa = DB_BIBLIO_PATH if os.path.exists(DB_BIBLIO_PATH) else os.path.join("data", "biblioteca_conocimiento_universal.db")

    if os.environ.get("BUSQUEDA_V2", "0") == "1":
        if os.path.exists(DB_BIBLIO_PATH):
            try:
                from buscador_biblioteca_v2 import buscar_v2
                conn_v2 = sqlite3.connect(DB_BIBLIO_PATH)
                resultados_v2 = buscar_v2(conn_v2, texto, limit=5, max_por_video=2)
                conn_v2.close()

                if resultados_v2:
                    nombre_u = ((from_u or {}).get("first_name") or (from_u or {}).get("username") or "").strip()
                    saludo_u = f"**{nombre_u}** " if nombre_u else ""
                    resp = f"📚 {saludo_u}Aquí tienes lo que encontré en la Biblioteca del Conocimiento Universal (Motor V2):\n\n"
                    for idx, r in enumerate(resultados_v2):
                        seg = r["inicio_segundos"]
                        m = seg // 60
                        s = seg % 60
                        seg_link = r.get("inicio_link_segundos", max(0, seg - 5))
                        url = f"https://youtu.be/{r['video_id']}?t={seg_link}"
                        resp += f"**{idx+1}. {r['titulo']}**\n"
                        resp += f"⏱️ *Minuto:* [{m:02d}:{s:02d}]({url})\n"
                        txt_mostrar = r["texto"].strip()
                        if len(txt_mostrar) > 180:
                            txt_mostrar = txt_mostrar[:180] + "..."
                        resp += f"💬 \"{txt_mostrar}\"\n\n"

                    reply_markup = None
                    if str(chat_id).startswith("-"):
                        reply_markup = {
                            "inline_keyboard": [
                                [{"text": "📩 Enviar a mi Telegram Privado", "callback_data": "biblio_priv"}]
                            ]
                        }
                    m_id = enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id_reply, reply_markup=reply_markup)
                    if m_id:
                        _CACHE_RESPUESTAS_BIBLIO[str(m_id)] = resp
                        if len(_CACHE_RESPUESTAS_BIBLIO) > 200:
                            _CACHE_RESPUESTAS_BIBLIO.pop(next(iter(_CACHE_RESPUESTAS_BIBLIO)), None)
                    return True
                else:
                    enviar_mensaje(chat_id, "😔 No encontré ninguna enseñanza sobre ese tema en la Biblioteca. Intenta con otros términos clave.", reply_to_message_id=msg_id_reply)
                    return True
            except Exception as e_v2:
                print(f"[Biblioteca V2] Error en motor V2, ejecutando fallback automático a V1: {e_v2}")

    # Búsqueda V1 tradicional (funciona sobre la base unificada biblioteca_v2.db)
    if not os.path.exists(db_activa):
        enviar_mensaje(chat_id, "⏳ La Biblioteca de transcripciones aún se está construyendo. Intenta más tarde.", reply_to_message_id=msg_id_reply)
        return True

    try:
        conn = sqlite3.connect(db_activa)
        c = conn.cursor()
        conditions = []
        params = []
        for p in palabras:
            if len(p) > 3:
                conditions.append("t.texto LIKE ?")
                params.append(f"%{p}%")
        if not conditions:
            conditions = ["t.texto LIKE ?"]
            params = [f"%{' '.join(palabras)}%"]

        query = "SELECT v.titulo, t.inicio_segundos, t.texto, v.video_id FROM transcripciones t INNER JOIN videos v ON t.video_id = v.video_id WHERE "
        query += " AND ".join(conditions) + " LIMIT 3"
        c.execute(query, params)
        resultados = c.fetchall()
        conn.close()

        if resultados:
            nombre_u = ((from_u or {}).get("first_name") or (from_u or {}).get("username") or "").strip()
            saludo_u = f"**{nombre_u}** " if nombre_u else ""
            resp = f"📚 {saludo_u}Aquí tienes lo que encontré en la Biblioteca del Conocimiento Universal dentro de los videos del Maestro Jesus Mario Carrillo y los Guardianes del Universo:\n\n"
            for idx, (titulo, seg, txt_frag, vid) in enumerate(resultados):
                m = seg // 60
                s = seg % 60
                url = f"https://youtu.be/{vid}?t={seg}"
                resp += f"**{idx+1}. {titulo}**\n"
                resp += f"⏱️ *Minuto:* [{m:02d}:{s:02d}]({url})\n"
                resp += f"💬 \"{txt_frag[:120]}...\"\n\n"
            reply_markup = None
            if str(chat_id).startswith("-"):
                reply_markup = {
                    "inline_keyboard": [
                        [{"text": "📩 Enviar a mi Telegram Privado", "callback_data": "biblio_priv"}]
                    ]
                }
            m_id = enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id_reply, reply_markup=reply_markup)
            if m_id:
                _CACHE_RESPUESTAS_BIBLIO[str(m_id)] = resp
                if len(_CACHE_RESPUESTAS_BIBLIO) > 200:
                    _CACHE_RESPUESTAS_BIBLIO.pop(next(iter(_CACHE_RESPUESTAS_BIBLIO)), None)
        else:
            enviar_mensaje(chat_id, "😔 No encontré ninguna enseñanza exacta con esas palabras en la Biblioteca. Intenta con otros términos clave.", reply_to_message_id=msg_id_reply)
    except Exception as e:
        enviar_mensaje(chat_id, f"⚠️ Error consultando la Biblioteca: {e}", reply_to_message_id=msg_id_reply)

    return True


def es_solicitud_de_audio(texto: str, chat_id: int | str) -> bool:
    """
    Detecta si un mensaje es una pregunta o petición de un audio del catálogo (meditación o mensaje).
    Ejemplos:
      - 'tienes el mensaje 989?'
      - '¿Tienes la meditacion 21?'
      - 'me pasas el mensaje 800'
      - 'audio del mensaje 989'
      - 'meditacion 21' (en privado o grupo)
    """
    if not texto:
        return False
    t_up = texto.upper()

    # Si es declaración de tarea diaria para el grupo, no es solicitud individual
    if any(k in t_up for k in ["TAREA PARA MAÑANA", "TAREA PARA MANANA", "MEDITACION DE TAREA", "MENSAJE DE TAREA", "TAREA DE MEDITACION", "TAREA DE MENSAJE"]):
        return False

    tiene_palabra_audio = any(w in t_up for w in ["MEDITACION", "MEDITACIÓN", "MENSAJE", "AUDIO"])
    tiene_numero = bool(re.search(r"\b\d{1,4}\b", t_up))

    if not (tiene_palabra_audio and tiene_numero):
        return False

    # En chat privado (chat_id > 0), cualquier mención de meditación/mensaje con número es para el bot
    if int(chat_id) > 0:
        return True

    # En grupos (chat_id < 0), verificar que sea una pregunta o petición
    verbos = [
        "TIENES", "TIENE", "TIENEN", "HAY", "PASAME", "PASA", "PASAS",
        "COMPARTE", "COMPARTIR", "QUIERO", "QUISIERA", "ENVIAME", "ENVIA",
        "MANDAME", "MANDA", "AUDIO DE", "AUDIO DEL", "BUSCA", "BUSCAR",
        "REGALAME", "ME DAS", "ME PASAS", "QUIEN TIENE", "ALGUIEN TIENE",
        "POR FAVOR", "DESCARGAR", "SUBIR", "DONDE ESTA", "¿TIENES", "¿HAY",
        "DISPONIBLE", "COMPARTEN"
    ]
    if any(v in t_up for v in verbos):
        return True

    if re.match(r"^(?:AUDIO\s+)?(?:MEDITACI[OÓ]N|MENSAJE)\s+#?\d{1,4}", t_up.strip()):
        return True
    if re.match(r"^AUDIO\s+#?\d{1,4}", t_up.strip()):
        return True

    return False


def _limpiar_avisos_descarga_colgados(chat_destino) -> None:
    """No usar TG_SESSION en Render para evitar AuthKeyDuplicatedError con GitHub Actions."""
    return


_TIMER_TAREA_ADICIONAL = {"vid": None}


def procesar_programacion_yttarea(vid_tarea: str, u_admin_id: int | str = None, chat_destino: int | str = None) -> None:
    chat_destino = chat_destino or CHAT_ID
    if not chat_destino:
        return
    url_yt = f"https://www.youtube.com/watch?v={vid_tarea}"
    from radar_youtube import CANALES_RADAR, extraer_entradas_xml, obtener_titulo_video, obtener_info_oembed
    import shutil
    import glob

    # Limpiar posibles mensajes colgados previos en segundo plano
    threading.Thread(target=_limpiar_avisos_descarga_colgados, args=(chat_destino,), daemon=True).start()

    # Obtener metadatos del video mediante oEmbed y CANALES_RADAR
    info_oe = obtener_info_oembed(vid_tarea)
    tit_found = info_oe.get("title", "").strip() or obtener_titulo_video(vid_tarea)
    autor_oe = info_oe.get("author_name", "").strip()
    autor_url = info_oe.get("author_url", "").strip()

    canal_nom = autor_oe or "ALANISO"
    for c_r in CANALES_RADAR:
        if c_r.get("nombre", "").lower() in autor_oe.lower() or c_r.get("handle", "").lower() in autor_url.lower():
            canal_nom = c_r.get("nombre", canal_nom)
            break

    es_mario = (
        any(k in autor_oe.upper() for k in ["MARIO", "CARRILLO"])
        or any(k in autor_url.lower() for k in ["mariocarrillo", "@mariocarrillo"])
        or any(k in str(canal_nom).upper() for k in ["MARIO", "CARRILLO"])
        or any(k in tit_found.upper() for k in ["MARIO CARRILLO", "JESUS MARIO", "JESÚS MARIO"])
        or vid_tarea == "v5zwtMKOj3A"
    )

    tipo_aviso = "Tarea Adicional" if es_mario else "Tarea Oficial"
    m_prog = enviar_mensaje(
        chat_destino,
        f"⏳ **Descargando audio de YouTube y programando como {tipo_aviso}...**\n📺 https://www.youtube.com/watch?v={vid_tarea}\n*Por favor espera un momento mientras procesamos el archivo.*"
    )

    if not tit_found:
        for c_r in CANALES_RADAR:
            try:
                u_rss = f"https://www.youtube.com/feeds/videos.xml?channel_id={c_r['id']}"
                r_rss = urllib.request.Request(u_rss, headers={'User-Agent': 'Mozilla/5.0'})
                xml_rss = urllib.request.urlopen(r_rss, timeout=6).read().decode('utf-8', errors='ignore')
                for ent in extraer_entradas_xml(xml_rss):
                    if ent["video_id"] == vid_tarea:
                        tit_found = ent["titulo"]
                        canal_nom = c_r.get("nombre", canal_nom)
                        break
            except Exception:
                pass
            if tit_found:
                break

    if not tit_found:
        try:
            res_tit = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "--extractor-args", "youtube:player_client=android,mweb", "--print", "%(title)s", url_yt],
                capture_output=True, text=True, timeout=15
            )
            if res_tit.returncode == 0 and res_tit.stdout.strip():
                tit_found = res_tit.stdout.strip()
        except Exception:
            pass

    if not tit_found:
        tit_found = "El significado .de los 666y el signo del poder de la bestia$$$" if vid_tarea == "v5zwtMKOj3A" else f"Enseñanza / Práctica {vid_tarea}"

    # Descargar o reutilizar audio en disco de forma robusta
    archivo_descargado = descargar_audio_youtube_robusto(vid_tarea, tit_found)


    ahora_col = datetime.now(ZoneInfo("America/Bogota"))
    fecha_hoy_str = ahora_col.strftime("%d/%m/%Y")

    # Revisar lista/cola existente de hoy
    cola_existente = []
    ruta_cola = os.path.join(carp_med, "cola_hoy.json")
    if os.path.exists(ruta_cola):
        try:
            with open(ruta_cola, "r", encoding="utf-8") as fc:
                d_c = json.load(fc)
                if isinstance(d_c, dict) and d_c.get("fecha") == fecha_hoy_str:
                    cola_existente = d_c.get("cola", [])
        except Exception:
            pass

    # Asegurar que la Pista #1 sea siempre la meditación oficial del día cuando se agrega un audio adicional
    if es_mario and (not cola_existente or all((c.get("info") or {}).get("es_mario") for c in cola_existente)):
        info_base = obtener_info_tarea_hoy()
        if info_base and not info_base.get("es_mario"):
            info_base_clean = dict(info_base)
            info_base_clean.pop("cola_audios", None)
            r_med1 = info_base_clean.get("audio_path") or os.path.join(carp_med, "meditacion_hoy.mp3")
            pista_base = {
                "ruta": os.path.abspath(r_med1),
                "info": info_base_clean,
                "titulo": f"{info_base_clean.get('tipo', 'Meditación').title()} #{info_base_clean.get('numero', '')} - {info_base_clean.get('titulo', '')}".strip(" -#")
            }
            cola_existente = [pista_base] + [c for c in cola_existente if (c.get("info") or {}).get("video_id") != vid_tarea]

    if es_mario:
        idx_pista = max(2, len(cola_existente) + 1)
        ruta_mp3_hoy = os.path.join(carp_med, f"meditacion_hoy_{idx_pista}.mp3")
    else:
        ruta_mp3_hoy = os.path.join(carp_med, "meditacion_hoy.mp3")

    if os.path.exists(archivo_descargado) and os.path.getsize(archivo_descargado) > 1000:
        if os.path.abspath(archivo_descargado) != os.path.abspath(ruta_mp3_hoy):
            shutil.copy2(archivo_descargado, ruta_mp3_hoy)

    if es_mario:
        tipo_t = "MENSAJE"
        num_t = ""
        t_nom = "Mensaje"
        info_cat = {
            "numero": "",
            "tipo": "MENSAJE",
            "titulo": tit_found,
            "maestro": "JESUS MARIO CARRILLO DURAN",
            "fecha": fecha_hoy_str,
            "fecha_tarea_admin": fecha_hoy_str,
            "url_youtube": url_yt,
            "video_id": vid_tarea,
            "fuente": "YOUTUBE",
            "canal": "Maestro Mario Carrillo",
            "es_mario": True,
            "es_adicional": True,
            "espera_post_meditacion_min": 30,
            "audio_path": os.path.abspath(ruta_mp3_hoy)
        }
    else:
        info_cat = identificar_audio_catalogo(texto=tit_found or vid_tarea)
        if not info_cat:
            tit_up = tit_found.upper()
            tipo_t = "MENSAJE" if "MENSAJE" in tit_up else "MEDITACION"
            m_num = re.search(r'(?:#|N[°º]|NUMERO\s*|NO\.\s*)?(\b\d{1,4}\b)', tit_found, re.IGNORECASE)
            num_t = m_num.group(1) if m_num else ""
            t_nom = "Meditación" if "MEDITACI" in str(tipo_t).upper() else "Mensaje"
            mae_t = "Alaniso"
            if "GUARDIANES" in tit_up:
                mae_t = "Guardianes del Universo"
            elif "ALANISO" in tit_up or "ALANISO" in str(canal_nom).upper():
                mae_t = "Alaniso"

            info_cat = {
                "numero": num_t,
                "tipo": tipo_t,
                "titulo": tit_found,
                "maestro": mae_t,
                "fecha": fecha_hoy_str,
                "fecha_tarea_admin": fecha_hoy_str,
                "url_youtube": url_yt,
                "video_id": vid_tarea,
                "fuente": "YOUTUBE",
                "audio_path": os.path.abspath(ruta_mp3_hoy)
            }
        else:
            info_cat["url_youtube"] = url_yt
            info_cat["video_id"] = vid_tarea
            info_cat["fecha_tarea_admin"] = fecha_hoy_str
            info_cat["audio_path"] = os.path.abspath(ruta_mp3_hoy)
            tipo_t = info_cat.get("tipo", "MEDITACION")
            num_t = info_cat.get("numero", "")
            t_nom = "Meditación" if "MEDITACI" in str(tipo_t).upper() else "Mensaje"

    if es_mario:
        cap_audio = (
            f"🧘 **MENSAJE DEL MAESTRO JESUS MARIO CARRILLO DURAN**\n"
            f"📌 **Título:** «{info_cat.get('titulo', '')}»\n"
            f"👤 **Maestro:** JESUS MARIO CARRILLO DURAN\n"
            f"🗓️ **Grabación original:** {fecha_hoy_str}\n\n"
            f"🎧 Audio adicional preparado para sonar en la reunión de hoy a las 7:56 PM (30 minutos después de terminar la meditación)."
        )
        perf_aud = "JESUS MARIO CARRILLO DURAN"
        tit_aud = f"MENSAJE DEL MAESTRO JESUS MARIO CARRILLO DURAN - {info_cat.get('titulo', '')} (Encolado +30 min)"
    else:
        cap_audio = (
            f"🧘 **{t_nom} #{num_t}**\n" if num_t else f"🧘 **{t_nom} Especial**\n"
        ) + (
            f"📌 **Título:** «{info_cat.get('titulo', '')}»\n"
            f"👤 **Maestro:** {info_cat.get('maestro', 'Alaniso')}\n"
            f"🗓️ **Grabación / YouTube:** {fecha_hoy_str}\n\n"
            f"🎧 Audio oficial preparado para la práctica de hoy a las 7:56 PM."
        )
        perf_aud = info_cat.get('maestro', 'Alaniso')
        tit_aud = f"{t_nom} #{num_t} - {info_cat.get('titulo', '')}" if num_t else info_cat.get('titulo', '')

    bot_u = obtener_info_bot()
    param_priv = f"audio_yt_{vid_tarea}" if es_mario else (f"audio_{tipo_t.lower()}_{num_t}" if num_t else "audio")
    teclado_aud = {"inline_keyboard": [[{"text": "📥 RECIBIR AUDIO EN MI TELEGRAM PRIVADO 🎧", "url": f"https://t.me/{bot_u}?start={param_priv}"}]]} if bot_u else None

    msg_id_audio_final = None
    if os.path.exists(ruta_mp3_hoy) and os.path.getsize(ruta_mp3_hoy) > 1000:
        ok_a, m_id_a, f_id_a = enviar_audio(
            chat_destino,
            ruta_mp3_hoy,
            caption=cap_audio,
            title=tit_aud,
            performer=perf_aud,
            reply_markup=teclado_aud
        )
        if ok_a:
            msg_id_audio_final = m_id_a
            info_cat["file_id"] = f_id_a
            info_cat["msg_id_audio"] = m_id_a

    # Eliminar aviso de '⏳ Descargando...' inmediatamente tras subir el audio
    if m_prog:
        eliminar_mensaje(chat_destino, m_prog)

    # Actualizar cola_hoy.json y meta_hoy.json (conservando cola_audios y file_id)
    if es_mario:
        item_mario = {
            "ruta": os.path.abspath(ruta_mp3_hoy),
            "info": info_cat,
            "titulo": f"MENSAJE DEL MAESTRO JESUS MARIO CARRILLO DURAN: «{tit_found}»"
        }
        cola_filtrada = [c for c in cola_existente if (c.get("info") or {}).get("video_id") != vid_tarea]
        cola_final = cola_filtrada + [item_mario]

        payload_cola = {"fecha": fecha_hoy_str, "cola": cola_final}
        with open(os.path.join(carp_med, "cola_hoy.json"), "w", encoding="utf-8") as f_cj:
            json.dump(payload_cola, f_cj, ensure_ascii=False, indent=2)

        meta_a_guardar = dict(cola_final[0].get("info") or info_cat)
        meta_a_guardar["fecha_tarea_admin"] = fecha_hoy_str
        meta_a_guardar["cola_audios"] = [c.get("info") for c in cola_final if c.get("info")]
        with open(os.path.join(carp_med, "meta_hoy.json"), "w", encoding="utf-8") as fm:
            json.dump(meta_a_guardar, fm, ensure_ascii=False, indent=2)
    else:
        with open(os.path.join(carp_med, "meta_hoy.json"), "w", encoding="utf-8") as fm:
            json.dump(info_cat, fm, ensure_ascii=False, indent=2)
        with open(os.path.join(carp_med, "cola_hoy.json"), "w", encoding="utf-8") as f_cj:
            json.dump({"fecha": fecha_hoy_str, "cola": [{"ruta": os.path.abspath(ruta_mp3_hoy), "info": info_cat, "titulo": f"{t_nom} #{num_t} - {info_cat.get('titulo', '')}"}]}, f_cj, ensure_ascii=False, indent=2)

    guardar_audio_registrado(info_cat, file_id=info_cat.get("file_id"), msg_id=msg_id_audio_final)

    anuncio = generar_anuncio_tarea(info_cat, fecha_hoy_str)
    teclado_t = armar_teclado_audio(chat_destino, msg_id_audio=msg_id_audio_final, numero_tarea=num_t, tipo_tarea=tipo_t)
    m_id_anuncio = enviar_mensaje(chat_destino, anuncio, reply_markup=teclado_t)
    if m_id_anuncio:
        _TAREA_FLOTANTE.update({"msg_id": m_id_anuncio, "contador": 0, "texto": anuncio, "reply_markup": teclado_t, "chat_id": chat_destino})

    if es_mario:
        enviar_mensaje(
            chat_destino,
            f"✅ **¡Tarea ADICIONAL del día programada exitosamente desde YouTube!**\n\n"
            f"🧘 **MENSAJE DEL MAESTRO JESUS MARIO CARRILLO DURAN:** «{info_cat.get('titulo', '')}»\n"
            f"👤 **Maestro:** MAESTRO JESUS MARIO CARRILLO\n"
            f"🎧 El archivo MP3 ya está descargado y listo para sonar en la reunión de las 7:56 PM. DESPUES DE LA MEDITACION"
        )
    else:
        enviar_mensaje(
            chat_destino,
            f"✅ **¡Tarea del día programada exitosamente desde YouTube!**\n\n"
            f"🧘 **{t_nom} #{num_t}:** «{info_cat.get('titulo', '')}»\n"
            f"👤 **Maestro:** {info_cat.get('maestro', 'Alaniso')}\n"
            f"🎧 El archivo MP3 ya está descargado y listo para sonar en la reunión de las 7:56 PM."
        )

    # Encolar en la llamada en vivo (si está activa en GitHub Actions)
    if es_mario and msg_id_audio_final:
        def _sincronizar_con_sala_en_vivo():
            try:
                m_enc = enviar_mensaje(chat_destino, "/encolar", reply_to_message_id=msg_id_audio_final)
                time.sleep(8)
                if m_enc:
                    eliminar_mensaje(chat_destino, m_enc)
            except Exception as e_sync:
                log_debug(f"Nota encolando en sala en vivo: {e_sync}")

        threading.Thread(target=_sincronizar_con_sala_en_vivo, daemon=True).start()

    # Enviar notificaciones privadas en segundo plano sin bloquear el grupo
    def _enviar_notifs_privadas():
        try:
            db_pts = cargar_puntos()
            usuarios = db_pts.get("usuarios", {})
            sin_privado = cargar_usuarios_sin_privado()
            for u_id_loop, datos in usuarios.items():
                if str(u_id_loop) == str(chat_destino) or str(u_id_loop) in sin_privado:
                    continue
                try:
                    if int(str(u_id_loop)) <= 0:
                        continue
                except ValueError:
                    continue
                if es_mario:
                    txt_priv = (
                        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
                        f"📢 ⚠️ **¡ATENCIÓN {datos.get('nombre', 'Compañero').upper()}!** ⚠️ 📢\n"
                        f"🕊️✨ **SE PROGRAMO NUEVO AUDIO A LA T A R E A   D E L   D Í A** ✨🕊️\n"
                        f"🗓️ **FECHA: {fecha_hoy_str}**\n"
                        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
                        f"Hola **{datos.get('nombre', 'Compañero')}**, hoy en la reunión de las 7:56 PM trabajaremos:\n\n"
                        f"🧘 **MENSAJE DEL MAESTRO JESUS MARIO CARRILLO DURAN**\n"
                        f"📌 **Título:** «{info_cat['titulo']}»\n"
                        f"👤 **Maestro:** JESUS MARIO CARRILLO DURAN | 🗓️ **Fecha:** {fecha_hoy_str}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏰ **¡Te esperamos puntual esta noche a las 7:56 PM!**\n"
                        f"👇 *Toca el botón abajo para escuchar el audio directamente.*"
                    )
                else:
                    txt_priv = (
                        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
                        f"📢 ⚠️ **¡ATENCIÓN {datos.get('nombre', 'Compañero').upper()}!** ⚠️ 📢\n"
                        f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
                        f"🗓️ **FECHA: {fecha_hoy_str}**\n"
                        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
                        f"Hola **{datos.get('nombre', 'Compañero')}**, hoy en la reunión de las 7:56 PM trabajaremos:\n\n"
                        f"🧘 **{tipo_t.upper()} #{num_t}**\n"
                        f"📌 **Título:** «{info_cat['titulo']}»\n"
                        f"👤 **Maestro:** {info_cat['maestro']} | 🗓️ **Fecha:** {fecha_hoy_str}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏰ **¡Te esperamos puntual esta noche a las 7:56 PM!**\n"
                        f"👇 *Toca el botón abajo para escuchar el audio directamente.*"
                    )
                enviar_mensaje(u_id_loop, txt_priv, reply_markup=teclado_t)
        except Exception as e_priv_notif:
            print("Nota enviando notificaciones privadas de tarea:", e_priv_notif)

    threading.Thread(target=_enviar_notifs_privadas, daemon=True).start()


def escuchar_comandos() -> None:
    if not BOT_TOKEN:
        print("Error: Define la variable de entorno BOT_TOKEN.")
        return

    # Iniciar servidor HTTP para health check (Koyeb / Render)
    threading.Thread(target=iniciar_servidor_health, daemon=True).start()

    # Iniciar reloj para aviso previo de preparación automático (7:26 PM Colombia - 30 min antes)
    def hilo_recordatorio_726():
        tz_col = ZoneInfo("America/Bogota")
        ultimo_intento = 0.0
        while True:
            try:
                ahora = datetime.now(tz_col)
                minutos = ahora.hour * 60 + ahora.minute
                en_ventana = (19 * 60 + 26) <= minutos <= (19 * 60 + 45)
                ya_enviado = _FECHA_ULTIMO_AVISO_AUTO == ahora.strftime("%Y-%m-%d")
                if en_ventana and not ya_enviado and time.time() - ultimo_intento >= 60:
                    ultimo_intento = time.time()
                    log_debug("⏰ Disparando aviso previo automático de preparación (7:26 PM)...")
                    enviar_aviso_preparacion_sala()
            except Exception as e:
                log_debug(f"Error en hilo_recordatorio_726: {e}")
            time.sleep(20)

    threading.Thread(target=hilo_recordatorio_726, daemon=True).start()

    # Iniciar radar de canales de YouTube (ALANISO 2012 y Maestro Mario Carrillo)
    try:
        from radar_youtube import iniciar_radar
        iniciar_radar(enviar_mensaje, CHAT_ID, bot_enviar_foto_func=enviar_foto)
    except Exception as e_rad:
        print("⚠️ No se pudo iniciar el radar de YouTube:", e_rad)

    # ── Evitar HTTP 409 Conflict ─────────────────────────────────────────────
    # Llamar deleteWebhook para liberar el token de cualquier webhook activo
    # antes de iniciar el long-polling.  Si otra instancia está corriendo,
    # sus requests de getUpdates fallarán con 409 hasta que Render la mate.
    _ALLOWED_UPDATES_PARAM = urllib.parse.quote(json.dumps(["message", "edited_message", "callback_query"]))
    try:
        url_dw = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=false"
        urllib.request.urlopen(urllib.request.Request(url_dw, headers={"User-Agent": "BotComandos"}), timeout=10)
        print("✅ deleteWebhook ejecutado correctamente al inicio.")
    except Exception as e_dw:
        print(f"⚠️ deleteWebhook falló (no crítico): {e_dw}")

    try:
        url_init_up = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?limit=1&timeout=0&allowed_updates={_ALLOWED_UPDATES_PARAM}"
        urllib.request.urlopen(urllib.request.Request(url_init_up, headers={"User-Agent": "BotComandos"}), timeout=10)
        print("✅ allowed_updates (mensajes y callbacks) restaurado en Telegram.")
    except Exception as e_init:
        print(f"⚠️ Error restaurando allowed_updates: {e_init}")

    # Cargar offset persistido en disco para no reprocesar updates tras reinicio
    _OFFSET_FILE = os.path.join("data", "last_update_id.txt")
    try:
        if os.path.exists(_OFFSET_FILE):
            with open(_OFFSET_FILE, "r") as _f_off:
                offset = int(_f_off.read().strip()) + 1
                print(f"🔁 Reanudando desde offset guardado: {offset}")
        else:
            offset = 0
    except Exception:
        offset = 0

    # Set en memoria para deduplicar updates dentro de la misma ejecución
    _updates_procesados: set = set()

    # ── Iniciar scheduler de meditaciones diarias (03:00 AM) ──
    try:
        from schedule_meditaciones import iniciar_scheduler
        iniciar_scheduler()
        print("✅ Scheduler iniciado")
    except Exception as e:
        print(f"⚠️ Error al iniciar scheduler: {e}")

    print("🤖 Bot de comandos iniciado. Escuchando /puntos, /ranking, /reglas, /ayuda, /meditacion, /buscar, /resumen, /acta, /tarea...")

    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=20&allowed_updates={_ALLOWED_UPDATES_PARAM}"
            req = urllib.request.Request(url, headers={"User-Agent": "BotComandos"})
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.loads(r.read().decode())

            if not res.get("ok"):
                time.sleep(3)
                continue

            for update in res.get("result", []):
                _uid = update["update_id"]
                offset = _uid + 1

                # ── Persistir offset en disco para sobrevivir reinicios ──────
                try:
                    os.makedirs("data", exist_ok=True)
                    with open(_OFFSET_FILE, "w") as _f_off_w:
                        _f_off_w.write(str(_uid))
                except Exception:
                    pass

                # ── Deduplicar: ignorar si ya procesamos este update_id ──────
                if _uid in _updates_procesados:
                    print(f"⚠️ Update {_uid} ya procesado (instancia duplicada), ignorando.")
                    continue
                _updates_procesados.add(_uid)
                # Mantener el set acotado a los últimos 500 para no crecer indefinidamente
                if len(_updates_procesados) > 500:
                    _updates_procesados.discard(min(_updates_procesados))

                print("Recibido update:", _uid)

                if "callback_query" in update:
#                     import json
                    cb = update["callback_query"]
                    cb_from = cb.get("from", {})
                    if cb_from.get("id"):
                        marcar_usuario_con_privado(cb_from["id"])
                    cb_id = cb.get("id")
                    cb_data = cb.get("data", "")
                    msg_cb = cb.get("message", {})
                    chat_id_cb = msg_cb.get("chat", {}).get("id")
                    
                    if cb_data.startswith("ytmp3_"):
                        vid = cb_data.split("_", 1)[1]
                        u_from = update["callback_query"]["from"]
                        u_id = u_from.get("id")
                        u_nom = f"{u_from.get('first_name', '')} {u_from.get('last_name', '')}".strip() or "Usuario"

                        try:
                            url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                            urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({
                                "callback_query_id": cb_id,
                                "text": "🎧 Obteniendo audio MP3...\n\nEstamos extrayendo el audio en alta calidad. En breves momentos te lo entregaremos por aquí.",
                                "show_alert": True
                            }).encode(), headers={"Content-Type": "application/json"}), timeout=10)
                        except Exception:
                            pass

                        def procesar_descarga_ytmp3(vid_target, user_id_target, user_nombre_target, chat_origen):
                            from radar_youtube import obtener_titulo_video
                            tit_v = obtener_titulo_video(vid_target) or f"Audio {vid_target}"

                            archivo_mp3 = descargar_audio_youtube_robusto(vid_target, tit_v)

                            if archivo_mp3 and os.path.exists(archivo_mp3) and os.path.getsize(archivo_mp3) > 1000:
                                caption_priv = (
                                    f"🎧 **Audio descargado:** «{tit_v}»\n"
                                    f"🔗 https://www.youtube.com/watch?v={vid_target}\n\n"
                                    f"✨ *Audio oficial solicitado para tu estudio.*"
                                )
                                enviado_priv = False
                                if user_id_target:
                                    ok_priv, _, _ = enviar_audio(
                                        user_id_target,
                                        archivo_mp3,
                                        caption=caption_priv,
                                        title=tit_v,
                                        performer="ALANISO / Maestro Mario Carrillo"
                                    )
                                    enviado_priv = ok_priv

                                if not enviado_priv and chat_origen:
                                    caption_grp = (
                                        f"🎧 **Audio descargado de YouTube:** «{tit_v}»\n"
                                        f"👤 Para: {user_nombre_target}\n"
                                        f"🔗 https://www.youtube.com/watch?v={vid_target}\n\n"
                                        f"💡 *(Para recibir los audios por privado en el futuro, abre un chat con el bot y presiona Iniciar).*"
                                    )
                                    enviar_audio(
                                        chat_origen,
                                        archivo_mp3,
                                        caption=caption_grp,
                                        title=tit_v,
                                        performer="ALANISO / Maestro Mario Carrillo"
                                    )
                            else:
                                if chat_origen:
                                    enviar_mensaje(
                                        chat_origen,
                                        f"⚠️ No se pudo extraer el audio del video de YouTube: https://www.youtube.com/watch?v={vid_target}\nPor favor intenta nuevamente en unos momentos."
                                    )

                        threading.Thread(target=procesar_descarga_ytmp3, args=(vid, u_id, u_nom, chat_id_cb), daemon=True).start()
                        continue

                    elif cb_data.startswith("yttarea_"):
                        vid = cb_data.split("_", 1)[1]
                        user_id_cb = update["callback_query"]["from"].get("id")
                        admins_set = obtener_admin_ids(chat_id_cb)
                        for hard_a in (8204833441, 8278899029, 8916842088, 8384683142, 1779560581, 6902578190, 8953593022):
                            admins_set.add(hard_a)

                        if user_id_cb not in admins_set:
                            try:
                                url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                                urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({
                                    "callback_query_id": cb_id,
                                    "text": "⛔ Solo los administradores pueden fijar o reprogramar la tarea del día.",
                                    "show_alert": True
                                }).encode(), headers={"Content-Type": "application/json"}), timeout=10)
                            except Exception:
                                pass
                            continue
                        else:
                            try:
                                url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                                urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({
                                    "callback_query_id": cb_id,
                                    "text": "✅ Programando audio de YouTube para la sala..."
                                }).encode(), headers={"Content-Type": "application/json"}), timeout=10)
                            except Exception:
                                pass

                            threading.Thread(target=procesar_programacion_yttarea, args=(vid, user_id_cb, chat_id_cb), daemon=True).start()
                        continue

                    elif cb_data.startswith("panel_"):
                        user_id_cb = update["callback_query"]["from"].get("id")
                        admins_set = obtener_admin_ids(chat_id_cb)
                        for hard_a in (8204833441, 8278899029, 8916842088, 8384683142, 1779560581, 6902578190, 8953593022):
                            admins_set.add(hard_a)

                        if user_id_cb not in admins_set:
                            try:
                                url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                                urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "⛔ Solo los administradores pueden utilizar el panel de control de la sala.", "show_alert": True}).encode(), headers={"Content-Type": "application/json"}), timeout=10)
                            except Exception:
                                pass
                            continue

                        accion = cb_data.split("_")[1]
                        comando = ""
                        texto_feedback = ""
                        if accion == "play":
                            comando = "/reproducir"
                            texto_feedback = "▶️ Reanudando / Reproduciendo..."
                        elif accion == "pausa":
                            comando = "/pausar"
                            texto_feedback = "⏸️ Pausando..."
                        elif accion == "rewind":
                            comando = "/atrasar 30"
                            texto_feedback = "⏪ Retrocediendo 30 segundos..."
                        elif accion == "forward":
                            comando = "/adelantar 30"
                            texto_feedback = "⏩ Adelantando 30 segundos..."
                        elif accion == "voldown":
                            comando = "/voldown"
                            texto_feedback = "🔉 Reduciendo volumen..."
                        elif accion == "volup":
                            comando = "/volup"
                            texto_feedback = "🔊 Aumentando volumen..."
                        elif accion == "stop":
                            comando = "/detener"
                            texto_feedback = "⏹️ Deteniendo reproducción..."
                        elif accion in ("nextaudio", "saltaraudio"):
                            comando = "/saltaraudio"
                            texto_feedback = "⏭️ Saltando al siguiente audio..."
                        elif accion == "limpiarcola":
                            comando = "/limpiarcola"
                            texto_feedback = "🗑️ Vaciando cola de reproducción..."
                        elif accion == "vercola":
                            comando = "/cola"
                            texto_feedback = "📋 Consultando cola de reproducción..."
                        elif accion == "encolar":
                            texto_feedback = "➕ Para encolar: escribe /encolar <número>"
                            txt_enc = (
                                "➕ **ENCOLAR AUDIO PARA DESPUÉS DE LA MEDITACIÓN**\n"
                                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                "🌟 *La meditación programada para hoy tiene prioridad #1 y terminará de sonar primero.*\n\n"
                                "👉 **Para añadir un audio que suene a continuación:**\n"
                                "• Escribe: `/encolar <número o título>` *(ej: `/encolar 15` o `/encolar mensaje 606`)*\n"
                                "• O responde a cualquier audio en el grupo con `/encolar`\n\n"
                                "💡 *El nuevo audio se colocará en la cola y sonará automáticamente al terminar la meditación.*"
                            )
                            enviar_mensaje(chat_id_cb, txt_enc)
                        elif accion == "nextturno":
                            comando = "/siguiente"
                            texto_feedback = "🎤 Siguiente turno..."
                        elif accion == "limpiarturnos":
                            comando = "/limpiarturnos"
                            texto_feedback = "✋ Vaciando lista de turnos..."
                        elif accion == "desmutear":
                            comando = "/desmuteartodos"
                            texto_feedback = "🔓 Desbloqueando micrófonos..."
                        elif accion == "limpiar":
                            comando = "/limpiarsala"
                            texto_feedback = "🧹 Limpiando mensajes..."
                        elif accion == "stoprec":
                            comando = "/detenergrabacion"
                            texto_feedback = "🛑 Deteniendo grabación..."

                        # Notificar al bucle IPC de la llamada en tiempo real
                        try:
                            os.makedirs("data", exist_ok=True)
                            ipc_data = {
                                "accion": accion,
                                "sender_id": user_id_cb,
                                "sender_nom": f"{update['callback_query']['from'].get('first_name', '')} {update['callback_query']['from'].get('last_name', '')}".strip() or "Admin",
                                "timestamp": time.time()
                            }
                            with open(os.path.join("data", "control_panel_ipc.json"), "w", encoding="utf-8") as f_ipc:
                                json.dump(ipc_data, f_ipc)
                        except Exception as e_ipc_w:
                            print("Nota guardando IPC:", e_ipc_w)

                        if comando and chat_id_cb:
                            m_id_cmd = enviar_mensaje(chat_id_cb, comando)
                            if m_id_cmd:
                                def _borrar_cmd_diferido(_cid=chat_id_cb, _mid=m_id_cmd):
                                    time.sleep(8.0)
                                    eliminar_mensaje(_cid, _mid)
                                threading.Thread(target=_borrar_cmd_diferido, daemon=True).start()

                        try:
                            url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                            req_ans = urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": texto_feedback or f"Ejecutado: {comando}"}).encode(), headers={"Content-Type": "application/json"})
                            urllib.request.urlopen(req_ans, timeout=10)
                        except Exception:
                            pass
                        continue

                    elif cb_data == "biblio_priv" or cb_data.startswith("biblio_priv"):
                        user_id_cb = cb_from.get("id")
                        msg_id_cb = msg_cb.get("message_id")
                        texto_a_enviar = _CACHE_RESPUESTAS_BIBLIO.get(str(msg_id_cb)) or msg_cb.get("text", "")
                        
                        if user_id_cb and texto_a_enviar:
                            m_id_priv = enviar_mensaje(user_id_cb, texto_a_enviar)
                            if m_id_priv:
                                try:
                                    url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                                    req_ans = urllib.request.Request(
                                        url_ans,
                                        data=json.dumps({
                                            "callback_query_id": cb_id,
                                            "text": "✅ ¡Listo! Te envié la información a tu Telegram privado."
                                        }).encode(),
                                        headers={"Content-Type": "application/json"}
                                    )
                                    urllib.request.urlopen(req_ans, timeout=10)
                                except Exception:
                                    pass
                            else:
                                bot_info = obtener_info_bot()
                                if bot_info:
                                    txt_alerta = f"⚠️ Para que pueda escribirte al privado, primero debes abrir el chat con EL ASISTENTE TOBY (@{bot_info}) y presionar EL BOTON 'INICIAR'."
                                else:
                                    txt_alerta = "⚠️ Para que pueda escribirte al privado, primero debes abrir el chat con EL ASISTENTE TOBY y presionar EL BOTON 'INICIAR'."
                                try:
                                    url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                                    req_ans = urllib.request.Request(
                                        url_ans,
                                        data=json.dumps({
                                            "callback_query_id": cb_id,
                                            "text": txt_alerta,
                                            "show_alert": True
                                        }).encode(),
                                        headers={"Content-Type": "application/json"}
                                    )
                                    urllib.request.urlopen(req_ans, timeout=10)
                                except Exception:
                                    pass
                        continue
                msg = update.get("message")
                if not msg:
                    continue
                
                # --- LOGICA EN PRIVADO (AUDIOS DRIVE vs BIBLIOTECA YOUTUBE) ---
                chat_type = msg.get("chat", {}).get("type")
                if chat_type == "private":
                    from_u = msg.get("from", {})
                    if from_u.get("id"):
                        marcar_usuario_con_privado(from_u["id"])
                    texto_priv = (msg.get("text") or msg.get("caption") or "").strip()
                    msg_id_priv = msg.get("message_id")
                    chat_id_priv = msg.get("chat", {}).get("id")
                
                    if texto_priv and not texto_priv.startswith("/"):
                        t_priv_up = texto_priv.upper()
                        # Caso A: Si pide audio (mensaje o meditación con o sin número) -> Exclusivo Google Drive
                        if es_solicitud_de_audio(texto_priv, chat_id_priv) or any(w in t_priv_up for w in ["AUDIO", "MEDITACION", "MEDITACIÓN", "MENSAJE"]):
                            info_cat_priv = identificar_audio_catalogo(texto=texto_priv)
                            if not info_cat_priv:
                                m_num_priv = re.search(r"\b(\d{1,4})\b", texto_priv)
                                if m_num_priv:
                                    t_req_priv = "MENSAJE" if "MENSAJE" in t_priv_up else "MEDITACION"
                                    n_req_priv = int(m_num_priv.group(1))
                                    info_cat_priv = {"numero": n_req_priv, "tipo": t_req_priv, "titulo": f"{t_req_priv.title()} #{n_req_priv}", "maestro": "Comunidad", "fecha": ""}
                            if info_cat_priv:
                                entregar_audio_meditacion(chat_id_priv, info_cat_priv, msg_id_reply=msg_id_priv, user_id_privado=chat_id_priv)
                                continue

                        # Caso B: Si menciona la biblioteca o pregunta sobre ella -> Exclusivo Base de Datos de Transcripciones de YouTube
                        if "BIBLIOTECA" in t_priv_up or "CONOCIMIENTO UNIVERSAL" in t_priv_up:
                            responder_consulta_biblioteca(chat_id_priv, texto_priv, msg_id_reply=msg_id_priv, from_u=from_u)
                            continue

                        # Caso C: Consulta libre en lenguaje natural sin palabra clave específica
                        # Ofrecemos orientación clara para que elija entre Audio de Drive o Biblioteca de YouTube
                        txt_guia = (
                            "👋 ¡Hola! Para brindarte la mejor respuesta:\n\n"
                            "🎧 **¿Buscas un Audio o Meditación?**\n"
                            "Escribe por ejemplo: *«audio meditacion 21»* o *«mensaje 989»* y te enviaré el archivo directo de Google Drive.\n\n"
                            "📚 **¿Buscas en la Biblioteca de Conocimiento Universal (YouTube)?**\n"
                            "Menciona la palabra **biblioteca**, por ejemplo:\n"
                            "*«Toby busca en la biblioteca qué se dice sobre los 144.000»*"
                        )
                        enviar_mensaje(chat_id_priv, txt_guia, reply_to_message_id=msg_id_priv)
                        continue
                # ------------------------------------

                # --- LOGICA MENSAJE FLOTANTE ---
                chat_id_msg = msg.get("chat", {}).get("id")
                if chat_id_msg and _TAREA_FLOTANTE["msg_id"] and chat_id_msg == _TAREA_FLOTANTE["chat_id"]:
                    from_id = msg.get("from", {}).get("id")
                    if not BOT_ID or from_id != BOT_ID:
    #                         from zoneinfo import ZoneInfo
    #                         from datetime import datetime
                        ahora_flot = datetime.now(ZoneInfo("America/Bogota"))
                        minutos_flot = ahora_flot.hour * 60 + ahora_flot.minute
                        # Solo flota hasta las 7:26 PM (19*60 + 26 = 1166)
                        if minutos_flot < 1166:
                            _TAREA_FLOTANTE["contador"] += 1
                            if False:
                                eliminar_mensaje(chat_id_msg, _TAREA_FLOTANTE["msg_id"])
                                nuevo_id = enviar_mensaje(chat_id_msg, _TAREA_FLOTANTE["texto"], reply_markup=_TAREA_FLOTANTE["reply_markup"])
                                if nuevo_id:
                                    _TAREA_FLOTANTE["msg_id"] = nuevo_id
                                    _TAREA_FLOTANTE["contador"] = 0
                # -------------------------------


                from_user = msg.get("from", {})
                user_id = from_user.get("id")

                # Ignorar completamente bots (excepto anónimo oficial) para evitar bucles
                if from_user.get("is_bot") and user_id != 1087968824 and from_user.get("username") != "GroupAnonymousBot":
                    continue
                if BOT_ID and user_id == BOT_ID:
                    continue

                texto = (msg.get("text") or msg.get("caption") or "").strip()
                chat_id = msg["chat"]["id"]
                msg_id = msg["message_id"]
                nombre = f"{from_user.get('first_name', '')} {from_user.get('last_name', '')}".strip()

                # Ignorar mensajes automáticos de bot o sistema para prevenir ecos y bucles
                if any(texto.startswith(prefix) for prefix in ("✅", "📢", "🕊️", "▶️", "🔍", "📋", "🧘✨", "🎙️", "ℹ️", "⚠️", "⛔", "[", "🔴", "⚪")):
                    continue

                texto_upper = texto.upper()
                if any(k in texto_upper for k in [
                    "DESDE GOOGLE DRIVE", "OBTENIDOS DESDE", "BUSCANDO AUDIO PARA",
                    "TAREA DEL DÍA", "TAREA DEL DIA", "LISTA DE REPRODUCCIÓN",
                    "REPRODUCIENDO MEDITACIÓN", "INICIANDO REPRODUCCIÓN", "PROGRAMADOS PARA REPRODUCIRSE"
                ]):
                    continue

                # Detectar si se subió un audio/documento o se declaró tarea por texto
                audio_obj = msg.get("audio") or msg.get("voice") or msg.get("document")
                es_tarea_declarada = any(k in texto_upper for k in [
                    "MEDITACION DE TAREA", "TAREA DE MEDITACION",
                    "MENSAJE DE TAREA", "TAREA DE MENSAJE",
                    "TAREA PARA MAÑANA", "TAREA PARA MANANA", "TAREA PARA HOY",
                    "TAREA DEL DÍA", "TAREA DEL DIA",
                    "MEDITACION DE HOY", "MENSAJE DE HOY"
                ]) or (
                    any(t_pal in texto_upper for t_pal in ["TAREA", "MEDITACION", "MEDITACIÓN", "MENSAJE"])
                    and any(w in texto_upper for w in ["MAÑANA", "MANANA", "PARA HOY", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO", "LUNES", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE"])
                    and re.search(r"\b\d{1,4}\b", texto_upper)
                )

                if audio_obj or es_tarea_declarada:
                    nombre_archivo = audio_obj.get("file_name", "") if isinstance(audio_obj, dict) else ""
                    titulo_audio = audio_obj.get("title", "") if isinstance(audio_obj, dict) else ""
                    performer_audio = audio_obj.get("performer", "") if isinstance(audio_obj, dict) else ""
                    texto_busq = f"{texto} {nombre_archivo} {titulo_audio} {performer_audio}".strip()
                    items_encontrados = identificar_todos_los_audios(texto=texto_busq, nombre_archivo=nombre_archivo)
                    info_cat = items_encontrados[0] if items_encontrados else identificar_audio_catalogo(texto=texto_busq, nombre_archivo=nombre_archivo)
                    if info_cat:
                        f_id = audio_obj.get("file_id") if isinstance(audio_obj, dict) else None
                        num = info_cat["numero"]
                        tipo_audio = info_cat.get("tipo", "MEDITACION")

                        # Si se envió directamente en privado con archivo físico (solo administradores)
                        if chat_id > 0 and f_id:
                            if not es_mensaje_de_admin(msg, chat_id):
                                enviar_mensaje(
                                    chat_id,
                                    "⛔ Solo los administradores pueden registrar audios oficiales en el catálogo.",
                                    reply_to_message_id=msg_id
                                )
                                continue
                            info_cat["file_id"] = f_id
                            info_cat["msg_id_audio"] = msg_id
                            guardar_audio_registrado(info_cat, file_id=f_id, msg_id=msg_id)
                            enviar_mensaje(
                                chat_id,
                                f"✅ **¡Audio guardado exitosamente!**\n\n"
                                f"🧘 **{tipo_audio.title()} #{info_cat['numero']}:** «{info_cat['titulo']}»\n"
                                f"👤 **Maestro:** {info_cat['maestro']}\n"
                                f"🗓️ **Grabación:** {info_cat['fecha']}\n\n"
                                f"El bot ha registrado este archivo y ahora se lo entregará directamente a cualquier usuario que lo solicite con `/meditacion` o el botón de audio.",
                                reply_to_message_id=msg_id
                            )

                        # Si es declaración de tarea (en el grupo o en privado por admin)
                        if es_tarea_declarada or (CHAT_ID and str(chat_id) == str(CHAT_ID) and audio_obj):
                            if not es_mensaje_de_admin(msg, chat_id):
                                # Si un usuario no administrador menciona la tarea, solo entregarle la tarea actual que ya fue fijada por los admins
                                log_debug(f"Usuario no admin {user_id} intentó programar tarea. Bloqueado.")
                                info_cat_act = obtener_info_tarea_hoy()
                                if info_cat_act:
                                    entregar_audio_meditacion(chat_id, info_cat_act, msg_id_reply=msg_id, user_id_privado=user_id)
                                else:
                                    enviar_mensaje(chat_id, "ℹ️ Solo los administradores pueden programar la tarea del día.", reply_to_message_id=msg_id)
                                continue

                            fecha_admin = extraer_fecha_de_texto(texto)
                            msg_id_audio_final = msg_id if audio_obj else None
                            audios_procesados = []

                            lista_a_procesar = items_encontrados if items_encontrados else [info_cat]
                            for it_proc in lista_a_procesar:
                                t_proc = it_proc.get("tipo", "MEDITACION")
                                n_proc = it_proc.get("numero")
                                fid_proc = f_id if (len(lista_a_procesar) == 1 and f_id) else it_proc.get("file_id")

                                # Si no vino con audio físico, buscar y descargar automáticamente de Google Drive
                                if not fid_proc and n_proc:
                                    t_nombre = "Meditación" if "MEDITACI" in str(t_proc).upper() else "Mensaje"
                                    enviar_mensaje(chat_id, f"🔍 Buscando audio para {t_nombre} #{n_proc}...", reply_to_message_id=msg_id)
                                    log_debug(f"Buscando audio para {t_proc} #{n_proc}...")
                                    ruta_audio_desc = obtener_o_descargar_audio(t_proc, int(n_proc))
                                    if ruta_audio_desc:
                                        cap_audio = f"🧘 **{t_nombre} #{n_proc}:** «{it_proc.get('titulo', '')}»\n👤 **Maestro:** {it_proc.get('maestro', 'Alaniso')}\n🗓️ **Grabación:** {it_proc.get('fecha', '')}"
                                        bot_u_tarea = obtener_info_bot()
                                        clean_t_proc = "mensaje" if "MENSAJE" in str(t_proc).upper() else "meditacion"
                                        param_aud_proc = f"audio_{clean_t_proc}_{n_proc}"
                                        teclado_audio_tarea = {"inline_keyboard": [[{"text": "📥 RECIBIR AUDIO EN MI TELEGRAM PRIVADO 🎧", "url": f"https://t.me/{bot_u_tarea}?start={param_aud_proc}"}]]} if (int(chat_id) < 0 and bot_u_tarea) else None
                                        ok_a, m_id_a, f_id_a = enviar_audio(
                                            chat_id,
                                            ruta_audio_desc,
                                            caption=cap_audio,
                                            title=f"{t_nombre} #{n_proc} - {it_proc.get('titulo', '')}",
                                            performer=it_proc.get('maestro', 'Alaniso'),
                                            reply_markup=teclado_audio_tarea
                                        )
                                        if ok_a:
                                            fid_proc = f_id_a
                                            it_proc["file_id"] = f_id_a
                                            it_proc["msg_id_audio"] = m_id_a
                                            if not msg_id_audio_final:
                                                msg_id_audio_final = m_id_a

                                it_proc["file_id"] = fid_proc
                                guardar_audio_registrado(it_proc, file_id=fid_proc, msg_id=it_proc.get("msg_id_audio"))
                                audios_procesados.append(it_proc)

                            try:
                                os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
                                info_guardar = dict(info_cat)
                                info_guardar["fecha_tarea_admin"] = fecha_admin
                                if len(audios_procesados) > 1:
                                    info_guardar["cola_audios"] = audios_procesados
                                with open(os.path.join("data", "meditaciones", "meta_hoy.json"), "w", encoding="utf-8") as fm:
                                    json.dump(info_guardar, fm, ensure_ascii=False, indent=2)
                            except Exception:
                                pass

                            # 2. Enviar anuncio con botones al chat actual
                            anuncio = generar_anuncio_tarea(audios_procesados if len(audios_procesados) > 1 else info_cat, fecha_admin)
                            teclado_actual = armar_teclado_audio(chat_id, msg_id_audio_final, numero_tarea=num, tipo_tarea=tipo_audio, audios_lista=audios_procesados)
                            m_id = enviar_mensaje(chat_id, anuncio, reply_markup=teclado_actual)
                            if m_id:
                                _TAREA_FLOTANTE.update({"msg_id": m_id, "contador": 0, "texto": anuncio, "reply_markup": teclado_actual, "chat_id": chat_id})

                            # 3. Si la orden se dio en privado Y CHAT_ID del grupo está configurado, publicar también en el grupo
                            if chat_id > 0 and CHAT_ID and str(chat_id) != str(CHAT_ID):
                                log_debug(f"Publicando copia de la tarea en el grupo {CHAT_ID}...")
                                teclado_grupo = armar_teclado_audio(CHAT_ID, msg_id_audio_final, numero_tarea=num, tipo_tarea=tipo_audio, audios_lista=audios_procesados)
                                enviar_mensaje(CHAT_ID, anuncio, reply_markup=teclado_grupo)

                            # 4. Enviar notificación privada a miembros registrados
                            ahora_col = datetime.now(ZoneInfo("America/Bogota"))
                            if not fecha_admin:
                                if ahora_col.hour > 20 or (ahora_col.hour == 20 and ahora_col.minute >= 32):
                                    fecha_priv = (ahora_col + timedelta(days=1)).strftime("%d/%m/%Y")
                                else:
                                    fecha_priv = ahora_col.strftime("%d/%m/%Y")
                            else:
                                fecha_priv = fecha_admin

                            es_hoy_priv = fecha_priv == ahora_col.strftime("%d/%m/%Y")
                            tiempo_saludo = "hoy" if es_hoy_priv else "mañana"

                            # ── Deduplicar declaración de tarea (primer bloque) ─────────────
                            _tarea_uid_file = os.path.join("data", "ultima_tarea_update_id.txt")
                            _tarea_uid_actual = str(_uid) if "_uid" in dir() else ""
                            _ya_procesada = False
                            try:
                                if os.path.exists(_tarea_uid_file) and _tarea_uid_actual:
                                    with open(_tarea_uid_file, "r") as _f_tuid:
                                        if _f_tuid.read().strip() == _tarea_uid_actual:
                                            print(f"⚠️ Tarea update_id={_tarea_uid_actual} ya procesada, saltando notificaciones.")
                                            _ya_procesada = True
                                if not _ya_procesada and _tarea_uid_actual:
                                    with open(_tarea_uid_file, "w") as _f_tuid_w:
                                        _f_tuid_w.write(_tarea_uid_actual)
                            except Exception:
                                pass

                            if not _ya_procesada:
                                db_pts = cargar_puntos()
                                usuarios = db_pts.get("usuarios", {})
                                sin_privado = cargar_usuarios_sin_privado()
                                enviados_priv = 0
                                for u_id, datos in usuarios.items():
                                    if (CHAT_ID and str(u_id) == str(CHAT_ID)) or str(u_id) == str(chat_id):
                                        continue
                                    if str(u_id) in sin_privado:
                                        continue
                                    # Solo enviar a usuarios con chat privado positivo
                                    try:
                                        if int(str(u_id)) <= 0:
                                            continue
                                    except ValueError:
                                        continue
                                    if len(audios_procesados) > 1:
                                        txt_items_p = "\n".join(f"• **{it.get('tipo', 'Audio').title()} #{it.get('numero')}:** «{it.get('titulo')}»" for it in audios_procesados)
                                        txt_priv = (
                                            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
                                            f"📢 ⚠️ **¡ATENCIÓN {datos.get('nombre', 'Compañero').upper()}!** ⚠️ 📢\n"
                                            f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
                                            f"🗓️ **FECHA: {fecha_priv}**\n"
                                            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
                                            f"Hola **{datos.get('nombre', 'Compañero')}**, {tiempo_saludo} trabajaremos con:\n\n"
                                            f"{txt_items_p}\n\n"
                                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                            f"⏰ **Te esperamos a las 7:56 PM para la apertura de la sala.**\n"
                                            f"👇 *Usa los botones abajo para escuchar los audios.*"
                                        )
                                    else:
                                        txt_priv = (
                                            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
                                            f"📢 ⚠️ **¡ATENCIÓN {datos.get('nombre', 'Compañero').upper()}!** ⚠️ 📢\n"
                                            f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
                                            f"🗓️ **FECHA: {fecha_priv}**\n"
                                            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
                                            f"Hola **{datos.get('nombre', 'Compañero')}**, {tiempo_saludo} trabajaremos con:\n\n"
                                            f"🧘 **{info_cat.get('tipo', 'MEDITACION').upper()} #{info_cat['numero']}**\n"
                                            f"📌 **Título:** «{info_cat['titulo']}»\n"
                                            f"👤 **Maestro:** {info_cat['maestro']} | 🗓️ **Grabación:** {info_cat['fecha']}\n\n"
                                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                            f"⏰ **Te esperamos puntual a las 7:56 PM para la apertura de la sala.**\n"
                                            f"👇 *Toca el botón abajo para escuchar el audio directamente.*"
                                        )
                                    if enviar_mensaje(u_id, txt_priv, reply_markup=teclado_actual):
                                        enviados_priv += 1
                                log_debug(f"Notificaciones privadas de tarea enviadas a {enviados_priv} miembros con chat activo.")

                # Petición de audio en lenguaje natural (ej: "¿Tienes el mensaje 989?", "meditación 21") -> Exclusivo Google Drive
                if not es_tarea_declarada and not audio_obj and es_solicitud_de_audio(texto, chat_id):
                    info_cat = identificar_audio_catalogo(texto=texto)
                    if not info_cat:
                        m_num = re.search(r"\b(\d{1,4})\b", texto)
                        if m_num:
                            tipo_req = "MENSAJE" if "MENSAJE" in texto_upper else "MEDITACION"
                            num_req = int(m_num.group(1))
                            info_cat = {"numero": num_req, "tipo": tipo_req, "titulo": f"{tipo_req.title()} #{num_req}", "maestro": "Comunidad", "fecha": ""}
                    if info_cat:
                        entregar_audio_meditacion(chat_id, info_cat, msg_id_reply=msg_id, user_id_privado=user_id)
                        continue

                # Búsqueda en la Biblioteca en lenguaje natural dentro del grupo (menciona biblioteca) -> Exclusivo BD YouTube
                if not es_tarea_declarada and not audio_obj and ("BIBLIOTECA" in texto_upper or "CONOCIMIENTO UNIVERSAL" in texto_upper):
                    mencion_toby = ("TOBY" in texto_upper or "@" in texto or msg.get("reply_to_message", {}).get("from", {}).get("id") == BOT_ID)
                    if mencion_toby or "BIBLIOTECA" in texto_upper:
                        responder_consulta_biblioteca(chat_id, texto, msg_id_reply=msg_id, from_u=from_user)
                        continue

                # Detectar orden de administradores para limpiar la sala de notificaciones del robot
                texto_lower = texto.lower()
                cmd_primero = texto.split()[0].lower().split("@")[0] if texto else ""
                es_orden_limpieza = any(p in texto_lower for p in [
                    "notificaciones del robot",
                    "notificaciones del bot",
                    "ventanas del robot",
                    "ventanas del bot",
                    "limpia la sala de notificaciones",
                    "limpiar la sala de notificaciones",
                    "limpiar notificaciones",
                    "limpia las notificaciones",
                    "limpia la sala",
                    "limpiar la sala",
                    "limpiar sala",
                    "borrar notificaciones",
                    "borra las notificaciones",
                    "borrar ventanas",
                    "limpiar avisos",
                ]) or (
                    any(v in texto_lower for v in ["limpia", "limpiar", "borra", "borrar"])
                    and any(t in texto_lower for t in ["notificacion", "notificaciones", "ventana", "ventanas", "aviso", "avisos"])
                    and "turno" not in texto_lower
                ) or (cmd_primero in ("/limpiarsala", "/limpiaravisos", "/limpieza"))

                if es_orden_limpieza:
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "⛔ Solo los administradores pueden solicitar la limpieza de la sala.", reply_to_message_id=msg_id)
                        continue

                    # Eliminar la orden escrita por el admin para no dejar rastro
                    eliminar_mensaje(chat_id, msg_id)
                    m_aviso = enviar_mensaje(chat_id, "🧹 **Iniciando limpieza:** Eliminando notificaciones y ventanas del bot en la sala...")
                    cant = limpiar_sala_notificaciones(chat_id)
                    if m_aviso:
                        time.sleep(3)
                        eliminar_mensaje(chat_id, m_aviso)
                    continue

                if not texto.startswith("/"):
                    continue

                partes = texto.split()
                cmd = partes[0].lower().split("@")[0]
                param = partes[1].lower() if len(partes) > 1 else ""
                db = cargar_puntos()

                if cmd in ("/puntos", "/miperfil"):
                    admins_set = obtener_admin_ids()
                    resp = generar_texto_miperfil(user_id, db, nombre, es_admin=(user_id in admins_set))
                    enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)
                elif cmd in ("/ranking", "/top") or (cmd == "/start" and param == "ranking"):
                    admins_set = obtener_admin_ids()
                    resp = generar_texto_ranking(db, admin_ids=admins_set)
                    enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)
                elif cmd in ("/meditacion", "/meditacion_hoy", "/audio", "/mensaje", "/playlist", "/cola") or (cmd == "/start" and (param in ("audio", "meditacion", "tarea") or param.startswith("audio_") or param.startswith("meditacion_") or param.startswith("mensaje_"))):
                    param_texto = "" if (cmd == "/start" and param in ("audio", "meditacion", "tarea")) else (" ".join(partes[1:]).strip() if (len(partes) > 1 and not param.startswith("audio")) else "")
                    if cmd == "/start" and param.startswith("audio_"):
                        sub = param[6:]  # ej: "meditacion_6" o "6" o "mensaje_989"
                        if "_" in sub:
                            p_t, p_n = sub.split("_", 1)
                            param_texto = f"{p_t} {p_n}"
                        elif sub.isdigit():
                            param_texto = f"meditacion {sub}"
                        else:
                            param_texto = sub
                    elif cmd == "/start" and param.startswith(("meditacion_", "mensaje_")):
                        p_t, p_n = param.split("_", 1)
                        param_texto = f"{p_t} {p_n}"

                    info_cat = None
                    if param_texto:
                        prefijo = "mensaje" if (cmd == "/mensaje" or "mensaje" in param_texto.lower()) else "meditacion"
                        busqueda = f"{prefijo} {param_texto}" if not any(w in param_texto.lower() for w in ["meditacion", "mensaje"]) else param_texto
                        info_cat = identificar_audio_catalogo(texto=busqueda)
                        if not info_cat:
                            enviar_mensaje(chat_id, f"ℹ️ No se encontró ninguna meditación o mensaje correspondiente a «{param_texto}» en el catálogo.", reply_to_message_id=msg_id)
                            continue
                    else:
                        # Obtener meditación activa y validada del día
                        info_cat = obtener_info_tarea_hoy()

                    if cmd in ("/playlist", "/cola") and info_cat:
                        cola_audios = info_cat.get("cola_audios")
                        if cola_audios and isinstance(cola_audios, list) and len(cola_audios) > 1:
                            cola_formato = [{"info": ca, "titulo": ca.get("titulo", "")} for ca in cola_audios]
                            txt_pl = formatear_cola_audios(cola_formato) + "\n\n🎧 *A continuación te entrego los audios oficiales de la lista:* 👇"
                        else:
                            num_txt = info_cat.get("numero", "")
                            tit_txt = info_cat.get("titulo", "")
                            mae_txt = info_cat.get("maestro", "Alaniso")
                            fec_txt = info_cat.get("fecha", "")
                            txt_pl = (
                                f"📋 **LISTA DE REPRODUCCIÓN PROGRAMADA PARA HOY:**\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"🧘 **Práctica:** Meditación #{num_txt} - «{tit_txt}»\n"
                                f"👤 **Maestro:** {mae_txt} | 📅 {fec_txt}\n\n"
                                f"🎧 *A continuación te entrego el audio oficial para su estudio previo:* 👇"
                            )
                        enviar_mensaje(chat_id, txt_pl, reply_to_message_id=msg_id)

                    entregar_audio_meditacion(chat_id, info_cat, msg_id_reply=msg_id, user_id_privado=user_id)
                elif cmd in ("/progreso",):
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "🚫 Solo admins.", reply_to_message_id=msg_id)
                        continue
                    estado_path = os.path.join("data", "estado_descarga.json")
                    if os.path.exists(estado_path):
    #                         import json
                        try:
                            with open(estado_path, "r", encoding="utf-8") as f_est:
                                st = json.load(f_est)
                            barra = "█" * int(st['porcentaje'] / 5) + "░" * (20 - int(st['porcentaje'] / 5))
                            msg_prog = f"📊 **Progreso Biblioteca Universal**\n\n"
                            msg_prog += f"[{barra}] {st['porcentaje']}%\n\n"
                            msg_prog += f"✅ **Completados:** {st['completados']} / {st['total']}\n"
                            msg_prog += f"⏳ **Tiempo restante:** {st['tiempo_estimado_restante']}\n"
                            msg_prog += f"⚠️ **Imprevistos (Errores):** {st['errores']}\n"
                            msg_prog += f"🔄 **Última actualización:** {st['ultima_actualizacion']}"
                            enviar_mensaje(chat_id, msg_prog, reply_to_message_id=msg_id)
                        except:
                            enviar_mensaje(chat_id, "⚠️ Error leyendo el estado de la descarga.", reply_to_message_id=msg_id)
                    else:
                        enviar_mensaje(chat_id, "⏳ El escáner aún no ha generado el archivo de progreso. Posiblemente siga en la Fase 1 (Inventario).", reply_to_message_id=msg_id)
                elif cmd in ("/radar", "/canales", "/videos"):
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "⛔ Solo administradores pueden consultar el radar de canales.", reply_to_message_id=msg_id)
                        continue
                    enviar_mensaje(chat_id, "📡 **Escaneando canales de YouTube en este instante...**\n• ALANISO 2012 (@ALANISO-2012)\n• Maestro Mario Carrillo (@mariocarrillo7919)", reply_to_message_id=msg_id)
                    try:
                        from radar_youtube import chequear_canales
                        cant = chequear_canales(enviar_mensaje, chat_id, bot_enviar_foto_func=enviar_foto)
                        if cant == 0:
                            enviar_mensaje(chat_id, "✅ Los canales de YouTube están al día. No hay videos nuevos pendientes de anunciar.", reply_to_message_id=msg_id)
                    except Exception as e_rad_cmd:
                        enviar_mensaje(chat_id, f"⚠️ Error escaneando canales: {e_rad_cmd}", reply_to_message_id=msg_id)
                    continue
                elif cmd in ("/anunciar", "/anuncio_video", "/publicar_video"):
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "⛔ Solo administradores pueden anunciar videos.", reply_to_message_id=msg_id)
                        continue
                    partes_txt = msg.get("text", "").split(maxsplit=1)
                    arg = partes_txt[1].strip() if len(partes_txt) > 1 else ""
                    if not arg:
                        enviar_mensaje(chat_id, "ℹ️ Uso: `/anunciar <ID_O_LINK_DE_YOUTUBE>`\nEjemplo: `/anunciar k9ZTyOTa5BI`", reply_to_message_id=msg_id)
                        continue
                    m_vid = re.search(r'(?:v=|\/|youtu\.be\/)([a-zA-Z0-9_-]{11})', arg)
                    vid_target = m_vid.group(1) if m_vid else arg.strip()
                    try:
                        from radar_youtube import anunciar_video_manual
                        ok = anunciar_video_manual(vid_target, enviar_mensaje, CHAT_ID or chat_id, bot_enviar_foto_func=enviar_foto, forzar=True)
                        if ok:
                            enviar_mensaje(chat_id, f"✅ Video `{vid_target}` anunciado exitosamente con miniatura HD.", reply_to_message_id=msg_id)
                        else:
                            enviar_mensaje(chat_id, f"⚠️ No se pudo obtener información del video `{vid_target}`.", reply_to_message_id=msg_id)
                    except Exception as e_anun:
                        enviar_mensaje(chat_id, f"⚠️ Error anunciando video: {e_anun}", reply_to_message_id=msg_id)
                    continue
                elif cmd in ("/luna", "/faseluna", "/lunar"):
                    try:
                        from astronomia_luna import calcular_astronomia_lunar
                        astro = calcular_astronomia_lunar()
                        txt_luna = (
                            f"🌕 **FASE LUNAR DE HOY (Bucaramanga, Colombia)**\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🌓 **Fase:** {astro['fase']}\n"
                            f"✨ **Iluminación:** {astro['iluminacion']}%\n"
                            f"📅 **Edad lunar:** {astro['edad']} días\n"
                            f"🌍 **Distancia:** {astro['distancia']:,} km\n\n"
                            f"🌙 ↗️ **Salida:** {astro['salida']}\n"
                            f"🌙 ↘️ **Puesta:** {astro['puesta']}\n"
                        ).replace(",", ".")
                        enviar_mensaje(chat_id, txt_luna, reply_to_message_id=msg_id)
                    except Exception as e_luna_cmd:
                        enviar_mensaje(chat_id, f"⚠️ Error calculando fase lunar: {e_luna_cmd}", reply_to_message_id=msg_id)
                    continue
                elif cmd == "/panel":
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "🚫 Solo los administradores pueden usar el panel de control.", reply_to_message_id=msg_id)
                        continue
                    teclado_panel = {
                        "inline_keyboard": [
                            [{"text": "⏪ -30s", "callback_data": "panel_rewind"}, {"text": "⏯️ Pausa / Play", "callback_data": "panel_play"}, {"text": "⏩ +30s", "callback_data": "panel_forward"}],
                            [{"text": "🔉 Vol -", "callback_data": "panel_voldown"}, {"text": "⏹️ Detener", "callback_data": "panel_stop"}, {"text": "🔊 Vol +", "callback_data": "panel_volup"}],
                            [{"text": "➕ Encolar Audio", "callback_data": "panel_encolar"}, {"text": "📋 Ver Cola", "callback_data": "panel_vercola"}, {"text": "⏭️ Sig. Audio", "callback_data": "panel_nextaudio"}],
                            [{"text": "🗑️ Limpiar Cola", "callback_data": "panel_limpiarcola"}, {"text": "🎤 Sig. Turno", "callback_data": "panel_nextturno"}, {"text": "✋ Limpiar Turnos", "callback_data": "panel_limpiarturnos"}],
                            [{"text": "🔓 Abrir Micros", "callback_data": "panel_desmutear"}, {"text": "🧹 Limpiar Sala", "callback_data": "panel_limpiar"}]
                        ]
                    }
                    enviar_mensaje(chat_id, "🎛 **PANEL DE CONTROL DE SALA**\n*(Solo funciona durante la llamada)*\nPresiona los botones para controlar el bot en tiempo real:", reply_markup=teclado_panel)
                    eliminar_mensaje(chat_id, msg_id)
                elif cmd in ("/aviso", "/recordatorio", "/preparacion", "/aviso30min"):
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "⛔ Solo los administradores pueden enviar el aviso de preparación.", reply_to_message_id=msg_id)
                        continue
                    enviar_aviso_preparacion_sala(target_chat_id=chat_id, forzar=True)
                    if chat_id > 0:
                        enviar_mensaje(chat_id, "✅ Aviso de preparación enviado exitosamente.", reply_to_message_id=msg_id)
                    continue
                elif cmd in ("/tarea", "/anunciartarea", "/anunciar", "/publicartarea", "/guardaraudio", "/setaudio"):
                    # Si se llama /tarea a secas (sin parametros), entregar la tarea programada del dia a cualquiera (admin o miembro)
                    if cmd == "/tarea" and len(partes) == 1 and not (msg.get("reply_to_message")):
                        info_act = obtener_info_tarea_hoy()
                        if info_act:
                            entregar_audio_meditacion(chat_id, info_act, msg_id_reply=msg_id, user_id_privado=user_id)
                        else:
                            enviar_mensaje(chat_id, "ℹ️ Aún no hay una tarea programada para hoy.", reply_to_message_id=msg_id)
                        continue

                    # Si se intenta programar o anunciar la tarea con parametros, exigir permisos de administrador
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "⛔ Solo los administradores pueden programar o anunciar la tarea del día.", reply_to_message_id=msg_id)
                        continue

                    param_texto = " ".join(partes[1:]).strip() if len(partes) > 1 else ""
                    reply_m = msg.get("reply_to_message") or {}
                    if not param_texto and reply_m:
                        param_texto = (reply_m.get("text") or reply_m.get("caption") or "").strip()
                    if not param_texto:
                        enviar_mensaje(chat_id, "ℹ️ Uso: `/tarea [número o nombre]` (ej: `/tarea 20` o responde a un audio con `/tarea`).", reply_to_message_id=msg_id)
                    else:
                        info_cat = identificar_audio_catalogo(texto=param_texto)
                        if info_cat:
                            msg_id_audio = reply_m.get("message_id") if reply_m else None
                            reply_audio = (reply_m.get("audio") or reply_m.get("voice") or reply_m.get("document")) if reply_m else None
                            f_id = reply_audio.get("file_id") if (reply_audio and isinstance(reply_audio, dict)) else None
                            if f_id:
                                info_cat["file_id"] = f_id
                            if msg_id_audio:
                                info_cat["msg_id_audio"] = msg_id_audio

                            # Si no se pasó audio adjunto ni existía file_id, buscar y subir automáticamente desde Google Drive
                            if not f_id and not msg_id_audio and info_cat.get("numero"):
                                try:
                                    t_nom = "Meditación" if "MEDITACI" in str(info_cat.get("tipo", "")).upper() else "Mensaje"
                                    n_num = int(info_cat["numero"])
                                    enviar_mensaje(chat_id, f"🔍 Buscando audio para {t_nom} #{n_num} en Google Drive...", reply_to_message_id=msg_id)
                                    ruta_audio_desc = obtener_o_descargar_audio(info_cat.get("tipo", "MEDITACION"), n_num)
                                    if ruta_audio_desc and os.path.exists(ruta_audio_desc):
                                        cap_audio = (
                                            f"🧘 **{t_nom} #{n_num}**\n"
                                            f"📌 **Título:** «{info_cat.get('titulo', '')}»\n"
                                            f"👤 **Maestro:** {info_cat.get('maestro', 'Alaniso')}\n"
                                            f"🗓️ **Grabación original:** {info_cat.get('fecha', '')}\n\n"
                                            f"🎧 Audio oficial para la práctica de hoy."
                                        )
                                        bot_u = obtener_info_bot()
                                        clean_t = "mensaje" if "MENSAJE" in str(info_cat.get("tipo", "")).upper() else "meditacion"
                                        param_priv = f"audio_{clean_t}_{n_num}"
                                        teclado_aud = {"inline_keyboard": [[{"text": "📥 RECIBIR AUDIO EN MI TELEGRAM PRIVADO 🎧", "url": f"https://t.me/{bot_u}?start={param_priv}"}]]} if bot_u else None
                                        target_chat_audio = CHAT_ID if (int(chat_id) > 0 and CHAT_ID) else chat_id
                                        ok_a, m_id_a, f_id_a = enviar_audio(
                                            target_chat_audio,
                                            ruta_audio_desc,
                                            caption=cap_audio,
                                            title=f"{t_nom} #{n_num} - {info_cat.get('titulo', '')}",
                                            performer=info_cat.get('maestro', 'Alaniso'),
                                            reply_markup=teclado_aud
                                        )
                                        if ok_a:
                                            f_id = f_id_a
                                            msg_id_audio = m_id_a
                                            info_cat["file_id"] = f_id_a
                                            info_cat["msg_id_audio"] = m_id_a
                                except Exception as e_aud_cmd:
                                    print("Nota buscando/subiendo audio en comando /tarea:", e_aud_cmd)

                            guardar_audio_registrado(info_cat, file_id=f_id, msg_id=msg_id_audio)


                            if cmd in ("/guardaraudio", "/setaudio"):
                                enviar_mensaje(chat_id, f"✅ Audio vinculado exitosamente a **{info_cat.get('tipo', 'MEDITACION').title()} #{info_cat['numero']}**: «{info_cat['titulo']}».", reply_to_message_id=msg_id)
                                continue

                            try:
                                os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
                                with open(os.path.join("data", "meditaciones", "meta_hoy.json"), "w", encoding="utf-8") as fm:
                                    json.dump(info_cat, fm, ensure_ascii=False, indent=2)
                            except Exception:
                                pass
                            fecha_admin = extraer_fecha_de_texto(param_texto) or (extraer_fecha_de_texto(reply_m.get("text") or reply_m.get("caption") or "") if reply_m else None)
                            anuncio = generar_anuncio_tarea(info_cat, fecha_admin)
                            teclado = armar_teclado_audio(chat_id, msg_id_audio, numero_tarea=info_cat.get('numero'), tipo_tarea=info_cat.get('tipo'))
                            m_id = enviar_mensaje(chat_id, anuncio, reply_markup=teclado)
                            if m_id:
                                _TAREA_FLOTANTE.update({"msg_id": m_id, "contador": 0, "texto": anuncio, "reply_markup": teclado, "chat_id": chat_id})
                            fecha_priv = fecha_admin or datetime.now(ZoneInfo("America/Bogota")).strftime("%d/%m/%Y")
                            # ── Deduplicar declaración de tarea ─────────────────────────────
                            # Si Render arranca dos instancias, ambas procesarán el mismo
                            # update. Guardamos el update_id de la última tarea procesada en
                            # disco.  Si coincide, no volvemos a notificar.
                            _tarea_uid_file = os.path.join("data", "ultima_tarea_update_id.txt")
                            _tarea_uid_actual = str(_uid) if "_uid" in dir() else ""
                            _ya_procesada = False
                            try:
                                if os.path.exists(_tarea_uid_file) and _tarea_uid_actual:
                                    with open(_tarea_uid_file, "r") as _f_tuid:
                                        if _f_tuid.read().strip() == _tarea_uid_actual:
                                            print(f"⚠️ Tarea update_id={_tarea_uid_actual} ya procesada, saltando notificaciones.")
                                            _ya_procesada = True
                                if not _ya_procesada and _tarea_uid_actual:
                                    with open(_tarea_uid_file, "w") as _f_tuid_w:
                                        _f_tuid_w.write(_tarea_uid_actual)
                            except Exception:
                                pass

                            if not _ya_procesada:
                                db_pts = cargar_puntos()
                                usuarios = db_pts.get("usuarios", {})
                                sin_privado = cargar_usuarios_sin_privado()
                                enviados_priv = 0
                                for u_id, datos in usuarios.items():
                                    if str(u_id) == str(chat_id):
                                        continue
                                    if str(u_id) in sin_privado:
                                        continue
                                    # Solo enviar a usuarios con chat privado positivo
                                    try:
                                        if int(str(u_id)) <= 0:
                                            continue
                                    except ValueError:
                                        continue
                                    txt_priv = (
                                        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
                                        f"📢 ⚠️ **¡ATENCIÓN {datos.get('nombre', 'Compañero').upper()}!** ⚠️ 📢\n"
                                        f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
                                        f"🗓️ **FECHA: {fecha_priv}**\n"
                                        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
                                        f"Hola **{datos.get('nombre', 'Compañero')}**, hoy en la reunión de las 7:56 PM trabajaremos:\n\n"
                                        f"🧘 **{info_cat.get('tipo', 'MEDITACION').upper()} #{info_cat['numero']}**\n"
                                        f"📌 **Título:** «{info_cat['titulo']}»\n"
                                        f"👤 **Maestro:** {info_cat['maestro']} | 🗓️ **Fecha:** {info_cat['fecha']}\n\n"
                                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                        f"⏰ **¡Te esperamos puntual esta noche a las 7:56 PM!**\n"
                                        f"👇 *Toca el botón abajo para escuchar el audio directamente.*"
                                    )
                                    if enviar_mensaje(u_id, txt_priv, reply_markup=teclado):
                                        enviados_priv += 1
                                log_debug(f"Notificaciones privadas de tarea enviadas a {enviados_priv} miembros con chat activo.")
                        else:
                            enviar_mensaje(chat_id, f"ℹ️ No se encontró ninguna meditación o mensaje correspondiente a «{param_texto}» en el catálogo.", reply_to_message_id=msg_id)
                elif cmd in ("/turno", "/pedirturno", "/ceder", "/turnos", "/mano"):
                    resp = (
                        "🎙️ **Moderación y Turnos de Palabra:**\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "La lista de turnos se gestiona en tiempo real dentro del grupo durante la llamada diaria (7:56 PM a 10:30 PM).\n\n"
                        "✋ **Para pedir la palabra:** Escribe `/turno` en el grupo o levanta la mano ✋ en la sala de voz.\n"
                        "🤝 **Para ceder la palabra:** Escribe `/ceder` en el grupo.\n"
                        "📋 **Para ver la cola:** Escribe `/turnos` en el grupo.\n"
                        "🔇 **Protección anti-ruido:** Si tu micrófono queda abierto sin hablar por 5 segundos, el sistema lo silenciará automáticamente para proteger la sala."
                    )
                    enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)
                elif cmd in ("/buscar",):
                    termino = " ".join(partes[1:]) if len(partes) > 1 else ""
                    resp = buscar_en_minutas(termino)
                    enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)
                elif cmd in ("/resumen",):
                    fecha_req = partes[1].strip() if len(partes) > 1 else None
                    minuta = obtener_minuta(fecha_req)
                    if minuta:
                        resp = f"📝 **MINUTA DE LA REUNIÓN ({minuta['fecha']})**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{minuta['resumen']}"
                        enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)
                    else:
                        enviar_mensaje(chat_id, f"ℹ️ No se encontró ninguna minuta registrada para {fecha_req or 'la última fecha'}.", reply_to_message_id=msg_id)
                elif cmd in ("/acta",):
                    fecha_req = partes[1].strip() if len(partes) > 1 else None
                    minuta = obtener_minuta(fecha_req)
                    if minuta and minuta.get("ruta_pdf") and os.path.exists(minuta["ruta_pdf"]):
                        enviar_documento(chat_id, minuta["ruta_pdf"], caption=f"📄 **Acta Oficial de la Reunión ({minuta['fecha']})**")
                    else:
                        enviar_mensaje(chat_id, "ℹ️ No hay un documento PDF de acta disponible para esa fecha.", reply_to_message_id=msg_id)
                elif cmd in ("/oracion",) or (cmd == "/start" and param == "oracion"):
                    resp = (
                        "🕊️ **ORACIÓN Y RECOGIMIENTO COMUNITARIO**\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "\"En este momento de quietud y gratitud, acallamos nuestra mente y abrimos el corazón.\n\n"
                        "Agradecemos por este día, por cada respiración, por los aprendizajes recibidos y por la presencia de cada persona en esta comunidad.\n\n"
                        "Pedimos paz profunda en nuestro interior, claridad en los pensamientos, serenidad en las acciones y bienestar para nuestras familias.\n\n"
                        "Guardamos silencio y respiramos en calma, presentes en el aquí y el ahora.\"\n\n"
                        "🙏 *Mantengamos silencio en la sala para cultivar la paz interior de todos.*"
                    )
                    enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)
                elif cmd in ("/reglas", "/ayuda") or (cmd == "/start" and param == "reglas") or cmd == "/start":
                    resp = generar_texto_reglas()
                    enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)

        except Exception as e:
            print("Error en bucle de comandos:", e)
            import sys; sys.stdout.flush()
            time.sleep(3)


if __name__ == "__main__":
    escuchar_comandos()
