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
        if self.path == "/diag":
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
        "✋ **TURNOS Y MODERACIÓN DE MICRÓFONOS:**\n"
        "• Escribe `/turno` en el grupo o levanta la mano ✋ en la sala para pedir la palabra.\n"
        "• Máximo 2 personas hablando a la vez para evitar interferencias.\n"
        "• Si dejas el micrófono abierto sin hablar por 5 segundos, el bot lo silenciará automáticamente para proteger la sala de ruidos de fondo.\n\n"
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

    datos = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res_data = json.loads(r.read().decode())
            m_id = res_data.get("result", {}).get("message_id")
            if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                registrar_msg_bot(m_id)
            return m_id
    except Exception as e:
        print(f"Error enviando mensaje a {chat_id}:", e)
        import sys; sys.stdout.flush()
        if "parse_mode" in payload:
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
            log_debug(f"Telegram rechazó foto ({chat_id}): {res}")
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


def _enviar_aviso_preparacion_sala_impl(cid) -> int | None:

    # Obtener tarea del día si está disponible
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
        log_debug(f"Iniciando subida de audio local a {chat_id} ({os.path.basename(ruta_audio)}, {tam_mb} MB)...")
        with open(ruta_audio, "rb") as f:
            files = {"audio": (os.path.basename(ruta_audio), f, "audio/mpeg")}
            r = requests.post(url, data=data, files=files, timeout=180)
            res = r.json()
            if not res.get("ok") and "parse_mode" in data:
                data_fb = dict(data)
                del data_fb["parse_mode"]
                f.seek(0)
                files_fb = {"audio": (os.path.basename(ruta_audio), f, "audio/mpeg")}
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
            "🧘 **Meditación Diaria:**\nAún no hay un audio de meditación disponible para hoy. Puedes consultar el catálogo escribiendo `/meditacion [número]` o `/mensaje [número]`.",
            reply_to_message_id=msg_id_reply
        )
        return

    tipo_nombre = info_cat.get('tipo', 'Meditación').title()
    num = str(info_cat.get('numero', '')).strip()
    titulo = info_cat.get('titulo', '')
    maestro = info_cat.get('maestro', 'Comunidad')
    fecha = info_cat.get('fecha', '')

    caption = (
        f"🧘 **{tipo_nombre} #{num}**\n"
        f"📌 **Título:** «{titulo}»\n"
        f"👤 **Guía:** {maestro}\n"
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

    # B) file_id en meta_hoy.json (si coincide el número o si no se especificó)
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

    # Intentar enviar vía file_id si lo tenemos
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
        f"👤 **Maestro / Guía:** {maestro}\n"
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

    if re.match(r"^(?:MEDITACI[OÓ]N|MENSAJE|AUDIO)\s+#?\d{1,4}", t_up.strip()):
        return True

    return False


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

    print("🤖 Bot de comandos iniciado. Escuchando /puntos, /ranking, /reglas, /ayuda, /meditacion, /buscar, /resumen, /acta, /tarea...")
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
                print("Recibido update:", update.get("update_id"))
                
                if "callback_query" in update:
#                     import json
                    cb = update["callback_query"]
                    cb_id = cb.get("id")
                    cb_data = cb.get("data", "")
                    msg_cb = cb.get("message", {})
                    chat_id_cb = msg_cb.get("chat", {}).get("id")
                    
                    if cb_data.startswith("ytmp3_"):

                    
                        vid = cb_data.split("_")[1]

                    
                        url_yt = f"https://www.youtube.com/watch?v={vid}"

                    
#                         import urllib.request

                    
                        try:

                    
                            url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"

                    
                            urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "⏳ Descargando MP3 desde YouTube... (Esto tomará 1 minuto)", "show_alert": True}).encode(), headers={"Content-Type": "application/json"}), timeout=10)

                    
                        except: pass

                    
                        def descargar_y_enviar(user_id):
                            tmp_path = os.path.join("data", f"tmp_{vid}.mp3")
                            cmd = ["python", "-m", "yt_dlp", "-x", "--audio-format", "mp3", "--audio-quality", "5", "-o", tmp_path, url_yt]
                            subprocess.run(cmd)
                            if os.path.exists(tmp_path):
                                try:
                                    url_doc = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
                                    with open(tmp_path, "rb") as f_aud:
                                        requests.post(url_doc, data={"chat_id": user_id, "caption": "🎧 Aquí tienes el audio solicitado."}, files={"document": f_aud})
                                    os.remove(tmp_path)

                    
                                except: pass

                    
