import os
import re
import json
import urllib.request

RUTA_CACHE_DRIVE = os.path.join("data", "meditaciones", "cache_drive.json")
CARPETA_MEDITACIONES = os.path.join("data", "meditaciones")

SERIES_MENSAJES = {
    600: "16rPoq1rwOueNZ5LXkT1pz0h2WB7GEIZG",
    700: "1b8-u2ymkq00N4RWZMm26O9eTYpfEMAuv",
    800: "1pbGRgig2oUIXBcSehah3hWf_BKz-NkBG",
    900: "1MlFCjEOYYnI1zn4R52I1-Z2_b5t_LNT7",
    1000: "1oH5HFW0v9AuKeDbcUilLy75YMn_MI1Pg",
    1100: "1xm3ajR9_jhzBQGkJyv0Qgkf9ItowgBRx",
}

SERIES_MEDITACIONES = {
    1: "1ZpsxN0KHYOnDELBMmin9a_y69rOm7hBj",  # 1-99
    100: "11b2EY2Lo-GQyYvqkNCw1GcUuh6x1L61F",
    200: "1cYL5K4-zm14Wk2mQ7VAZeU9lUXfcBkY1",
    300: "1HleGnc9YsLW7KuMa0gSYMQIMi6bqJuX7",
    400: "17R62yQdRLXYXBz8YtHA7R5eyYiEBUKv0",
    500: "1jCqRg-rvF6jqJqDsdxFXZgVW5EffHaMx",
    600: "15BZpe4bbyYxsjxRXh_rrw35bwB9BbQrC",
    700: "1VNEeIgNP7JcXLeSjHF_FpqHGGZYuuZOI",
    800: "1wiYfYB5lrGEgTylsxfLr2orUpYCf8dxT",
    900: "1GvcSWOaH5H9n3edbfbORoSyiOkWCPpBe",
    1000: "1IxObmFk8EJJgHxVIG5a-Euv6yT7nC9SF",
}


def cargar_cache_drive() -> dict:
    if os.path.exists(RUTA_CACHE_DRIVE):
        try:
            with open(RUTA_CACHE_DRIVE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def guardar_en_cache_drive(clave: str, drive_id: str, nombre_archivo: str) -> None:
    try:
        os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
        cache = cargar_cache_drive()
        cache[clave] = {
            "drive_id": drive_id,
            "nombre_archivo": nombre_archivo
        }
        with open(RUTA_CACHE_DRIVE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Nota guardando cache drive:", e)


def buscar_audio_en_drive(tipo: str, numero: int) -> tuple[str | None, str | None]:
    """
    Busca el ID de archivo y nombre en Google Drive para una meditación o mensaje.
    Retorna (drive_file_id, nombre_archivo) o (None, None).
    """
    t = tipo.upper()
    clave_cache = f"{t}_{numero}"
    cache = cargar_cache_drive()
    if clave_cache in cache:
        item = cache[clave_cache]
        return item.get("drive_id"), item.get("nombre_archivo")

    sub_id = None
    if "MENSAJE" in t:
        base = (numero // 100) * 100
        sub_id = SERIES_MENSAJES.get(base)
    else:
        if 1 <= numero <= 99:
            sub_id = SERIES_MEDITACIONES.get(1)
        else:
            base = (numero // 100) * 100
            sub_id = SERIES_MEDITACIONES.get(base)

    if not sub_id:
        return None, None

    try:
        # 1. Probar primero con embeddedfolderview (obtiene todos los archivos sin límite de 50)
        url_embed = f"https://drive.google.com/embeddedfolderview?id={sub_id}#list"
        req = urllib.request.Request(url_embed, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", errors="ignore")

        items_embed = re.findall(r'id="entry-([a-zA-Z0-9_-]+?)".*?flip-entry-title[^>]*>([^<]+?)<', html, re.DOTALL)
        matches = [(nombre.strip(), f_id) for f_id, nombre in items_embed]

        # 2. Si no arrojó resultados, fallback a la URL estándar de carpeta
        if not matches:
            url = f"https://drive.google.com/drive/folders/{sub_id}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=12) as r:
                html = r.read().decode("utf-8", errors="ignore")
            pattern = r'aria-label="([^"]+?\.(?:mp3|m4a|wav|ogg))[^\"]*"\s+data-handled-by-drag-and-drop="true"\s+ssk=[\'"]5:auSv138:([a-zA-Z0-9_-]+?)(?:-\d+-\d+)?[\'"]'
            matches = re.findall(pattern, html, re.IGNORECASE)

        # Reglas de coincidencia para el número solicitado
        s_num = str(numero)
        posibles = [
            rf"(?:^|[^\d]){s_num}(?:[^\d]|$)",
            rf"(?:^|[^\d])0{s_num}(?:[^\d]|$)",
            rf"(?:^|[^\d])00{s_num}(?:[^\d]|$)",
        ]

        for nombre, f_id in matches:
            for p in posibles:
                if re.search(p, nombre):
                    guardar_en_cache_drive(clave_cache, f_id, nombre.strip())
                    return f_id, nombre.strip()

    except Exception as e:
        print(f"Error consultando subcarpeta de Drive para {tipo} #{numero}:", e)

    return None, None


def descargar_audio_de_drive(file_id: str, ruta_destino: str) -> bool:
    """
    Descarga directamente el archivo .mp3 desde Google Drive sin requerir credenciales.
    """
    if not file_id:
        return False
    try:
        os.makedirs(os.path.dirname(os.path.abspath(ruta_destino)), exist_ok=True)
        url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=45) as r:
            with open(ruta_destino, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)

        if os.path.exists(ruta_destino) and os.path.getsize(ruta_destino) > 5000:
            print(f"Audio descargado con éxito desde Drive: {ruta_destino} ({os.path.getsize(ruta_destino)} bytes)")
            return True
        else:
            if os.path.exists(ruta_destino):
                os.remove(ruta_destino)
            return False
    except Exception as e:
        print(f"Error descargando audio de Drive ({file_id}):", e)
        if os.path.exists(ruta_destino):
            try:
                os.remove(ruta_destino)
            except Exception:
                pass
        return False


def obtener_o_descargar_audio(tipo: str, numero: int) -> str | None:
    """
    Verifica si el audio ya existe localmente. Si no, lo busca en Drive y lo descarga.
    Retorna la ruta local del archivo o None si no se pudo obtener.
    """
    t_slug = "mensaje" if "MENSAJE" in tipo.upper() else "meditacion"
    nombre_local = f"{t_slug}_{numero}.mp3"
    ruta_local = os.path.join(CARPETA_MEDITACIONES, nombre_local)

    # Si ya existe en disco y tiene contenido
    if os.path.exists(ruta_local) and os.path.getsize(ruta_local) > 5000:
        return ruta_local

    # Si no, buscar en Drive
    drive_id, nombre_drive = buscar_audio_en_drive(tipo, numero)
    if drive_id:
        ok = descargar_audio_de_drive(drive_id, ruta_local)
        if ok:
            return ruta_local

    return None
