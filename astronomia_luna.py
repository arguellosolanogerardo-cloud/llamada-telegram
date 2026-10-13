"""
Módulo de cálculo astronómico lunar y generación de carátula en alta definición
para la Comunidad de Meditación de Bucaramanga.
Calcula fase lunar, porcentaje de iluminación, edad lunar, distancia a la Tierra,
y horas de salida/puesta de la Luna para Bucaramanga (Colombia).
"""
import math
import os
import datetime
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageFilter


def calcular_astronomia_lunar(fecha_hora: datetime.datetime = None, lat: float = 7.1254, lon: float = -73.1198) -> dict:
    """Calcula efemérides lunares exactas con fórmulas astronómicas de Jean Meeus."""
    if fecha_hora is None:
        bogota = ZoneInfo("America/Bogota")
        fecha_hora = datetime.datetime.now(bogota)

    utc = fecha_hora.astimezone(datetime.timezone.utc)
    y, m, d = utc.year, utc.month, utc.day
    h = utc.hour + utc.minute / 60.0 + utc.second / 3600.0

    if m <= 2:
        y -= 1
        m += 12
    a = math.floor(y / 100)
    b = 2 - a + math.floor(a / 4)
    jd = math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + h / 24.0 + b - 1524.5

    T = (jd - 2451545.0) / 36525.0

    # Ángulos fundamentales en grados
    D = (297.8501921 + 445267.1114034 * T) % 360.0
    M = (357.5291092 + 35999.0502909 * T) % 360.0        # Sol
    M_prime = (134.9633964 + 477198.8675055 * T) % 360.0  # Luna
    F = (93.2720950 + 483202.0175233 * T) % 360.0

    rad = math.radians
    # Distancia en kilómetros a la Tierra
    distancia_km = (
        385000.56
        - 20905.355 * math.cos(rad(M_prime))
        - 3699.111 * math.cos(rad(2 * D - M_prime))
        - 2955.968 * math.cos(rad(2 * D))
        - 569.925 * math.cos(rad(2 * M_prime))
    )

    # Ángulo de fase lunar
    i = (
        180.0 - D
        - 6.289 * math.sin(rad(M_prime))
        + 2.100 * math.sin(rad(M))
        - 1.274 * math.sin(rad(2 * D - M_prime))
        - 0.658 * math.sin(rad(2 * D))
        - 0.214 * math.sin(rad(2 * M_prime))
        - 0.110 * math.sin(rad(D))
    )
    i = (i + 360.0) % 360.0

    # Porcentaje de iluminación (0% a 100%)
    iluminacion = (1.0 + math.cos(rad(i))) / 2.0 * 100.0

    # Edad lunar en días (ciclo sinódico = 29.530588853 días)
    synodic = 29.530588853
    d_fase = (D) % 360.0
    edad_dias = (d_fase / 360.0) * synodic

    # Determinación oficial del nombre de la fase en español
    if edad_dias < 1.84 or edad_dias > 27.69:
        fase_nombre = "LUNA NUEVA"
        tipo_icono = "nueva"
    elif edad_dias < 5.53:
        fase_nombre = "LUNA CRECIENTE"
        tipo_icono = "creciente"
    elif edad_dias < 9.23:
        fase_nombre = "CUARTO CRECIENTE"
        tipo_icono = "cuarto_creciente"
    elif edad_dias < 12.92:
        fase_nombre = "LUNA GIBOSA CRECIENTE"
        tipo_icono = "gibosa_creciente"
    elif edad_dias < 16.61:
        fase_nombre = "LUNA LLENA"
        tipo_icono = "llena"
    elif edad_dias < 20.30:
        fase_nombre = "LUNA GIBOSA MENGUANTE"
        tipo_icono = "gibosa_menguante"
    elif edad_dias < 24.00:
        fase_nombre = "CUARTO MENGUANTE"
        tipo_icono = "cuarto_menguante"
    else:
        fase_nombre = "LUNA MENGUANTE"
        tipo_icono = "menguante"

    # Horas aproximadas de salida y puesta para coordenadas de Bucaramanga
    h_salida_base = (6.0 + (d_fase / 360.0) * 24.0) % 24.0
    h_puesta_base = (h_salida_base + 12.4) % 24.0

    def formatear_hora(h_dec: float) -> str:
        hh = int(h_dec)
        mm = int((h_dec - hh) * 60)
        ampm = "AM" if hh < 12 else "PM"
        hh_12 = hh if 1 <= hh <= 12 else (hh - 12 if hh > 12 else 12)
        return f"{hh_12:02d}:{mm:02d} {ampm}"

    return {
        "fase": fase_nombre,
        "tipo": tipo_icono,
        "iluminacion": round(iluminacion, 1),
        "edad": round(edad_dias, 1),
        "distancia": int(round(distancia_km)),
        "salida": formatear_hora(h_salida_base),
        "puesta": formatear_hora(h_puesta_base),
    }


