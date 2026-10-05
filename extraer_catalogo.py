import re
import json
import os
import pypdf

PDF_PATH = r"E:\DEVELOPER\AI\FACTORY SOFTWARE\TESTING\bot_llamadas_telegram\LISTA DE MENSAJES Y MEDITACIONES.pdf"
OUTPUT_JSON = os.path.join("data", "catalogo_audios.json")


def limpiar_texto(t: str) -> str:
    if not t:
        return ""
    # Reemplazar comillas raras o saltos
    t = t.replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", t)


def extraer_catalogo():
    if not os.path.exists(PDF_PATH):
        print(f"Error: No existe el archivo {PDF_PATH}")
        return

    reader = pypdf.PdfReader(PDF_PATH)
    total_pages = len(reader.pages)
    print(f"Leyendo PDF ({total_pages} páginas)...")

    meditaciones = {}
    mensajes = {}

    current_maestro_med = "Alaniso"

    # ==========================================
    # 1. EXTRAER MEDITACIONES (Páginas 1 a 21)
    # ==========================================
    raw_med_items = []
    current_item = ""

    for p_num in range(1, 22):
        txt = reader.pages[p_num - 1].extract_text() or ""
        for line in txt.split("\n"):
            line = line.strip()
            if not line:
                continue
            if "ANTES Y DESPUES DE LAS MEDITACIONES" in line.upper():
                if current_item:
                    raw_med_items.append(current_item)
                    current_item = ""
                break

            m_start = re.match(r"^(\d+)\s+", line)
            if m_start:
                num = int(m_start.group(1))
                if 1 <= num <= 1113:
                    if current_item:
                        raw_med_items.append(current_item)
                    current_item = line
                    continue

            if current_item:
                current_item += " " + line

    if current_item:
        raw_med_items.append(current_item)

    print(f"Items brutos de meditaciones agrupados: {len(raw_med_items)}")

    for raw in raw_med_items:
        raw = limpiar_texto(raw)
        m = re.match(r"^(\d+)\s+(.+)$", raw)
        if not m:
            continue
        num = int(m.group(1))
        resto = m.group(2).strip()

        # Quitar precio final si existe (e.g. $50.00, $100.00, etc.)
        resto = re.sub(r"\$[\d\.,]+\s*$", "", resto).strip()

        # Extraer maestro al final
        # Maestros conocidos o comodín comillas
        maestro_match = re.search(r'([A-Za-zÁÉÍÓÚáéíóú\s\-,\."]+)$', resto)
        # Buscar fecha: patrones como DD/MM/YY, DD/MM/YYYY, DD MM YYYY, MM/DD/YY, etc.
        # Buscamos la última ocurrencia de fecha en el texto
        fecha_match = None
        for f_cand in re.finditer(r'(\d{1,2}[/\-\s]\d{1,2}[/\-\s]\d{2,4}|\d{1,2}\s+[a-zA-Z]{3,10}\s+\d{2,4})', resto):
            fecha_match = f_cand

        fecha_str = ""
        maestro_str = ""
        titulo_str = resto

        if fecha_match:
            idx_start = fecha_match.start()
            idx_end = fecha_match.end()
            titulo_str = resto[:idx_start].strip()
            fecha_str = fecha_match.group(1).strip()
            maestro_part = resto[idx_end:].strip()
            if maestro_part:
                maestro_str = maestro_part
        
        # Limpiar maestro
        if not maestro_str or maestro_str == '"' or '\"' in maestro_str:
            maestro_str = current_maestro_med
        else:
            # Si el maestro tiene letras válidas, actualizar current_maestro_med
            clean_m = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚ\s\-]', '', maestro_str).strip()
            if clean_m and len(clean_m) >= 3:
                current_maestro_med = clean_m
                maestro_str = clean_m

        titulo_str = titulo_str.rstrip(".").rstrip(",").strip()

        meditaciones[str(num)] = {
            "numero": num,
            "tipo": "MEDITACION",
            "titulo": titulo_str,
            "fecha": fecha_str,
            "maestro": maestro_str or "Alaniso"
        }

    # ==========================================
    # 2. EXTRAER MENSAJES (Páginas 21 a 29)
    # ==========================================
    current_maestro_msg = "Alaniso"
    raw_msg_items = []
    current_msg = ""

    for p_num in range(21, 30):
        txt = reader.pages[p_num - 1].extract_text() or ""
        lines = txt.split("\n")
        in_section = False
        if p_num > 21:
            in_section = True

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if "ANTES Y DESPUES DE LAS MEDITACIONES" in line.upper():
                in_section = True
                continue
            if not in_section:
                continue

            # Buscar patrón de inicio: <numero> Mensaje ...
            m_start = re.match(r"^(\d+)\s+(Mensaje|Menasje)", line, re.IGNORECASE)
            if m_start:
                if current_msg:
                    raw_msg_items.append(current_msg)
                current_msg = line
                continue

            if current_msg:
                current_msg += " " + line

    if current_msg:
        raw_msg_items.append(current_msg)

    print(f"Items brutos de mensajes agrupados: {len(raw_msg_items)}")

    for raw in raw_msg_items:
        raw = limpiar_texto(raw)
        m = re.match(r"^(\d+)\s+(.+)$", raw)
        if not m:
            continue
        num = int(m.group(1))
        resto = m.group(2).strip()

        # Quitar precio final si existe
        resto = re.sub(r"\$[\d\.,]+\s*$", "", resto).strip()

        # Extraer fechas y maestro
        # Ejemplo: Mensaje 15 ene 2016 11/06/23 Alaniso
        # Ejemplo: Mensaje antes, Meditacion , Mensaje despúes 28 nov 2015 10/30/23 Alaniso
        fechas = list(re.finditer(r'(\d{1,2}[/\-\s]\d{1,2}[/\-\s]\d{2,4}|\d{1,2}\s+[a-zA-Z]{3,10}\s+\d{2,4})', resto))
        
        fecha_orig = ""
        fecha_dif = ""
        maestro_str = ""
        
        if len(fechas) >= 2:
            fecha_orig = fechas[0].group(1).strip()
            fecha_dif = fechas[1].group(1).strip()
            maestro_part = resto[fechas[1].end():].strip()
            if maestro_part:
                clean_m = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚ\s\-]', '', maestro_part).strip()
                if clean_m:
                    maestro_str = clean_m
        elif len(fechas) == 1:
            fecha_orig = fechas[0].group(1).strip()
            maestro_part = resto[fechas[0].end():].strip()
            if maestro_part:
                clean_m = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚ\s\-]', '', maestro_part).strip()
                if clean_m:
                    maestro_str = clean_m

        if maestro_str:
            current_maestro_msg = maestro_str
        else:
            maestro_str = current_maestro_msg

        # Si en el texto dice "Mensaje antes, Meditacion , Mensaje despúes", el título es descriptivo
        subtipo = "Antes y Después" if "antes" in resto.lower() and "desp" in resto.lower() else "Mensaje Previo"
        titulo_str = f"Mensaje del {fecha_orig}" if fecha_orig else f"Mensaje #{num}"

        mensajes[str(num)] = {
            "numero": num,
            "tipo": "MENSAJE",
            "subtipo": subtipo,
            "titulo": titulo_str,
            "fecha_original": fecha_orig,
            "fecha_difusion": fecha_dif,
            "maestro": maestro_str or "Alaniso"
        }

    resultado_total = {
        "total_meditaciones": len(meditaciones),
        "total_mensajes": len(mensajes),
        "meditaciones": meditaciones,
        "mensajes": mensajes
    }

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(resultado_total, f, ensure_ascii=False, indent=2)

    print(f"Catálogo generado exitosamente en {OUTPUT_JSON}:")
    print(f"  • Total Meditaciones extraídas: {len(meditaciones)}")
    print(f"  • Total Mensajes extraídos: {len(mensajes)}")


if __name__ == "__main__":
    extraer_catalogo()
