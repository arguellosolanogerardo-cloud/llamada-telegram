import os
import sys
import re
import json
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from catalogo_audios import identificar_audio_catalogo, formatear_info_audio, cargar_catalogo

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP")
RUTA_PUNTOS = os.path.join("data", "puntos.json")

TG_API_ID = os.environ.get("TG_API_ID")
TG_API_HASH = os.environ.get("TG_API_HASH")
TG_SESSION = os.environ.get("TG_SESSION")


def extraer_fecha_de_texto(texto: str) -> str | None:
    if not texto:
        return None

    tz_col = ZoneInfo("America/Bogota")
    ahora = datetime.now(tz_col)
    t_lower = texto.lower()

    # 1. "mañana" / "manana"
    if "mañana" in t_lower or "manana" in t_lower:
        manana = ahora + timedelta(days=1)
        return manana.strftime("%d/%m/%Y")

    # 2. "hoy"
    if re.search(r"\bpara\s+hoy\b|\bhoy\b", t_lower):
        return ahora.strftime("%d/%m/%Y")

    # 3. Formato numérico standard: DD/MM/AAAA, DD-MM-AAAA, DD.MM.AAAA
    m = re.search(r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})\b", texto)
    if m:
        dia, mes, anio = m.group(1), m.group(2), m.group(3)
        if len(dia) == 1: dia = f"0{dia}"
        if len(mes) == 1: mes = f"0{mes}"
        if len(anio) == 2: anio = f"20{anio}"
        return f"{dia}/{mes}/{anio}"

    # 4. Formato de texto: "6 de octubre", "6 octubre", "martes 6 octubre"
    meses = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "setiembre": "09", "octubre": "10",
        "noviembre": "11", "diciembre": "12"
    }
    pattern_mes = r"\b(\d{1,2})\s+(?:de\s+)?(" + "|".join(meses.keys()) + r")\b"
    m_mes = re.search(pattern_mes, t_lower)
    if m_mes:
        dia = m_mes.group(1)
        mes_txt = m_mes.group(2)
        mes = meses[mes_txt]
        if len(dia) == 1: dia = f"0{dia}"
        anio = str(ahora.year)
        return f"{dia}/{mes}/{anio}"

    return None




def enviar_mensaje(chat_id: int | str, texto: str, reply_markup: dict = None) -> bool:
    if not BOT_TOKEN:
        print("BOT_TOKEN no configurado.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    datos = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        print(f"Error enviando mensaje a {chat_id}:", e)
        return False


def generar_anuncio_tarea(info: dict, fecha_str: str = None) -> str:
    tz_col = ZoneInfo("America/Bogota")
    ahora = datetime.now(tz_col)
    if not fecha_str:
        if ahora.hour > 20 or (ahora.hour == 20 and ahora.minute >= 32):
            fecha_obj = ahora + timedelta(days=1)
        else:
            fecha_obj = ahora
        fecha_str = fecha_obj.strftime("%d/%m/%Y")
    else:
        try:
            fecha_obj = datetime.strptime(fecha_str, "%d/%m/%Y").replace(tzinfo=tz_col)
        except Exception:
            fecha_obj = ahora

    tipo_raw = str(info.get("tipo", "")).upper()
    tipo = "Meditación" if "MEDITACI" in tipo_raw else "Mensaje"
    num = info.get("numero", "")
    titulo = info.get("titulo", "")
    maestro = info.get("maestro", "Guía Espiritual")
    fecha_orig = info.get("fecha", "")

    es_hoy = fecha_obj.date() == ahora.date()
    tiempo_palabra = "hoy" if es_hoy else "mañana" if fecha_obj.date() == (ahora + timedelta(days=1)).date() else f"el {fecha_str}"
    cronograma_palabra = f"esta noche ({fecha_str})" if es_hoy else f"la noche del {fecha_str}"

    return (
        f"🕊️ **TAREA DEL DÍA {fecha_str}** 🕊️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Comunidad, {tiempo_palabra} ({fecha_str}) trabajaremos con la siguiente práctica:\n\n"
        f"🧘 **{tipo} #{num}:** «{titulo}»\n"
        f"👤 **Maestro / Guía:** {maestro}\n"
        f"🗓️ **Grabación original:** {fecha_orig}\n\n"
        f"⏰ **Cronograma para {cronograma_palabra}:**\n"
        f"• **7:56 PM:** Apertura de la sala de voz en Telegram.\n"
        f"• **8:24 PM:** Oración y recogimiento en silencio (3 min).\n"
        f"• **8:27 PM:** Pausa de respiración consciente (5 min).\n"
        f"• **8:32 PM:** Reproducción en vivo de la {tipo.lower()}.\n\n"
        f"🎧 *El audio ya fue publicado en el grupo para su estudio previo.*"
    )


_BOT_USER_CACHE = None


def obtener_info_bot() -> str:
    global _BOT_USER_CACHE
    if _BOT_USER_CACHE:
        return _BOT_USER_CACHE
    if not BOT_TOKEN:
        return ""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        req = urllib.request.Request(url, headers={"User-Agent": "PublicarTareaBot"})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode())
            if res.get("ok"):
                _BOT_USER_CACHE = res["result"].get("username", "")
                return _BOT_USER_CACHE
    except Exception as e:
        print("Nota obteniendo getMe:", e)
    return ""


