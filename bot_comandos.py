import json
import os
import time
import urllib.request
import urllib.parse
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler

from ia_resumen import buscar_en_minutas, obtener_minuta
from catalogo_audios import identificar_audio_catalogo, formatear_info_audio
from publicar_tarea import generar_anuncio_tarea, armar_teclado_audio, extraer_fecha_de_texto

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP")
RUTA_PUNTOS = os.path.join("data", "puntos.json")
RUTA_AUDIOS_REGISTRADOS = os.path.join("data", "meditaciones", "audios_registrados.json")
URL_RAW_GITHUB = "https://raw.githubusercontent.com/arguellosolanogerardo-cloud/llamada-telegram/main/data/puntos.json"


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


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot Comandos OK")

    def do_POST(self):
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


def generar_texto_miperfil(user_id: int, db_puntos: dict, user_nombre: str = "") -> str:
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


def generar_texto_ranking(db_puntos: dict) -> str:
    usuarios = db_puntos.get("usuarios", {})
    if not usuarios:
        return "🏆 **Ranking Mensual:** Aún no hay registros de asistencia este mes."

    top = sorted(usuarios.values(), key=lambda x: x.get("puntos_mes", x.get("puntos_totales", 0)), reverse=True)[:10]
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
        "• 🛡️ *Puntualidad de Hierro:* 5 días seguidos en el podio (Top 3 primeros).\n"
        "• 🎙️ *Voz de la Comunidad:* Hablar en 7 llamadas consecutivas.\n"
        "• 🧘 *Mente Serena:* Completar 10 meditaciones en el mes.\n"
        "• 👑 *Centinela:* Asistir a más del 90% de las reuniones del mes.\n\n"
        "✋ **TURNOS Y MODERACIÓN DE MICRÓFONOS:**\n"
        "• Escribe `/turno` en el grupo o levanta la mano ✋ en la sala para pedir la palabra.\n"
        "• Máximo 2 personas hablando a la vez para evitar interferencias.\n"
        "• Si dejas el micrófono abierto sin hablar por 15 segundos, el bot lo silenciará automáticamente para proteger la sala de ruidos de fondo.\n\n"
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


def enviar_mensaje(chat_id: int | str, texto: str, reply_to_message_id: int = None, reply_markup: dict = None) -> None:
    if not BOT_TOKEN:
        print("BOT_TOKEN no configurado.")
        return
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
            pass
    except Exception as e:
        print(f"Error enviando mensaje a {chat_id}:", e)


def enviar_audio(chat_id: int | str, ruta_audio: str, caption: str = "", title: str = "Meditación Diaria", performer: str = "Comunidad") -> bool:
    if not BOT_TOKEN or not ruta_audio:
        return False

    # Si es un file_id de Telegram (no existe como archivo local en disco)
    if not os.path.exists(ruta_audio):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
        payload = {
            "chat_id": chat_id,
            "audio": ruta_audio,
            "caption": caption,
            "parse_mode": "Markdown",
            "title": title,
            "performer": performer,
        }
        datos = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                res = json.loads(r.read().decode())
                print(f"Audio enviado via file_id a {chat_id}:", r.status)
                return res.get("ok", False)
        except Exception as e:
            print(f"Error enviando audio por file_id a {chat_id}:", e)
            return False

    boundary = "----WebKitFormBoundaryAudio7MA4YWxk"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"

    try:
        with open(ruta_audio, "rb") as f:
            file_bytes = f.read()

        body = bytearray()
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode())
        if caption:
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode())
        if title:
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n{title}\r\n".encode())
        if performer:
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"performer\"\r\n\r\n{performer}\r\n".encode())

        filename = os.path.basename(ruta_audio)
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{filename}\"\r\nContent-Type: audio/mpeg\r\n\r\n".encode())
        body.extend(file_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            url,
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode())
            print(f"Audio de meditación enviado a {chat_id}:", r.status)
            return res.get("ok", False)
    except Exception as e:
        print(f"Error enviando audio a {chat_id}:", e)
        return False


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
                print(f"Audio reenviado a {chat_id}")
                return True
    except Exception as ef:
        print(f"Nota forwardMessage {from_chat_id}:{m_id} -> {chat_id}:", ef)

    return False


