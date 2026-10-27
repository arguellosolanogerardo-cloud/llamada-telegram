import os
import zipfile

db_path = os.path.join("data", "biblioteca_conocimiento_universal.db")
zip_path = os.path.join("data", "biblioteca.zip")
if not os.path.exists(db_path) and os.path.exists(zip_path):
    try:
        print("Descomprimiendo la Biblioteca del Conocimiento Universal...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall("data")
    except Exception as e:
        print("Error descomprimiendo BD:", e)

import asyncio
import json
import os
import re
import time
import urllib.request
import urllib.parse
import threading
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler

from ia_resumen import buscar_en_minutas, obtener_minuta
from catalogo_audios import identificar_audio_catalogo, formatear_info_audio, identificar_todos_los_audios, formatear_cola_audios
from publicar_tarea import generar_anuncio_tarea, armar_teclado_audio, extraer_fecha_de_texto, obtener_info_bot
from drive_manager import obtener_o_descargar_audio, buscar_audio_en_drive

BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_ID = int(BOT_TOKEN.split(":")[0]) if (BOT_TOKEN and ":" in BOT_TOKEN) else None
CHAT_ID = os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP")
TG_API_ID = os.environ.get("TG_API_ID")
TG_API_HASH = os.environ.get("TG_API_HASH")
TG_SESSION = os.environ.get("TG_SESSION")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

RUTA_PUNTOS = os.path.join("data", "puntos.json")
RUTA_AUDIOS_REGISTRADOS = os.path.join("data", "meditaciones", "audios_registrados.json")
RUTA_MSGS_BOT = os.path.join("data", "mensajes_bot_grupo.json")
URL_RAW_GITHUB = "https://raw.githubusercontent.com/arguellosolanogerardo-cloud/llamada-telegram/main/data/puntos.json"

COLA_LOGS = []
_TAREA_FLOTANTE = {"msg_id": None, "contador": 0, "texto": "", "reply_markup": None, "chat_id": None}

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


def guardar_audio_registrado(info_cat: dict, file_id: str = None, msg_id: int | str = None) -> None:
    if not info_cat:
        return
    try:
        os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
        db = cargar_audios_registrados()
        tipo = str(info_cat.get("tipo", "MEDITACION")).upper()
        num = str(info_cat.get("numero", "")).strip()
        registro = dict(info_cat)
        if file_id:
            registro["file_id"] = file_id
        if msg_id:
            registro["msg_id_audio"] = msg_id
        for k in [f"{tipo}_{num}", num]:
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

    # 3. Disparar workflow de limpieza en GitHub Actions si GITHUB_TOKEN est├í presente
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
        if self.path in ("/aviso", "/aviso_previo", "/recordatorio"):
            m_id = enviar_aviso_preparacion_sala()
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message_id": m_id}).encode())
            return
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot Comandos OK")

    def do_POST(self):
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
                    os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
                    ruta_meta = os.path.join("data", "meditaciones", "meta_hoy.json")
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


def iniciar_servidor_health():
    port = int(os.environ.get("PORT", 8000))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        server.serve_forever()
    except Exception as e:
        print("Nota servidor health check:", e)



def obtener_rango(puntos: int) -> str:
    if puntos >= 1800:
        return "≡ƒÆÄ Diamante"
    if puntos >= 750:
        return "≡ƒÑç Oro"
    if puntos >= 250:
        return "≡ƒÑê Plata"
    return "≡ƒÑë Bronce"


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
    # Identificadores de administradores an├│nimos en Telegram
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
    """Verifica si un mensaje proviene de un administrador o del due├▒o (incluye administradores an├│nimos o que env├¡an como el grupo/canal)."""
    from_user = msg.get("from", {})
    user_id = from_user.get("id")

    # Rechazar cualquier bot como administrador (a menos que sea el bot an├│nimo oficial de Telegram)
    if from_user.get("is_bot") and user_id != 1087968824 and from_user.get("username") != "GroupAnonymousBot":
        return False
    if BOT_ID and user_id == BOT_ID:
        return False

    # 1. Si el mensaje se envi├│ a nombre del grupo o canal
    sender_chat = msg.get("sender_chat")
    if sender_chat:
        sc_id = sender_chat.get("id")
        if sc_id and (str(sc_id) == str(chat_id) or (CHAT_ID and str(sc_id) == str(CHAT_ID))):
            return True

    # 2. Si el remitente es el bot an├│nimo oficial de Telegram (@GroupAnonymousBot)
    if user_id == 1087968824 or from_user.get("username") == "GroupAnonymousBot":
        return True

    # 3. Verificar si el usuario est├í en la lista de administradores del grupo
    if user_id:
        admins_set = obtener_admin_ids(chat_id)
        if user_id in admins_set:
            return True

    return False


def generar_texto_miperfil(user_id: int, db_puntos: dict, user_nombre: str = "", es_admin: bool = False) -> str:
    if es_admin:
        nombre = user_nombre or "Administrador"
        return (
            f"≡ƒææ **PERFIL DE MODERACI├ôN: {nombre}**\n"
            "ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü\n"
            "≡ƒ¢í∩╕Å **Rol:** Administrador / Moderador de la Sala\n\n"
            "Γä╣∩╕Å *Los administradores y moderadores est├ín exentos del sistema de puntos y no participan en los rankings ni podios de puntualidad, garantizando una competencia justa y transparente para toda la comunidad.*"
        )

    usuarios = db_puntos.get("usuarios", {})
    u = usuarios.get(str(user_id))
    if not u:
        nombre = user_nombre or "Compa├▒ero"
        return (
            f"≡ƒæñ **Perfil de Asistencia:** {nombre}\n\n"
            f"A├║n no registras asistencias v├ílidas en las llamadas.\n"
            f"┬í├Ünete hoy a las 7:56 PM para ganar tus primeros puntos y subir de rango!"
        )
    nombre = u.get("nombre", user_nombre or "Usuario")
    pts_mes = u.get("puntos_mes", u.get("puntos_totales", 0))
    pts_tot = u.get("puntos_totales", 0)
    rango = obtener_rango(pts_tot)
    racha = u.get("racha_actual", 0)
    asistencias_mes = u.get("asistencias_mes", 0)
    asistencias_tot = u.get("asistencias_totales", 0)
    medallas = u.get("medallas", [])
    txt_medallas = "\nΓÇó " + "\nΓÇó ".join(medallas) if medallas else "Ninguna a├║n"

    return (
        f"≡ƒæñ **FICHA DE USUARIO: {nombre}**\n"
        f"ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü\n"
        f"≡ƒÄû∩╕Å **Rango actual:** {rango}\n"
        f"≡ƒÅå **Puntos del mes:** {pts_mes} pts\n"
        f"Γ¡É **Puntos hist├│ricos:** {pts_tot} pts\n"
        f"≡ƒöÑ **Racha actual:** {racha} d├¡as consecutivos\n"
        f"≡ƒôà **Asistencias:** {asistencias_mes} este mes ({asistencias_tot} en total)\n\n"
        f"≡ƒÅà **Medallas obtenidas:**{txt_medallas}"
    )


def generar_texto_ranking(db_puntos: dict, admin_ids: set = None) -> str:
    usuarios = db_puntos.get("usuarios", {})
    if not usuarios:
        return "≡ƒÅå **Ranking Mensual:** A├║n no hay registros de asistencia este mes."

    if admin_ids is None:
        admin_ids = obtener_admin_ids()

    usuarios_filtrados = [
        u for u in usuarios.values()
        if int(u.get("id", 0)) not in admin_ids
    ]
    if not usuarios_filtrados:
        return "≡ƒÅå **Ranking Mensual:** A├║n no hay registros de participantes de la comunidad este mes."

    top = sorted(usuarios_filtrados, key=lambda x: x.get("puntos_mes", x.get("puntos_totales", 0)), reverse=True)[:10]
    lineas = [
        "≡ƒÅå **TOP 10 DE ASISTENCIA Y PUNTOS (ESTE MES)** ≡ƒÅå",
        "ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü",
    ]
    medallas_top = ["≡ƒÑç", "≡ƒÑê", "≡ƒÑë"] + [f"{i}." for i in range(4, 11)]
    for i, u in enumerate(top):
        pts = u.get("puntos_mes", u.get("puntos_totales", 0))
        rango = obtener_rango(u.get("puntos_totales", 0))
        medallas = " ".join([m.split()[0] for m in u.get("medallas", [])])
        lineas.append(f"{medallas_top[i]} {rango} **{u['nombre']}** ΓÇö {pts} pts {medallas}".strip())

    lineas.append("\n≡ƒÆí Escribe `/puntos` para ver tus estad├¡sticas personales.")
    return "\n".join(lineas)


def generar_texto_reglas() -> str:
    return (
        "≡ƒô£ **SISTEMA DE PUNTOS Y REGLAS DE LA COMUNIDAD**\n"
        "ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü\n"
        "Cada noche a las 7:56 PM se abre la llamada diaria. ┬íParticipa y suma puntos!\n\n"
        "ΓÅ░ **PUNTUALIDAD:**\n"
        "ΓÇó Entrar en los primeros 5 min: **+25 pts**\n"
        "ΓÇó Entrar entre min 5 y 10: **+15 pts**\n\n"
        "≡ƒîƒ **PERMANENCIA:**\n"
        "ΓÇó Asistencia completa (>= 80% de la sesi├│n): **+50 pts**\n"
        "ΓÇó Asistencia parcial: **+20 a +35 pts**\n\n"
        "≡ƒÄÖ∩╕Å **MICR├ôFONO / VOZ:**\n"
        "ΓÇó Hablar y aportar activamente: **+20 pts**\n\n"
        "≡ƒºÿ **MEDITACI├ôN DIARIA (8:32 PM):**\n"
        "ΓÇó Participar en la meditaci├│n: **+30 pts**\n\n"
        "≡ƒöÑ **RACHAS:**\n"
        "ΓÇó Asistir d├¡as seguidos: **+5 pts extra por d├¡a consecutivo**\n\n"
        "≡ƒÅà **MEDALLAS ESPECIALES:**\n"
        "ΓÇó ≡ƒ¢í∩╕Å *Puntualidad de Hierro:* 5 d├¡as seguidos en el podio (Top 9 de puntualidad).\n"
        "ΓÇó ≡ƒÄÖ∩╕Å *Voz de la Comunidad:* Hablar en 7 llamadas consecutivas.\n"
        "ΓÇó ≡ƒºÿ *Mente Serena:* Completar 10 meditaciones en el mes.\n"
        "ΓÇó ≡ƒææ *Centinela:* Asistir a m├ís del 90% de las reuniones del mes.\n\n"
        "≡ƒææ **ADMINISTRADORES Y MODERADORES:**\n"
        "ΓÇó Los administradores y moderadores est├ín exentos del sistema de puntos y no entran en el ranking ni en el podio de puntualidad, garantizando una competencia justa para todos los miembros de la comunidad.\n\n"
        "Γ£ï **TURNOS Y MODERACI├ôN DE MICR├ôFONOS:**\n"
        "ΓÇó Escribe `/turno` en el grupo o levanta la mano Γ£ï en la sala para pedir la palabra.\n"
        "ΓÇó M├íximo 2 personas hablando a la vez para evitar interferencias.\n"
        "ΓÇó Si dejas el micr├│fono abierto sin hablar por 5 segundos, el bot lo silenciar├í autom├íticamente para proteger la sala de ruidos de fondo.\n\n"
        "≡ƒô¥ **MINUTAS Y ACTAS CON IA:**\n"
        "ΓÇó Escribe `/resumen` para leer la minuta oficial de la ├║ltima sesi├│n.\n"
        "ΓÇó Escribe `/buscar <palabra>` para encontrar temas tratados en llamadas anteriores.\n"
        "ΓÇó Escribe `/acta [fecha]` para consultar el documento formal.\n\n"
        "≡ƒææ **GRABACI├ôN (SOLO ADMINS):**\n"
        "ΓÇó `/estadograbacion` ΓÇö Consultar estado actual.\n"
        "ΓÇó `/pausargrabacion` ΓÇö Pausar la grabaci├│n (ej. tema confidencial).\n"
        "ΓÇó `/reanudargrabacion` ΓÇö Reanudar la grabaci├│n.\n"
        "ΓÇó `/detenergrabacion` ΓÇö Cancelar y borrar grabaci├│n de hoy.\n\n"
        "≡ƒÆÄ **RANGOS:** Bronce (<250) | Plata (250+) | Oro (750+) | Diamante (1800+)\n"
        "┬íLos 3 primeros del mes reciben menci├│n de honor!"
    )


def enviar_mensaje(chat_id: int | str, texto: str, reply_to_message_id: int = None, reply_markup: dict = None) -> int | None:
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

    datos = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res_data = json.loads(r.read().decode())
            m_id = res_data.get("result", {}).get("message_id")
            if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                registrar_msg_bot(m_id)
            return m_id
    except Exception as e:
        print(f"Error enviando mensaje a {chat_id}:", e)
    return None


def enviar_foto(chat_id: int | str, ruta_foto: str, caption: str = "", reply_markup: dict = None) -> int | None:
    if not BOT_TOKEN or not ruta_foto or not os.path.exists(ruta_foto):
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {
        "chat_id": str(chat_id),
        "caption": caption,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
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
            log_debug(f"Telegram rechaz├│ foto ({chat_id}): {res}")
    except Exception as e:
        log_debug(f"Error enviando foto a {chat_id}: {e}")
    return None


def generar_banner_aviso_previo(ruta_salida: str, info_tarea: dict = None) -> str | None:
    """Genera la tarjeta gráfica oficial en alta resolución para el aviso de preparación de las 7:26 PM.
    Utiliza la plantilla visual HD (data/assets/plantilla_aviso_30min.png) sobreescribiendo la meditación del día.
    Si la plantilla no estuviera disponible, genera el diseño programático como fallback.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        # 1. Determinar el texto de la meditación del día
        tipo = info_tarea.get('tipo', 'Meditación').capitalize() if info_tarea else "Meditación"
        num = info_tarea.get('numero', '') if info_tarea else ""
        tit = info_tarea.get('titulo', '') if info_tarea else ""
        maestro = info_tarea.get('maestro', '') if info_tarea else ""

        if num and tit:
            txt_med = f"🧘 Sesión de Hoy: {tipo} #{num} - «{tit}»"
            if maestro:
                txt_med += f" ({maestro})"
        elif tit:
            txt_med = f"🧘 Sesión de Hoy: «{tit}»"
        else:
            txt_med = "🧘 Sesión de Hoy: Videollamada y Meditación en Directo"

        if len(txt_med) > 85:
            txt_med = txt_med[:82] + "..."

        ruta_plantilla = os.path.join("data", "assets", "plantilla_aviso_30min.png")

        # 2. Si existe la plantilla visual HD subida por el usuario
        if os.path.exists(ruta_plantilla):
            img = Image.open(ruta_plantilla).convert("RGB")
            draw = ImageDraw.Draw(img)

            font_tarea = None
            for fn in ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]:
                try:
                    font_tarea = ImageFont.truetype(fn, 19)
                    break
                except Exception:
                    continue
            if not font_tarea:
                font_tarea = ImageFont.load_default()

            try:
                bbox = draw.textbbox((0, 0), txt_med, font=font_tarea)
                th = bbox[3] - bbox[1]
            except Exception:
                th = 20
            y_text = 143 + (56 - th) // 2

            draw.text((68, y_text), txt_med, fill=(254, 243, 199), font=font_tarea)

            os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
            img.save(ruta_salida, "PNG", optimize=True)
            return ruta_salida

        # Fallback programático (si no está el archivo de plantilla)
        width, height = 1080, 680
        img = Image.new("RGB", (width, height), color=(15, 23, 42))
        draw = ImageDraw.Draw(img)

        for y in range(height):
            r = int(14 + (28 - 14) * (y / height))
            g = int(20 + (16 - 20) * (y / height))
            b = int(48 + (72 - 48) * (y / height))
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        draw.rounded_rectangle([(16, 16), (width - 16, height - 16)], radius=24, outline=(99, 102, 241), width=3)
        draw.rounded_rectangle([(22, 22), (width - 22, height - 22)], radius=20, outline=(56, 189, 248), width=2)

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

        draw.rounded_rectangle([(45, 38), (width - 45, 128)], radius=18, fill=(67, 24, 255), outline=(147, 197, 253), width=2)
        draw.text((75, 58), "AVISO: VIDEOLLAMADA EN 30 MINUTOS (7:56 PM)", fill=(255, 255, 255), font=font_badge)

        y_caja_start = 148
        if info_tarea:
            draw.rounded_rectangle([(45, y_caja_start), (width - 45, y_caja_start + 65)], radius=14, fill=(120, 53, 15), outline=(245, 158, 11), width=2)
            draw.text((70, y_caja_start + 20), txt_med, fill=(254, 243, 199), font=font_tarea)
            y_caja_start += 80

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

        draw.text((75, height - 52), "Grupo La Verdad Os Hará Libres  •  Apertura en directo a las 7:56 PM", fill=(148, 163, 184), font=font_body)

        os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
        img.save(ruta_salida, "PNG")
        return ruta_salida
    except Exception as e:
        log_debug(f"Nota generando banner con Pillow: {e}")
        return None


_LOCK_AVISO = threading.Lock()
_FECHA_ULTIMO_AVISO: str | None = None


def enviar_aviso_preparacion_sala(target_chat_id=None, forzar=False) -> int | None:
    """Env├¡a el aviso previo. Sin `forzar`, solo se env├¡a una vez por d├¡a (Colombia)."""
    global _FECHA_ULTIMO_AVISO
    cid = target_chat_id or CHAT_ID
    if not cid:
        log_debug("Aviso previo: CHAT_ID no configurado")
        return None

    fecha_hoy = datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d")
    with _LOCK_AVISO:
        if not forzar and _FECHA_ULTIMO_AVISO == fecha_hoy:
            log_debug("Aviso previo ya enviado hoy; se omite duplicado")
            return None
        m_id = _enviar_aviso_preparacion_sala_impl(cid)
        if m_id:
            _FECHA_ULTIMO_AVISO = fecha_hoy
        return m_id


def _enviar_aviso_preparacion_sala_impl(cid) -> int | None:

    # Obtener tarea del d├¡a si est├í disponible
    info_tarea = None
    ruta_meta = os.path.join("data", "meditaciones", "meta_hoy.json")
    if os.path.exists(ruta_meta):
        try:
            with open(ruta_meta, "r", encoding="utf-8") as fm:
                info_tarea = json.load(fm)
        except Exception:
            pass

    txt_med_bloque = ""
    if info_tarea and info_tarea.get("numero"):
        tipo = info_tarea.get("tipo", "Meditaci├│n").capitalize()
        num = info_tarea.get("numero")
        tit = info_tarea.get("titulo", "")
        maestro = info_tarea.get("maestro", "")
        txt_med_bloque = f"≡ƒºÿ **Sesi├│n de Hoy:** {tipo} #{num} ΓÇö ┬½{tit}┬╗ ({maestro})\n"

    # Texto con cuadro de cita / blockquote de Telegram
    caption = (
        "≡ƒöö **RECORDATORIO: VIDEOLLAMADA GRUPAL EN 30 MINUTOS** ΓÅ░\n"
        "ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü\n"
        "≡ƒòù **Apertura de sala:** 7:56 PM Colombia\n"
        f"{txt_med_bloque}"
        "> ≡ƒôï **CONSEJOS IMPORTANTES ANTES DE ENTRAR:**\n"
        "> \n"
        "> ≡ƒöï **Bater├¡a:** Carga tu dispositivo al menos al 50% o con├⌐ctalo.\n"
        "> ≡ƒô╢ **Conexi├│n:** Usa Wi-Fi o datos estables (evita cambiar de red durante la llamada).\n"
        "> ΓÜÖ∩╕Å **Android:** Ajusta Telegram en *\"Sin restricciones\"* en Bater├¡a y f├¡jalo con candado en apps recientes.\n"
        "> ≡ƒöü **Estabilidad:** Si se cae seguido: *Ajustes > Privacidad > Llamadas > Peer-to-peer > \"Nunca\"*.\n"
        "> ≡ƒÄº **Espacio y Audio:** Prepara tus aud├¡fonos y busca un lugar tranquilo para la sesi├│n.\n\n"
        "Γ£¿ *┬íNos encontramos puntuales a las 7:56 PM para compartir juntos!*"
    )

    bot_u = obtener_info_bot()
    inline_kb = []
    if bot_u:
        inline_kb.append([
            {"text": "≡ƒºÿ Ver Tarea del D├¡a", "url": f"https://t.me/{bot_u}?start=meditacion"},
            {"text": "≡ƒÅå Ranking Mensual", "url": f"https://t.me/{bot_u}?start=ranking"}
        ])
        inline_kb.append([
            {"text": "≡ƒô£ Reglas de Asistencia y Puntos", "url": f"https://t.me/{bot_u}?start=reglas"}
        ])
    reply_markup = {"inline_keyboard": inline_kb} if inline_kb else None

    # Intentar generar la tarjeta gr├ífica en color v├¡vido
    ruta_banner = os.path.join("data", "meditaciones", "banner_aviso_previo.png")
    ruta_gen = generar_banner_aviso_previo(ruta_banner, info_tarea=info_tarea)

    m_id = None
    if ruta_gen and os.path.exists(ruta_gen):
        m_id = enviar_foto(cid, ruta_gen, caption=caption, reply_markup=reply_markup)

    # Si fall├│ la foto, enviar mensaje de texto formateado con el cuadro
    if not m_id:
        m_id = enviar_mensaje(cid, caption, reply_markup=reply_markup)

    if m_id:
        log_debug(f"Aviso de preparaci├│n enviado con ├⌐xito a {cid}: msg_id={m_id}")
    else:
        log_debug(f"Γ¥î Aviso de preparaci├│n FALL├ô (foto y texto) para {cid}")
    return m_id


def enviar_audio(chat_id: int | str, ruta_audio: str, caption: str = "", title: str = "Meditaci├│n Diaria", performer: str = "Comunidad", reply_markup: dict = None) -> tuple[bool, int | None, str | None]:
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
            if res.get("ok"):
                res_m = res.get("result", {})
                m_id = res_m.get("message_id")
                if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                    registrar_msg_bot(m_id)
                f_id = (res_m.get("audio") or res_m.get("document") or {}).get("file_id") or ruta_audio
                log_debug(f"Audio enviado v├¡a file_id a {chat_id}: msg_id={m_id}")
                return True, m_id, f_id
            log_debug(f"Telegram rechaz├│ audio file_id ({chat_id}): {res}")
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
        log_debug(f"Iniciando subida de audio local a {chat_id} ({os.path.basename(ruta_audio)}, {tam_mb} MB)...")
        with open(ruta_audio, "rb") as f:
            files = {"audio": (os.path.basename(ruta_audio), f, "audio/mpeg")}
            r = requests.post(url, data=data, files=files, timeout=180)
            res = r.json()
            if res.get("ok"):
                res_m = res.get("result", {})
                m_id = res_m.get("message_id")
                if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                    registrar_msg_bot(m_id)
                f_id = (res_m.get("audio") or res_m.get("document") or {}).get("file_id")
                dur = round(time.time() - t_inicio, 1)
                log_debug(f"Audio subido con ├⌐xito a {chat_id} en {dur}s: msg_id={m_id}, file_id={f_id}")
                return True, m_id, f_id
            log_debug(f"Telegram rechaz├│ audio local ({chat_id}): {res}")
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
        ruta_meta = os.path.join("data", "meditaciones", "meta_hoy.json")
        if os.path.exists(ruta_meta):
            try:
                with open(ruta_meta, "r", encoding="utf-8") as fm:
                    info_cat = json.load(fm)
            except Exception:
                pass

    if not info_cat:
        enviar_mensaje(
            chat_id,
            "≡ƒºÿ **Meditaci├│n Diaria:**\nA├║n no hay un audio de meditaci├│n disponible para hoy. Puedes consultar el cat├ílogo escribiendo `/meditacion [n├║mero]` o `/mensaje [n├║mero]`.",
            reply_to_message_id=msg_id_reply
        )
        return

    tipo_nombre = info_cat.get('tipo', 'Meditaci├│n').title()
    num = str(info_cat.get('numero', '')).strip()
    titulo = info_cat.get('titulo', '')
    maestro = info_cat.get('maestro', 'Comunidad')
    fecha = info_cat.get('fecha', '')

    caption = (
        f"≡ƒºÿ **{tipo_nombre} #{num}**\n"
        f"≡ƒôî **T├¡tulo:** ┬½{titulo}┬╗\n"
        f"≡ƒæñ **Gu├¡a:** {maestro}\n"
        f"≡ƒùô∩╕Å **Grabaci├│n original:** {fecha}\n\n"
        "≡ƒÄº Audio para tu pr├íctica en diferido."
    )
    title = f"{tipo_nombre} #{num} - {titulo}"
    performer = maestro

    bot_u = obtener_info_bot()
    clean_tipo = "mensaje" if "MENSAJE" in tipo_nombre.upper() else "meditacion"
    param_audio = f"audio_{clean_tipo}_{num}" if num else "audio"
    teclado_grupo = {"inline_keyboard": [[{"text": "≡ƒôÑ RECIBIR AUDIO EN MI TELEGRAM PRIVADO ≡ƒÄº", "url": f"https://t.me/{bot_u}?start={param_audio}"}]]} if (int(chat_id) < 0 and bot_u) else None

    def enviar_copia_privada(ref_audio):
        if user_id_privado and str(user_id_privado) != str(chat_id) and int(user_id_privado) > 0:
            try:
                enviar_audio(user_id_privado, ref_audio, caption=caption, title=title, performer=performer)
            except Exception:
                pass

    # 1. Buscar en fuentes de audio disponibles
    # A) file_id directo en info_cat
    audio_file_id = info_cat.get("file_id")

    # B) file_id en meta_hoy.json (si coincide el n├║mero o si no se especific├│)
    ruta_meta = os.path.join("data", "meditaciones", "meta_hoy.json")
    meta_hoy = {}
    if os.path.exists(ruta_meta):
        try:
            with open(ruta_meta, "r", encoding="utf-8") as fm:
                meta_hoy = json.load(fm)
        except Exception:
            pass

    if not audio_file_id and meta_hoy:
        if not num or str(meta_hoy.get("numero", "")).strip() == num:
            audio_file_id = meta_hoy.get("file_id")

    # C) file_id en base de datos de audios registrados
    db_audios = cargar_audios_registrados()
    if not audio_file_id and db_audios:
        reg = db_audios.get(f"{tipo_nombre.upper()}_{num}") or db_audios.get(num)
        if reg:
            audio_file_id = reg.get("file_id")

    # Intentar enviar v├¡a file_id si lo tenemos
    if audio_file_id:
        ok, m_id, f_id = enviar_audio(chat_id, audio_file_id, caption=caption, title=title, performer=performer, reply_markup=teclado_grupo)
        if ok:
            enviar_copia_privada(audio_file_id)
            return

    # D) Buscar archivo local en disco
    ruta_local = None
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
    if not msg_id_audio and meta_hoy and (not num or str(meta_hoy.get("numero", "")).strip() == num):
        msg_id_audio = meta_hoy.get("msg_id_audio")
    if not msg_id_audio and db_audios:
        reg = db_audios.get(f"{tipo_nombre.upper()}_{num}") or db_audios.get(num)
        if reg:
            msg_id_audio = reg.get("msg_id_audio")

    origen_grupo = CHAT_ID or meta_hoy.get("chat_id_grupo")
    if msg_id_audio and origen_grupo:
        if copiar_mensaje(chat_id, origen_grupo, msg_id_audio, caption=caption):
            enviar_copia_privada(audio_file_id)
            return

    # F) Descargar autom├íticamente desde Google Drive!
    if num and num.isdigit():
        enviar_mensaje(chat_id, f"≡ƒöì Buscando audio para {tipo_nombre} #{num}...", reply_to_message_id=msg_id_reply)
        ruta_drive = obtener_o_descargar_audio(tipo_nombre, int(num))
        if ruta_drive:
            ok, m_id, f_id = enviar_audio(chat_id, ruta_drive, caption=caption, title=title, performer=performer, reply_markup=teclado_grupo)
            if ok:
                if f_id:
                    guardar_audio_registrado(info_cat, file_id=f_id, msg_id=m_id)
                enviar_copia_privada(f_id or ruta_drive)
                return

    # G) Si a├║n no est├í cargado el archivo en ninguna fuente
    txt_cat = (
        f"≡ƒºÿ **CAT├üLOGO OFICIAL DE AUDIOS**\n"
        f"ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü\n"
        f"≡ƒôî **{tipo_nombre} #{num}:** ┬½{titulo}┬╗\n"
        f"≡ƒæñ **Maestro / Gu├¡a:** {maestro}\n"
        f"≡ƒùô∩╕Å **Fecha de grabaci├│n original:** {fecha}\n\n"
        f"Γä╣∩╕Å El archivo .mp3 correspondiente a├║n no se encuentra registrado en el almacenamiento del bot ni en la carpeta de Google Drive.\n\n"
        f"≡ƒÆí **Para administradores:** Puedes enviar o reenviar el archivo de audio directamente a este chat privado para vincularlo a la meditaci├│n #{num}."
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


def es_solicitud_de_audio(texto: str, chat_id: int | str) -> bool:
    """
    Detecta si un mensaje es una pregunta o petici├│n de un audio del cat├ílogo (meditaci├│n o mensaje).
    Ejemplos:
      - 'tienes el mensaje 989?'
      - '┬┐Tienes la meditacion 21?'
      - 'me pasas el mensaje 800'
      - 'audio del mensaje 989'
      - 'meditacion 21' (en privado o grupo)
    """
    if not texto:
        return False
    t_up = texto.upper()

    # Si es declaraci├│n de tarea diaria para el grupo, no es solicitud individual
    if any(k in t_up for k in ["TAREA PARA MA├æANA", "TAREA PARA MANANA", "MEDITACION DE TAREA", "MENSAJE DE TAREA", "TAREA DE MEDITACION", "TAREA DE MENSAJE"]):
        return False

    tiene_palabra_audio = any(w in t_up for w in ["MEDITACION", "MEDITACI├ôN", "MENSAJE", "AUDIO"])
    tiene_numero = bool(re.search(r"\b\d{1,4}\b", t_up))

    if not (tiene_palabra_audio and tiene_numero):
        return False

    # En chat privado (chat_id > 0), cualquier menci├│n de meditaci├│n/mensaje con n├║mero es para el bot
    if int(chat_id) > 0:
        return True

    # En grupos (chat_id < 0), verificar que sea una pregunta o petici├│n
    verbos = [
        "TIENES", "TIENE", "TIENEN", "HAY", "PASAME", "PASA", "PASAS",
        "COMPARTE", "COMPARTIR", "QUIERO", "QUISIERA", "ENVIAME", "ENVIA",
        "MANDAME", "MANDA", "AUDIO DE", "AUDIO DEL", "BUSCA", "BUSCAR",
        "REGALAME", "ME DAS", "ME PASAS", "QUIEN TIENE", "ALGUIEN TIENE",
        "POR FAVOR", "DESCARGAR", "SUBIR", "DONDE ESTA", "┬┐TIENES", "┬┐HAY",
        "DISPONIBLE", "COMPARTEN"
    ]
    if any(v in t_up for v in verbos):
        return True

    if re.match(r"^(?:MEDITACI[O├ô]N|MENSAJE|AUDIO)\s+#?\d{1,4}", t_up.strip()):
        return True

    return False


def escuchar_comandos() -> None:
    if not BOT_TOKEN:
        print("Error: Define la variable de entorno BOT_TOKEN.")
        return

    # Iniciar servidor HTTP para health check (Koyeb / Render)
    threading.Thread(target=iniciar_servidor_health, daemon=True).start()

    # Iniciar reloj para aviso previo de preparaci├│n autom├ítico (7:26 PM Colombia - 30 min antes)
    def hilo_recordatorio_726():
        tz_col = ZoneInfo("America/Bogota")
        ultimo_intento = 0.0
        while True:
            try:
                ahora = datetime.now(tz_col)
                minutos = ahora.hour * 60 + ahora.minute
                en_ventana = (19 * 60 + 26) <= minutos <= (19 * 60 + 45)
                ya_enviado = _FECHA_ULTIMO_AVISO == ahora.strftime("%Y-%m-%d")
                if en_ventana and not ya_enviado and time.time() - ultimo_intento >= 60:
                    ultimo_intento = time.time()
                    log_debug("ΓÅ░ Disparando aviso previo autom├ítico de preparaci├│n (7:26 PM)...")
                    enviar_aviso_preparacion_sala()
            except Exception as e:
                log_debug(f"Error en hilo_recordatorio_726: {e}")
            time.sleep(20)

    threading.Thread(target=hilo_recordatorio_726, daemon=True).start()

    print("≡ƒñû Bot de comandos iniciado. Escuchando /puntos, /ranking, /reglas, /ayuda, /meditacion, /buscar, /resumen, /acta, /tarea...")
    offset = 0

    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
            req = urllib.request.Request(url, headers={"User-Agent": "BotComandos"})
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.loads(r.read().decode())

            if not res.get("ok"):
                time.sleep(3)
                continue

            for update in res.get("result", []):
                offset = update["update_id"] + 1
                
                if "callback_query" in update:
                    import json
                    cb = update["callback_query"]
                    cb_id = cb.get("id")
                    cb_data = cb.get("data", "")
                    msg_cb = cb.get("message", {})
                    chat_id_cb = msg_cb.get("chat", {}).get("id")
                    
                    if cb_data.startswith("ytmp3_"):

                    
                        vid = cb_data.split("_")[1]

                    
                        url_yt = f"https://www.youtube.com/watch?v={vid}"

                    
                        import urllib.request

                    
                        try:

                    
                            url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"

                    
                            urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "ΓÅ│ Descargando MP3 desde YouTube... (Esto tomar├í 1 minuto)", "show_alert": True}).encode(), headers={"Content-Type": "application/json"}), timeout=10)

                    
                        except: pass

                    
                        def descargar_y_enviar(user_id):

                    
                            import subprocess

                    
                            import os

                    
                            tmp_path = os.path.join("data", f"tmp_{vid}.mp3")

                    
                            cmd = ["python", "-m", "yt_dlp", "-x", "--audio-format", "mp3", "--audio-quality", "5", "-o", tmp_path, url_yt]

                    
                            subprocess.run(cmd)

                    
                            if os.path.exists(tmp_path):

                    
                                try:

                    
                                    url_doc = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"

                    
                                    import requests

                    
                                    with open(tmp_path, "rb") as f_aud:

                    
                                        requests.post(url_doc, data={"chat_id": user_id, "caption": "≡ƒÄº Aqu├¡ tienes el audio solicitado."}, files={"document": f_aud})

                    
                                    os.remove(tmp_path)

                    
                                except: pass

                    
                        import threading

                    
                        threading.Thread(target=descargar_y_enviar, args=(update["callback_query"]["from"].get("id"),)).start()

                    
                        continue

                    
                    elif cb_data.startswith("yttarea_"):

                    
                        vid = cb_data.split("_")[1]

                    
                        url_yt = f"https://www.youtube.com/watch?v={vid}"

                    
                        user_id_cb = update["callback_query"]["from"].get("id")

                    
                        if user_id_cb not in admins_set:

                    
                            try:

                    
                                url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"

                    
                                urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "≡ƒÜ½ Solo administradores.", "show_alert": True}).encode(), headers={"Content-Type": "application/json"}), timeout=10)

                    
                            except: pass

                    
                        else:

                    
                            try:

                    
                                url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"

                    
                                urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "Γ£à Programando audio para esta noche..."}).encode(), headers={"Content-Type": "application/json"}), timeout=10)

                    
                            except: pass

                    
                            enviar_mensaje(chat_id_cb, f"/tarea {url_yt}")

                    
                        continue

                    
                    elif cb_data.startswith("panel_"):
                        import urllib.request
                        import time
                        accion = cb_data.split("_")[1]
                        comando = ""
                        if accion == "play": comando = "/reproducir"
                        elif accion == "pausa": comando = "/pausar"
                        elif accion == "nextaudio": comando = "/saltaraudio"
                        elif accion == "nextturno": comando = "/siguiente"
                        elif accion == "desmutear": comando = "/desmuteartodos"
                        elif accion == "limpiar": comando = "/limpiarsala"
                        elif accion == "stoprec": comando = "/detenergrabacion"
                        
                        if comando and chat_id_cb:
                            m_id_cmd = enviar_mensaje(chat_id_cb, comando)
                            if m_id_cmd:
                                time.sleep(0.5)
                                eliminar_mensaje(chat_id_cb, m_id_cmd)
                        
                        try:
                            url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                            req_ans = urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": f"Ejecutado: {comando}"}).encode(), headers={"Content-Type": "application/json"})
                            urllib.request.urlopen(req_ans, timeout=10)
                        except Exception:
                            pass
                    continue
                
                msg = update.get("message")
                if not msg:
                    continue
                
                # --- LOGICA BIBLIOTECARIO PRIVADO ---
                chat_type = msg.get("chat", {}).get("type")
                if chat_type == "private":
                    texto = msg.get("text", "")
                    msg_id_priv = msg.get("message_id")
                    chat_id_priv = msg.get("chat", {}).get("id")
                    
                    if texto and not texto.startswith("/"):
                        enviar_mensaje(chat_id_priv, "≡ƒöì *Buscando en la Biblioteca Conocimiento Universal...*", reply_to_message_id=msg_id_priv)
                        
                        # Guardar auditorA-a
                        import json
                        auditoria_path = os.path.join("data", "auditoria_consultas.json")
                        consultas = []
                        if os.path.exists(auditoria_path):
                            try:
                                with open(auditoria_path, "r", encoding="utf-8") as f_aud:
                                    consultas = json.load(f_aud)
                            except: pass
                        consultas.append({
                            "fecha": datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d %H:%M:%S"),
                            "usuario_id": from_user.get("id"),
                            "nombre": from_user.get("first_name", "Usuario"),
                            "pregunta": texto
                        })
                        with open(auditoria_path, "w", encoding="utf-8") as f_aud:
                            json.dump(consultas, f_aud, indent=4, ensure_ascii=False)
                            
                        # Buscar en SQLite
                        import sqlite3
                        db_path = os.path.join("data", "biblioteca_conocimiento_universal.db")
                        if os.path.exists(db_path):
                            try:
                                conn = sqlite3.connect(db_path)
                                c = conn.cursor()
                                palabras = texto.lower().replace("buscame", "").replace("donde", "").replace("habla", "").replace("sobre", "").strip().split()
                                query = "SELECT v.titulo, t.inicio_segundos, t.texto, v.video_id FROM transcripciones t INNER JOIN videos v ON t.video_id = v.video_id WHERE "
                                conditions = []
                                params = []
                                for p in palabras:
                                    if len(p) > 3:
                                        conditions.append("t.texto LIKE ?")
                                        params.append(f"%{p}%")
                                if not conditions:
                                    # Fallback
                                    conditions = ["t.texto LIKE ?"]
                                    params = [f"%{texto.strip()}%"]
                                    
                                query += " AND ".join(conditions) + " LIMIT 3"
                                c.execute(query, params)
                                resultados = c.fetchall()
                                conn.close()
                                
                                if resultados:
                                    resp = "≡ƒôÜ **Aqu├¡ tienes lo que encontr├⌐ en la Biblioteca:**\n\n"
                                    for idx, (titulo, seg, txt_frag, vid) in enumerate(resultados):
                                        m = seg // 60
                                        s = seg % 60
                                        url = f"https://youtu.be/{vid}?t={seg}"
                                        resp += f"**{idx+1}. {titulo}**\n"
                                        resp += f"ΓÅ▒∩╕Å *Minuto:* [{m:02d}:{s:02d}]({url})\n"
                                        resp += f"≡ƒÆ¼ \"{txt_frag[:100]}...\"\n\n"
                                    
                                    enviar_mensaje(chat_id_priv, resp)
                                else:
                                    enviar_mensaje(chat_id_priv, "≡ƒÿö No encontr├⌐ ninguna ense├▒anza exacta con esas palabras. Intenta usar otras palabras clave.")
                            except Exception as e:
                                enviar_mensaje(chat_id_priv, f"ΓÜá∩╕Å Error buscando: {e}")
                        else:
                            enviar_mensaje(chat_id_priv, "ΓÅ│ La Biblioteca Aon se estA┬í construyendo. Intenta mAs tarde.")
                    continue
                # ------------------------------------

                # --- LOGICA MENSAJE FLOTANTE ---
                chat_id_msg = msg.get("chat", {}).get("id")
                if chat_id_msg and _TAREA_FLOTANTE["msg_id"] and chat_id_msg == _TAREA_FLOTANTE["chat_id"]:
                    from_id = msg.get("from", {}).get("id")
                    if not BOT_ID or from_id != BOT_ID:
                        from zoneinfo import ZoneInfo
                        from datetime import datetime
                        ahora_flot = datetime.now(ZoneInfo("America/Bogota"))
                        minutos_flot = ahora_flot.hour * 60 + ahora_flot.minute
                        # Solo flota hasta las 7:26 PM (19*60 + 26 = 1166)
                        if minutos_flot < 1166:
                            _TAREA_FLOTANTE["contador"] += 1
                            if _TAREA_FLOTANTE["contador"] >= 8:
                                eliminar_mensaje(chat_id_msg, _TAREA_FLOTANTE["msg_id"])
                                nuevo_id = enviar_mensaje(chat_id_msg, _TAREA_FLOTANTE["texto"], reply_markup=_TAREA_FLOTANTE["reply_markup"])
                                if nuevo_id:
                                    _TAREA_FLOTANTE["msg_id"] = nuevo_id
                                    _TAREA_FLOTANTE["contador"] = 0
                # -------------------------------


                from_user = msg.get("from", {})
                user_id = from_user.get("id")

                # Ignorar completamente bots (excepto an├│nimo oficial) para evitar bucles
                if from_user.get("is_bot") and user_id != 1087968824 and from_user.get("username") != "GroupAnonymousBot":
                    continue
                if BOT_ID and user_id == BOT_ID:
                    continue

                texto = (msg.get("text") or msg.get("caption") or "").strip()
                chat_id = msg["chat"]["id"]
                msg_id = msg["message_id"]
                nombre = f"{from_user.get('first_name', '')} {from_user.get('last_name', '')}".strip()

                # Ignorar mensajes autom├íticos de bot o sistema para prevenir ecos y bucles
                if any(texto.startswith(prefix) for prefix in ("Γ£à", "≡ƒôó", "≡ƒòè∩╕Å", "Γû╢∩╕Å", "≡ƒöì", "≡ƒôï", "≡ƒºÿΓ£¿", "≡ƒÄÖ∩╕Å", "Γä╣∩╕Å", "ΓÜá∩╕Å", "Γ¢ö", "[", "≡ƒö┤", "ΓÜ¬")):
                    continue

                texto_upper = texto.upper()
                if any(k in texto_upper for k in [
                    "DESDE GOOGLE DRIVE", "OBTENIDOS DESDE", "BUSCANDO AUDIO PARA",
                    "TAREA DEL D├ìA", "TAREA DEL DIA", "LISTA DE REPRODUCCI├ôN",
                    "REPRODUCIENDO MEDITACI├ôN", "INICIANDO REPRODUCCI├ôN", "PROGRAMADOS PARA REPRODUCIRSE"
                ]):
                    continue

                # Detectar si se subi├│ un audio/documento o se declar├│ tarea por texto
                audio_obj = msg.get("audio") or msg.get("voice") or msg.get("document")
                es_tarea_declarada = any(k in texto_upper for k in [
                    "MEDITACION DE TAREA", "TAREA DE MEDITACION",
                    "MENSAJE DE TAREA", "TAREA DE MENSAJE",
                    "TAREA PARA MA├æANA", "TAREA PARA MANANA", "TAREA PARA HOY",
                    "TAREA DEL D├ìA", "TAREA DEL DIA",
                    "MEDITACION DE HOY", "MENSAJE DE HOY"
                ]) or (
                    any(t_pal in texto_upper for t_pal in ["TAREA", "MEDITACION", "MEDITACI├ôN", "MENSAJE"])
                    and any(w in texto_upper for w in ["MA├æANA", "MANANA", "PARA HOY", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO", "LUNES", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE"])
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

                        # Si se envi├│ directamente en privado con archivo f├¡sico (solo administradores)
                        if chat_id > 0 and f_id:
                            if not es_mensaje_de_admin(msg, chat_id):
                                enviar_mensaje(
                                    chat_id,
                                    "Γ¢ö Solo los administradores pueden registrar audios oficiales en el cat├ílogo.",
                                    reply_to_message_id=msg_id
                                )
                                continue
                            info_cat["file_id"] = f_id
                            info_cat["msg_id_audio"] = msg_id
                            guardar_audio_registrado(info_cat, file_id=f_id, msg_id=msg_id)
                            enviar_mensaje(
                                chat_id,
                                f"Γ£à **┬íAudio guardado exitosamente!**\n\n"
                                f"≡ƒºÿ **{tipo_audio.title()} #{info_cat['numero']}:** ┬½{info_cat['titulo']}┬╗\n"
                                f"≡ƒæñ **Gu├¡a:** {info_cat['maestro']}\n"
                                f"≡ƒùô∩╕Å **Grabaci├│n:** {info_cat['fecha']}\n\n"
                                f"El bot ha registrado este archivo y ahora se lo entregar├í directamente a cualquier usuario que lo solicite con `/meditacion` o el bot├│n de audio.",
                                reply_to_message_id=msg_id
                            )

                        # Si es declaraci├│n de tarea (en el grupo o en privado por admin)
                        if es_tarea_declarada or (CHAT_ID and str(chat_id) == str(CHAT_ID) and audio_obj):
                            if not es_mensaje_de_admin(msg, chat_id):
                                # Si un usuario no administrador menciona la tarea, solo entregarle la tarea actual que ya fue fijada por los admins
                                log_debug(f"Usuario no admin {user_id} intent├│ programar tarea. Bloqueado.")
                                ruta_meta_actual = os.path.join("data", "meditaciones", "meta_hoy.json")
                                info_cat_act = None
                                if os.path.exists(ruta_meta_actual):
                                    try:
                                        with open(ruta_meta_actual, "r", encoding="utf-8") as f_act:
                                            info_cat_act = json.load(f_act)
                                    except Exception:
                                        pass
                                if info_cat_act:
                                    entregar_audio_meditacion(chat_id, info_cat_act, msg_id_reply=msg_id, user_id_privado=user_id)
                                else:
                                    enviar_mensaje(chat_id, "Γä╣∩╕Å Solo los administradores pueden programar la tarea del d├¡a.", reply_to_message_id=msg_id)
                                continue

                            fecha_admin = extraer_fecha_de_texto(texto)
                            msg_id_audio_final = msg_id if audio_obj else None
                            audios_procesados = []

                            lista_a_procesar = items_encontrados if items_encontrados else [info_cat]
                            for it_proc in lista_a_procesar:
                                t_proc = it_proc.get("tipo", "MEDITACION")
                                n_proc = it_proc.get("numero")
                                fid_proc = f_id if (len(lista_a_procesar) == 1 and f_id) else it_proc.get("file_id")

                                # Si no vino con audio f├¡sico, buscar y descargar autom├íticamente de Google Drive
                                if not fid_proc and n_proc:
                                    enviar_mensaje(chat_id, f"≡ƒöì Buscando audio para {t_proc.title()} #{n_proc}...", reply_to_message_id=msg_id)
                                    log_debug(f"Buscando audio para {t_proc} #{n_proc}...")
                                    ruta_audio_desc = obtener_o_descargar_audio(t_proc, int(n_proc))
                                    if ruta_audio_desc:
                                        cap_audio = f"≡ƒºÿ **{t_proc.title()} #{n_proc}:** ┬½{it_proc.get('titulo', '')}┬╗\n≡ƒæñ **Gu├¡a:** {it_proc.get('maestro', 'Alaniso')}\n≡ƒùô∩╕Å **Grabaci├│n:** {it_proc.get('fecha', '')}"
                                        ok_a, m_id_a, f_id_a = enviar_audio(
                                            chat_id,
                                            ruta_audio_desc,
                                            caption=cap_audio,
                                            title=f"{t_proc.title()} #{n_proc} - {it_proc.get('titulo', '')}",
                                            performer=it_proc.get('maestro', 'Alaniso')
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

                            # 3. Si la orden se dio en privado Y CHAT_ID del grupo est├í configurado, publicar tambi├⌐n en el grupo
                            if chat_id > 0 and CHAT_ID and str(chat_id) != str(CHAT_ID):
                                log_debug(f"Publicando copia de la tarea en el grupo {CHAT_ID}...")
                                teclado_grupo = armar_teclado_audio(CHAT_ID, msg_id_audio_final, numero_tarea=num, tipo_tarea=tipo_audio, audios_lista=audios_procesados)
                                enviar_mensaje(CHAT_ID, anuncio, reply_markup=teclado_grupo)

                            # 4. Enviar notificaci├│n privada a miembros registrados
                            ahora_col = datetime.now(ZoneInfo("America/Bogota"))
                            if not fecha_admin:
                                if ahora_col.hour > 20 or (ahora_col.hour == 20 and ahora_col.minute >= 32):
                                    fecha_priv = (ahora_col + timedelta(days=1)).strftime("%d/%m/%Y")
                                else:
                                    fecha_priv = ahora_col.strftime("%d/%m/%Y")
                            else:
                                fecha_priv = fecha_admin

                            es_hoy_priv = fecha_priv == ahora_col.strftime("%d/%m/%Y")
                            tiempo_saludo = "hoy" if es_hoy_priv else "ma├▒ana"
                            usuarios = db.get("usuarios", {})
                            for u_id, datos in usuarios.items():
                                if (CHAT_ID and str(u_id) == str(CHAT_ID)) or str(u_id) == str(chat_id):
                                    continue
                                if len(audios_procesados) > 1:
                                    txt_items_p = "\n".join(f"ΓÇó **{it.get('tipo', 'Audio').title()} #{it.get('numero')}:** ┬½{it.get('titulo')}┬╗" for it in audios_procesados)
                                    txt_priv = (
                                        f"≡ƒòè∩╕Å **TAREA DEL D├ìA {fecha_priv}** ≡ƒòè∩╕Å\n"
                                        f"Hola **{datos.get('nombre', 'Compa├▒ero')}**, {tiempo_saludo} trabajaremos con:\n\n"
                                        f"{txt_items_p}\n\n"
                                        f"ΓÅ░ Te esperamos puntual a las 7:56 PM para la apertura de la sala."
                                    )
                                else:
                                    txt_priv = (
                                        f"≡ƒòè∩╕Å **TAREA DEL D├ìA {fecha_priv}** ≡ƒòè∩╕Å\n"
                                        f"Hola **{datos.get('nombre', 'Compa├▒ero')}**, {tiempo_saludo} trabajaremos con:\n\n"
                                        f"≡ƒºÿ **{info_cat.get('tipo', 'MEDITACION').title()} #{info_cat['numero']}:** ┬½{info_cat['titulo']}┬╗\n"
                                        f"≡ƒæñ **Gu├¡a:** {info_cat['maestro']} | ≡ƒùô∩╕Å **Grabaci├│n:** {info_cat['fecha']}\n\n"
                                        f"ΓÅ░ Te esperamos puntual a las 7:56 PM para la apertura de la sala."
                                    )
                                enviar_mensaje(u_id, txt_priv, reply_markup=teclado_actual)

                # Petici├│n de audio en lenguaje natural (ej: "┬┐Tienes el mensaje 989?", "meditaci├│n 21")
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
                        enviar_mensaje(chat_id, "Γ¢ö Solo los administradores pueden solicitar la limpieza de la sala.", reply_to_message_id=msg_id)
                        continue

                    # Eliminar la orden escrita por el admin para no dejar rastro
                    eliminar_mensaje(chat_id, msg_id)
                    m_aviso = enviar_mensaje(chat_id, "≡ƒº╣ **Iniciando limpieza:** Eliminando notificaciones y ventanas del bot en la sala...")
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
                elif cmd in ("/meditacion", "/meditacion_hoy", "/audio", "/mensaje") or (cmd == "/start" and (param in ("audio", "meditacion", "tarea") or param.startswith("audio_") or param.startswith("meditacion_") or param.startswith("mensaje_"))):
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
                            enviar_mensaje(chat_id, f"Γä╣∩╕Å No se encontr├│ ninguna meditaci├│n o mensaje correspondiente a ┬½{param_texto}┬╗ en el cat├ílogo.", reply_to_message_id=msg_id)
                            continue
                    else:
                        # Obtener meditaci├│n activa del d├¡a
                        ruta_meta = os.path.join("data", "meditaciones", "meta_hoy.json")
                        if os.path.exists(ruta_meta):
                            try:
                                with open(ruta_meta, "r", encoding="utf-8") as fm:
                                    info_cat = json.load(fm)
                            except Exception:
                                pass
                        if not info_cat:
                            ruta_med = os.path.join("data", "meditaciones", "meditacion_hoy.mp3")
                            if os.path.exists(ruta_med) and os.path.getsize(ruta_med) > 0:
                                info_cat = identificar_audio_catalogo(nombre_archivo=os.path.basename(ruta_med))
                        if not info_cat:
                            db_a = cargar_audios_registrados()
                            if db_a:
                                info_cat = list(db_a.values())[-1]

                    entregar_audio_meditacion(chat_id, info_cat, msg_id_reply=msg_id, user_id_privado=user_id)
                elif cmd in ("/progreso",):
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "≡ƒÜ½ Solo admins.", reply_to_message_id=msg_id)
                        continue
                    estado_path = os.path.join("data", "estado_descarga.json")
                    if os.path.exists(estado_path):
                        import json
                        try:
                            with open(estado_path, "r", encoding="utf-8") as f_est:
                                st = json.load(f_est)
                            barra = "Γûê" * int(st['porcentaje'] / 5) + "Γûæ" * (20 - int(st['porcentaje'] / 5))
                            msg_prog = f"≡ƒôè **Progreso Biblioteca Universal**\n\n"
                            msg_prog += f"[{barra}] {st['porcentaje']}%\n\n"
                            msg_prog += f"Γ£à **Completados:** {st['completados']} / {st['total']}\n"
                            msg_prog += f"ΓÅ│ **Tiempo restante:** {st['tiempo_estimado_restante']}\n"
                            msg_prog += f"ΓÜá∩╕Å **Imprevistos (Errores):** {st['errores']}\n"
                            msg_prog += f"≡ƒöä **├Ültima actualizaci├│n:** {st['ultima_actualizacion']}"
                            enviar_mensaje(chat_id, msg_prog, reply_to_message_id=msg_id)
                        except:
                            enviar_mensaje(chat_id, "ΓÜá∩╕Å Error leyendo el estado de la descarga.", reply_to_message_id=msg_id)
                    else:
                        enviar_mensaje(chat_id, "ΓÅ│ El esc├íner a├║n no ha generado el archivo de progreso. Posiblemente siga en la Fase 1 (Inventario).", reply_to_message_id=msg_id)
                    continue
                elif cmd == "/panel":
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "≡ƒÜ½ Solo los administradores pueden usar el panel de control.", reply_to_message_id=msg_id)
                        continue
                    teclado_panel = {
                        "inline_keyboard": [
                            [{"text": "▶️ Play", "callback_data": "panel_play"}, {"text": "⏸️ Pausa", "callback_data": "panel_pausa"}, {"text": "⏭️ Siguiente", "callback_data": "panel_nextaudio"}],
                            [{"text": "🎙️ Sig. Turno", "callback_data": "panel_nextturno"}, {"text": "🔓 Abrir Micros", "callback_data": "panel_desmutear"}],
                            [{"text": "🧹 Limpiar Sala", "callback_data": "panel_limpiar"}]
                        ]
                    }
                    enviar_mensaje(chat_id, "🎛️ **PANEL DE CONTROL DE SALA**\n*(Solo funciona durante la llamada)*\nPresiona los botones para controlar el bot en tiempo real:", reply_markup=teclado_panel)
                    eliminar_mensaje(chat_id, msg_id)
                elif cmd in ("/aviso", "/recordatorio", "/preparacion", "/aviso30min"):
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "Γ¢ö Solo los administradores pueden enviar el aviso de preparaci├│n.", reply_to_message_id=msg_id)
                        continue
                    enviar_aviso_preparacion_sala(target_chat_id=chat_id, forzar=True)
                    if chat_id > 0:
                        enviar_mensaje(chat_id, "Γ£à Aviso de preparaci├│n enviado exitosamente.", reply_to_message_id=msg_id)
                    continue
                elif cmd in ("/tarea", "/anunciartarea", "/anunciar", "/publicartarea", "/guardaraudio", "/setaudio"):
                    if not es_mensaje_de_admin(msg, chat_id):
                        if cmd == "/tarea" and len(partes) == 1:
                            ruta_meta_act = os.path.join("data", "meditaciones", "meta_hoy.json")
                            info_act = None
                            if os.path.exists(ruta_meta_act):
                                try:
                                    with open(ruta_meta_act, "r", encoding="utf-8") as f_act:
                                        info_act = json.load(f_act)
                                except Exception:
                                    pass
                            if info_act:
                                entregar_audio_meditacion(chat_id, info_act, msg_id_reply=msg_id, user_id_privado=user_id)
                            else:
                                enviar_mensaje(chat_id, "Γä╣∩╕Å A├║n no hay una tarea programada para hoy por los administradores.", reply_to_message_id=msg_id)
                        else:
                            enviar_mensaje(chat_id, "Γ¢ö Solo los administradores pueden programar o anunciar la tarea del d├¡a.", reply_to_message_id=msg_id)
                        continue

                    param_texto = " ".join(partes[1:]).strip() if len(partes) > 1 else ""
                    reply_m = msg.get("reply_to_message") or {}
                    if not param_texto and reply_m:
                        param_texto = (reply_m.get("text") or reply_m.get("caption") or "").strip()
                    if not param_texto:
                        enviar_mensaje(chat_id, "Γä╣∩╕Å Uso: `/tarea [n├║mero o nombre]` (ej: `/tarea 20` o responde a un audio con `/tarea`).", reply_to_message_id=msg_id)
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

                            guardar_audio_registrado(info_cat, file_id=f_id, msg_id=msg_id_audio)

                            if cmd in ("/guardaraudio", "/setaudio"):
                                enviar_mensaje(chat_id, f"Γ£à Audio vinculado exitosamente a **{info_cat.get('tipo', 'MEDITACION').title()} #{info_cat['numero']}**: ┬½{info_cat['titulo']}┬╗.", reply_to_message_id=msg_id)
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
                            db_pts = cargar_puntos()
                            usuarios = db_pts.get("usuarios", {})
                            for u_id, datos in usuarios.items():
                                if str(u_id) == str(chat_id):
                                    continue
                                txt_priv = (
                                    f"≡ƒòè∩╕Å **TAREA DEL D├ìA {fecha_priv}** ≡ƒòè∩╕Å\n"
                                    f"Hola **{datos.get('nombre', 'Compa├▒ero')}**, hoy en la reuni├│n de las 7:56 PM trabajaremos:\n\n"
                                    f"≡ƒºÿ **{info_cat.get('tipo', 'MEDITACION').title()} #{info_cat['numero']}:** ┬½{info_cat['titulo']}┬╗\n"
                                    f"≡ƒæñ **Gu├¡a:** {info_cat['maestro']} | ≡ƒùô∩╕Å **Fecha:** {info_cat['fecha']}\n\n"
                                    f"┬íTe esperamos puntual esta noche a las 7:56 PM!"
                                )
                                enviar_mensaje(u_id, txt_priv, reply_markup=teclado)
                        else:
                            enviar_mensaje(chat_id, f"Γä╣∩╕Å No se encontr├│ ninguna meditaci├│n o mensaje correspondiente a ┬½{param_texto}┬╗ en el cat├ílogo.", reply_to_message_id=msg_id)
                elif cmd in ("/turno", "/pedirturno", "/ceder", "/turnos", "/mano"):
                    resp = (
                        "≡ƒÄÖ∩╕Å **Moderaci├│n y Turnos de Palabra:**\n"
                        "ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü\n"
                        "La lista de turnos se gestiona en tiempo real dentro del grupo durante la llamada diaria (7:56 PM a 10:30 PM).\n\n"
                        "Γ£ï **Para pedir la palabra:** Escribe `/turno` en el grupo o levanta la mano Γ£ï en la sala de voz.\n"
                        "≡ƒñ¥ **Para ceder la palabra:** Escribe `/ceder` en el grupo.\n"
                        "≡ƒôï **Para ver la cola:** Escribe `/turnos` en el grupo.\n"
                        "≡ƒöç **Protecci├│n anti-ruido:** Si tu micr├│fono queda abierto sin hablar por 5 segundos, el sistema lo silenciar├í autom├íticamente para proteger la sala."
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
                        resp = f"≡ƒô¥ **MINUTA DE LA REUNI├ôN ({minuta['fecha']})**\nΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü\n{minuta['resumen']}"
                        enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)
                    else:
                        enviar_mensaje(chat_id, f"Γä╣∩╕Å No se encontr├│ ninguna minuta registrada para {fecha_req or 'la ├║ltima fecha'}.", reply_to_message_id=msg_id)
                elif cmd in ("/acta",):
                    fecha_req = partes[1].strip() if len(partes) > 1 else None
                    minuta = obtener_minuta(fecha_req)
                    if minuta and minuta.get("ruta_pdf") and os.path.exists(minuta["ruta_pdf"]):
                        enviar_documento(chat_id, minuta["ruta_pdf"], caption=f"≡ƒôä **Acta Oficial de la Reuni├│n ({minuta['fecha']})**")
                    else:
                        enviar_mensaje(chat_id, "Γä╣∩╕Å No hay un documento PDF de acta disponible para esa fecha.", reply_to_message_id=msg_id)
                elif cmd in ("/oracion",) or (cmd == "/start" and param == "oracion"):
                    resp = (
                        "≡ƒòè∩╕Å **ORACI├ôN Y RECOGIMIENTO COMUNITARIO**\n"
                        "ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü\n"
                        "\"En este momento de quietud y gratitud, acallamos nuestra mente y abrimos el coraz├│n.\n\n"
                        "Agradecemos por este d├¡a, por cada respiraci├│n, por los aprendizajes recibidos y por la presencia de cada persona en esta comunidad.\n\n"
                        "Pedimos paz profunda en nuestro interior, claridad en los pensamientos, serenidad en las acciones y bienestar para nuestras familias.\n\n"
                        "Guardamos silencio y respiramos en calma, presentes en el aqu├¡ y el ahora.\"\n\n"
                        "≡ƒÖÅ *Mantengamos silencio en la sala para cultivar la paz interior de todos.*"
                    )
                    enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)
                elif cmd in ("/reglas", "/ayuda") or (cmd == "/start" and param == "reglas") or cmd == "/start":
                    resp = generar_texto_reglas()
                    enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)

        except Exception as e:
            print("Error en bucle de comandos:", e)
            time.sleep(3)


if __name__ == "__main__":
    escuchar_comandos()
