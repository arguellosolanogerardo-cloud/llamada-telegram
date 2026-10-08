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


def identificar_todos_los_audios(texto: str = "", nombre_archivo: str = "") -> list[dict]:
    """
    Identifica uno o varios audios del catálogo mencionados en un texto o nombre de archivo.
    Permite combinaciones como:
    - "Meditación 14 y Mensaje 3"
    - "Meditaciones 5, 6, 7"
    - "/meditacion 14, 15"
    - Mensajes o audios individuales.
    """
    if not texto and not nombre_archivo:
        return []

    texto_combinado = f"{texto or ''} {nombre_archivo or ''}".strip()
    cat = cargar_catalogo()
    meditaciones = cat.get("meditaciones", {})
    mensajes = cat.get("mensajes", {})

    encontrados = []
    vistos = set()

    # 1. Secciones explícitas con palabras clave (MEDITACION, MENSAJE, TAREA) seguidas de números
    patron_secciones = re.finditer(
        r"\b(MENSAJE|MENSAJES|MEDITACI[OÓ]N|MEDITACIONES|TAREA)\s*(?:DE\s*TAREA)?\s*#?\s*(\d+[\d\s,yeE#\-/]*)",
        texto_combinado,
        re.IGNORECASE
    )
    for m in patron_secciones:
        palabra = m.group(1).upper()
        bloque_nums = m.group(2)
        tipo = "MENSAJE" if "MENSAJE" in palabra else "MEDITACION"

        nums = re.findall(r"\b(\d{1,4})\b", bloque_nums)
        for num_str in nums:
            clave = f"{tipo}_{num_str}"
            if clave in vistos:
                continue
            vistos.add(clave)

            if tipo == "MENSAJE":
                if num_str in mensajes:
                    item = dict(mensajes[num_str])
                    item["detectado_como"] = "MENSAJE"
                    encontrados.append(item)
                elif num_str in meditaciones:
                    item_med = meditaciones[num_str]
                    encontrados.append({
                        "numero": int(num_str),
                        "tipo": "MENSAJE",
                        "subtipo": "Mensaje Previo a Meditación",
                        "titulo": f"Mensaje del {item_med.get('fecha', '')} (Asociado a Meditación #{num_str})",
                        "fecha_original": item_med.get("fecha", ""),
                        "fecha": item_med.get("fecha", ""),
                        "maestro": item_med.get("maestro", "Alaniso"),
                        "detectado_como": "MENSAJE"
                    })
            else:
                if num_str in meditaciones:
                    item = dict(meditaciones[num_str])
                    item["detectado_como"] = "MEDITACION"
                    encontrados.append(item)

    # 2. Comandos con lista separada por comas o espacios: '/meditacion 14, 15'
    if not encontrados:
        nums_coma = re.findall(r"\b(\d{1,4})\b", texto_combinado)
        if len(nums_coma) > 1 and any(k in texto_combinado.lower() for k in ["meditacion", "meditación", "mensaje", "cola", "play", ","]):
            for n in nums_coma:
                clave = f"MEDITACION_{n}"
                if clave not in vistos and n in meditaciones:
                    vistos.add(clave)
                    item = dict(meditaciones[n])
                    item["detectado_como"] = "MEDITACION"
                    encontrados.append(item)

    # 3. Fallback: Si no detectó múltiples, usar la función clásica singular
    if not encontrados:
        item_singular = identificar_audio_catalogo(texto, nombre_archivo)
        if item_singular:
            encontrados.append(item_singular)

    return encontrados


def formatear_cola_audios(cola: list[dict], indice_actual: int = 0, reproduciendo: bool = False) -> str:
    """Genera una tarjeta elegante para Telegram mostrando la lista de audios programados."""
    if not cola:
        return "ℹ️ No hay audios en la lista de reproducción programada para hoy."

    total = len(cola)
    lineas = [f"📋 **LISTA DE REPRODUCCIÓN ({total} audio{'s' if total > 1 else ''}):**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    emojis_num = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for idx, item in enumerate(cola):
        info = item.get("info") or {}
        tipo = info.get("tipo", "MEDITACION").upper()
        num = info.get("numero", "")
        titulo = info.get("titulo") or item.get("titulo", "Audio")
        maestro = info.get("maestro", "Alaniso")
        icono_tipo = "🧘" if tipo == "MEDITACION" else "📜"

        pref_num = emojis_num[idx] if idx < len(emojis_num) else f"[{idx+1}]"

        estado_pista = ""
        if reproduciendo:
            if idx == indice_actual:
                estado_pista = " ▶️ *(Reproduciendo ahora)*"
            elif idx < indice_actual:
                estado_pista = " ✅ *(Finalizado)*"
            else:
                estado_pista = " ⏳ *(En espera)*"

        num_txt = f" #{num}" if num else ""
        lineas.append(f"{pref_num} {icono_tipo} **{tipo.capitalize()}{num_txt}:** *«{titulo}»*{estado_pista}\n   🎙️ Maestro: {maestro}")

    return "\n\n".join(lineas)
