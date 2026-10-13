"""
Módulo de cálculo astronómico lunar y generación de carátula en alta definición
para la Comunidad de Meditación de Bucaramanga.
Calcula fase lunar, porcentaje de iluminación, edad lunar, distancia a la Tierra,
y horas de salida/puesta de la Luna para Bucaramanga (Colombia).
"""
import math
import os
import random
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
    """Genera un disco lunar realista con franja blanca luminosa y aura/halo celestial para resaltar en el cosmos."""
    size = radius * 2
    cx, cy = radius, radius

    # 1. Base del cuerpo lunar (esfera 3D visible con mares, en azul noche cósmico)
    moon_body = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d_body = ImageDraw.Draw(moon_body)
    d_body.ellipse([(0, 0), (size - 1, size - 1)], fill=(24, 30, 46, 255))

    scale = radius / 110.0
    manchas = [
        (cx - int(30 * scale), cy - int(25 * scale), int(38 * scale), int(30 * scale), (32, 40, 60, 255)),
        (cx + int(25 * scale), cy - int(15 * scale), int(32 * scale), int(28 * scale), (30, 38, 56, 255)),
        (cx + int(45 * scale), cy + int(5 * scale), int(28 * scale), int(26 * scale), (34, 42, 62, 255)),
        (cx - int(40 * scale), cy + int(20 * scale), int(36 * scale), int(42 * scale), (28, 36, 54, 255)),
        (cx + int(10 * scale), cy + int(40 * scale), int(30 * scale), int(25 * scale), (32, 40, 58, 255)),
    ]
    for mx, my, mw, mh, col in manchas:
        d_body.ellipse([(mx - mw // 2, my - mh // 2), (mx + mw // 2, my + mh // 2)], fill=col)

    # 2. Capa de iluminación blanca pura y brillante
    lit_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d_lit = ImageDraw.Draw(lit_layer)
    d_lit.ellipse([(0, 0), (size - 1, size - 1)], fill=(255, 255, 255, 255))

    manchas_lit = [
        (cx + int(25 * scale), cy - int(15 * scale), int(32 * scale), int(28 * scale), (225, 235, 248, 255)),
        (cx + int(45 * scale), cy + int(5 * scale), int(28 * scale), int(26 * scale), (210, 225, 242, 255)),
    ]
    for mx, my, mw, mh, col in manchas_lit:
        d_lit.ellipse([(mx - mw // 2, my - mh // 2), (mx + mw // 2, my + mh // 2)], fill=col)

    # Máscara del terminador: asegura franja blanca clara y nítida según la fase del día
    lit_mask = Image.new("L", (size, size), 0)
    d_m = ImageDraw.Draw(lit_mask)
    frac = max(0.08, min(0.98, illumination / 100.0))

    for y in range(size):
        dy = y - cy
        if abs(dy) >= radius:
            continue
        dx_circle = math.sqrt(radius**2 - dy**2)
        x_left = cx - dx_circle
        x_right = cx + dx_circle
        if is_waxing:
            x_term = cx + dx_circle * (1.0 - 2.0 * frac)
            if x_term < x_right:
                d_m.line([(max(x_left, x_term), y), (x_right, y)], fill=255)
        else:
            x_term = cx + dx_circle * (2.0 * frac - 1.0)
            if x_term > x_left:
                d_m.line([(x_left, y), (min(x_right, x_term), y)], fill=255)

    lit_mask = lit_mask.filter(ImageFilter.GaussianBlur(1.0))

    # Combinar cuerpo lunar y zona iluminada
    final_moon = moon_body.copy()
    final_moon.paste(lit_layer, (0, 0), mask=lit_mask)

    # Borde celeste de 1px para delimitar suavemente el perfil lunar
    d_f = ImageDraw.Draw(final_moon)
    d_f.ellipse([(0, 0), (size - 1, size - 1)], outline=(160, 190, 235, 220), width=1)

    # 3. HALO Y AURA BLANCA RADIANTE ALREDEDOR DE LA LUNA
    pad = 40
    canvas_size = size + pad * 2
    halo_canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    d_halo = ImageDraw.Draw(halo_canvas)

    # Capa 1: Aura amplia difusa blanca celestial
    d_halo.ellipse([(pad - 20, pad - 20), (pad + size + 19, pad + size + 19)], fill=(210, 230, 255, 95))
    halo_canvas = halo_canvas.filter(ImageFilter.GaussianBlur(20))

    # Capa 2: Aura media luminosa blanca
    halo_mid = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    d_mid = ImageDraw.Draw(halo_mid)
    d_mid.ellipse([(pad - 8, pad - 8), (pad + size + 7, pad + size + 7)], fill=(255, 255, 255, 140))
    halo_mid = halo_mid.filter(ImageFilter.GaussianBlur(8))
    halo_canvas.paste(halo_mid, (0, 0), mask=halo_mid)

    # Capa 3: Anillo nítido de luz perimetral blanca
    halo_ring = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    d_ring = ImageDraw.Draw(halo_ring)
    d_ring.ellipse([(pad - 1, pad - 1), (pad + size, pad + size)], outline=(255, 255, 255, 200), width=2)
    halo_canvas.paste(halo_ring, (0, 0), mask=halo_ring)

    # Pegar la luna sobre el halo
    halo_canvas.paste(final_moon, (pad, pad), mask=final_moon)
    return halo_canvas


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


def crear_universo_con_orion(width: int = 1280, height: int = 720, frame_idx: int = 0, total_frames: int = 20, seed: int = 42) -> Image.Image:
    """Genera el manto cósmico denso (+650 estrellas) con polvo estelar y la constelación de Orión titilando."""
    img = Image.new("RGB", (width, height), (1, 2, 7))

    # Polvo cósmico y nebulosas sutiles
    nebula = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    n_draw = ImageDraw.Draw(nebula)
    n_draw.ellipse([(800, -100), (1350, 400)], fill=(20, 30, 65, 45))
    n_draw.ellipse([(-100, 200), (450, 750)], fill=(25, 20, 55, 35))
    n_draw.ellipse([(400, 150), (900, 550)], fill=(15, 25, 50, 25))
    nebula = nebula.filter(ImageFilter.GaussianBlur(50))
    img.paste(nebula, (0, 0), mask=nebula)
    draw = ImageDraw.Draw(img)

    rng = random.Random(seed)
    drift_x = int((frame_idx / max(1, total_frames)) * width) % width

    def is_forbidden(x, y):
        if (x - 640) ** 2 + (y - 300) ** 2 < 118 ** 2:
            return True
        if 135 < x < 375 and 245 < y < 345:
            return True
        if 905 < x < 1145 and 245 < y < 345:
            return True
        if 160 < x < 1120 and 520 < y < 630:
            return True
        if 200 < x < 1080 and 40 < y < 185:
            return True
        return False

    # 650 micro-estrellas densas
    for _ in range(650):
        base_x = rng.randint(0, width)
        y = rng.randint(25, height - 25)
        x = (base_x + drift_x) % width
        if is_forbidden(x, y):
            continue
        b = rng.randint(70, 175)
        draw.point((x, y), fill=(b, b, min(255, b + 30)))

    # 120 estrellas medianas
    for _ in range(120):
        base_x = rng.randint(0, width)
        y = rng.randint(25, height - 25)
        x = (base_x + drift_x) % width
        if is_forbidden(x, y):
            continue
        b = rng.randint(170, 235)
        draw.ellipse([(x - 1, y - 1), (x + 1, y + 1)], fill=(b, min(255, b + 10), 255))

    # 25 estrellas prominentes con destellos
    for _ in range(25):
        base_x = rng.randint(0, width)
        y = rng.randint(30, height - 30)
        x = (base_x + drift_x) % width
        if is_forbidden(x, y):
            continue
        draw.ellipse([(x - 2, y - 2), (x + 2, y + 2)], fill=(255, 255, 255))
        draw.line([(x - 5, y), (x + 5, y)], fill=(200, 225, 255, 170))
        draw.line([(x, y - 5), (x, y + 5)], fill=(200, 225, 255, 170))

    # Constelación de Orión (cuadrante superior derecho despejado)
    twinkle_t = (frame_idx / max(1, total_frames)) * 2 * math.pi
    ox = 1060 + int(math.sin(twinkle_t * 0.5) * 5)
    oy = 135

    orion_stars = {
        "betelgeuse": (-32, -42, (255, 175, 95), 4.0, math.sin(twinkle_t * 3.0)),
        "bellatrix":  ( 24, -38, (215, 235, 255), 3.0, math.cos(twinkle_t * 2.5)),
        "mintaka":    (-14,  -2, (240, 245, 255), 2.5, math.sin(twinkle_t * 4.0)),
        "alnilam":    (  0,   2, (245, 250, 255), 3.0, math.sin(twinkle_t * 3.5 + 1)),
        "alnitak":    ( 14,   6, (240, 245, 255), 2.5, math.cos(twinkle_t * 4.0)),
        "saiph":      (-28,  44, (200, 220, 255), 3.0, math.sin(twinkle_t * 2.0)),
        "rigel":      ( 32,  40, (230, 245, 255), 4.5, math.cos(twinkle_t * 3.2)),
    }

    # Líneas tenues de la constelación
    line_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    l_draw = ImageDraw.Draw(line_layer)
    conexiones = [
        ("betelgeuse", "bellatrix"),
        ("betelgeuse", "alnitak"),
        ("bellatrix", "mintaka"),
        ("mintaka", "alnilam"),
        ("alnilam", "alnitak"),
        ("alnitak", "saiph"),
        ("mintaka", "rigel"),
        ("saiph", "rigel"),
    ]
    for s1, s2 in conexiones:
        p1 = (ox + orion_stars[s1][0], oy + orion_stars[s1][1])
        p2 = (ox + orion_stars[s2][0], oy + orion_stars[s2][1])
        l_draw.line([p1, p2], fill=(100, 140, 200, 85), width=1)

    img.paste(line_layer, (0, 0), mask=line_layer)
    draw = ImageDraw.Draw(img)

    for name, (dx, dy, base_rgb, base_r, tw_val) in orion_stars.items():
        sx = ox + dx
        sy = oy + dy
        pulsacion = 0.85 + 0.25 * tw_val
        cur_r = max(1.5, base_r * pulsacion)
        cur_col = tuple(min(255, int(c * pulsacion)) for c in base_rgb)

        halo_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        h_draw = ImageDraw.Draw(halo_layer)
        halo_r = cur_r * 2.8
        h_draw.ellipse([(sx - halo_r, sy - halo_r), (sx + halo_r, sy + halo_r)], fill=(*base_rgb, int(45 * pulsacion)))
        halo_layer = halo_layer.filter(ImageFilter.GaussianBlur(3))
        img.paste(halo_layer, (0, 0), mask=halo_layer)
        draw = ImageDraw.Draw(img)

        draw.ellipse([(sx - cur_r, sy - cur_r), (sx + cur_r, sy + cur_r)], fill=cur_col)
        if base_r >= 3:
            spike_len = int(cur_r * 2.5)
            draw.line([(sx - spike_len, sy), (sx + spike_len, sy)], fill=(*base_rgb, int(160 * pulsacion)))
            draw.line([(sx, sy - spike_len), (sx, sy + spike_len)], fill=(*base_rgb, int(160 * pulsacion)))

    try:
        f_orion = ImageFont.truetype("arial.ttf", 13)
        draw.text((ox, oy + 58), "ORIÓN", fill=(140, 175, 220, 160), font=f_orion, anchor="mm")
    except Exception:
        pass

    return img


def generar_video_meditacion_luna(
    numero: str,
    titulo: str,
    maestro: str,
    duracion_seg: float = 1800.0,
    ruta_salida: str = None,
) -> str | None:
    """Genera el video MP4 HD con estrellas en movimiento, Orión titilando y reloj/barra animados en tiempo real."""
    if not ruta_salida:
        os.makedirs(os.path.join("data", "meditaciones"), exist_ok=True)
        ruta_salida = os.path.join("data", "meditaciones", "caratula_meditacion.mp4")

    try:
        import subprocess
        width, height = 1280, 720
        temp_dir = os.path.join("data", "meditaciones", "temp_frames")
        os.makedirs(temp_dir, exist_ok=True)

        seed_val = int(numero) if numero and str(numero).isdigit() else 1094
        dur_seg = max(60.0, float(duracion_seg))

        # 1. Generar 20 fotogramas para el bucle de 10s de estrellas y Orión titilando
        num_frames = 20
        for i in range(num_frames):
            frame = crear_universo_con_orion(width, height, frame_idx=i, total_frames=num_frames, seed=seed_val)
            frame.save(os.path.join(temp_dir, f"frame_{i:03d}.png"))

        loop_video = os.path.join(temp_dir, "stars_loop.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-r", "2",
            "-i", os.path.join(temp_dir, "frame_%03d.png"),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            loop_video
        ], capture_output=True, check=True)

        # 2. Generar capa transparente con la Luna, títulos multilínea, maestro, etc.
        fg = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(fg)

        # Marco exterior e interior
        draw.rounded_rectangle([(24, 20), (1256, 700)], radius=22, outline=(245, 158, 11), width=2)
        draw.rounded_rectangle([(34, 30), (1246, 690)], radius=16, outline=(42, 48, 64), width=1)

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

        # Cabecera dinámica
        num_txt = f"MEDITACIÓN #{numero}" if numero else "MEDITACIÓN DIARIA"
        draw.text((640, 56), num_txt, fill=(251, 191, 36), font=font_med, anchor="mm")

        tit_raw = (titulo or "").strip()
        tit_clean = f"«{tit_raw}»" if not tit_raw.startswith("«") else tit_raw
        max_tit_w = 920
        lineas_tit = wrap_text_balanced(tit_clean, font_tit, max_tit_w, draw)
        active_font_tit = font_tit
        if len(lineas_tit) > 2 and font_tit_small:
            lineas_tit = wrap_text_balanced(tit_clean, font_tit_small, max_tit_w, draw)
            active_font_tit = font_tit_small

        line_h = 36 if active_font_tit == font_tit else 30
        start_tit_y = 104 if len(lineas_tit) == 1 else (96 if len(lineas_tit) == 2 else 90)
        for idx, linea in enumerate(lineas_tit):
            curr_y = start_tit_y + idx * line_h
            draw.text((640, curr_y), linea, fill=(255, 255, 255), font=active_font_tit, anchor="mm")

        ultimo_tit_y = start_tit_y + (len(lineas_tit) - 1) * line_h
        m_y = ultimo_tit_y + 34
        m_txt = f"Maestro: {maestro}" if maestro else "Guía: Alaniso"
        draw.text((640, m_y), m_txt, fill=(199, 210, 254), font=font_sub, anchor="mm")

        # Luna
        astro = calcular_astronomia_lunar()
        moon_cy = max(295, m_y + 112)
        is_waxing = astro["edad"] < 14.765
        moon_img = render_moon_disc(radius=92, illumination=astro["iluminacion"], is_waxing=is_waxing)
        mw, mh = moon_img.size
        fg.paste(moon_img, (640 - mw // 2, moon_cy - mh // 2), mask=moon_img)

        # Cajas laterales
        box_y1 = moon_cy - 35
        box_y2 = moon_cy + 30
        draw.rounded_rectangle([(140, box_y1), (370, box_y2)], radius=14, fill=(14, 16, 22, 230), outline=(50, 58, 80), width=1)
        draw.text((255, moon_cy - 15), "SALIDA", fill=(251, 191, 36), font=font_astro, anchor="mm")
        draw.text((255, moon_cy + 11), f"{astro['salida']} (Bucaramanga)", fill=(241, 245, 249), font=font_astro, anchor="mm")

        draw.rounded_rectangle([(910, box_y1), (1140, box_y2)], radius=14, fill=(14, 16, 22, 230), outline=(50, 58, 80), width=1)
        draw.text((1025, moon_cy - 15), "PUESTA", fill=(148, 163, 184), font=font_astro, anchor="mm")
        draw.text((1025, moon_cy + 11), f"{astro['puesta']} (Bucaramanga)", fill=(241, 245, 249), font=font_astro, anchor="mm")

        # Métricas
        fase_y = moon_cy + 120
        draw.text((640, fase_y), astro["fase"], fill=(251, 191, 36), font=font_phase, anchor="mm")
        txt_ast = f"Iluminación: {astro['iluminacion']}%   •   Edad: {astro['edad']} días   •   Distancia: {astro['distancia']:,} km".replace(",", ".")
        draw.text((640, fase_y + 36), txt_ast, fill=(180, 195, 225), font=font_astro, anchor="mm")

        # Marco de fondo de la barra de progreso
        draw.rounded_rectangle([(180, 550), (1100, 564)], radius=7, fill=(24, 26, 34, 210), outline=(48, 54, 72), width=1)
        min_tot, seg_tot = divmod(int(dur_seg), 60)
        # Triángulo nítido de reproducción y duración total
        draw.polygon([(182, 592), (196, 600), (182, 608)], fill=(255, 255, 255))
        draw.text((945, 600), f"{min_tot:02d}:{seg_tot:02d}", fill=(251, 191, 36), font=font_time, anchor="lm")

        fg_path = os.path.join(temp_dir, "overlay_fg.png")
        fg.save(fg_path)

        # 3. Composición FFmpeg a 1 fps (super ligera y ultra rápida)
        pct_expr = r"(%{{eif\:floor(min(100, 100*t/" + str(dur_seg) + r"))\:d}}\\\%)"
        time_expr = r"%{{eif\:floor(t/60)\:d\:2}}\:%{{eif\:floor(mod(t,60))\:d\:2}}"
        filter_expr = (
            "[0:v]copy[bg]; "
            "[bg][1:v]overlay=0:0[scene]; "
            f"[scene]drawbox=x=180:y=550:w='min(920, 920*t/{dur_seg})':h=14:color=0xF59E0B:t=fill[b1]; "
            f"[b1]drawbox=x='171 + min(920, 920*t/{dur_seg})':y=542:w=18:h=30:color=0xF59E0B@0.4:t=fill[b2]; "
            f"[b2]drawbox=x='175 + min(920, 920*t/{dur_seg})':y=545:w=10:h=24:color=white:t=fill[b3]; "
            f"[b3]drawtext=text='{time_expr}':x=208:y=587:fontcolor=white:fontsize=26[b4]; "
            f"[b4]drawtext=text='{pct_expr}':x=1028:y=587:fontcolor=0xFBBF24:fontsize=26[out]"
        )
        cmd_final = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-r", "1", "-i", loop_video,
            "-loop", "1", "-r", "1", "-i", fg_path,
            "-filter_complex", filter_expr,
            "-map", "[out]",
            "-t", str(int(dur_seg)),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
            ruta_salida
        ]
        subprocess.run(cmd_final, capture_output=True, check=True)
        return ruta_salida
    except Exception as e:
        print("Nota generando video animado de meditación:", e)
        return None


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
        # 1. Fondo cósmico espacial profundo con campo estelar denso y constelación de Orión
        seed_val = int(numero) if numero and str(numero).isdigit() else 1094
        img = crear_universo_con_orion(width, height, frame_idx=0, total_frames=20, seed=seed_val)
        draw = ImageDraw.Draw(img)

        # 2. Marco exterior elegante
        draw.rounded_rectangle([(24, 20), (1256, 700)], radius=22, outline=(245, 158, 11), width=2)
        draw.rounded_rectangle([(34, 30), (1246, 690)], radius=16, outline=(42, 48, 64), width=1)

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
        draw.text((255, salida_t_y), "SALIDA", fill=(251, 191, 36), font=font_astro, anchor="mm")
        draw.text((255, salida_v_y), f"{astro['salida']} (Bucaramanga)", fill=(241, 245, 249), font=font_astro, anchor="mm")

        draw.rounded_rectangle([(910, box_y1), (1140, box_y2)], radius=14, fill=(14, 14, 18), outline=(50, 56, 75), width=1)
        draw.text((1025, salida_t_y), "PUESTA", fill=(148, 163, 184), font=font_astro, anchor="mm")
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

        # Triángulo nítido de reproducción
        draw.polygon([(bar_x1 + 2, 592), (bar_x1 + 16, 600), (bar_x1 + 2, 608)], fill=(255, 255, 255))
        draw.text((bar_x1 + 28, 600), f"{min_prog:02d}:{seg_prog:02d}", fill=(255, 255, 255), font=font_time, anchor="lm")
        txt_tiempo_der = f"{min_dur:02d}:{seg_dur:02d}   ({pct_val}%)"
        draw.text((bar_x2, 600), txt_tiempo_der, fill=(251, 191, 36), font=font_time, anchor="rm")

        img.save(ruta_salida, format="JPEG", quality=95)
        return ruta_salida
    except Exception as e:
        print("Error generando carátula lunar de meditación:", e)
        return None