def entregar_audio_meditacion(chat_id: int | str, info_cat: dict, msg_id_reply: int | str = None) -> None:
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
        if enviar_audio(chat_id, audio_file_id, caption=caption, title=title, performer=performer):
            return

    # D) Buscar archivo local en disco
    ruta_local = None
    ruta_med_hoy = os.path.join("data", "meditaciones", "meditacion_hoy.mp3")
    if (not num or (meta_hoy and str(meta_hoy.get("numero", "")).strip() == num)) and os.path.exists(ruta_med_hoy) and os.path.getsize(ruta_med_hoy) > 0:
        ruta_local = ruta_med_hoy
    else:
        for f_name in [f"meditacion_{num}.mp3", f"{num}.mp3"]:
            candidato = os.path.join("data", "meditaciones", f_name)
            if os.path.exists(candidato) and os.path.getsize(candidato) > 0:
                ruta_local = candidato
                break

    if ruta_local:
        if enviar_audio(chat_id, ruta_local, caption=caption, title=title, performer=performer):
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
            return

    # F) Si aún no está cargado el archivo en ninguna fuente, entregar ficha del catálogo con instrucciones
    txt_cat = (
        f"🧘 **CATÁLOGO OFICIAL DE AUDIOS**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 **{tipo_nombre} #{num}:** «{titulo}»\n"
        f"👤 **Maestro / Guía:** {maestro}\n"
        f"🗓️ **Fecha de grabación original:** {fecha}\n\n"
        f"ℹ️ El archivo .mp3 correspondiente aún no se encuentra registrado en el almacenamiento del bot.\n\n"
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
            print(f"Documento enviado a {chat_id}:", r.status)
    except Exception as e:
        print(f"Error enviando documento a {chat_id}:", e)


def escuchar_comandos() -> None:
    if not BOT_TOKEN:
        print("Error: Define la variable de entorno BOT_TOKEN.")
        return

    # Iniciar servidor HTTP para health check (Koyeb / Render)
    threading.Thread(target=iniciar_servidor_health, daemon=True).start()

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
                msg = update.get("message")
                if not msg:
                    continue

                texto = (msg.get("text") or msg.get("caption") or "").strip()
                chat_id = msg["chat"]["id"]
                msg_id = msg["message_id"]
                from_user = msg.get("from", {})
                user_id = from_user.get("id")
                nombre = f"{from_user.get('first_name', '')} {from_user.get('last_name', '')}".strip()

                # Detectar si se subió un audio/documento de tarea o meditación
                audio_obj = msg.get("audio") or msg.get("voice") or msg.get("document")
                es_tarea_declarada = any(k in texto.upper() for k in ["MEDITACION DE TAREA", "TAREA DE MEDITACION", "TAREA DEL DÍA", "TAREA DEL DIA", "MEDITACION DE HOY"])
                if audio_obj or es_tarea_declarada:
                    nombre_archivo = audio_obj.get("file_name", "") if isinstance(audio_obj, dict) else ""
                    titulo_audio = audio_obj.get("title", "") if isinstance(audio_obj, dict) else ""
                    performer_audio = audio_obj.get("performer", "") if isinstance(audio_obj, dict) else ""
                    texto_busq = f"{texto} {nombre_archivo} {titulo_audio} {performer_audio}".strip()
                    info_cat = identificar_audio_catalogo(texto=texto_busq, nombre_archivo=nombre_archivo)
                    if info_cat:
                        f_id = audio_obj.get("file_id") if isinstance(audio_obj, dict) else None
                        info_cat["file_id"] = f_id
                        info_cat["msg_id_audio"] = msg_id
                        guardar_audio_registrado(info_cat, file_id=f_id, msg_id=msg_id)

                        # Si se envió directamente al bot en chat privado, confirmar al usuario/admin
                        if chat_id > 0 and f_id:
                            enviar_mensaje(
                                chat_id,
                                f"✅ **¡Audio guardado exitosamente!**\n\n"
                                f"🧘 **{info_cat.get('tipo', 'MEDITACION').title()} #{info_cat['numero']}:** «{info_cat['titulo']}»\n"
                                f"👤 **Guía:** {info_cat['maestro']}\n"
                                f"🗓️ **Grabación:** {info_cat['fecha']}\n\n"
                                f"El bot ha registrado este archivo y ahora se lo entregará directamente a cualquier usuario que lo solicite con `/meditacion` o el botón de audio.",
                                reply_to_message_id=msg_id
                            )

                        # Si se declara como tarea o se subió en el grupo oficial
                        if es_tarea_declarada or (CHAT_ID and str(chat_id) == str(CHAT_ID)):
                            try:
                                os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
                                with open(os.path.join("data", "meditaciones", "meta_hoy.json"), "w", encoding="utf-8") as fm:
                                    json.dump(info_cat, fm, ensure_ascii=False, indent=2)
                            except Exception:
                                pass

                            fecha_admin = extraer_fecha_de_texto(texto)
                            anuncio = generar_anuncio_tarea(info_cat, fecha_admin)
                            teclado = armar_teclado_audio(chat_id, msg_id)
                            enviar_mensaje(chat_id, anuncio, reply_markup=teclado)

                            # Enviar notificación privada a miembros registrados
                            fecha_priv = fecha_admin or datetime.now(ZoneInfo("America/Bogota")).strftime("%d/%m/%Y")
                            usuarios = db.get("usuarios", {})
                            for u_id, datos in usuarios.items():
                                if str(u_id) == str(chat_id):
                                    continue
                                txt_priv = (
                                    f"🕊️ **TAREA DEL DÍA {fecha_priv}** 🕊️\n"
                                    f"Hola **{datos.get('nombre', 'Compañero')}**, hoy trabajaremos con:\n\n"
                                    f"🧘 **{info_cat.get('tipo', 'MEDITACION').title()} #{info_cat['numero']}:** «{info_cat['titulo']}»\n"
                                    f"👤 **Guía:** {info_cat['maestro']} | 🗓️ **Grabación:** {info_cat['fecha']}\n\n"
                                    f"⏰ Te esperamos puntual a las 7:56 PM para la apertura de la sala."
                                )
                                enviar_mensaje(u_id, txt_priv, reply_markup=teclado)

                if not texto.startswith("/"):
                    continue

                partes = texto.split()
                cmd = partes[0].lower().split("@")[0]
                param = partes[1].lower() if len(partes) > 1 else ""
                db = cargar_puntos()

                if cmd in ("/puntos", "/miperfil"):
                    resp = generar_texto_miperfil(user_id, db, nombre)
                    enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)
                elif cmd in ("/ranking", "/top") or (cmd == "/start" and param == "ranking"):
                    resp = generar_texto_ranking(db)
                    enviar_mensaje(chat_id, resp, reply_to_message_id=msg_id)
                elif cmd in ("/meditacion", "/meditacion_hoy", "/audio", "/mensaje") or (cmd == "/start" and param == "audio"):
                    param_texto = " ".join(partes[1:]).strip() if (len(partes) > 1 and param != "audio") else ""
                    info_cat = None
                    if param_texto:
                        prefijo = "mensaje" if cmd == "/mensaje" else "meditacion"
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

                    entregar_audio_meditacion(chat_id, info_cat, msg_id_reply=msg_id)
                elif cmd in ("/tarea", "/anunciartarea", "/anunciar", "/publicartarea", "/guardaraudio", "/setaudio"):
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
                            teclado = armar_teclado_audio(chat_id, msg_id_audio)
                            enviar_mensaje(chat_id, anuncio, reply_markup=teclado)
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
                        "🔇 **Protección anti-ruido:** Si tu micrófono queda abierto sin hablar por 15 segundos, el sistema lo silenciará automáticamente para proteger la sala."
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
            time.sleep(3)


if __name__ == "__main__":
    escuchar_comandos()