def armar_teclado_audio(chat_id: int | str, msg_id_audio: int | str = None, bot_user: str = "", username_grupo: str = None) -> dict:
    if not bot_user:
        bot_user = obtener_info_bot()

    url_audio = None
    if msg_id_audio and str(msg_id_audio).startswith("http"):
        url_audio = str(msg_id_audio).strip()
    elif msg_id_audio:
        m_num = re.search(r"(\d+)", str(msg_id_audio))
        id_msg = m_num.group(1) if m_num else str(msg_id_audio).strip()
        if username_grupo:
            url_audio = f"https://t.me/{username_grupo}/{id_msg}"
        else:
            clean_id = str(chat_id).replace("-100", "").lstrip("-")
            url_audio = f"https://t.me/c/{clean_id}/{id_msg}"

    botones = []
    if url_audio:
        botones.append([{"text": "🎧 ESCUCHAR / VER AUDIO EN EL GRUPO 👆", "url": url_audio}])
    elif username_grupo:
        botones.append([{"text": "🎧 IR AL GRUPO 👆", "url": f"https://t.me/{username_grupo}"}])
    else:
        clean_id = str(chat_id).replace("-100", "").lstrip("-")
        botones.append([{"text": "🎧 IR AL GRUPO 👆", "url": f"https://t.me/c/{clean_id}"}])

    if bot_user:
        botones.append([{"text": "📥 RECIBIR AUDIO EN MI TELEGRAM PRIVADO 🎧", "url": f"https://t.me/{bot_user}?start=audio"}])

    return {"inline_keyboard": botones}


def buscar_id_audio_en_grupo(chat_id: int | str, numero: int | str = "") -> tuple[int | None, str | None]:
    """Usa Telethon para escanear el grupo y encontrar el ID del mensaje del audio."""
    if not (TG_API_ID and TG_API_HASH and TG_SESSION and chat_id):
        return None, None
    try:
        import asyncio
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        async def _buscar():
            client = TelegramClient(StringSession(TG_SESSION), int(TG_API_ID), TG_API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return None, None

            destino = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            entidad = await client.get_entity(destino)
            username = getattr(entidad, "username", None)
            num_str = str(numero).strip()
            msg_id_match = None

            async for msg in client.iter_messages(entidad, limit=40):
                es_audio = False
                if msg.audio or msg.voice:
                    es_audio = True
                elif msg.document and any(getattr(a, "file_name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")) for a in getattr(msg.document, "attributes", [])):
                    es_audio = True

                if es_audio:
                    texto_m = (msg.raw_text or "").upper()
                    nombre_m = getattr(getattr(msg, "file", None), "name", "") or ""
                    if num_str and (num_str in texto_m or num_str in nombre_m):
                        await client.disconnect()
                        return msg.id, username
                    elif msg_id_match is None:
                        msg_id_match = msg.id

            await client.disconnect()
            return msg_id_match, username

        return asyncio.run(_buscar())
    except Exception as e:
        print("Nota buscando ID del audio con Telethon:", e)
        return None, None


