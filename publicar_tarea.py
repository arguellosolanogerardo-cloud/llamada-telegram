import os
import sys
import re
import json
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from catalogo_audios import identificar_audio_catalogo, formatear_info_audio, cargar_catalogo, identificar_todos_los_audios

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP") or "").strip()
RUTA_PUNTOS = os.path.join("data", "puntos.json")

TG_API_ID = (os.environ.get("TG_API_ID") or "").strip()
TG_API_HASH = (os.environ.get("TG_API_HASH") or "").strip()
TG_SESSION = (os.environ.get("TG_SESSION") or "").strip()


def extraer_fecha_de_texto(texto: str, fecha_referencia: datetime = None) -> str | None:
    if not texto:
        return None

    tz_col = ZoneInfo("America/Bogota")
    if fecha_referencia:
        if fecha_referencia.tzinfo is None:
            ahora = fecha_referencia.replace(tzinfo=tz_col)
        else:
            ahora = fecha_referencia.astimezone(tz_col)
    else:
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


def enviar_audio(chat_id: int | str, ruta_audio: str, caption: str = "", title: str = "Meditación Diaria", performer: str = "Comunidad", reply_markup: dict = None) -> tuple[bool, int | None, str | None]:
    if not BOT_TOKEN or not ruta_audio:
        return False, None, None

    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"

    # Si es file_id
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
                f_id = (res_m.get("audio") or res_m.get("document") or {}).get("file_id") or ruta_audio
                return True, m_id, f_id
            print(f"Telegram rechazó audio file_id ({chat_id}): {res}")
            return False, None, None
        except Exception as e:
            print(f"Error enviando audio por file_id a {chat_id}: {e}")
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
        with open(ruta_audio, "rb") as f:
            files = {"audio": (os.path.basename(ruta_audio), f, "audio/mpeg")}
            r = requests.post(url, data=data, files=files, timeout=180)
            res = r.json()
            if not res.get("ok") and "parse_mode" in data:
                del data["parse_mode"]
                f.seek(0)
                r = requests.post(url, data=data, files=files, timeout=180)
                res = r.json()
            if res.get("ok"):
                res_m = res.get("result", {})
                m_id = res_m.get("message_id")
                f_id = (res_m.get("audio") or res_m.get("document") or {}).get("file_id")
                return True, m_id, f_id
            print(f"Telegram rechazó audio local ({chat_id}): {res}")
            return False, None, None
    except Exception as e:
        print(f"Error enviando audio local a {chat_id}: {e}")
        return False, None, None





