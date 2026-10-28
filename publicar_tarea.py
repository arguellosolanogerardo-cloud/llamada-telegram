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


def enviar_audio(chat_id: int | str, ruta_audio: str, caption: str = "", title: str = "Meditación Diaria", performer: str = "Comunidad", reply_markup: dict = None, thumbnail: str = None) -> tuple[bool, int | None, str | None]:
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

    f_thumb = None
    try:
        with open(ruta_audio, "rb") as f:
            files = {"audio": (os.path.basename(ruta_audio), f, "audio/mpeg")}
            if thumbnail and os.path.exists(thumbnail):
                try:
                    f_thumb = open(thumbnail, "rb")
                    files["thumbnail"] = (os.path.basename(thumbnail), f_thumb, "image/jpeg")
                except Exception as e_th:
                    print("Nota abriendo thumbnail para audio:", e_th)
            r = requests.post(url, data=data, files=files, timeout=180)
            res = r.json()
            if not res.get("ok") and "parse_mode" in data:
                del data["parse_mode"]
                f.seek(0)
                if f_thumb:
                    f_thumb.seek(0)
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
    finally:
        if f_thumb:
            try:
                f_thumb.close()
            except Exception:
                pass





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
    Soporta de forma totalmente dinámica cualquier resolución de plantilla (ej. 671x1024 o 832x1270).
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        ruta_plantilla = os.path.join("data", "assets", "plantilla_tarea_3am.png")
        if not os.path.exists(ruta_plantilla):
            return None

        img = Image.open(ruta_plantilla).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Escala dinámica basada en resolución base de referencia (671 x 1024)
        w, h = img.size
        sx = w / 671.0
        sy = h / 1024.0

        def f_scale(tam: int) -> int:
            return max(10, int(tam * sy))

        font_fecha = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], f_scale(23))
        font_cat = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], f_scale(25))
        font_label = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], f_scale(16))
        font_grab = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], f_scale(25))

        # 1. Fecha del día en la cápsula superior (Grande y centrada)
        txt_fecha = f"{dia_semana.upper()} {fecha_str}".strip()
        bbox_f = draw.textbbox((0, 0), txt_fecha, font=font_fecha)
        fw = bbox_f[2] - bbox_f[0]
        fh = bbox_f[3] - bbox_f[1]
        x1_f, x2_f = int(212 * sx), int(508 * sx)
        y1_f, y_box_h = int(171 * sy), int(41 * sy)
        x_f = x1_f + (x2_f - x1_f - fw) // 2
        y_f = y1_f + (y_box_h - fh) // 2
        draw.text((x_f, y_f), txt_fecha, font=font_fecha, fill=(245, 250, 255))

        # 2. Categoría (MEDITACIÓN o MENSAJE) - Grande
        tipo_raw = str(info_audio.get("tipo", "MEDITACION")).upper()
        txt_cat = "MEDITACIÓN" if "MEDITACI" in tipo_raw else "MENSAJE"
        bbox_c = draw.textbbox((0, 0), txt_cat, font=font_cat)
        cw = bbox_c[2] - bbox_c[0]
        ch = bbox_c[3] - bbox_c[1]
        x1_c, x2_c = int(115 * sx), int(318 * sx)
        y1_c, y_cat_h = int(348 * sy), int(54 * sy)
        x_c = x1_c + (x2_c - x1_c - cw) // 2
        y_c = y1_c + (y_cat_h - ch) // 2
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            draw.text((x_c + dx, y_c + dy), txt_cat, font=font_cat, fill=(0, 150, 190))
        draw.text((x_c, y_c), txt_cat, font=font_cat, fill=(235, 252, 255))

        # 3. Número dentro del anillo de neón (Sin '#', tamaño grande ajustado al círculo)
        num_raw = str(info_audio.get("numero", "")).strip().lstrip("#")
        txt_num = num_raw if num_raw else ""

        # Centro óptico del anillo dorado
        cx, cy = int(176 * sx), int(486 * sy)

        # Ajuste dinámico de tamaño: lo más grande posible dentro del círculo sin salirse
        max_nw = int(68 * sx)
        max_nh = int(39 * sy)
        tam_base = 42
        font_num = None
        while tam_base >= 22:
            f_test = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], f_scale(tam_base))
            bb = draw.textbbox((0, 0), txt_num, font=f_test)
            if (bb[2] - bb[0]) <= max_nw and (bb[3] - bb[1]) <= max_nh:
                font_num = f_test
                break
            tam_base -= 1
        if font_num is None:
            font_num = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], f_scale(24))

        bbox_n = draw.textbbox((0, 0), txt_num, font=font_num)
        x_n = cx - (bbox_n[2] + bbox_n[0]) // 2
        y_n = cy - (bbox_n[3] + bbox_n[1]) // 2
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
            draw.text((x_n + dx, y_n + dy), txt_num, font=font_num, fill=(0, 180, 220))
        draw.text((x_n, y_n), txt_num, font=font_num, fill=(225, 255, 250))

        # 4. Título dinámico dentro de la tarjeta morada (Grande y centrado)
        tit_raw = str(info_audio.get("titulo", "")).strip()
        if tit_raw.startswith("«") and tit_raw.endswith("»"):
            tit_limpio = tit_raw[1:-1].strip()
        else:
            tit_limpio = tit_raw.strip('"\'')
        texto_completo = f"Título: «{tit_limpio}»"

        max_ancho_tit = int(255 * sx)
        max_alto_tit = int(126 * sy)
        tam_tit_base = 20
        lineas_tit = []
        font_title = None

        while tam_tit_base >= 13:
            font_title = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], f_scale(tam_tit_base))
            lineas_tit = _ajustar_lineas_texto(draw, texto_completo, font_title, max_ancho_tit)
            line_height = f_scale(tam_tit_base + 8)
            total_h = len(lineas_tit) * line_height
            if total_h <= max_alto_tit:
                break
            tam_tit_base -= 1

        line_height = f_scale(tam_tit_base + 8)
        total_h = len(lineas_tit) * line_height
        y_tit_start = int(512 * sy) + (max_alto_tit - total_h) // 2

        for idx_l, lin in enumerate(lineas_tit):
            bbox_l = draw.textbbox((0, 0), lin, font=font_title)
            lw = bbox_l[2] - bbox_l[0]
            x_tit = int(46 * sx) + (int(270 * sx) - lw) // 2
            y_cur = y_tit_start + idx_l * line_height
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                draw.text((x_tit + dx, y_cur + dy), lin, font=font_title, fill=(175, 45, 175))
            draw.text((x_tit, y_cur), lin, font=font_title, fill=(255, 215, 255))

        # 5. Maestro (Grande y nítido)
        maestro_raw = str(info_audio.get("maestro", "Alaniso")).strip()
        x_col = int(118 * sx)
        draw.text((x_col, int(658 * sy)), "Maestro:", font=font_label, fill=(195, 225, 240))
        tam_m = f_scale(21 if len(maestro_raw) <= 22 else 17)
        font_m = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], tam_m)
        draw.text((x_col, int(684 * sy)), maestro_raw, font=font_m, fill=(255, 255, 255))

        # 6. Grabación original (Grande)
        fecha_orig = str(info_audio.get("fecha_original") or info_audio.get("fecha") or "No indicada").strip()
        draw.text((x_col, int(740 * sy)), "Grabación original:", font=font_label, fill=(195, 225, 240))
        draw.text((x_col, int(766 * sy)), fecha_orig, font=font_grab, fill=(255, 235, 180))

        os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
        img.save(ruta_salida, "PNG", optimize=True)
        return ruta_salida
    except Exception as e:
        print("Error generando banner tarea:", e)
        return None


