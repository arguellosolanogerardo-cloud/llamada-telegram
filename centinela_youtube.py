#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
centinela_youtube.py
====================
Centinela automático para monitorear y precargar los audios limpios de YouTube.
Diseñado para ejecutarse en entorno local (con IP residencial libre de bloqueos de YouTube).

Uso:
    python centinela_youtube.py                # Escanea canales y sincroniza pendientes con push a GitHub
    python centinela_youtube.py --no-push      # Descarga sin hacer git push
    python centinela_youtube.py --video <URL>  # Descarga un video específico por ID o URL
"""

import os
import sys
import json
import re
import argparse
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

CANALES_RSS = [
    {
        "id": "UCms8TOzGiu0Ozj-QmpwstQw",
        "nombre": "ALANISO 2012",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCms8TOzGiu0Ozj-QmpwstQw"
    },
    {
        "id": "UCjEjDB1gZMGh0QegLjN1o7w",
        "nombre": "Maestro Mario Carrillo",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCjEjDB1gZMGh0QegLjN1o7w"
    }
]

CARP_MED = os.path.join("data", "meditaciones")
RUTA_VISTOS = os.path.join("data", "radar_vistos.json")


def extraer_video_id(texto: str) -> str:
    """Extrae el ID de 11 caracteres de una URL o texto de YouTube."""
    if not texto:
        return ""
    texto = texto.strip()
    m = re.search(r"(?:v=|\/|youtu\.be\/|embed\/)([a-zA-Z0-9_-]{11})", texto)
    if m:
        return m.group(1)
    if len(texto) == 11 and re.match(r"^[a-zA-Z0-9_-]{11}$", texto):
        return texto
    return ""


def obtener_videos_rss(url_rss: str) -> list[dict]:
    """Lee el feed RSS oficial de YouTube (rápido, sin bloqueos ni límites)."""
    videos = []
    try:
        req = urllib.request.Request(url_rss, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015"
        }
        for entry in root.findall("atom:entry", ns):
            vid_elem = entry.find("yt:videoId", ns)
            tit_elem = entry.find("atom:title", ns)
            if vid_elem is not None and vid_elem.text:
                vid = vid_elem.text.strip()
                tit = tit_elem.text.strip() if (tit_elem is not None and tit_elem.text) else f"Video {vid}"
                videos.append({"id": vid, "titulo": tit})
    except Exception as e:
        print(f"⚠️ Error leyendo feed RSS ({url_rss}): {e}")
    return videos


def cargar_vistos() -> list[str]:
    if os.path.exists(RUTA_VISTOS):
        try:
            with open(RUTA_VISTOS, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, list):
                    return [str(x) for x in d]
        except Exception:
            pass
    return []


def guardar_vistos(vistos: list[str]) -> None:
    try:
        os.makedirs(os.path.dirname(RUTA_VISTOS), exist_ok=True)
        unicos = []
        for x in vistos:
            if x and x not in unicos:
                unicos.append(x)
        with open(RUTA_VISTOS, "w", encoding="utf-8") as f:
            json.dump(unicos[-150:], f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error guardando radar_vistos: {e}")


def main():
    parser = argparse.ArgumentParser(description="Centinela local de precarga de audios de YouTube")
    parser.add_argument("--video", "-v", type=str, help="ID o URL de un video específico a descargar", default="")
    parser.add_argument("--no-push", action="store_true", help="No ejecutar git push al finalizar")
    parser.add_argument("--limite", "-l", type=int, default=5, help="Máximo de videos a descargar por canal en cada escaneo")
    args = parser.parse_args()

    os.makedirs(CARP_MED, exist_ok=True)
    vistos = cargar_vistos()

    from bot_comandos import descargar_audio_youtube_robusto

    candidatos = []

    # 1. Modo video específico
    if args.video:
        vid_esp = extraer_video_id(args.video)
        if not vid_esp:
            print(f"❌ No se pudo identificar un ID de YouTube válido en: {args.video}")
            return
        candidatos.append({"id": vid_esp, "titulo": f"Video {vid_esp}", "canal": "Manual"})
    else:
        # 2. Modo escaneo de canales oficiales vía RSS
        print("🔍 Escaneando canales oficiales de YouTube vía RSS...")
        for canal in CANALES_RSS:
            items = obtener_videos_rss(canal["rss"])
            print(f"   📡 {canal['nombre']}: {len(items)} videos detectados en feed reciente.")
            agregados = 0
            for it in items:
                v_id = it["id"]
                archivo_mp3 = os.path.join(CARP_MED, f"yt_clean_{v_id}.mp3")
                # Si falta el audio MP3 en disco, es candidato
                if not os.path.exists(archivo_mp3) or os.path.getsize(archivo_mp3) < 1000:
                    candidatos.append({
                        "id": v_id,
                        "titulo": it["titulo"],
                        "canal": canal["nombre"]
                    })
                    agregados += 1
                    if agregados >= args.limite:
                        break

    if not candidatos:
        print("✅ Todos los videos recientes de los canales ya cuentan con su audio MP3 limpio precargado.")
        return

    print(f"\n⚡ Se encontraron {len(candidatos)} video(s) pendientes de precarga:")
    for c in candidatos:
        print(f"   • [{c['canal']}] {c['id']} - {c['titulo']}")

    descargados_ok = []

    for idx, c in enumerate(candidatos, 1):
        v_id = c["id"]
        tit = c["titulo"]
        print(f"\n🔄 [{idx}/{len(candidatos)}] Extrayendo audio limpio para: {v_id} («{tit}»)...")
        try:
            archivo_mp3, origen = descargar_audio_youtube_robusto(v_id, tit)
            if archivo_mp3 and os.path.exists(archivo_mp3) and os.path.getsize(archivo_mp3) > 1000:
                mb = round(os.path.getsize(archivo_mp3) / (1024 * 1024), 2)
                print(f"   ✅ Audio listo en disco: {archivo_mp3} ({mb} MB)")
                descargados_ok.append(v_id)
                if v_id not in vistos:
                    vistos.append(v_id)
            else:
                print(f"   ❌ No se pudo descargar el audio para {v_id}")
        except Exception as e_desc:
            print(f"   ❌ Error descargando {v_id}: {e_desc}")

    if descargados_ok:
        guardar_vistos(vistos)
        print(f"\n🎉 {len(descargados_ok)} audio(s) descargados y guardados con éxito.")

        if not args.no_push:
            print("\n🚀 Sincronizando con GitHub (origin/main) para actualizar Render...")
            try:
                subprocess.run(["git", "add", "data/radar_vistos.json"], check=True)
                for v_id in descargados_ok:
                    f_mp3 = os.path.join(CARP_MED, f"yt_clean_{v_id}.mp3")
                    if os.path.exists(f_mp3):
                        subprocess.run(["git", "add", f_mp3], check=True)

                msg = f"fix(youtube): precarga automatica de {len(descargados_ok)} audio(s) limpios por centinela local"
                res_c = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
                if res_c.returncode == 0:
                    print("   ✅ Commit creado.")
                    res_p = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
                    if res_p.returncode == 0:
                        print("   ✅ Push exitoso a GitHub. Render comenzará el despliegue automático.")
                    else:
                        print(f"   ⚠️ Error en git push: {res_p.stderr.strip()}")
                else:
                    print(f"   ℹ️ Sin cambios pendientes para commit: {res_c.stdout.strip()}")
            except Exception as e_git:
                print(f"   ⚠️ Error sincronizando con Git: {e_git}")
    else:
        print("\nℹ️ No se descargaron audios nuevos.")


if __name__ == "__main__":
    main()
