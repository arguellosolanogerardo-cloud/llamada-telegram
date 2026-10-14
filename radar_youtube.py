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


def cargar_vistos() -> list:
    if os.path.exists(RADAR_DB_PATH):
        try:
            with open(RADAR_DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(x) for x in data]
        except Exception as e:
            print("Nota leyendo radar_vistos:", e)
    return []


def guardar_vistos(vistos: list) -> None:
    try:
        os.makedirs(os.path.dirname(RADAR_DB_PATH), exist_ok=True)
        unicos = []
        for x in vistos:
            if x not in unicos:
                unicos.append(x)
        with open(RADAR_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(unicos[-100:], f, indent=2)
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


def obtener_titulo_video(vid: str) -> str:
    """Obtiene el título de un video de YouTube vía oEmbed (muy rápido y ligero) o yt-dlp como fallback."""
    if not vid:
        return ""
    # 1. oEmbed oficial de YouTube (rápido, sin dependencias)
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
            tit = data.get("title", "").strip()
            if tit:
                return tit
    except Exception:
        pass

    # 2. yt-dlp fallback
    try:
        res = subprocess.run(
            ["yt-dlp", "--print", "%(title)s", f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True, timeout=10
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


def anunciar_video_manual(vid: str, bot_enviar_mensaje_func, target_chat, bot_enviar_foto_func=None) -> bool:
    """Publica manualmente el anuncio de un video con su miniatura HD y botones interactivos."""
    if not vid:
        return False
    titulo = obtener_titulo_video(vid) or f"Video {vid}"
    url_foto = obtener_url_miniatura(vid)
    ahora_col = datetime.now(ZoneInfo("America/Bogota")).strftime("%d/%m/%Y")

    texto_anuncio = (
        f"🔔 **¡NUEVO VIDEO PUBLICADO EN YOUTUBE!** 🐼\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📺 **Canal:** ALANISO 2012\n"
        f"✨ **Título:** «{titulo}»\n"
        f"🗓️ **Publicado:** Recientemente ({ahora_col})\n\n"
        f"🔗 **Ver en YouTube:**\nhttps://www.youtube.com/watch?v={vid}"
    )

    teclado = {
        "inline_keyboard": [
            [{"text": "🎧 Obtener Audio MP3", "callback_data": f"ytmp3_{vid}"},
             {"text": "📅 Programar como Tarea", "callback_data": f"yttarea_{vid}"}],
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

    return enviado


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
        for r in meta_rows:
            for p in r.get("metadataParts", []):
                lbl = p.get("accessibilityLabel", "")
                txt = p.get("text", {}).get("content", "")
                candidate = lbl or txt
                if any(w in candidate.lower() for w in ["min", "hora", "seg", "día", "dia", "semana", "mes", "año", "day", "hour", "week", "month", "year"]):
                    pub_txt = candidate
                    break
            if pub_txt:
                break
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
        cmd = ["yt-dlp", "--flat-playlist", "--print", "%(id)s|||%(title)s", "--playlist-end", "10", url_canal]
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


def extraer_videos_canal(canal: dict) -> list:
    """Aplica la estrategia Multi-Tier para obtener videos del canal:
       Tier 1: Web scraping de ytInitialData (lockupViewModel)
       Tier 2: yt-dlp
       Tier 3: XML RSS Feed de YouTube
    """
    url_canal = canal.get("url") or f"https://www.youtube.com/{canal.get('handle', '')}/videos"

    # Tier 1: Web scraping
    videos = extraer_videos_web(url_canal)
    if videos:
        return videos

    # Tier 2: yt-dlp
    videos = extraer_videos_ytdlp(url_canal)
    if videos:
        return videos

    # Tier 3: XML RSS Feed
    try:
        url_rss = f"https://www.youtube.com/feeds/videos.xml?channel_id={canal['id']}"
        req = urllib.request.Request(url_rss, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            xml_texto = resp.read().decode('utf-8', errors='ignore')
            if xml_texto:
                return extraer_entradas_xml(xml_texto)
    except Exception:
        pass

    return []


def chequear_canales(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func=None) -> int:
    """Revisa los canales de YouTube y anuncia nuevos videos. Retorna cantidad de videos anunciados."""
    vistos = cargar_vistos()
    es_primera_vez = len(vistos) == 0
    nuevos_vistos = list(vistos)
    ahora_utc = datetime.now(timezone.utc)
    target_chat = chat_id_grupo or os.environ.get("CHAT_ID") or os.environ.get("TG_GROUP") or -1002963691819
    anunciados = 0

    for canal in CANALES_RADAR:
        try:
            entradas = extraer_videos_canal(canal)
            for idx, datos in enumerate(entradas):
                vid = datos["video_id"]
                dt_pub = datos.get("published_dt")
                pub_txt = (datos.get("published_text") or "").lower()
                source = datos.get("source", "")

                if vid in vistos or vid in nuevos_vistos:
                    continue

                # Si es la primera vez que se inicializa la BD, registrar existentes sin anunciar
                if es_primera_vez:
                    nuevos_vistos.append(vid)
                    continue

                # Criterio robusto de novedad
                es_reciente = False
                if dt_pub:
                    segundos = (ahora_utc - dt_pub).total_seconds()
                    es_reciente = segundos < 86400  # Últimas 24 horas
                elif pub_txt:
                    palabras_recientes = ["min", "hora", "seg", "ahora", "vivo", "live", "hour", "sec", "now", "estreno", "premier"]
                    es_reciente = any(w in pub_txt for w in palabras_recientes)
                elif source == "ytdlp":
                    # Si viene de yt-dlp y es de los 2 primeros del canal
                    es_reciente = idx < 2

                # Si no es reciente (ej: video publicado hace días/meses), marcar como visto sin notificar
                if not es_reciente:
                    nuevos_vistos.append(vid)
                    continue

                # Marcar como visto
                nuevos_vistos.append(vid)

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

                texto_anuncio = (
                    f"🔔 **¡NUEVO VIDEO PUBLICADO EN YOUTUBE!** 🐼\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📺 **Canal:** {canal['nombre']}\n"
                    f"✨ **Título:** «{datos['titulo']}»\n"
                    f"🗓️ **Publicado:** {fecha_txt}\n\n"
                    f"🔗 **Ver en YouTube:**\n{datos['link']}"
                )

                teclado = {
                    "inline_keyboard": [
                        [{"text": "🎧 Obtener Audio MP3", "callback_data": f"ytmp3_{vid}"},
                         {"text": "📅 Programar como Tarea", "callback_data": f"yttarea_{vid}"}],
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
                        bot_enviar_mensaje_func(target_chat, texto_anuncio, reply_markup=teclado)
                        anunciados += 1
                    except Exception as e_send:
                        print(f"⚠️ Error enviando anuncio de radar ({vid}): {e_send}")

                # Pausa de 3 segundos entre anuncios para evitar rate-limits de Telegram
                time.sleep(3)
        except Exception as e:
            print(f"⚠️ Error revisando radar {canal['nombre']}: {e}")

    if len(nuevos_vistos) > len(vistos):
        guardar_vistos(nuevos_vistos)
        if anunciados > 0:
            threading.Thread(target=sincronizar_github_vistos, args=(nuevos_vistos,), daemon=True).start()

    return anunciados


def radar_loop(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func=None):
    # Primera revisión al arrancar
    try:
        chequear_canales(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func=bot_enviar_foto_func)
    except Exception as e:
        print(f"⚠️ Error en primera revisión del radar: {e}")

    while True:
        try:
            time.sleep(90)  # Cada 90 segundos (1.5 minutos)
            chequear_canales(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func=bot_enviar_foto_func)
        except Exception as e:
            print(f"⚠️ Error en loop radar YouTube: {e}")
            time.sleep(30)


def iniciar_radar(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func=None):
    t = threading.Thread(target=radar_loop, args=(bot_enviar_mensaje_func, chat_id_grupo, bot_enviar_foto_func), daemon=True)
    t.start()
    print("📡 Radar de YouTube iniciado en segundo plano (ALANISO 2012 y Mario Carrillo, sondeo cada 90s con miniaturas HD).")