def generar_tarjeta_audio(ruta_hd: str, ruta_thumb: str, info_audio: dict) -> tuple[str, str] | None:
    """Genera la tarjeta visual HD (960x560) y la carátula cuadrada (320x320) oficial para el audio del día.
    Estética Cyberpunk: Fondo verde neón suave esmeralda, marco perimetral con línea violeta neón brillante y tipografía grande.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        w, h = 960, 560
        img = Image.new("RGB", (w, h), color=(6, 24, 17))
        draw = ImageDraw.Draw(img)

        # 1. Fondo degradado verde neon cibernetico
        for y in range(h):
            ratio = y / h
            r = int(5 + (12 - 5) * ratio)
            g = int(28 + (54 - 28) * (1 - abs(ratio - 0.5) * 1.7))
            b = int(20 + (36 - 20) * ratio)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_ov = ImageDraw.Draw(overlay)
        for rad in range(240, 0, -10):
            alpha = int(16 * (1 - rad / 240))
            draw_ov.ellipse([w//2 - rad*2, h//2 - int(rad*1.1), w//2 + rad*2, h//2 + int(rad*1.1)], fill=(0, 255, 160, alpha))
        img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))
        draw = ImageDraw.Draw(img)

        # 2. Marco perimetral VIOLETA NEON con resplandor multidimensional
        for bw in range(16, 0, -2):
            draw.rounded_rectangle([20 - bw, 20 - bw, w - 20 + bw, h - 20 + bw], radius=28, outline=(150, 25, 235), width=1)

        draw.rounded_rectangle([19, 19, w - 19, h - 19], radius=27, outline=(195, 55, 255), width=2)
        draw.rounded_rectangle([21, 21, w - 21, h - 21], radius=25, outline=(225, 110, 255), width=3)
        draw.rounded_rectangle([23, 23, w - 23, h - 23], radius=23, outline=(255, 235, 255), width=1)
        draw.rounded_rectangle([32, 32, w - 32, h - 32], radius=16, outline=(130, 20, 210), width=1)

        # 3. Tipografias en tamano grande
        font_tit_head = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 35)
        font_badge = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 21)
        font_tit_audio = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 31)
        font_label = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 23)
        font_val = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 26)
        font_footer = _obtener_fuente(["segoeuib.ttf", "arialbd.ttf"], 21)

        tipo_raw = str(info_audio.get("tipo", "MEDITACION")).upper()
        cat_txt = "MEDITACIÓN" if "MEDITACI" in tipo_raw else "MENSAJE"
        num_txt = str(info_audio.get("numero", "")).strip()
        txt_header = f"{cat_txt}  #{num_txt}".strip()

        # Capsula verde neon superior
        draw.rounded_rectangle([55, 45, 475, 110], radius=18, fill=(12, 48, 35), outline=(0, 255, 170), width=2)
        px, py = 80, 68
        draw.polygon([(px, py), (px + 16, py + 10), (px, py + 20)], fill=(0, 255, 190))
        draw.text((112, 58), txt_header, font=font_tit_head, fill=(0, 255, 190))

        # Badge AUDIO OFICIAL
        draw.rounded_rectangle([w - 265, 50, w - 55, 105], radius=16, fill=(35, 15, 60), outline=(200, 70, 255), width=2)
        draw.ellipse([w - 245, 71, w - 233, 83], fill=(235, 185, 255))
        draw.text((w - 220, 64), "AUDIO OFICIAL", font=font_badge, fill=(235, 185, 255))

        draw.line([(55, 126), (w - 55, 126)], fill=(180, 50, 255), width=2)

        # Titulo de la practica (Grande)
        draw.ellipse([55, 148, 67, 160], fill=(0, 255, 180))
        draw.text((78, 140), "Título de la práctica:", font=font_label, fill=(160, 255, 210))

        tit_raw = str(info_audio.get("titulo", "")).strip().strip("\"'«»")
        texto_tit = f"«{tit_raw}»"

        palabras = texto_tit.split()
        lineas = []
        cur = []
        for p in palabras:
            prueba = " ".join(cur + [p])
            bbox = draw.textbbox((0, 0), prueba, font=font_tit_audio)
            if (bbox[2] - bbox[0]) <= (w - 120):
                cur.append(p)
            else:
                lineas.append(" ".join(cur))
                cur = [p]
        if cur:
            lineas.append(" ".join(cur))

        y_t = 182
        for lin in lineas:
            draw.text((77, y_t + 1), lin, font=font_tit_audio, fill=(5, 20, 15))
            draw.text((75, y_t), lin, font=font_tit_audio, fill=(255, 255, 255))
            y_t += 42

        y_card = max(y_t + 20, 335)

        # Caja Maestro (Maestro: en lugar de Maestro espiritual)
        draw.rounded_rectangle([55, y_card, 475, y_card + 80], radius=14, fill=(10, 40, 30), outline=(0, 200, 140), width=1)
        draw.ellipse([75, y_card + 18, 85, y_card + 28], fill=(0, 255, 170))
        draw.text((95, y_card + 10), "Maestro:", font=font_label, fill=(170, 255, 220))
        maestro_txt = str(info_audio.get("maestro", "Alaniso")).strip()
        draw.text((95, y_card + 40), maestro_txt, font=font_val, fill=(255, 245, 200))

        # Caja Grabacion Original
        draw.rounded_rectangle([495, y_card, w - 55, y_card + 80], radius=14, fill=(10, 40, 30), outline=(0, 200, 140), width=1)
        draw.ellipse([515, y_card + 18, 525, y_card + 28], fill=(255, 220, 120))
        draw.text((535, y_card + 10), "Grabación original:", font=font_label, fill=(170, 255, 220))
        fecha_orig_txt = str(info_audio.get("fecha_original") or info_audio.get("fecha") or "No indicada").strip()
        draw.text((535, y_card + 40), fecha_orig_txt, font=font_val, fill=(255, 220, 120))

        # Footer
        draw.line([(55, h - 80), (w - 55, h - 80)], fill=(180, 50, 255), width=1)
        draw.ellipse([55, h - 55, 65, h - 45], fill=(0, 255, 190))
        draw.text((75, h - 62), "Práctica oficial para la reunión virtual en Telegram • 7:56 PM", font=font_footer, fill=(0, 255, 190))

        os.makedirs(os.path.dirname(os.path.abspath(ruta_hd)), exist_ok=True)
        img.save(ruta_hd, "PNG", optimize=True)

        # Generar thumbnail cuadrado 1:1 (320x320) con fondo verde neón y halo violeta
        # para el reproductor circular de Telegram (detrás de la flecha blanca de play)
        os.makedirs(os.path.dirname(os.path.abspath(ruta_thumb)), exist_ok=True)
        img_sq = Image.new("RGB", (320, 320))
        draw_sq = ImageDraw.Draw(img_sq)
        cx, cy = 160, 160
        # Degradado radial verde neón luminoso
        for r in range(160, -1, -1):
            factor = r / 160.0
            red = int(40 * (1 - factor) + 0 * factor)
            green = int(255 * (1 - factor) + 180 * factor)
            blue = int(160 * (1 - factor) + 85 * factor)
            draw_sq.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(red, green, blue))

        # Halo perimetral violeta neón a juego con el marco de la tarjeta visual
        for bw in range(14, 0, -1):
            alpha_v = 1.0 - (bw / 14.0)
            r_c = int(195 * alpha_v)
            g_c = int(55 * alpha_v)
            b_c = int(255 * alpha_v)
            draw_sq.ellipse([bw, bw, 320 - bw, 320 - bw], outline=(r_c, g_c, b_c))

        img_sq.save(ruta_thumb, "JPEG", quality=95)

        return ruta_hd, ruta_thumb
    except Exception as e:
        print("Error generando tarjeta y cover de audio:", e)
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


def guardar_audio_registrado(info_cat: dict, file_id: str = None, msg_id: int | str = None) -> None:
    """Registra el audio y su file_id en data/meditaciones/audios_registrados.json."""
    if not info_cat:
        return
    try:
        ruta_reg = os.path.join("data", "meditaciones", "audios_registrados.json")
        os.makedirs(os.path.dirname(ruta_reg), exist_ok=True)
        db = {}
        if os.path.exists(ruta_reg):
            try:
                with open(ruta_reg, "r", encoding="utf-8") as f:
                    db = json.load(f)
            except Exception:
                db = {}
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
        with open(ruta_reg, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando audio registrado:", e)


def publicar_tarea_dia(parametro: str, fecha_param: str = None, msg_id_audio: int | str = None, forzar_audio: bool = True) -> dict | list | None:
    """Identifica uno o varios audios por número o texto y publica la tarea completa oficial tal cual el comando /tarea:
    1. Descarga el audio desde Google Drive y genera la tarjeta de audio HD y carátula.
    2. Sube el Audio MP3 directamente al grupo oficial con su botón oficial de privado.
    3. Envía la Tarjeta Gráfica HD debajo del audio en el grupo oficial.
    4. Registra el audio y su file_id en audios_registrados.json.
    5. Guarda y sincroniza atómicamente meta_hoy.json y cola_hoy.json para la llamada de las 7:56 PM.
    6. Genera y publica el Banner Oficial Neón de la Tarea del Día con su teclado interactivo.
    7. Actualiza _TAREA_FLOTANTE en el bot si está corriendo.
    8. Envía la notificación privada con formato de alerta roja a todos los miembros de la comunidad.
    """
    items = identificar_todos_los_audios(texto=parametro)
    if not items:
        info_sing = identificar_audio_catalogo(texto=parametro)
        if info_sing:
            items = [info_sing]
    if not items:
        print(f"No se encontró información en el catálogo para: {parametro}")
        return None

    info = items[0]

    carp_med_pub = os.path.join("data", "meditaciones")
    os.makedirs(carp_med_pub, exist_ok=True)

    # Determinar la fecha provista por el administrador o fecha actual
    fecha_final = None
    if fecha_param and fecha_param.strip():
        fecha_final = extraer_fecha_de_texto(fecha_param.strip()) or fecha_param.strip()
    if not fecha_final:
        fecha_final = extraer_fecha_de_texto(parametro)
    if not fecha_final:
        tz_col = ZoneInfo("America/Bogota")
        fecha_final = datetime.now(tz_col).strftime("%d/%m/%Y")

    username_grupo = None

    # Si forzar_audio es True o no tenemos msg_id_audio, descargar de Google Drive y subir al grupo
    if CHAT_ID and (forzar_audio or not msg_id_audio) and info.get("numero"):
        try:
            from drive_manager import obtener_o_descargar_audio
            tipo_raw = str(info.get("tipo", "MEDITACION")).upper()
            t_nombre = "Meditación" if "MEDITACI" in tipo_raw else "Mensaje"
            num_int = int(str(info["numero"]).strip())

            print(f"🔍 Buscando audio para {t_nombre} #{num_int} en Google Drive...")
            ruta_audio_desc = obtener_o_descargar_audio(info.get("tipo", "MEDITACION"), num_int)
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

                r_tarjeta_hd = os.path.join(carp_med_pub, f"tarjeta_audio_{num_int}.png")
                r_tarjeta_thumb = os.path.join(carp_med_pub, f"cover_audio_{num_int}.jpg")
                res_tarj = generar_tarjeta_audio(r_tarjeta_hd, r_tarjeta_thumb, info)

                # 1. ENVIAR PRIMERO EL AUDIO MP3 (para que quede ARRIBA y se pueda dar play de inmediato)
                print(f"Subiendo archivo de audio al grupo {CHAT_ID}...")
                ok_aud, m_id_aud, f_id_aud = enviar_audio(
                    CHAT_ID,
                    ruta_audio_desc,
                    caption=cap_audio,
                    title=f"{t_nombre} #{num_int} - {info.get('titulo', '')}",
                    performer=info.get('maestro', 'Alaniso'),
                    reply_markup=teclado_aud,
                    thumbnail=r_tarjeta_thumb if (res_tarj and os.path.exists(r_tarjeta_thumb)) else None
                )
                if ok_aud:
                    msg_id_audio = m_id_aud
                    info["file_id"] = f_id_aud
                    info["msg_id_audio"] = m_id_aud
                    print(f"✅ Audio oficial publicado en el grupo: msg_id={m_id_aud}")

                # 2. ENVIAR LA TARJETA GRÁFICA HD (debajo del audio)
                if res_tarj and os.path.exists(r_tarjeta_hd):
                    enviar_foto(CHAT_ID, r_tarjeta_hd, caption=f"✨ **{t_nombre} #{num_int}** — «{info.get('titulo', '')}»", reply_markup=teclado_aud)
                    print("✅ Tarjeta gráfica HD enviada al grupo.")
        except Exception as e_aud_pub:
            print(f"⚠️ Nota descargando/publicando audio en el grupo: {e_aud_pub}")

    # Guardar audio registrado para acceso inmediato en privado
    guardar_audio_registrado(info, file_id=info.get("file_id"), msg_id=msg_id_audio)

    # Guardar metadatos del día y reiniciar cola_hoy.json limpia
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
        ruta_meta = os.path.join(carp_med_pub, "meta_hoy.json")
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

    # Sincronizar metadatos con el bot en Render si está activo y no es el propio proceso
    try:
        url_render = os.environ.get("RENDER_BOT_URL", "").strip()
        if url_render and not url_render.startswith("http://localhost"):
            if not url_render.endswith("/tarea"):
                url_render = url_render.rstrip("/") + "/tarea"
            req_sync = urllib.request.Request(
                url_render,
                data=json.dumps({"info": info_guardar, "msg_id_audio": msg_id_audio}).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "PublicarTareaClient"}
            )
            with urllib.request.urlopen(req_sync, timeout=5) as r_sync:
                print("Metadatos de la tarea sincronizados con Render.")
    except Exception:
        pass

    texto_anuncio = generar_anuncio_tarea(items if len(items) > 1 else info, fecha_final)
    bot_username = obtener_info_bot()
    teclado = armar_teclado_audio(CHAT_ID, msg_id_audio, bot_user=bot_username, numero_tarea=info['numero'], tipo_tarea=info.get('tipo'), audios_lista=items) if CHAT_ID else None

    # Determinar nombre del día de la semana para el banner
    dias_semana_map = {
        0: "LUNES", 1: "MARTES", 2: "MIÉRCOLES", 3: "JUEVES",
        4: "VIERNES", 5: "SÁBADO", 6: "DOMINGO"
    }
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

    m_id_banner = None
    ok_grupo = False

    # 1. Enviar Banner Oficial al Grupo Principal
    if CHAT_ID:
        if banner_generado and os.path.exists(banner_generado):
            ok_grupo, m_id_banner, _ = enviar_foto(CHAT_ID, banner_generado, caption=caption_grupo, reply_markup=teclado)
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

    # 2. Actualizar _TAREA_FLOTANTE en el bot si está corriendo en el mismo proceso
    try:
        import sys
        bot_mod = sys.modules.get("bot_comandos") or sys.modules.get("__main__")
        if bot_mod and hasattr(bot_mod, "_TAREA_FLOTANTE"):
            bot_mod._TAREA_FLOTANTE.update({
                "msg_id": m_id_banner or msg_id_audio,
                "contador": 0,
                "texto": caption_grupo if banner_generado else texto_anuncio,
                "reply_markup": teclado,
                "chat_id": CHAT_ID,
                "ruta_foto": banner_generado if (banner_generado and os.path.exists(banner_generado)) else None
            })
            print("✅ _TAREA_FLOTANTE actualizada en el bot.")
    except Exception:
        pass

    # 3. Enviar Notificaciones Privadas a TODOS los miembros (formato alerta roja idéntico a /tarea)
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
                teclado_priv = armar_teclado_audio(CHAT_ID, msg_id_audio, bot_user=bot_username, numero_tarea=info['numero'], tipo_tarea=info.get('tipo'), audios_lista=items)

                if len(items) > 1:
                    txt_detalles = "\n".join(f"• **{it.get('tipo', 'Audio').title()} #{it.get('numero')}:** «{it.get('titulo')}»" for it in items)
                    texto_priv = (
                        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
                        f"📢 ⚠️ **¡ATENCIÓN {nom_usuario.upper()}!** ⚠️ 📢\n"
                        f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
                        f"🗓️ **FECHA: {fecha_final}**\n"
                        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
                        f"Hola **{nom_usuario}**, hoy en la reunión de las 7:56 PM trabajaremos con:\n\n"
                        f"{txt_detalles}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏰ **¡Te esperamos puntual esta noche a las 7:56 PM!**\n"
                        f"👇 *Toca los botones abajo para escuchar los audios.*"
                    )
                else:
                    t_str_tipo = info.get('tipo', 'MEDITACION').upper()
                    texto_priv = (
                        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n"
                        f"📢 ⚠️ **¡ATENCIÓN {nom_usuario.upper()}!** ⚠️ 📢\n"
                        f"🕊️✨ **T A R E A   D E L   D Í A** ✨🕊️\n"
                        f"🗓️ **FECHA: {fecha_final}**\n"
                        f"🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
                        f"Hola **{nom_usuario}**, hoy en la reunión de las 7:56 PM trabajaremos:\n\n"
                        f"🧘 **{t_str_tipo} #{info['numero']}**\n"
                        f"📌 **Título:** «{info['titulo']}»\n"
                        f"👤 **Maestro:** {info['maestro']} | 🗓️ **Fecha:** {info['fecha']}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏰ **¡Te esperamos puntual esta noche a las 7:56 PM!**\n"
                        f"👇 *Toca el botón abajo para escuchar el audio directamente.*"
                    )

                if enviar_mensaje(uid, texto_priv, reply_markup=teclado_priv):
                    enviados_priv += 1
            print(f"✅ Notificaciones privadas de tarea enviadas a {enviados_priv} miembros con formato oficial de alerta y botones.")
        except Exception as e:
            print("Nota enviando notificaciones privadas:", e)

    return items if len(items) > 1 else info


if __name__ == "__main__":
    param = sys.argv[1] if len(sys.argv) > 1 else "20"
    fecha = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].strip() else None
    msg_id = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].strip() else None
    publicar_tarea_dia(param, fecha, msg_id)
