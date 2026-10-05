import json
import os
import re

RUTA_CATALOGO_JSON = os.path.join("data", "catalogo_audios.json")
_CATALOGO_CACHE = None


def cargar_catalogo() -> dict:
    global _CATALOGO_CACHE
    if _CATALOGO_CACHE is not None:
        return _CATALOGO_CACHE

    if os.path.exists(RUTA_CATALOGO_JSON):
        try:
            with open(RUTA_CATALOGO_JSON, "r", encoding="utf-8") as f:
                _CATALOGO_CACHE = json.load(f)
                return _CATALOGO_CACHE
        except Exception as e:
            print("Nota cargando catalogo_audios.json:", e)

    return {"meditaciones": {}, "mensajes": {}}


def obtener_meditacion_por_numero(numero: int | str) -> dict | None:
    cat = cargar_catalogo()
    return cat.get("meditaciones", {}).get(str(numero))


def obtener_mensaje_por_numero(numero: int | str) -> dict | None:
    cat = cargar_catalogo()
    return cat.get("mensajes", {}).get(str(numero))


def identificar_audio_catalogo(texto: str = "", nombre_archivo: str = "") -> dict | None:
    """Identifica automáticamente si un texto o nombre de archivo corresponde

    a una Meditación o Mensaje del catálogo histórico, extrayendo título,
    fecha original y Maestro.
    """
    texto_combinado = f"{texto or ''} {nombre_archivo or ''}".strip()
    if not texto_combinado:
        return None

    cat = cargar_catalogo()
    meditaciones = cat.get("meditaciones", {})
    mensajes = cat.get("mensajes", {})

    # 1. Detectar si dice explícitamente "MENSAJE" con número
    m_msg = re.search(r"\bMENSAJE\s*#?\s*(\d+)\b", texto_combinado, re.IGNORECASE)
    if m_msg:
        num_str = m_msg.group(1)
        if num_str in mensajes:
            item = dict(mensajes[num_str])
            item["detectado_como"] = "MENSAJE"
            return item
        elif num_str in meditaciones:
            # Si el mensaje se grabó el mismo día que esa meditación
            item_med = meditaciones[num_str]
            return {
                "numero": int(num_str),
                "tipo": "MENSAJE",
                "subtipo": "Mensaje Previo a Meditación",
                "titulo": f"Mensaje del {item_med.get('fecha', '')} (Asociado a Meditación #{num_str})",
                "fecha_original": item_med.get("fecha", ""),
                "fecha": item_med.get("fecha", ""),
                "maestro": item_med.get("maestro", "Alaniso"),
                "detectado_como": "MENSAJE"
            }

    # 2. Detectar si dice explícitamente "MEDITACION" o "TAREA" con número
    m_med = re.search(r"\b(?:MEDITACI[OÓ]N|TAREA)\s*(?:DE\s*TAREA)?\s*#?\s*(\d+)\b", texto_combinado, re.IGNORECASE)
    if m_med:
        num_str = m_med.group(1)
        if num_str in meditaciones:
            item = dict(meditaciones[num_str])
            item["detectado_como"] = "MEDITACION"
            return item

    # 3. Detectar si el nombre del archivo empieza o contiene un número (ej: 14.mp3, med_14.mp3)
    m_file = re.search(r"(?:^|[_\-\s])(\d{1,4})(?:[_\-\s]|\.mp3|\.wav|\.m4a|\.ogg)", nombre_archivo, re.IGNORECASE)
    if m_file:
        num_str = m_file.group(1)
        if "mensaje" in nombre_archivo.lower() and num_str in mensajes:
            item = dict(mensajes[num_str])
            item["detectado_como"] = "MENSAJE"
            return item
        if num_str in meditaciones:
            item = dict(meditaciones[num_str])
            item["detectado_como"] = "MEDITACION"
            return item

    # 4. Búsqueda por número aislado en el texto si se menciona tarea o meditación
    if any(k in texto_combinado.upper() for k in ["MEDITACION", "MEDITACIÓN", "TAREA"]):
        m_num = re.search(r"\b(\d{1,4})\b", texto_combinado)
        if m_num:
            num_str = m_num.group(1)
            if num_str in meditaciones:
                item = dict(meditaciones[num_str])
                item["detectado_como"] = "MEDITACION"
                return item

    # 5. Búsqueda por número puro directo (ej: "20" o "#20")
    texto_limpio = re.sub(r"[#\s]", "", texto.strip())
    if texto_limpio.isdigit():
        if texto_limpio in meditaciones:
            item = dict(meditaciones[texto_limpio])
            item["detectado_como"] = "MEDITACION"
            return item
        elif texto_limpio in mensajes:
            item = dict(mensajes[texto_limpio])
            item["detectado_como"] = "MENSAJE"
            return item

    return None


def formatear_info_audio(info: dict) -> str:
    """Formatea la información del catálogo para ser enviada en anuncios de Telegram."""
    if not info:
        return ""

    tipo = info.get("tipo", "MEDITACION").upper()
    num = info.get("numero", "")
    titulo = info.get("titulo", "")
    fecha = info.get("fecha_original") or info.get("fecha", "")
    maestro = info.get("maestro", "Alaniso")

    if tipo == "MEDITACION":
        lineas = [
            f"🧘✨ **MEDITACIÓN #{num}:** *«{titulo}»*",
            f"🎙️ **Maestro:** {maestro} | 📅 **Grabación original:** {fecha}",
        ]
    else:
        lineas = [
            f"📜✨ **MENSAJE #{num}:** *«{titulo}»*",
            f"🎙️ **Maestro:** {maestro} | 📅 **Grabación original:** {fecha}",
            "ℹ️ *Mensaje transmitido antes de la meditación.*",
        ]

    return "\n".join(lineas)