def render_moon_disc(radius: int = 92, illumination: float = 84.6, is_waxing: bool = True) -> Image.Image:
    """Genera un disco lunar realista con sombra tridimensional y cráteres según la fase."""
    size = radius * 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = radius, radius

    # 1. Base gris perla de la luna
    draw.ellipse([(0, 0), (size - 1, size - 1)], fill=(228, 233, 242, 255))

    # 2. Relieve y mares lunares
    scale = radius / 110.0
    manchas = [
        (cx - int(30 * scale), cy - int(25 * scale), int(38 * scale), int(30 * scale), (160, 168, 180, 220)),
        (cx + int(25 * scale), cy - int(15 * scale), int(32 * scale), int(28 * scale), (150, 160, 175, 220)),
        (cx + int(45 * scale), cy + int(5 * scale), int(28 * scale), int(26 * scale), (145, 155, 170, 220)),
        (cx - int(40 * scale), cy + int(20 * scale), int(36 * scale), int(42 * scale), (155, 165, 178, 220)),
        (cx + int(10 * scale), cy + int(40 * scale), int(30 * scale), int(25 * scale), (165, 172, 185, 220)),
        (cx - int(10 * scale), cy - int(50 * scale), int(22 * scale), int(18 * scale), (170, 178, 190, 200)),
    ]
    for mx, my, mw, mh, col in manchas:
        draw.ellipse([(mx - mw // 2, my - mh // 2), (mx + mw // 2, my + mh // 2)], fill=col)

    # 3. Sombra del terminador según iluminación física exacta
    frac = max(0.0, min(1.0, illumination / 100.0))
    shadow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_layer)
    s_color = (0, 0, 0, 255)

    for y in range(size):
        dy = y - cy
        if abs(dy) >= radius:
            continue
        dx_circle = math.sqrt(radius**2 - dy**2)
        x_left = cx - dx_circle
        x_right = cx + dx_circle

        if is_waxing:
            x_term = cx + dx_circle * (1.0 - 2.0 * frac)
            if x_term > x_left:
                s_draw.line([(x_left, y), (min(x_right, x_term), y)], fill=s_color)
        else:
            x_term = cx + dx_circle * (2.0 * frac - 1.0)
            if x_term < x_right:
                s_draw.line([(max(x_left, x_term), y), (x_right, y)], fill=s_color)

    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(1.2))

    # Cortar estrictamente al círculo de la luna
    mask_circle = Image.new("L", (size, size), 0)
    m_draw = ImageDraw.Draw(mask_circle)
    m_draw.ellipse([(0, 0), (size - 1, size - 1)], fill=255)

    img.paste(shadow_layer, (0, 0), mask=mask_circle)

    # Resplandor suave externo sobre fondo negro para resaltar la luna
    glow = Image.new("RGBA", (size + 36, size + 36), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow)
    g_draw.ellipse([(18, 18), (size + 17, size + 17)], fill=(195, 218, 255, 45))
    glow = glow.filter(ImageFilter.GaussianBlur(10))

    result = Image.new("RGBA", (size + 36, size + 36), (0, 0, 0, 0))
    result.paste(glow, (0, 0))
    result.paste(img, (18, 18), mask=mask_circle)
    return result


def wrap_text_balanced(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Divide el texto en líneas armoniosas respetando el ancho máximo y evitando palabras huérfanas."""
    w_full = draw.textlength(text, font=font) if hasattr(draw, "textlength") else font.getlength(text)
    if w_full <= max_width:
        return [text]

    words = text.split()
    if len(words) <= 1:
        return [text]

    lines = []
    curr = []
    for w in words:
        test = " ".join(curr + [w])
        width = draw.textlength(test, font=font) if hasattr(draw, "textlength") else font.getlength(test)
        if width <= max_width or not curr:
            curr.append(w)
        else:
            lines.append(" ".join(curr))
            curr = [w]
    if curr:
        lines.append(" ".join(curr))

    # Si se divide en 2 líneas y la segunda tiene 1 sola palabra, balancear
    if len(lines) == 2:
        words1 = lines[0].split()
        words2 = lines[1].split()
        if len(words2) <= 2 and len(words1) > 3:
            cand1 = " ".join(words1[:-2])
            cand2 = " ".join(words1[-2:] + words2)
            w2 = draw.textlength(cand2, font=font) if hasattr(draw, "textlength") else font.getlength(cand2)
            if w2 <= max_width:
                return [cand1, cand2]
            cand1 = " ".join(words1[:-1])
            cand2 = " ".join(words1[-1:] + words2)
            w2 = draw.textlength(cand2, font=font) if hasattr(draw, "textlength") else font.getlength(cand2)
            if w2 <= max_width:
                return [cand1, cand2]

    return lines


def generar_caratula_meditacion_luna(
    numero: str,
    titulo: str,
    maestro: str,
    duracion_seg: float = 0.0,
    progreso_seg: float = 0.0,
    ruta_salida: str = None,
) -> str | None:
    """Genera la imagen HD 1280x720 con la luna diaria, datos astronómicos y la barra de avance."""
    if not ruta_salida:
        os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
        ruta_salida = os.path.join("data", "meditaciones", "caratula_meditacion.jpg")

    try:
        os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
        width, height = 1280, 720
        # 1. Fondo negro espacial profundo (0, 0, 0) para máximo contraste y realce de la Luna
        img = Image.new("RGB", (width, height), color=(0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 2. Marco exterior elegante
        draw.rounded_rectangle([(24, 20), (1256, 700)], radius=22, outline=(245, 158, 11), width=2)
        draw.rounded_rectangle([(34, 30), (1246, 690)], radius=16, outline=(38, 42, 56), width=1)

        # 3. Fuentes
        font_med = font_tit = font_tit_small = font_sub = font_phase = font_astro = font_time = None
        for f_cand in ["segoeuib.ttf", "arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"]:
            try:
                font_med = ImageFont.truetype(f_cand, 40)
                font_tit = ImageFont.truetype(f_cand, 30)
                font_tit_small = ImageFont.truetype(f_cand, 25)
                font_sub = ImageFont.truetype(f_cand, 22)
                font_phase = ImageFont.truetype(f_cand, 28)
                font_astro = ImageFont.truetype(f_cand, 20)
                font_time = ImageFont.truetype(f_cand, 26)
                break
            except Exception:
                continue
        if not font_med:
            font_med = font_tit = font_tit_small = font_sub = font_phase = font_astro = font_time = ImageFont.load_default()

        # 4. Cabecera dinámica (Meditación #, Título multilínea y Maestro)
        num_txt = f"MEDITACIÓN #{numero}" if numero else "MEDITACIÓN DIARIA"
        draw.text((640, 56), num_txt, fill=(251, 191, 36), font=font_med, anchor="mm")

        tit_raw = (titulo or "").strip()
        if not tit_raw:
            tit_raw = "Paz y Quietud Interior"
        if not tit_raw.startswith("«") and not tit_raw.endswith("»"):
            tit_clean = f"«{tit_raw}»"
        else:
            tit_clean = tit_raw

        # Margen seguro de 920px para evitar cualquier corte en pantallas móviles
        max_tit_w = 920
        lineas_tit = wrap_text_balanced(tit_clean, font_tit, max_tit_w, draw)
        active_font_tit = font_tit
        if len(lineas_tit) > 2 and font_tit_small:
            lineas_tit = wrap_text_balanced(tit_clean, font_tit_small, max_tit_w, draw)
            active_font_tit = font_tit_small

        line_h = 36 if active_font_tit == font_tit else 30
        if len(lineas_tit) == 1:
            start_tit_y = 104
        elif len(lineas_tit) == 2:
            start_tit_y = 96
        else:
            start_tit_y = 90

        for idx, linea in enumerate(lineas_tit):
            curr_y = start_tit_y + idx * line_h
            draw.text((640, curr_y), linea, fill=(255, 255, 255), font=active_font_tit, anchor="mm")

        ultimo_tit_y = start_tit_y + (len(lineas_tit) - 1) * line_h
        m_y = ultimo_tit_y + 34
        m_txt = f"Maestro: {maestro}" if maestro else "Guía: Alaniso"
        draw.text((640, m_y), m_txt, fill=(199, 210, 254), font=font_sub, anchor="mm")

        # 5. Cálculos astronómicos de la Luna de hoy
        astro = calcular_astronomia_lunar()

        # 6. Disco lunar renderizado (adaptativo a la altura de la cabecera)
        moon_cy = max(295, m_y + 112)
        is_waxing = astro["edad"] < 14.765
        moon_img = render_moon_disc(radius=92, illumination=astro["iluminacion"], is_waxing=is_waxing)
        mw, mh = moon_img.size
        moon_x = 640 - mw // 2
        moon_y = moon_cy - mh // 2
        img.paste(moon_img, (moon_x, moon_y), mask=moon_img)

        # 7. Cajas laterales de Salida y Puesta (centradas verticalmente con la Luna)
        box_y1 = moon_cy - 35
        box_y2 = moon_cy + 30
        salida_t_y = moon_cy - 15
        salida_v_y = moon_cy + 11

        draw.rounded_rectangle([(140, box_y1), (370, box_y2)], radius=14, fill=(14, 14, 18), outline=(50, 56, 75), width=1)
        draw.text((255, salida_t_y), "🌙  SALIDA", fill=(251, 191, 36), font=font_astro, anchor="mm")
        draw.text((255, salida_v_y), f"{astro['salida']} (Bucaramanga)", fill=(241, 245, 249), font=font_astro, anchor="mm")

        draw.rounded_rectangle([(910, box_y1), (1140, box_y2)], radius=14, fill=(14, 14, 18), outline=(50, 56, 75), width=1)
        draw.text((1025, salida_t_y), "🌙  PUESTA", fill=(148, 163, 184), font=font_astro, anchor="mm")
        draw.text((1025, salida_v_y), f"{astro['puesta']} (Bucaramanga)", fill=(241, 245, 249), font=font_astro, anchor="mm")

        # 8. Nombre de la fase lunar y métricas
        fase_y = moon_cy + 120
        draw.text((640, fase_y), astro["fase"], fill=(251, 191, 36), font=font_phase, anchor="mm")

        astro_line = f"Iluminación: {astro['iluminacion']}%   •   Edad: {astro['edad']} días   •   Distancia: {astro['distancia']:,} km".replace(",", ".")
        draw.text((640, fase_y + 36), astro_line, fill=(180, 195, 225), font=font_astro, anchor="mm")

        # 9. Zona de Barra de Avance y Tiempos (Espaciosa y sin pie de página)
        bar_x1 = 180
        bar_x2 = 1100
        bar_w = bar_x2 - bar_x1
        bar_y = 550
        bar_h = 14

        dur_total = duracion_seg if duracion_seg > 0 else 1800.0
        ratio = max(0.0, min(1.0, progreso_seg / max(1.0, dur_total)))
        progress_w = int(bar_w * ratio)

        # Fondo de la barra
        draw.rounded_rectangle([(bar_x1, bar_y), (bar_x2, bar_y + bar_h)], radius=7, fill=(24, 26, 34), outline=(48, 54, 72), width=1)

        # Barra llena activa (dorado ámbar)
        if progress_w > 0:
            draw.rounded_rectangle([(bar_x1, bar_y), (bar_x1 + progress_w, bar_y + bar_h)], radius=7, fill=(245, 158, 11))

        # Bolita deslizante con halo
        dot_cx = bar_x1 + progress_w
        dot_cy = bar_y + bar_h // 2
        draw.ellipse([(dot_cx - 14, dot_cy - 14), (dot_cx + 14, dot_cy + 14)], fill=(245, 158, 11, 80))
        draw.ellipse([(dot_cx - 10, dot_cy - 10), (dot_cx + 10, dot_cy + 10)], fill=(255, 255, 255), outline=(245, 158, 11), width=2)

        # 10. Cronómetros y Porcentaje
        min_prog, seg_prog = divmod(int(progreso_seg), 60)
        min_dur, seg_dur = divmod(int(dur_total), 60)
        pct_val = int(round(ratio * 100))

        txt_tiempo_izq = f"▶️  {min_prog:02d}:{seg_prog:02d}"
        txt_tiempo_der = f"{min_dur:02d}:{seg_dur:02d}   ({pct_val}%)"

        draw.text((bar_x1, 600), txt_tiempo_izq, fill=(255, 255, 255), font=font_time, anchor="lm")
        draw.text((bar_x2, 600), txt_tiempo_der, fill=(251, 191, 36), font=font_time, anchor="rm")

        img.save(ruta_salida, format="JPEG", quality=95)
        return ruta_salida
    except Exception as e:
        print("Error generando carátula lunar de meditación:", e)
        return None