# import threading

                    
                        threading.Thread(target=descargar_y_enviar, args=(update["callback_query"]["from"].get("id"),)).start()

                    
                        continue

                    
                    elif cb_data.startswith("yttarea_"):

                    
                        vid = cb_data.split("_")[1]

                    
                        url_yt = f"https://www.youtube.com/watch?v={vid}"

                    
                        user_id_cb = update["callback_query"]["from"].get("id")

                    
                        if user_id_cb not in admins_set:

                    
                            try:

                    
                                url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"

                    
                                urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "🚫 Solo administradores.", "show_alert": True}).encode(), headers={"Content-Type": "application/json"}), timeout=10)

                    
                            except: pass

                    
                        else:

                    
                            try:

                    
                                url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"

                    
                                urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "✅ Programando audio para esta noche..."}).encode(), headers={"Content-Type": "application/json"}), timeout=10)

                    
                            except: pass

                    
                            enviar_mensaje(chat_id_cb, f"/tarea {url_yt}")

                    
                        continue

                    
                    elif cb_data.startswith("panel_"):
#                         import urllib.request
#                         import time
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
                        enviar_mensaje(chat_id_priv, "🔍 *Buscando en la Biblioteca Conocimiento Universal...*", reply_to_message_id=msg_id_priv)
                        
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
                                    resp = "📚 **Aquí tienes lo que encontré en la Biblioteca:**\n\n"
                                    for idx, (titulo, seg, txt_frag, vid) in enumerate(resultados):
                                        m = seg // 60
                                        s = seg % 60
                                        url = f"https://youtu.be/{vid}?t={seg}"
                                        resp += f"**{idx+1}. {titulo}**\n"
                                        resp += f"⏱️ *Minuto:* [{m:02d}:{s:02d}]({url})\n"
                                        resp += f"💬 \"{txt_frag[:100]}...\"\n\n"
                                    
                                    enviar_mensaje(chat_id_priv, resp)
                                else:
                                    enviar_mensaje(chat_id_priv, "😔 No encontré ninguna enseñanza exacta con esas palabras. Intenta usar otras palabras clave.")
                            except Exception as e:
                                enviar_mensaje(chat_id_priv, f"⚠️ Error buscando: {e}")
                        else:
                            enviar_mensaje(chat_id_priv, "⏳ La Biblioteca aún se está construyendo. Intenta más tarde.")
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
                                f"👤 **Guía:** {info_cat['maestro']}\n"
                                f"🗓️ **Grabación:** {info_cat['fecha']}\n\n"
                                f"El bot ha registrado este archivo y ahora se lo entregará directamente a cualquier usuario que lo solicite con `/meditacion` o el botón de audio.",
                                reply_to_message_id=msg_id
                            )

                        # Si es declaración de tarea (en el grupo o en privado por admin)
                        if es_tarea_declarada or (CHAT_ID and str(chat_id) == str(CHAT_ID) and audio_obj):
                            if not es_mensaje_de_admin(msg, chat_id):
                                # Si un usuario no administrador menciona la tarea, solo entregarle la tarea actual que ya fue fijada por los admins
                                log_debug(f"Usuario no admin {user_id} intentó programar tarea. Bloqueado.")
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
                                        cap_audio = f"🧘 **{t_nombre} #{n_proc}:** «{it_proc.get('titulo', '')}»\n👤 **Guía:** {it_proc.get('maestro', 'Alaniso')}\n🗓️ **Grabación:** {it_proc.get('fecha', '')}"
                                        ok_a, m_id_a, f_id_a = enviar_audio(
                                            chat_id,
                                            ruta_audio_desc,
                                            caption=cap_audio,
                                            title=f"{t_nombre} #{n_proc} - {it_proc.get('titulo', '')}",
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
                            usuarios = db.get("usuarios", {})
                            for u_id, datos in usuarios.items():
                                if (CHAT_ID and str(u_id) == str(CHAT_ID)) or str(u_id) == str(chat_id):
                                    continue
                                if len(audios_procesados) > 1:
                                    txt_items_p = "\n".join(f"• **{it.get('tipo', 'Audio').title()} #{it.get('numero')}:** «{it.get('titulo')}»" for it in audios_procesados)
                                    txt_priv = (
                                        f"🕊️ **TAREA DEL DÍA {fecha_priv}** 🕊️\n"
                                        f"Hola **{datos.get('nombre', 'Compañero')}**, {tiempo_saludo} trabajaremos con:\n\n"
                                        f"{txt_items_p}\n\n"
                                        f"⏰ Te esperamos puntual a las 7:56 PM para la apertura de la sala."
                                    )
                                else:
                                    txt_priv = (
                                        f"🕊️ **TAREA DEL DÍA {fecha_priv}** 🕊️\n"
                                        f"Hola **{datos.get('nombre', 'Compañero')}**, {tiempo_saludo} trabajaremos con:\n\n"
                                        f"🧘 **{info_cat.get('tipo', 'MEDITACION').title()} #{info_cat['numero']}:** «{info_cat['titulo']}»\n"
                                        f"👤 **Guía:** {info_cat['maestro']} | 🗓️ **Grabación:** {info_cat['fecha']}\n\n"
                                        f"⏰ Te esperamos puntual a las 7:56 PM para la apertura de la sala."
                                    )
                                enviar_mensaje(u_id, txt_priv, reply_markup=teclado_actual)

                # Petición de audio en lenguaje natural (ej: "¿Tienes el mensaje 989?", "meditación 21")
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
                elif cmd in ("/meditacion", "/meditacion_hoy", "/audio", "/mensaje") or (cmd == "/start" and (param == "audio" or param.startswith("audio_") or param.startswith("meditacion_") or param.startswith("mensaje_"))):
                    param_texto = " ".join(partes[1:]).strip() if (len(partes) > 1 and not param.startswith("audio")) else ""
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
                        # Obtener meditación activa del día
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
                    continue
                elif cmd == "/panel":
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "🚫 Solo los administradores pueden usar el panel de control.", reply_to_message_id=msg_id)
                        continue
                    teclado_panel = {
                        "inline_keyboard": [
                            [{"text": "▶️ Play", "callback_data": "panel_play"}, {"text": "⏸️ Pausa", "callback_data": "panel_pausa"}, {"text": "⏭️ Siguiente", "callback_data": "panel_nextaudio"}],
                            [{"text": "🎤 Sig. Turno", "callback_data": "panel_nextturno"}, {"text": "🔓 Abrir Micros", "callback_data": "panel_desmutear"}],
                            [{"text": "🧹 Limpiar Sala", "callback_data": "panel_limpiar"}, {"text": "⏹️ Fin Grabación", "callback_data": "panel_stoprec"}]
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
                                enviar_mensaje(chat_id, "ℹ️ Aún no hay una tarea programada para hoy por los administradores.", reply_to_message_id=msg_id)
                        else:
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
                            db_pts = cargar_puntos()
                            usuarios = db_pts.get("usuarios", {})
                            for u_id, datos in usuarios.items():
                                if str(u_id) == str(chat_id):
                                    continue
                                txt_priv = (
                                    f"🕊️ **TAREA DEL DÍA {fecha_priv}** 🕊️\n"
                                    f"Hola **{datos.get('nombre', 'Compañero')}**, hoy en la reunión de las 7:56 PM trabajaremos:\n\n"
                                    f"🧘 **{info_cat.get('tipo', 'MEDITACION').title()} #{info_cat['numero']}:** «{info_cat['titulo']}»\n"
                                    f"👤 **Guía:** {info_cat['maestro']} | 🗓️ **Fecha:** {info_cat['fecha']}\n\n"
                                    f"¡Te esperamos puntual esta noche a las 7:56 PM!"
                                )
                                enviar_mensaje(u_id, txt_priv, reply_markup=teclado)
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
