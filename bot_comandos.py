import json
import os
import time
import urllib.request
import urllib.parse

from ia_resumen import buscar_en_minutas, obtener_minuta
from catalogo_audios import identificar_audio_catalogo, formatear_info_audio

BOT_TOKEN = os.environ.get("BOT_TOKEN")
RUTA_PUNTOS = os.path.join("data", "puntos.json")
URL_RAW_GITHUB = "https://raw.githubusercontent.com/arguellosolanogerardo-cloud/llamada-telegram/main/data/puntos.json"


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


def enviar_mensaje(chat_id: int | str, texto: str, reply_to_message_id: int = None) -> None:
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

    datos = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            pass
    except Exception as e:
        print(f"Error enviando mensaje a {chat_id}:", e)


def enviar_audio(chat_id: int | str, ruta_audio: str, caption: str = "", title: str = "Meditación Diaria", performer: str = "Comunidad") -> None:
    if not BOT_TOKEN or not os.path.exists(ruta_audio):
        return
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
            print(f"Audio de meditación enviado a {chat_id}:", r.status)
    except Exception as e:
        print(f"Error enviando audio a {chat_id}:", e)


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

    print("🤖 Bot de comandos iniciado. Escuchando /puntos, /ranking, /reglas, /ayuda, /meditacion, /buscar, /resumen, /acta...")
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
                if audio_obj:
                    nombre_archivo = audio_obj.get("file_name", "") if isinstance(audio_obj, dict) else ""
                    if any(k in texto.upper() for k in ["MEDITACION", "MEDITACIÓN", "TAREA", "MENSAJE"]) or any(k in nombre_archivo.upper() for k in ["MEDITACION", "MEDITACIÓN", "MENSAJE"]):
                        info_cat = identificar_audio_catalogo(texto, nombre_archivo)
                        if info_cat:
                            txt_card = formatear_info_audio(info_cat)
                            resp_confirmacion = (
                                f"✅ **Audio identificado en el Catálogo:**\n\n"
                                f"{txt_card}\n\n"
                                f"Programado para reproducirse hoy a las 8:32 PM en la sala de voz."
                            )
                            enviar_mensaje(chat_id, resp_confirmacion, reply_to_message_id=msg_id)
                            try:
                                os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
                                with open(os.path.join("data", "meditaciones", "meta_hoy.json"), "w", encoding="utf-8") as fm:
                                    json.dump(info_cat, fm, ensure_ascii=False, indent=2)
                            except Exception:
                                pass

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
                elif cmd in ("/meditacion", "/meditacion_hoy", "/audio", "/mensaje"):
                    param_texto = " ".join(partes[1:]).strip() if len(partes) > 1 else ""
                    if param_texto:
                        prefijo = "mensaje" if cmd == "/mensaje" else "meditacion"
                        busqueda = f"{prefijo} {param_texto}" if not any(w in param_texto.lower() for w in ["meditacion", "mensaje"]) else param_texto
                        info_cat = identificar_audio_catalogo(texto=busqueda)
                        if info_cat:
                            txt_cat = (
                                f"🧘 **CATÁLOGO OFICIAL DE AUDIOS**\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"📌 **{info_cat['tipo']} #{info_cat['numero']}:** «{info_cat['titulo']}»\n"
                                f"👤 **Maestro / Guía:** {info_cat['maestro']}\n"
                                f"🗓️ **Fecha de grabación original:** {info_cat['fecha']}"
                            )
                            enviar_mensaje(chat_id, txt_cat, reply_to_message_id=msg_id)
                        else:
                            enviar_mensaje(chat_id, f"ℹ️ No se encontró ninguna meditación o mensaje correspondiente a «{param_texto}» en el catálogo.", reply_to_message_id=msg_id)
                    else:
                        ruta_med = os.path.join("data", "meditaciones", "meditacion_hoy.mp3")
                        info_cat = None
                        if os.path.exists(ruta_med) and os.path.getsize(ruta_med) > 0:
                            ruta_meta = os.path.join("data", "meditaciones", "meta_hoy.json")
                            if os.path.exists(ruta_meta):
                                try:
                                    with open(ruta_meta, "r", encoding="utf-8") as fm:
                                        info_cat = json.load(fm)
                                except Exception:
                                    pass
                            if not info_cat:
                                info_cat = identificar_audio_catalogo(nombre_archivo=os.path.basename(ruta_med))

                            caption = "🧘 **Meditación Diaria**\nAquí tienes el audio de hoy para que realices tu práctica en diferido."
                            title = "Meditación Diaria"
                            performer = "Comunidad"
                            if info_cat:
                                caption = (
                                    f"🧘 **{info_cat['tipo']} #{info_cat['numero']}**\n"
                                    f"📌 **Título:** «{info_cat['titulo']}»\n"
                                    f"👤 **Guía:** {info_cat['maestro']}\n"
                                    f"🗓️ **Grabación original:** {info_cat['fecha']}\n\n"
                                    "Audio de hoy para tu práctica en diferido."
                                )
                                title = f"{info_cat['tipo']} #{info_cat['numero']} - {info_cat['titulo']}"
                                performer = info_cat["maestro"]

                            enviar_audio(
                                chat_id,
                                ruta_med,
                                caption=caption,
                                title=title,
                                performer=performer
                            )
                        else:
                            enviar_mensaje(
                                chat_id,
                                "🧘 **Meditación Diaria:**\nAún no hay un audio de meditación disponible para hoy. Puedes consultar el catálogo escribiendo `/meditacion [número]` o `/mensaje [número]`.",
                                reply_to_message_id=msg_id
                            )
                elif cmd in ("/tarea", "/anunciartarea", "/anunciar", "/publicartarea"):
                    param_texto = " ".join(partes[1:]).strip() if len(partes) > 1 else ""
                    if not param_texto and msg.get("reply_to_message"):
                        reply_m = msg.get("reply_to_message", {})
                        param_texto = (reply_m.get("text") or reply_m.get("caption") or "").strip()
                    if not param_texto:
                        enviar_mensaje(chat_id, "ℹ️ Uso: `/tarea [número o nombre]` (ej: `/tarea 20` o responde a un audio con `/tarea`).", reply_to_message_id=msg_id)
                    else:
                        from publicar_tarea import generar_anuncio_tarea
                        info_cat = identificar_audio_catalogo(texto=param_texto)
                        if info_cat:
                            try:
                                os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
                                with open(os.path.join("data", "meditaciones", "meta_hoy.json"), "w", encoding="utf-8") as fm:
                                    json.dump(info_cat, fm, ensure_ascii=False, indent=2)
                            except Exception:
                                pass
                            anuncio = generar_anuncio_tarea(info_cat)
                            enviar_mensaje(chat_id, anuncio)
                            db_pts = cargar_puntos()
                            usuarios = db_pts.get("usuarios", {})
                            for u_id, datos in usuarios.items():
                                if str(u_id) == str(chat_id):
                                    continue
                                txt_priv = (
                                    f"🕊️ **TAREA ESPIRITUAL DEL DÍA**\n"
                                    f"Hola **{datos.get('nombre', 'Compañero')}**, hoy en la reunión de las 7:56 PM trabajaremos:\n\n"
                                    f"🧘 **{info_cat.get('tipo', 'MEDITACION').title()} #{info_cat['numero']}:** «{info_cat['titulo']}»\n"
                                    f"👤 **Guía:** {info_cat['maestro']} | 🗓️ **Fecha:** {info_cat['fecha']}\n\n"
                                    f"¡Te esperamos puntual esta noche a las 7:56 PM!"
                                )
                                enviar_mensaje(u_id, txt_priv)
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