def enviar_foto(chat_id: int | str, foto: str, caption: str = "", reply_markup: dict = None) -> tuple[bool, int | None, str | None]:
    """Envía una foto a Telegram admitiendo tanto ruta local en disco como file_id existente."""
    if not BOT_TOKEN or not foto:
        return False, None, None

    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    # Caso 1: file_id previamente registrado en Telegram (ultrarrápido, sin re-subir bytes)
    if not os.path.exists(foto):
        data = {
            "chat_id": str(chat_id),
            "photo": str(foto),
            "caption": caption,
            "parse_mode": "Markdown",
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        try:
            r = requests.post(url, data=data, timeout=25)
            res = r.json()
            if not res.get("ok") and "parse_mode" in data:
                del data["parse_mode"]
                r = requests.post(url, data=data, timeout=25)
                res = r.json()
            if res.get("ok"):
                res_m = res.get("result", {})
                m_id = res_m.get("message_id")
                photos = res_m.get("photo", [])
                f_id = photos[-1].get("file_id") if photos else str(foto)
                return True, m_id, f_id
            print(f"Telegram rechazó foto por file_id ({chat_id}): {res}")
            return False, None, None
        except Exception as e:
            print(f"Error enviando foto por file_id a {chat_id}: {e}")
            return False, None, None

    # Caso 2: Archivo local en disco
    data = {
        "chat_id": str(chat_id),
        "caption": caption,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    try:
        with open(foto, "rb") as f:
            files = {"photo": (os.path.basename(foto), f, "image/png")}
            r = requests.post(url, data=data, files=files, timeout=40)
            res = r.json()
            if not res.get("ok") and "parse_mode" in data:
                del data["parse_mode"]
                f.seek(0)
                r = requests.post(url, data=data, files=files, timeout=40)
                res = r.json()
            if res.get("ok"):
                res_m = res.get("result", {})
                m_id = res_m.get("message_id")
                photos = res_m.get("photo", [])
                f_id = photos[-1].get("file_id") if photos else None
                return True, m_id, f_id
            print(f"Telegram rechazó foto local ({chat_id}): {res}")
            return False, None, None
    except Exception as e:
        print(f"Error enviando foto local a {chat_id}: {e}")
        return False, None, None


def _obtener_fuente(nombres: list[str], tamano: int):
    from PIL import ImageFont
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ruta_bundle = os.path.join(base_dir, "data", "assets", "fonts", "font_bold.ttf")
    if os.path.exists(ruta_bundle):
        try:
            return ImageFont.truetype(ruta_bundle, tamano)
        except Exception:
            pass
    for n in nombres:
        try:
            return ImageFont.truetype(n, tamano)
        except Exception:
            continue
    return ImageFont.load_default()


def _ajustar_lineas_texto(draw, texto: str, fuente, max_ancho: int) -> list[str]:
    palabras = texto.split()
    if not palabras:
        return []
    lineas = []
    linea_actual = []
    for p in palabras:
        prueba = " ".join(linea_actual + [p])
        bbox = draw.textbbox((0, 0), prueba, font=fuente)
        ancho = bbox[2] - bbox[0]
        if ancho <= max_ancho:
            linea_actual.append(p)
        else:
            if linea_actual:
                lineas.append(" ".join(linea_actual))
                linea_actual = [p]
            else:
                lineas.append(p)
                linea_actual = []
    if linea_actual:
        lineas.append(" ".join(linea_actual))
    return lineas


def generar_banner_tarea_dia(ruta_salida: str, info_audio: dict, dia_semana: str = "HOY", fecha_str: str = "") -> str | None:
    """Genera la imagen oficial en alta resolución de la Tarea del Día (3 AM) con estética Neón Cyberpunk.
    Inyecta dinámicamente fecha, tipo (Meditación/Mensaje), número, título, maestro y fecha de grabación original.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        ruta_plantilla = os.path.join("data", "assets", "plantilla_tarea_3am.png")
        if not os.path.exists(ruta_plantilla):
            return None

        img = Image.open(ruta_plantilla).convert("RGB")
        draw = ImageDraw.Draw(img)

        font_fecha = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 23)
        font_cat = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 25)
        font_label = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 16)
        font_grab = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 25)

        # 1. Fecha del día en la cápsula superior (Grande y centrada)
        txt_fecha = f"{dia_semana.upper()} {fecha_str}".strip()
        bbox_f = draw.textbbox((0, 0), txt_fecha, font=font_fecha)
        fw = bbox_f[2] - bbox_f[0]
        fh = bbox_f[3] - bbox_f[1]
        x_f = 212 + (508 - 212 - fw) // 2
        y_f = 171 + (41 - fh) // 2
        draw.text((x_f, y_f), txt_fecha, font=font_fecha, fill=(245, 250, 255))

        # 2. Categoría (MEDITACIÓN o MENSAJE) - Grande
        tipo_raw = str(info_audio.get("tipo", "MEDITACION")).upper()
        txt_cat = "MEDITACIÓN" if "MEDITACI" in tipo_raw else "MENSAJE"
        bbox_c = draw.textbbox((0, 0), txt_cat, font=font_cat)
        cw = bbox_c[2] - bbox_c[0]
        ch = bbox_c[3] - bbox_c[1]
        x_c = 115 + (318 - 115 - cw) // 2
        y_c = 348 + (54 - ch) // 2
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            draw.text((x_c + dx, y_c + dy), txt_cat, font=font_cat, fill=(0, 150, 190))
        draw.text((x_c, y_c), txt_cat, font=font_cat, fill=(235, 252, 255))

        # 3. Número dentro del anillo de neón - Grande
        num_raw = str(info_audio.get("numero", "")).strip()
        txt_num = f"#{num_raw}" if num_raw and not num_raw.startswith("#") else num_raw
        tam_num = 27 if len(txt_num) <= 5 else 23
        font_num = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], tam_num)
        bbox_n = draw.textbbox((0, 0), txt_num, font=font_num)
        nw = bbox_n[2] - bbox_n[0]
        nh = bbox_n[3] - bbox_n[1]
        cx, cy = 182, 476
        x_n = cx - nw // 2
        y_n = cy - nh // 2 - 2
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            draw.text((x_n + dx, y_n + dy), txt_num, font=font_num, fill=(0, 180, 220))
        draw.text((x_n, y_n), txt_num, font=font_num, fill=(225, 255, 250))

        # 4. Título dinámico dentro de la tarjeta morada (Grande y centrado)
        tit_raw = str(info_audio.get("titulo", "")).strip()
        if tit_raw.startswith("«") and tit_raw.endswith("»"):
            tit_limpio = tit_raw[1:-1].strip()
        else:
            tit_limpio = tit_raw.strip('"\'')
        texto_completo = f"Título: «{tit_limpio}»"

        max_ancho_tit = 255
        max_alto_tit = 126
        tam_tit = 20
        lineas_tit = []
        font_title = None

        while tam_tit >= 13:
            font_title = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], tam_tit)
            lineas_tit = _ajustar_lineas_texto(draw, texto_completo, font_title, max_ancho_tit)
            line_height = tam_tit + 8
            total_h = len(lineas_tit) * line_height
            if total_h <= max_alto_tit:
                break
            tam_tit -= 1

        line_height = tam_tit + 8
        total_h = len(lineas_tit) * line_height
        y_tit_start = 512 + (max_alto_tit - total_h) // 2

        for idx_l, lin in enumerate(lineas_tit):
            bbox_l = draw.textbbox((0, 0), lin, font=font_title)
            lw = bbox_l[2] - bbox_l[0]
            x_tit = 46 + (270 - lw) // 2
            y_cur = y_tit_start + idx_l * line_height
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                draw.text((x_tit + dx, y_cur + dy), lin, font=font_title, fill=(175, 45, 175))
            draw.text((x_tit, y_cur), lin, font=font_title, fill=(255, 215, 255))

        # 5. Maestro (Grande y nítido)
        maestro_raw = str(info_audio.get("maestro", "Alaniso")).strip()
        draw.text((115, 658), "Maestro:", font=font_label, fill=(195, 225, 240))
        font_m = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 21 if len(maestro_raw) <= 22 else 17)
        draw.text((115, 684), maestro_raw, font=font_m, fill=(255, 255, 255))

        # 6. Grabación original (Grande)
        fecha_orig = str(info_audio.get("fecha_original") or info_audio.get("fecha") or "No indicada").strip()
        draw.text((115, 740), "Grabación original:", font=font_label, fill=(195, 225, 240))
        draw.text((115, 766), fecha_orig, font=font_grab, fill=(255, 235, 180))

        os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
        img.save(ruta_salida, "PNG", optimize=True)
        return ruta_salida
    except Exception as e:
        print("Error generando banner tarea:", e)
        return None


def generar_anuncio_tarea(info: dict | list, fecha_str: str = None) -> str:
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

    DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_semana_nombre = DIAS_SEMANA[fecha_obj.weekday()]
    dia_semana_upper = dia_semana_nombre.upper()

    es_hoy = fecha_obj.date() == ahora.date()
    tiempo_palabra = f"hoy {dia_semana_upper}" if es_hoy else f"mañana {dia_semana_upper}" if fecha_obj.date() == (ahora + timedelta(days=1)).date() else f"el {dia_semana_upper} {fecha_str}"
    cronograma_palabra = f"esta noche de {dia_semana_nombre} ({fecha_str})" if es_hoy else f"la noche de {dia_semana_nombre} ({fecha_str})"

    if isinstance(info, list) and len(info) > 1:
        bloques_items = []
        for idx, it in enumerate(info, 1):
            it_mario = (
                it.get("es_mario", False)
                or any(k in str(it.get("maestro", "")).upper() for k in ["MARIO CARRILLO", "JESUS MARIO", "JESÚS MARIO"])
                or any(k in str(it.get("canal", "")).upper() for k in ["MARIO CARRILLO", "JESUS MARIO", "JESÚS MARIO"])
            )
            fecha_orig = it.get("fecha_original") or it.get("fecha", "")
            if it_mario:
                bloques_items.append(
                    f"{idx}️⃣ 🧘 **MENSAJE DEL MAESTRO JESUS MARIO CARRILLO DURAN:** «{it.get('titulo', '')}»\n"
                    f"    👤 **Maestro:** JESUS MARIO CARRILLO DURAN | 📅 **Grabación original:** {fecha_orig}"
                )
            else:
                tipo_raw = str(it.get("tipo", "")).upper()
                tipo = "Meditación" if "MEDITACI" in tipo_raw else "Mensaje"
                num = it.get("numero", "")
                titulo = it.get("titulo", "")
                maestro = it.get("maestro", "Alaniso")
                icono = "🧘" if tipo == "Meditación" else "📜"
                bloques_items.append(
                    f"{idx}️⃣ {icono} **{tipo} #{num}:** «{titulo}»\n"
                    f"    👤 **Maestro:** {maestro} | 📅 **Grabación original:** {fecha_orig}"
                )
        txt_items = "\n\n".join(bloques_items)
        return (
            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
            f"📢 ⚠️ **¡ATENCIÓN COMUNIDAD!** ⚠️ 📢\n"
            f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
            f"🗓️ **{dia_semana_upper}  {fecha_str}**\n"
            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
            f"👥 **GRUPO: LA VERDAD OS HARÁ LIBRES**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Para {tiempo_palabra} ({fecha_str}) trabajaremos con las siguientes prácticas en secuencia:\n\n"
            f"{txt_items}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ **HORARIOS PARA ESTA NOCHE (COLOMBIA):**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• 📞 **7:56 PM** → Apertura de la **REUNIÓN VIRTUAL** en Telegram.\n"
            f"• 🤫 **8:28 PM** → Oración y silencio (3 min). 🔇 **MICROFONOS APAGADOS**\n"
            f"• 🎧 **8:32 PM** → Reproducción en vivo secuencial. 🔇 **MICROFONOS APAGADOS**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎧 **LOS AUDIOS ESTÁN DISPONIBLES EN EL GRUPO**\n"
            f"👇 *Pueden escucharlos previamente tocando los mensajes de arriba.*"
        )

    if isinstance(info, list) and len(info) == 1:
        info = info[0]
    elif isinstance(info, list) and not info:
        info = {}

    tipo_raw = str(info.get("tipo", "")).upper()
    tipo = "Meditación" if "MEDITACI" in tipo_raw else "Mensaje"
    num = info.get("numero", "")
    titulo = info.get("titulo", "")
    maestro = info.get("maestro", "Alaniso")
    fecha_orig = info.get("fecha_original") or info.get("fecha", "")

    es_mario = (
        info.get("es_mario", False)
        or any(k in str(maestro).upper() for k in ["MARIO CARRILLO", "JESUS MARIO", "JESÚS MARIO"])
        or any(k in str(info.get("canal", "")).upper() for k in ["MARIO CARRILLO", "JESUS MARIO", "JESÚS MARIO"])
        or any(k in str(titulo).upper() for k in ["MARIO CARRILLO", "JESUS MARIO", "JESÚS MARIO"])
    )

    if es_mario:
        return (
            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
            f"📢 ⚠️ **¡ATENCIÓN COMUNIDAD!** ⚠️ 📢\n"
            f"🕊️✨ **SE PROGRAMO NUEVO AUDIO A LA T A R E A   D E L   D Í A** ✨🕊️\n"
            f"🗓️ **{dia_semana_upper}  {fecha_str}**\n"
            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
            f"👥 **GRUPO: LA VERDAD OS HARÁ LIBRES**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Para {tiempo_palabra} ({fecha_str}) trabajaremos con la siguiente práctica:\n\n"
            f"🧘 **MENSAJE DEL MAESTRO JESUS MARIO CARRILLO DURAN**\n"
            f"📌 **Título:** «{titulo}»\n"
            f"👤 **Maestro:** JESUS MARIO CARRILLO DURAN\n"
            f"🗓️ **Grabación original:** {fecha_orig}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ **HORARIOS PARA ESTA NOCHE (COLOMBIA):**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• 📞 **7:56 PM** → Apertura de la **REUNIÓN VIRTUAL** en Telegram.\n"
            f"• 🤫 **8:28 PM** → Oración y recogimiento (3 min). 🔇 **MICROFONOS APAGADOS**\n"
            f"• 🎧 **8:32 PM** → Reproducción en vivo de la meditación PROGRAMADA Y LUEGO ESTE AUDIO NUEVO🔇 **MICROFONOS APAGADOS**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎧 **EL AUDIO YA FUE PUBLICADO EN EL GRUPO**\n"
            f"👇 *Pueden escucharlo previamente tocando el mensaje de arriba o en el botón oficial.*"
        )

    return (
        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
        f"📢 ⚠️ **¡ATENCIÓN COMUNIDAD!** ⚠️ 📢\n"
        f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
        f"🗓️ **{dia_semana_upper}  {fecha_str}**\n"
        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
        f"👥 **GRUPO: LA VERDAD OS HARÁ LIBRES**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Para {tiempo_palabra} ({fecha_str}) trabajaremos con la siguiente práctica:\n\n"
        f"🧘 **{tipo.upper()} #{num}**\n"
        f"📌 **Título:** «{titulo}»\n"
        f"👤 **Maestro:** {maestro}\n"
        f"🗓️ **Grabación original:** {fecha_orig}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ **HORARIOS PARA ESTA NOCHE (COLOMBIA):**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• 📞 **7:56 PM** → Apertura de la **REUNIÓN VIRTUAL** en Telegram.\n"
        f"• 🤫 **8:28 PM** → Oración y recogimiento (3 min). 🔇 **MICROFONOS APAGADOS**\n"
        f"• 🎧 **8:32 PM** → Reproducción en vivo de la {tipo.lower()}. 🔇 **MICROFONOS APAGADOS**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎧 **EL AUDIO YA FUE PUBLICADO EN EL GRUPO**\n"
        f"👇 *Pueden escucharlo previamente tocando el mensaje de arriba o en el botón oficial.*"
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


def armar_teclado_audio(chat_id: int | str, msg_id_audio: int | str = None, bot_user: str = "", username_grupo: str = None, numero_tarea: int | str = None, tipo_tarea: str = None, audios_lista: list = None) -> dict:
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
        if audios_lista and len(audios_lista) > 1:
            for it in audios_lista:
                t_str = "mensaje" if "MENSAJE" in str(it.get("tipo", "")).upper() else "meditacion"
                n_str = it.get("numero", "")
                t_nom = "MENSAJE" if t_str == "mensaje" else "MEDITACIÓN"
                botones.append([{
                    "text": f"📥 RECIBIR {t_nom} #{n_str} EN PRIVADO 🎧",
                    "url": f"https://t.me/{bot_user}?start=audio_{t_str}_{n_str}"
                }])
        else:
            clean_tipo = "mensaje" if tipo_tarea and "MENSAJE" in str(tipo_tarea).upper() else "meditacion"
            param_audio = f"audio_{clean_tipo}_{numero_tarea}" if numero_tarea else "audio"
            botones.append([{"text": "📥 RECIBIR AUDIO EN MI TELEGRAM PRIVADO 🎧", "url": f"https://t.me/{bot_user}?start={param_audio}"}])

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


def publicar_tarea_dia(parametro: str, fecha_param: str = None, msg_id_audio: int | str = None) -> dict | list | None:
    """Identifica uno o varios audios por número o texto y envía el anuncio oficial al grupo y privados."""
    items = identificar_todos_los_audios(texto=parametro)
    if not items:
        info_sing = identificar_audio_catalogo(texto=parametro)
        if info_sing:
            items = [info_sing]
    if not items:
        print(f"No se encontró información en el catálogo para: {parametro}")
        return None

    info = items[0]

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

    # Si aún no está en el grupo, buscarlo en Drive y subir el archivo al grupo directamente
    if not msg_id_audio and CHAT_ID and info.get("numero"):
        try:
            from drive_manager import obtener_o_descargar_audio
            tipo_raw = str(info.get("tipo", "MEDITACION")).upper()
            t_nombre = "Meditación" if "MEDITACI" in tipo_raw else "Mensaje"
            num_int = int(str(info["numero"]).strip())

            print(f"Buscando audio para {t_nombre} #{num_int} en Google Drive...")
            ruta_audio_desc = obtener_o_descargar_audio(tipo_raw, num_int)
            if ruta_audio_desc and os.path.exists(ruta_audio_desc):
                cap_audio = (
                    f"🧘 **{t_nombre} #{num_int}**\n"
                    f"📌 **Título:** «{info.get('titulo', '')}»\n"
                    f"👤 **Maestro:** {info.get('maestro', 'Alaniso')}\n"
                    f"🗓️ **Grabación original:** {info.get('fecha_original') or info.get('fecha', '')}\n\n"
                    f"🎧 Audio oficial para la práctica de hoy."
                )
                bot_u_tarea = obtener_info_bot()
                clean_t = "mensaje" if "MENSAJE" in tipo_raw else "meditacion"
                param_priv = f"audio_{clean_t}_{num_int}"
                teclado_aud = {
                    "inline_keyboard": [[
                        {"text": "📥 RECIBIR AUDIO EN MI TELEGRAM PRIVADO 🎧", "url": f"https://t.me/{bot_u_tarea}?start={param_priv}"}
                    ]]
                } if bot_u_tarea else None

                print(f"Subiendo archivo de audio al grupo {CHAT_ID}...")
                ok_aud, m_id_aud, f_id_aud = enviar_audio(
                    CHAT_ID,
                    ruta_audio_desc,
                    caption=cap_audio,
                    title=f"{t_nombre} #{num_int} - {info.get('titulo', '')}",
                    performer=info.get('maestro', 'Alaniso'),
                    reply_markup=teclado_aud
                )
                if ok_aud:
                    msg_id_audio = m_id_aud
                    info["file_id"] = f_id_aud
                    info["msg_id_audio"] = m_id_aud
                    print(f"✅ Audio oficial publicado en el grupo: msg_id={m_id_aud}")
        except Exception as e_aud_pub:
            print(f"⚠️ Nota descargando/publicando audio en el grupo: {e_aud_pub}")


    # Guardar metadatos del día y reiniciar cola_hoy.json limpia
    carp_med_pub = os.path.join("data", "meditaciones")
    os.makedirs(carp_med_pub, exist_ok=True)
    ruta_meta = os.path.join(carp_med_pub, "meta_hoy.json")
    try:
        # Limpiar audios adicionales residuales de sesiones anteriores
        for fn in os.listdir(carp_med_pub):
            if fn.startswith(("meditacion_hoy_", "meditacion_extra", "yt_extra_")) and fn.endswith((".mp3", ".m4a", ".wav", ".ogg", ".mp4")):
                try:
                    os.remove(os.path.join(carp_med_pub, fn))
                except Exception:
                    pass
        info_guardar = dict(info)
        info_guardar["fecha_tarea_admin"] = fecha_final
        if len(items) > 1:
            info_guardar["cola_audios"] = items
        if msg_id_audio:
            info_guardar["msg_id_audio"] = msg_id_audio
        with open(ruta_meta, "w", encoding="utf-8") as f:
            json.dump(info_guardar, f, ensure_ascii=False, indent=2)
        # Dejar cola_hoy.json limpia únicamente con la(s) pista(s) de la tarea oficial
        cola_limpia = []
        for idx_it, it_p in enumerate(items, 1):
            r_it = os.path.join(carp_med_pub, "meditacion_hoy.mp3" if idx_it == 1 else f"meditacion_hoy_{idx_it}.mp3")
            t_it = "Meditación" if "MEDITACI" in str(it_p.get("tipo", "MEDITACION")).upper() else "Mensaje"
            cola_limpia.append({
                "ruta": os.path.abspath(r_it),
                "info": dict(it_p, msg_id_audio=msg_id_audio) if idx_it == 1 and msg_id_audio else it_p,
                "titulo": f"{t_it} #{it_p.get('numero', '')} - {it_p.get('titulo', '')}".strip(" -#")
            })
        with open(os.path.join(carp_med_pub, "cola_hoy.json"), "w", encoding="utf-8") as fc:
            json.dump({"fecha": fecha_final, "cola": cola_limpia}, fc, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando meta_hoy y cola_hoy:", e)

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

    texto_anuncio = generar_anuncio_tarea(items if len(items) > 1 else info, fecha_final)
    bot_username = obtener_info_bot()
    teclado = armar_teclado_audio(CHAT_ID, msg_id_audio, bot_username, username_grupo, numero_tarea=info['numero'], tipo_tarea=info.get('tipo'), audios_lista=items) if CHAT_ID else None

    # Determinar nombre del día de la semana para el banner
    dias_semana_map = {
        0: "LUNES", 1: "MARTES", 2: "MIÉRCOLES", 3: "JUEVES",
        4: "VIERNES", 5: "SÁBADO", 6: "DOMINGO"
    }
    dia_semana_nombre = "HOY"
    try:
        dt_p = datetime.strptime(fecha_final, "%d/%m/%Y")
        dia_semana_nombre = dias_semana_map.get(dt_p.weekday(), "HOY")
    except Exception:
        dt_p = datetime.now(ZoneInfo("America/Bogota"))
        dia_semana_nombre = dias_semana_map.get(dt_p.weekday(), "HOY")

    # Generar la tarjeta gráfica oficial HD (3 AM) con estética Neón Cyberpunk
    ruta_banner = os.path.join(carp_med_pub, "banner_tarea_hoy.png")
    banner_generado = generar_banner_tarea_dia(
        ruta_banner,
        info,
        dia_semana=dia_semana_nombre,
        fecha_str=fecha_final
    )

    caption_grupo = (
        f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
        f"🗓️ **{dia_semana_nombre.upper()}  {fecha_final}**\n\n"
        f"👥 **GRUPO: LA VERDAD OS HARÁ LIBRES**\n\n"
        f"👇 *Toca los botones oficiales para escuchar el audio en el grupo o recibirlo en tu privado.*"
    )
    if len(items) > 1:
        txt_extra = "\n".join(f"• **{it.get('tipo', 'Audio').title()} #{it.get('numero')}:** «{it.get('titulo')}»" for it in items)
        caption_grupo = (
            f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
            f"🗓️ **{dia_semana_nombre.upper()}  {fecha_final}**\n\n"
            f"👥 **GRUPO: LA VERDAD OS HARÁ LIBRES**\n"
            f"Prácticas en secuencia para hoy:\n{txt_extra}\n\n"
            f"👇 *Toca los botones oficiales para escuchar los audios en el grupo.*"
        )

    file_id_banner = None
    ok_grupo = False

    # 1. Enviar al Grupo Principal (primero intentar como foto HD)
    if CHAT_ID:
        if banner_generado and os.path.exists(banner_generado):
            ok_grupo, m_id_foto, file_id_banner = enviar_foto(CHAT_ID, banner_generado, caption=caption_grupo, reply_markup=teclado)
            if ok_grupo:
                print(f"✅ Banner HD de la tarea ({fecha_final}) publicado exitosamente en el grupo {CHAT_ID}.")

        # Fallback a texto si no se pudo enviar la foto
        if not ok_grupo:
            ok_grupo = enviar_mensaje(CHAT_ID, texto_anuncio, reply_markup=teclado)
            if ok_grupo:
                print(f"Anuncio de texto de la tarea ({fecha_final}) publicado en el grupo {CHAT_ID} (fallback).")
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
            ruta_sin_priv = os.path.join("data", "usuarios_sin_privado.json")
            sin_priv = set()
            if os.path.exists(ruta_sin_priv):
                try:
                    with open(ruta_sin_priv, "r", encoding="utf-8") as fs:
                        sin_priv = set(str(x) for x in json.load(fs))
                except Exception:
                    pass
            enviados_priv = 0
            foto_priv = file_id_banner or (banner_generado if banner_generado and os.path.exists(banner_generado) else None)

            for uid, datos in usuarios.items():
                if str(uid) == str(CHAT_ID):
                    continue
                if str(uid) in sin_priv:
                    continue
                try:
                    if int(str(uid)) <= 0:
                        continue
                except ValueError:
                    continue

                nom_usuario = datos.get('nombre', 'Compañero')
                teclado_priv = armar_teclado_audio(CHAT_ID, msg_id_audio, bot_username, username_grupo, numero_tarea=info['numero'], tipo_tarea=info.get('tipo'), audios_lista=items)

                enviado_ok = False
                if foto_priv:
                    caption_priv = (
                        f"🕊️✨ **TAREA DEL DÍA: {fecha_final}** ✨🕊️\n\n"
                        f"Hola **{nom_usuario}**, ¡aquí tienes la práctica oficial de hoy!\n"
                        f"⏰ Te esperamos a las 7:56 PM para la reunión virtual.\n\n"
                        f"👇 *Toca los botones abajo para escuchar tu audio.*"
                    )
                    enviado_ok, _, _ = enviar_foto(uid, foto_priv, caption=caption_priv, reply_markup=teclado_priv)

                if not enviado_ok:
                    if len(items) > 1:
                        txt_detalles = "\n".join(f"• **{it.get('tipo', 'Audio').title()} #{it.get('numero')}:** «{it.get('titulo')}»" for it in items)
                        texto_priv = (
                            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
                            f"📢 ⚠️ **¡ATENCIÓN {nom_usuario.upper()}!** ⚠️ 📢\n"
                            f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
                            f"🗓️ **FECHA: {fecha_final}**\n"
                            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
                            f"Hola **{nom_usuario}**, hoy trabajaremos con:\n\n"
                            f"{txt_detalles}\n\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"⏰ **Te esperamos a las 7:56 PM para la apertura de la sala.**\n"
                            f"👇 *Toca los botones abajo para escuchar los audios.*"
                        )
                    else:
                        texto_priv = (
                            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
                            f"📢 ⚠️ **¡ATENCIÓN {nom_usuario.upper()}!** ⚠️ 📢\n"
                            f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
                            f"🗓️ **FECHA: {fecha_final}**\n"
                            f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
                            f"Hola **{nom_usuario}**, hoy trabajaremos con:\n\n"
                            f"🧘 **{info.get('tipo', 'MEDITACION').upper()} #{info['numero']}**\n"
                            f"📌 **Título:** «{info['titulo']}»\n"
                            f"👤 **Maestro:** {info['maestro']} | 🗓️ **Grabación:** {info['fecha']}\n\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"⏰ **Te esperamos a las 7:56 PM para la apertura de la sala.**\n"
                            f"👇 *Toca el botón de abajo para escuchar el audio directamente.*"
                        )
                    if enviar_mensaje(uid, texto_priv, reply_markup=teclado_priv):
                        enviado_ok = True

                if enviado_ok:
                    enviados_priv += 1
            print(f"Notificación de la tarea enviada a {enviados_priv} miembros con banner HD y botones.")
        except Exception as e:
            print("Nota enviando a privados:", e)

    return items if len(items) > 1 else info


if __name__ == "__main__":
    param = sys.argv[1] if len(sys.argv) > 1 else "20"
    fecha = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].strip() else None
    msg_id = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].strip() else None
    publicar_tarea_dia(param, fecha, msg_id)
