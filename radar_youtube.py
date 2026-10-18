import os
import json
import time
import urllib.request
import re
import html
import threading
import sys
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


CANALES_RADAR = [
    {
        "id": "UCms8TOzGiu0Ozj-QmpwstQw",
        "nombre": "ALANISO 2012",
        "handle": "@ALANISO-2012",
        "url": "https://www.youtube.com/@ALANISO-2012/videos"
    },
    {
        "id": "UCjEjDB1gZMGh0QegLjN1o7w",
        "nombre": "Maestro Mario Carrillo",
        "handle": "@mariocarrillo7919",
        "url": "https://www.youtube.com/@mariocarrillo7919/videos"
    }
]

RADAR_DB_PATH = os.path.join("data", "radar_vistos.json")
GITHUB_RAW_VISTOS = "https://raw.githubusercontent.com/arguellosolanogerardo-cloud/llamada-telegram/main/data/radar_vistos.json"

# Candados y conjuntos en memoria para evitar colisiones y publicaciones duplicadas por concurrencia
_RADAR_LOCK = threading.Lock()
_MEMORIA_LOCK = threading.Lock()
_VIDEOS_EN_PROCESO = set()
_VIDEOS_VISTOS_MEMORIA = set()


def cargar_vistos() -> list:
    global _VIDEOS_VISTOS_MEMORIA
    locales = []
    if os.path.exists(RADAR_DB_PATH):
        try:
            with open(RADAR_DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    locales = [str(x) for x in data]
        except Exception as e:
            print("Nota leyendo radar_vistos local:", e)

    remotos = []
    try:
        url_nocache = f"{GITHUB_RAW_VISTOS}?t={int(time.time() // 60)}"
        req = urllib.request.Request(url_nocache, headers={"User-Agent": "BotRadarYouTube"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                remotos = [str(x) for x in data]
    except Exception:
        pass

    combinados = list(locales)
    nuevo_remoto = False
    for x in remotos:
        if x not in combinados:
            combinados.append(x)
            nuevo_remoto = True

    with _MEMORIA_LOCK:
        for x in combinados:
            _VIDEOS_VISTOS_MEMORIA.add(x)
        for x in _VIDEOS_VISTOS_MEMORIA:
            if x not in combinados:
                combinados.append(x)

    if nuevo_remoto and combinados:
        guardar_vistos(combinados)

    return combinados


def guardar_vistos(vistos: list) -> None:
    global _VIDEOS_VISTOS_MEMORIA
    try:
        os.makedirs(os.path.dirname(RADAR_DB_PATH), exist_ok=True)
        unicos = []
        with _MEMORIA_LOCK:
            for x in vistos:
                _VIDEOS_VISTOS_MEMORIA.add(str(x))
            for x in _VIDEOS_VISTOS_MEMORIA:
                if x not in unicos:
                    unicos.append(x)
        with open(RADAR_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(unicos[-150:], f, indent=2)
    except Exception as e:
        print("Nota guardando radar_vistos:", e)


def sincronizar_github_vistos(vistos: list) -> None:
    """Sincroniza la lista de videos vistos directamente con el repositorio de GitHub si hay token configurado."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return
    repo = "arguellosolanogerardo-cloud/llamada-telegram"
    url = f"https://api.github.com/repos/{repo}/contents/data/radar_vistos.json"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "BotRadarYouTube"
    }
    try:
        req_get = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req_get, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sha = data.get("sha")

        import base64
        unicos = []
        for x in vistos:
            if x not in unicos:
                unicos.append(x)
        contenido_str = json.dumps(unicos[-100:], indent=2)
        contenido_b64 = base64.b64encode(contenido_str.encode("utf-8")).decode("utf-8")
        payload = {
            "message": "chore(radar): sincronizar radar_vistos.json [skip ci]",
            "content": contenido_b64,
            "sha": sha
        }
        req_put = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="PUT"
        )
        with urllib.request.urlopen(req_put, timeout=10) as resp:
            if resp.status in (200, 201):
                print("📡 Radar YouTube: Sincronizado automáticamente con GitHub repo.")
    except Exception as e:
        print("Nota sincronizando radar con GitHub:", e)


def obtener_info_oembed(vid: str) -> dict:
    """Obtiene metadatos oficiales del video de YouTube vía oEmbed (título, autor)."""
    if not vid:
        return {}
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read().decode("utf-8", errors="ignore"))
    except Exception:
        pass
    return {}


def obtener_titulo_video(vid: str) -> str:
    """Obtiene el título de un video de YouTube vía oEmbed (muy rápido y ligero) o yt-dlp como fallback."""
    if not vid:
        return ""
    info = obtener_info_oembed(vid)
    tit = info.get("title", "").strip()
    if tit:
        return tit

    # 2. yt-dlp fallback
    try:
        res = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--extractor-args", "youtube:player_client=android,mweb", "--print", "%(title)s", f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True, timeout=12
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    return ""


def obtener_url_miniatura(vid: str) -> str:
    """Retorna la mejor URL de miniatura disponible para el video de YouTube (maxresdefault o hqdefault)."""
    if not vid:
        return ""
    url_max = f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
    try:
        req = urllib.request.Request(url_max, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as r:
            if r.status == 200:
                return url_max
    except Exception:
        pass
    return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"


def anunciar_video_manual(vid: str, bot_enviar_mensaje_func, target_chat, bot_enviar_foto_func=None, forzar: bool = False) -> bool:
    """Publica manualmente el anuncio de un video con su miniatura HD y botones interactivos."""
    if not vid:
        return False

    vistos = cargar_vistos()
    with _MEMORIA_LOCK:
        if not forzar and (vid in vistos or vid in _VIDEOS_VISTOS_MEMORIA or vid in _VIDEOS_EN_PROCESO):
            print(f"📡 Radar YouTube: El video {vid} ya fue anunciado previamente o está en proceso. Omitiendo duplicado.")
            return True
        _VIDEOS_EN_PROCESO.add(vid)

    try:
        info = obtener_info_oembed(vid)
        titulo = info.get("title", "").strip() or obtener_titulo_video(vid) or f"Video {vid}"
        autor = info.get("author_name", "").strip()

        canal_nombre = "ALANISO 2012"
        if any(m in autor.lower() for m in ["mario", "carrillo"]):
            canal_nombre = "Maestro Mario Carrillo"
        elif any(a in autor.lower() for a in ["alaniso"]):
            canal_nombre = "ALANISO 2012"
        elif autor:
            canal_nombre = autor

        url_foto = obtener_url_miniatura(vid)
        ahora_col = datetime.now(ZoneInfo("America/Bogota")).strftime("%d/%m/%Y")

        tit_limpio = str(titulo).replace("_", "\\_").replace("*", "")
        link_limpio = f"https://www.youtube.com/watch?v={vid}".replace("_", "\\_")

        texto_anuncio = (
            f"🔔 **¡NUEVO VIDEO PUBLICADO EN YOUTUBE!** 🐼\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📺 **Canal:** {canal_nombre}\n"
            f"✨ **Título:** «{tit_limpio}»\n"
            f"🗓️ **Publicado:** Recientemente ({ahora_col})\n\n"
            f"🔗 **Ver en YouTube:**\n{link_limpio}"
        )

        btn_tarea_lbl = "📅 Programar Audio Adicional" if ("MARIO" in str(canal_nombre).upper() or "CARRILLO" in str(canal_nombre).upper()) else "📅 Programar como Tarea"
        teclado = {
            "inline_keyboard": [
                [{"text": "🎧 Obtener Audio MP3", "callback_data": f"ytmp3_{vid}"},
                 {"text": btn_tarea_lbl, "callback_data": f"yttarea_{vid}"}],
                [{"text": "📺 Ver en YouTube ↗️", "url": f"https://www.youtube.com/watch?v={vid}"}]
            ]
        }

        enviado = False
        if bot_enviar_foto_func:
            try:
                m_id = bot_enviar_foto_func(target_chat, url_foto, caption=texto_anuncio, reply_markup=teclado)
                if m_id:
                    enviado = True
            except Exception as e_f:
                print(f"⚠️ Error foto en anuncio manual ({vid}): {e_f}")

        if not enviado and bot_enviar_mensaje_func:
            try:
                m_id = bot_enviar_mensaje_func(target_chat, texto_anuncio, reply_markup=teclado)
                if m_id:
                    enviado = True
            except Exception as e_m:
                print(f"⚠️ Error mensaje en anuncio manual ({vid}): {e_m}")

        if enviado:
            with _MEMORIA_LOCK:
                _VIDEOS_VISTOS_MEMORIA.add(vid)
                if vid not in vistos:
                    vistos.append(vid)
            guardar_vistos(vistos)
            threading.Thread(target=sincronizar_github_vistos, args=(vistos,), daemon=True).start()

        return enviado
    finally:
        with _MEMORIA_LOCK:
            _VIDEOS_EN_PROCESO.discard(vid)


def extraer_videos_web(url_canal: str) -> list:
    """Tier 1: Extrae los videos recientes navegando el canal (soporta lockupViewModel y videoRenderer)."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8'
    }
    try:
        req = urllib.request.Request(url_canal, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html_content = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Nota extrayendo web ({url_canal}): {e}")
        return []

    m = re.search(r'var ytInitialData = ({.*?});</script>', html_content)
    if not m:
        m = re.search(r'ytInitialData\s*=\s*({.*?});', html_content)
    if not m:
        return []

    try:
        data = json.loads(m.group(1))
    except Exception:
        return []

    videos = []
    vistos_set = set()

    # 1. lockupViewModel (YouTube 2025/2026)
    def buscar_lockups(obj):
        res = []
        if isinstance(obj, dict):
            if "lockupViewModel" in obj:
                res.append(obj["lockupViewModel"])
            for v in obj.values():
                res.extend(buscar_lockups(v))
        elif isinstance(obj, list):
            for it in obj:
                res.extend(buscar_lockups(it))
        return res

    for lk in buscar_lockups(data):
        vid = lk.get("contentId")
        if not vid or vid in vistos_set:
            continue
        metadata = lk.get("metadata", {}).get("lockupMetadataViewModel", {})
        title = metadata.get("title", {}).get("content", "")
        meta_rows = metadata.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
        pub_txt = ""
        fallback_txt = ""
        for r in meta_rows:
            for p in r.get("metadataParts", []):
                lbl = p.get("accessibilityLabel", "")
                txt = p.get("text", {}).get("content", "")
                candidate = (lbl or txt).strip()
                cand_low = candidate.lower()
                if not candidate:
                    continue
                # Ignorar contadores de vistas/usuarios
                es_vistas = (
                    bool(p.get("leadingIcon"))
                    or any(v_w in cand_low for v_w in ["vista", "view", "visualizaci", "watching", "esperando", "waiting"])
                )
                if any(w in cand_low for w in [
                    "min", "hora", "seg", "día", "dia", "semana", "mes", "año",
                    "day", "hour", "week", "month", "year", "hace", "ago",
                    "momento", "ahora", "now", "estreno", "premiere", "premier",
                    "vivo", "live", "directo", "streamed", "ayer", "yesterday"
                ]) or re.search(r'\b\d+\s*(?:s|sec|seg|m|min|h|hr|hrs|d|w|mo|y|yr)\b', cand_low):
                    pub_txt = candidate
                    break
                if not es_vistas and not fallback_txt:
                    fallback_txt = candidate
            if pub_txt:
                break
        if not pub_txt and fallback_txt:
            pub_txt = fallback_txt
        vistos_set.add(vid)
        videos.append({
            "video_id": vid,
            "titulo": title or "Nuevo video",
            "published_text": pub_txt,
            "published_dt": None,
            "link": f"https://www.youtube.com/watch?v={vid}",
            "source": "web"
        })

    # 2. Fallback a videoRenderer / gridVideoRenderer (legacy)
    if not videos:
        def buscar_video_renderers(obj):
            res = []
            if isinstance(obj, dict):
                if "videoRenderer" in obj:
                    res.append(obj["videoRenderer"])
                elif "gridVideoRenderer" in obj:
                    res.append(obj["gridVideoRenderer"])
                for v in obj.values():
                    res.extend(buscar_video_renderers(v))
            elif isinstance(obj, list):
                for it in obj:
                    res.extend(buscar_video_renderers(it))
            return res

        for vr in buscar_video_renderers(data):
            vid = vr.get("videoId")
            if not vid or vid in vistos_set:
                continue
            tit_obj = vr.get("title", {})
            runs = tit_obj.get("runs", [])
            title = runs[0].get("text", "") if runs else tit_obj.get("simpleText", "")
            pub = vr.get("publishedTimeText", {}).get("simpleText", "")
            vistos_set.add(vid)
            videos.append({
                "video_id": vid,
                "titulo": title or "Nuevo video",
                "published_text": pub,
                "published_dt": None,
                "link": f"https://www.youtube.com/watch?v={vid}",
                "source": "web_legacy"
            })

    return videos


def extraer_videos_ytdlp(url_canal: str) -> list:
    """Tier 2: Extrae los últimos videos del canal mediante yt-dlp."""
    try:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--extractor-args", "youtube:player_client=android,mweb",
            "--flat-playlist", "--print", "%(id)s|||%(title)s",
            "--playlist-end", "10",
            url_canal
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if res.returncode != 0 or not res.stdout.strip():
            return []
        videos = []
        for line in res.stdout.strip().split("\n"):
            line = line.strip()
            if not line or "|||" not in line:
                continue
            parts = line.split("|||", 1)
            vid = parts[0].strip()
            titulo = parts[1].strip()
            if vid:
                videos.append({
                    "video_id": vid,
                    "titulo": titulo or "Nuevo video",
                    "published_text": "Recientemente",
                    "published_dt": None,
                    "link": f"https://www.youtube.com/watch?v={vid}",
                    "source": "ytdlp"
                })
        return videos
    except Exception as e:
        print(f"Nota extrayendo yt-dlp ({url_canal}): {e}")
        return []


def extraer_entradas_xml(xml_texto: str) -> list:
    """Tier 3: Extrae entradas del feed RSS XML de YouTube."""
    entradas = []
    for entry in re.findall(r'<entry>(.*?)</entry>', xml_texto, re.DOTALL):
        vid_m = re.search(r'<yt:videoId>(.*?)</yt:videoId>', entry)
        title_m = re.search(r'<title>(.*?)</title>', entry)
        link_m = re.search(r'<link rel="alternate" href="(.*?)"/>', entry)
        pub_m = re.search(r'<published>(.*?)</published>', entry)
        if vid_m and title_m:
            vid = vid_m.group(1).strip()
            link = link_m.group(1).strip() if link_m else f"https://www.youtube.com/watch?v={vid}"
            pub_str = pub_m.group(1).strip() if pub_m else ""
            dt_pub = None
            if pub_str:
                try:
                    dt_pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    pass
            entradas.append({
                "video_id": vid,
                "titulo": html.unescape(title_m.group(1).strip()),
                "link": link,
                "published_str": pub_str,
                "published_dt": dt_pub,
                "published_text": "",
                "source": "xml"
            })
    return entradas


def es_programado_futuro(pub_txt: str) -> bool:
    """Detecta si el video es un estreno futuro programado que aún no ha salido."""
    if not pub_txt:
        return False
    txt = pub_txt.lower().strip()
    return any(w in txt for w in ["próximamente", "proximamente", "upcoming", "programado", "scheduled", "se estrena", "premieres"])


def es_antiguo_explicito(pub_txt: str) -> bool:
    """Evalúa si el texto de tiempo indica explícitamente que el video tiene más de 2 horas (días, semanas, meses, años o > 2h)."""
    if not pub_txt:
        return False
    txt = pub_txt.lower().strip()
    palabras_antiguas = [
        "día", "días", "dia", "dias", "day", "days",
        "semana", "semanas", "week", "weeks",
        "mes", "meses", "month", "months",
        "año", "años", "year", "years",
        "ayer", "yesterday"
    ]
    if any(w in txt for w in palabras_antiguas):
        return True
    if re.search(r'\b\d+\s*(?:d|w|mo|y|yr)\b', txt):
        return True
    m_horas = re.search(r'(?:hace\s*|streamed\s*)?(\d+)\s*(?:hora|horas|hour|hours|h|hr|hrs)\b', txt)
    if m_horas:
        return int(m_horas.group(1)) > 2
    return False


def evaluar_recencia_texto(pub_txt: str) -> bool:
    """Evalúa de forma robusta si un texto relativo de tiempo (en español o inglés)
    corresponde a una publicación reciente (dentro de las últimas 2 horas)."""
    if not pub_txt:
        return False
    txt = pub_txt.lower().strip()
    if es_programado_futuro(txt) or es_antiguo_explicito(txt):
        return False

    # Publicaciones inmediatas, minutos o transmisiones en directo
    inmediatos = [
        "seg", "sec", "min", "ahora", "now", "vivo", "live", "directo",
        "estreno", "premier", "premiere", "momento", "momentos", "reciente"
    ]
    if any(w in txt for w in inmediatos) or re.search(r'\b\d+\s*(?:s|sec|seg|m|min)\b', txt):
        return True

    # Horas: "hace 1 hora", "hace 2 horas", "hace 1 h", "1 hour ago", "1h ago", "streamed 1 hr ago"
    m_horas = re.search(r'(?:hace\s*|streamed\s*)?(\d+)\s*(?:hora|horas|hour|hours|h|hr|hrs)\b', txt)
    if m_horas:
        horas = int(m_horas.group(1))
        return horas <= 2

    return False


def extraer_videos_canal(canal: dict) -> list:
    """Estrategia Multi-Tier preservando estrictamente el orden cronológico (idx 0 = más reciente):
       Tier 1: Web scraping de ytInitialData (lockupViewModel / videoRenderer) en orden natural
       Tier 2: XML RSS Feed (para enriquecer published_dt si responde)
       Tier 3: yt-dlp como fallback final
    """
    videos = []
    por_id = {}

    # Tier 1: Web Scraping directo (Mantiene orden exacto: índice 0 = video más nuevo)
    url_canal = canal.get("url") or f"https://www.youtube.com/{canal.get('handle', '')}/videos"
    try:
        web_vids = extraer_videos_web(url_canal)
        for v in web_vids:
            vid = v["video_id"]
            if vid not in por_id:
                por_id[vid] = v
                videos.append(v)
    except Exception as e_web:
        print(f"Nota extrayendo web ({canal.get('nombre')}): {e_web}")

    # Tier 2: XML RSS Feed (enriquece timestamps exactos o agrega si web falló)
    if canal.get("id"):
        try:
            url_rss = f"https://www.youtube.com/feeds/videos.xml?channel_id={canal['id']}"
            req = urllib.request.Request(url_rss, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                xml_texto = resp.read().decode('utf-8', errors='ignore')
                if xml_texto:
                    for v in extraer_entradas_xml(xml_texto):
                        vid = v["video_id"]
                        if vid in por_id:
                            por_id[vid]["published_dt"] = v.get("published_dt")
                            por_id[vid]["published_str"] = v.get("published_str")
                        else:
                            por_id[vid] = v
                            videos.append(v)
        except Exception:
            pass

    # Tier 3: yt-dlp si ambos fallaron
    if not videos:
        videos = extraer_videos_ytdlp(url_canal)

    return videos


def chequear_canales(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func=None, es_arranque: bool = False) -> int:
    """Revisa los canales de YouTube y anuncia nuevos videos. Retorna cantidad de videos anunciados."""
    if not _RADAR_LOCK.acquire(blocking=False):
        print("📡 Radar YouTube: Chequeo de canales ya en curso por otro hilo/petición. Omitiendo ejecución concurrente.")
        return 0

    try:
        vistos = cargar_vistos()
        es_primera_vez = len(vistos) == 0
        nuevos_vistos = list(vistos)
        ahora_utc = datetime.now(timezone.utc)
        target_chat = chat_id_grupo or os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP") or -1002963691819
        anunciados = 0

        for canal in CANALES_RADAR:
            anunciados_canal = 0
            try:
                entradas = extraer_videos_canal(canal)
                for idx, datos in enumerate(entradas):
                    vid = datos["video_id"]
                    dt_pub = datos.get("published_dt")
                    pub_txt = (datos.get("published_text") or "").lower()
                    source = datos.get("source", "")

                    with _MEMORIA_LOCK:
                        if vid in vistos or vid in nuevos_vistos or vid in _VIDEOS_VISTOS_MEMORIA or vid in _VIDEOS_EN_PROCESO:
                            continue

                    # Si es la primera vez absoluta que se inicializa la BD (0 videos registrados),
                    # registrar existentes en silencio para no spamear todo el histórico
                    if es_primera_vez:
                        with _MEMORIA_LOCK:
                            _VIDEOS_VISTOS_MEMORIA.add(vid)
                        nuevos_vistos.append(vid)
                        continue

                    # Si ya se anunció un video de este canal en este ciclo, registrar el resto en silencio
                    # para evitar ráfagas o spam por subidas por lotes o archivos históricos
                    if anunciados_canal >= 1:
                        with _MEMORIA_LOCK:
                            _VIDEOS_VISTOS_MEMORIA.add(vid)
                        nuevos_vistos.append(vid)
                        continue

                    # Si es un estreno programado a futuro que aún no ha iniciado, esperar sin marcar como visto
                    if es_programado_futuro(pub_txt):
                        continue

                    # Criterio robusto de novedad:
                    # En operación normal: máximo 2 horas (7200s).
                    # En arranque (deploy/reinicio Render): máximo 30 minutos (1800s) para no anunciar backlog acumulado.
                    limite_seg = 1800 if es_arranque else 7200
                    es_reciente = False
                    if dt_pub:
                        segundos = (ahora_utc - dt_pub).total_seconds()
                        if segundos < 0:
                            continue
                        es_reciente = 0 <= segundos < limite_seg
                        if not es_reciente:
                            with _MEMORIA_LOCK:
                                _VIDEOS_VISTOS_MEMORIA.add(vid)
                            nuevos_vistos.append(vid)
                            continue
                    elif es_antiguo_explicito(pub_txt):
                        # El video dice explícitamente días, semanas, meses, años o > 2h -> marcar visto sin anunciar
                        with _MEMORIA_LOCK:
                            _VIDEOS_VISTOS_MEMORIA.add(vid)
                        nuevos_vistos.append(vid)
                        continue
                    elif es_arranque and re.search(r'(?:hace\s*|streamed\s*)?\d+\s*(?:hora|horas|hour|hours|h|hr|hrs)\b', pub_txt):
                        # En arranque del bot, si el texto dice horas, es backlog previo -> registrar en silencio
                        with _MEMORIA_LOCK:
                            _VIDEOS_VISTOS_MEMORIA.add(vid)
                        nuevos_vistos.append(vid)
                        continue
                    elif evaluar_recencia_texto(pub_txt):
                        es_reciente = True
                    elif idx < 3:
                        if es_arranque:
                            # En arranque sin fecha comprobable, no arriesgar spam -> registrar en silencio
                            with _MEMORIA_LOCK:
                                _VIDEOS_VISTOS_MEMORIA.add(vid)
                            nuevos_vistos.append(vid)
                            continue
                        # Está en el Top 3 más reciente del canal, no está en vistos y NO es antiguo -> ¡Es nuevo!
                        es_reciente = True
                    else:
                        # Posición >= 3 sin texto de tiempo claro: no anunciar, pero no envenenar vistos si es ambiguo
                        continue

                    # Reservar el video en proceso para evitar duplicados si otra llamada llega
                    with _MEMORIA_LOCK:
                        if vid in _VIDEOS_VISTOS_MEMORIA or vid in _VIDEOS_EN_PROCESO:
                            continue
                        _VIDEOS_EN_PROCESO.add(vid)

                    try:
                        # Formatear fecha para Colombia
                        fecha_txt = ""
                        if dt_pub:
                            try:
                                dt_col = dt_pub.astimezone(ZoneInfo("America/Bogota"))
                                fecha_txt = dt_col.strftime("%d/%m/%Y a las %I:%M %p")
                            except Exception:
                                fecha_txt = dt_pub.strftime("%d/%m/%Y")
                        elif datos.get("published_text"):
                            fecha_txt = datos["published_text"].capitalize()
                        else:
                            fecha_txt = "Hace unos momentos"

                        tit_limpio = str(datos['titulo']).replace("_", "\\_").replace("*", "")
                        link_limpio = str(datos['link']).replace("_", "\\_")

                        texto_anuncio = (
                            f"🔔 **¡NUEVO VIDEO PUBLICADO EN YOUTUBE!** 🐼\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"📺 **Canal:** {canal['nombre']}\n"
                            f"✨ **Título:** «{tit_limpio}»\n"
                            f"🗓️ **Publicado:** {fecha_txt}\n\n"
                            f"🔗 **Ver en YouTube:**\n{link_limpio}"
                        )

                        btn_tarea_lbl = "📅 Programar Audio Adicional" if ("MARIO" in str(canal['nombre']).upper() or "CARRILLO" in str(canal['nombre']).upper()) else "📅 Programar como Tarea"
                        teclado = {
                            "inline_keyboard": [
                                [{"text": "🎧 Obtener Audio MP3", "callback_data": f"ytmp3_{vid}"},
                                 {"text": btn_tarea_lbl, "callback_data": f"yttarea_{vid}"}],
                                [{"text": "📺 Ver en YouTube ↗️", "url": f"https://www.youtube.com/watch?v={vid}"}]
                            ]
                        }

                        url_foto = obtener_url_miniatura(vid)
                        enviado = False

                        print(f"📡 Radar YouTube: Anunciando nuevo video de {canal['nombre']} ({vid}): «{datos['titulo']}»")

                        # 1. Enviar con Foto de alta resolución (100% garantizado que muestra la miniatura HD)
                        if bot_enviar_foto_func:
                            try:
                                m_id = bot_enviar_foto_func(target_chat, url_foto, caption=texto_anuncio, reply_markup=teclado)
                                if m_id:
                                    enviado = True
                                    anunciados += 1
                            except Exception as e_foto:
                                print(f"⚠️ Error enviando anuncio con foto ({vid}): {e_foto}")

                        # 2. Si falló la foto o no se configuró, fallback a enviar_mensaje con vista previa solicitada
                        if not enviado and bot_enviar_mensaje_func:
                            try:
                                m_id_msg = bot_enviar_mensaje_func(target_chat, texto_anuncio, reply_markup=teclado)
                                if m_id_msg:
                                    enviado = True
                                    anunciados += 1
                            except Exception as e_send:
                                print(f"⚠️ Error enviando anuncio de radar ({vid}): {e_send}")

                        # SOLO marcar como visto si fue efectivamente enviado a Telegram
                        if enviado:
                            anunciados_canal += 1
                            with _MEMORIA_LOCK:
                                _VIDEOS_VISTOS_MEMORIA.add(vid)
                            nuevos_vistos.append(vid)
                            # Guardar inmediatamente en disco para que ningún otro proceso lo duplique
                            guardar_vistos(nuevos_vistos)
                            threading.Thread(target=sincronizar_github_vistos, args=(nuevos_vistos,), daemon=True).start()

                        # Pausa de 3 segundos entre anuncios para evitar rate-limits de Telegram
                        time.sleep(3)
                    finally:
                        with _MEMORIA_LOCK:
                            _VIDEOS_EN_PROCESO.discard(vid)

            except Exception as e:
                print(f"⚠️ Error revisando radar {canal['nombre']}: {e}")

        if len(nuevos_vistos) > len(vistos):
            guardar_vistos(nuevos_vistos)
            if anunciados > 0:
                threading.Thread(target=sincronizar_github_vistos, args=(nuevos_vistos,), daemon=True).start()

        return anunciados
    finally:
        _RADAR_LOCK.release()


def radar_loop(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func=None):
    # En arranque: chequear canales (anunciará videos genuinamente nuevos y recientes <6h que no estuvieran en vistos)
    try:
        cant_init = chequear_canales(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func=bot_enviar_foto_func, es_arranque=True)
        print(f"📡 Radar YouTube: Chequeo inicial de arranque completado ({cant_init} nuevos anunciados).")
    except Exception as e:
        print(f"⚠️ Error en primera revisión del radar: {e}")

    while True:
        try:
            time.sleep(60)  # Cada 60 segundos (1 minuto) para detección casi instantánea
            chequear_canales(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func=bot_enviar_foto_func, es_arranque=False)
        except Exception as e:
            print(f"⚠️ Error en loop radar YouTube: {e}")
            time.sleep(30)


def iniciar_radar(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func=None):
    t = threading.Thread(target=radar_loop, args=(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func), daemon=True)
    t.start()
    print("📡 Radar de YouTube iniciado en segundo plano (ALANISO 2012 y Mario Carrillo, sondeo cada 90s con miniaturas HD).")