def publicar_tarea_dia(parametro: str, fecha_param: str = None, msg_id_audio: int | str = None) -> dict | None:
    """Identifica el audio por número o texto y envía el anuncio oficial al grupo y privados."""
    info = identificar_audio_catalogo(texto=parametro)
    if not info:
        print(f"No se encontró información en el catálogo para: {parametro}")
        return None

    # Determinar la fecha provista por el administrador
    fecha_final = None
    if fecha_param and fecha_param.strip():
        fecha_final = extraer_fecha_de_texto(fecha_param.strip()) or fecha_param.strip()
    if not fecha_final:
        fecha_final = extraer_fecha_de_texto(parametro)
    if not fecha_final:
        tz_col = ZoneInfo("America/Bogota")
        fecha_final = datetime.now(tz_col).strftime("%d/%m/%Y")

    # Si no se pasó msg_id_audio, intentar localizarlo automáticamente en el grupo
    username_grupo = None
    if not msg_id_audio and CHAT_ID:
        msg_id_audio, username_grupo = buscar_id_audio_en_grupo(CHAT_ID, info["numero"])
        if msg_id_audio:
            print(f"Mensaje del audio detectado automáticamente: ID {msg_id_audio}")

    # Guardar metadatos del día
    os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
    ruta_meta = os.path.join("data", "meditaciones", "meta_hoy.json")
    try:
        info_guardar = dict(info)
        info_guardar["fecha_tarea_admin"] = fecha_final
        if msg_id_audio:
            info_guardar["msg_id_audio"] = msg_id_audio
        with open(ruta_meta, "w", encoding="utf-8") as f:
            json.dump(info_guardar, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando meta_hoy:", e)

    # Sincronizar metadatos con el bot en Render si está activo
    try:
        url_render = os.environ.get("RENDER_BOT_URL", "https://bot-meditaciones.onrender.com/tarea")
        req_sync = urllib.request.Request(
            url_render,
            data=json.dumps({"info": info_guardar, "msg_id_audio": msg_id_audio}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "PublicarTareaClient"}
        )
        with urllib.request.urlopen(req_sync, timeout=5) as r_sync:
            print("Metadatos de la tarea sincronizados con Render.")
    except Exception as e_sync:
        pass

    texto_anuncio = generar_anuncio_tarea(info, fecha_final)
    bot_username = obtener_info_bot()
    teclado = armar_teclado_audio(CHAT_ID, msg_id_audio, bot_username, username_grupo) if CHAT_ID else None

    # 1. Enviar al Grupo Principal con botón directo al audio
    if CHAT_ID:
        ok_grupo = enviar_mensaje(CHAT_ID, texto_anuncio, reply_markup=teclado)
        if ok_grupo:
            print(f"Anuncio de la tarea #{info['numero']} ({fecha_final}) publicado en el grupo {CHAT_ID} con enlace directo al mensaje.")
        else:
            print(f"No se pudo publicar en el grupo {CHAT_ID}.")
    else:
        print("Variable CHAT_ID o TG_GROUP no configurada.")

    # 2. Enviar por separado a cada miembro registrado
    if os.path.exists(RUTA_PUNTOS):
        try:
            with open(RUTA_PUNTOS, "r", encoding="utf-8") as f:
                db_puntos = json.load(f)
            usuarios = db_puntos.get("usuarios", {})
            enviados_priv = 0
            for uid, datos in usuarios.items():
                if str(uid) == str(CHAT_ID):
                    continue
                texto_priv = (
                    f"🕊️ **TAREA DEL DÍA {fecha_final}** 🕊️\n"
                    f"Hola **{datos.get('nombre', 'Compañero')}**, hoy trabajaremos con:\n\n"
                    f"🧘 **{info.get('tipo', 'MEDITACION').title()} #{info['numero']}:** «{info['titulo']}»\n"
                    f"👤 **Guía:** {info['maestro']} | 🗓️ **Grabación:** {info['fecha']}\n\n"
                    f"⏰ Te esperamos puntual a las 7:56 PM para la apertura de la sala."
                )
                teclado_priv = armar_teclado_audio(CHAT_ID, msg_id_audio, bot_username, username_grupo)
                if enviar_mensaje(uid, texto_priv, reply_markup=teclado_priv):
                    enviados_priv += 1
            print(f"Notificación privada enviada a {enviados_priv} miembros con botón al audio.")
        except Exception as e:
            print("Nota enviando a privados:", e)

    return info


if __name__ == "__main__":
    param = sys.argv[1] if len(sys.argv) > 1 else "20"
    fecha = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].strip() else None
    msg_id = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].strip() else None
    publicar_tarea_dia(param, fecha, msg_id)
