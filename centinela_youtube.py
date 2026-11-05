#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
centinela_youtube.py
====================
Centinela automático para monitorear, precargar y rotar audios limpios de YouTube.
Diseñado para ejecutarse en entorno local (con IP residencial libre de bloqueos de YouTube).

Arquitectura Híbrida:
1. Caché Caliente: Mantiene solo los 21 audios más recientes de YouTube en disco y Git (~350 MB).
2. Catálogo Permanente: Registra todos los audios y file_id en data/meditaciones/audios_registrados.json.
3. Rotación Automática: Cuando ingresa un audio nuevo, retira de Git los más antiguos conservándolos en el catálogo.

Uso:
    python centinela_youtube.py                   # Ejecuta 1 ciclo de escaneo y sincronización con GitHub
    python centinela_youtube.py --daemon          # Ejecuta en bucle continuo cada 15 minutos en segundo plano
    python centinela_youtube.py --intervalo 15    # Especifica los minutos entre cada escaneo continuo
    python centinela_youtube.py --video <URL>     # Descarga un video específico por ID o URL
    python centinela_youtube.py --max-cache 21    # Define cuántos audios conservar en caché caliente
"""

import os
import sys
import json
import re
import glob
import time
import argparse
import subprocess

# Fijar siempre el directorio de trabajo a la raíz del repositorio
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
try:
    os.chdir(BASE_DIR)
except Exception as e_cd:
    print(f"Nota fijando directorio de trabajo: {e_cd}")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

CARP_MED = os.path.join("data", "meditaciones")
RUTA_AUDIOS_REG = os.path.join(CARP_MED, "audios_registrados.json")


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


def cargar_audios_registrados() -> dict:
    if os.path.exists(RUTA_AUDIOS_REG):
        try:
            with open(RUTA_AUDIOS_REG, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:
            pass
    return {}


def guardar_audios_registrados(db: dict) -> None:
    try:
        os.makedirs(CARP_MED, exist_ok=True)
        with open(RUTA_AUDIOS_REG, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error guardando audios_registrados: {e}")


def rotar_audios_limpios(prioridad_ids: list[str] = None, limite_max: int = 21) -> list[str]:
    """Mantiene en disco y Git solo los `limite_max` audios más recientes en orden cronológico real de YouTube.
    Asegura los metadatos en audios_registrados.json antes de retirar los archivos viejos de Git.
    """
    archivos = glob.glob(os.path.join(CARP_MED, "yt_clean_*.mp3"))
    if len(archivos) <= limite_max:
        return []

    a_conservar = []
    if prioridad_ids:
        for p_id in prioridad_ids:
            f_path = os.path.join(CARP_MED, f"yt_clean_{p_id}.mp3")
            if os.path.exists(f_path) and len(a_conservar) < limite_max:
                a_conservar.append(os.path.normpath(f_path))

    # Si faltan para completar el límite, usar fecha de modificación como fallback
    if len(a_conservar) < limite_max:
        restantes = [f for f in archivos if os.path.normpath(f) not in a_conservar]
        restantes.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        for r_path in restantes:
            if len(a_conservar) < limite_max:
                a_conservar.append(os.path.normpath(r_path))

    norm_conservar = set(a_conservar)
    a_eliminar = [f for f in archivos if os.path.normpath(f) not in norm_conservar]

    if not a_eliminar:
        return []

    db_reg = cargar_audios_registrados()
    eliminados = []

    print(f"\n♻️ Rotación de caché caliente: Se conservan {len(a_conservar)} audios recientes. Retirando {len(a_eliminar)} antiguos.")
    for f_viejo in a_eliminar:
        m = re.search(r"yt_clean_([a-zA-Z0-9_-]{11})\.mp3$", f_viejo)
        v_id = m.group(1) if m else os.path.basename(f_viejo)
        mb = round(os.path.getsize(f_viejo) / (1024 * 1024), 2)

        # Garantizar que existe registro en audios_registrados.json
        clave_yt = f"YT_CLEAN_{v_id}"
        if clave_yt not in db_reg:
            db_reg[clave_yt] = {
                "video_id": f"CLEAN_{v_id}",
                "titulo": f"Audio {v_id}",
                "fuente": "YOUTUBE",
                "file_id": db_reg.get(f"YT_{v_id}", {}).get("file_id")
            }

        try:
            # Retirar de Git si está rastreado, o borrar de disco
            res_rm = subprocess.run(["git", "rm", "-f", f_viejo], capture_output=True, text=True)
            if res_rm.returncode != 0 and os.path.exists(f_viejo):
                os.remove(f_viejo)
            eliminados.append(v_id)
            print(f"   🗑️ Retirado de caché caliente: {os.path.basename(f_viejo)} ({mb} MB) [Catálogo preservado]")
        except Exception as e_rm:
            print(f"   ⚠️ Error retirando {f_viejo}: {e_rm}")

    guardar_audios_registrados(db_reg)
    return eliminados


def en_ventana_protegida_llamada() -> bool:
    """Verifica si la hora actual en Colombia está en la ventana de preparación/llamada (7:15 PM a 8:15 PM).
    Durante este intervalo se evitan reinicios en Render postergando el git push."""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("America/Bogota"))
        minutos = ahora.hour * 60 + ahora.minute
        return (19 * 60 + 15) <= minutos <= (20 * 60 + 15)
    except Exception:
        return False


def hay_commits_pendientes_push() -> bool:
    """Verifica si hay commits locales pendientes de enviar a origin/main."""
    try:
        res = subprocess.run(["git", "log", "origin/main..HEAD", "--oneline"], capture_output=True, text=True)
        return bool(res.stdout.strip())
    except Exception:
        return False


def pre_renderizar_video_meditacion_hoy() -> list[str]:
    """Pre-renderiza con la GPU NVIDIA (NVENC) los videos animados de la cola (oficial y adicionales) si aún no existen."""
    videos_listos = []
    try:
        import astronomia_luna
        import glob
        if not astronomia_luna.tiene_soporte_nvenc():
            return videos_listos

        from schedule_meditaciones import META_HOY, _cargar_json
        meta = _cargar_json(META_HOY) or {}
        items_a_revisar = []

        if meta.get("numero") or meta.get("titulo"):
            items_a_revisar.append(meta)

        for it in (meta.get("cola_audios") or []):
            if isinstance(it, dict):
                items_a_revisar.append(it)

        r_cola = os.path.join(CARP_MED, "cola_hoy.json")
        if os.path.exists(r_cola):
            try:
                with open(r_cola, "r", encoding="utf-8") as fc:
                    dc = json.load(fc)
                    for item_c in (dc.get("cola") or []):
                        inf = item_c.get("info")
                        if isinstance(inf, dict):
                            items_a_revisar.append(inf)
            except Exception:
                pass

        # También verificar archivos yt_clean_*.mp3 en disco
        for f_mp3 in glob.glob(os.path.join(CARP_MED, "yt_clean_*.mp3")):
            vid_id = os.path.basename(f_mp3).replace("yt_clean_", "").replace(".mp3", "")
            items_a_revisar.append({"video_id": vid_id, "tipo": "MENSAJE", "audio_path": f_mp3})

        vistos = set()
        for it in items_a_revisar:
            num = str(it.get("numero") or "").strip()
            vid = str(it.get("video_id") or "").strip()
            tipo = str(it.get("tipo") or "MEDITACION").strip().upper()
            tipo_tag = "mensaje" if "MENSAJE" in tipo else "meditacion"
            tag = f"{tipo_tag}_{num}" if num else (f"{tipo_tag}_{vid}" if vid else "")
            if not tag or tag in vistos:
                continue
            vistos.add(tag)

            nombre_mp4 = f"caratula_{tag}.mp4"
            ruta_mp4 = os.path.join(CARP_MED, nombre_mp4)

            if os.path.exists(ruta_mp4) and os.path.getsize(ruta_mp4) > 50000:
                res_st = subprocess.run(["git", "status", "--porcelain", ruta_mp4], capture_output=True, text=True)
                if res_st.stdout.strip():
                    videos_listos.append(ruta_mp4)
                continue

            tit = it.get("titulo") or (f"Mensaje {vid}" if vid else f"Meditación #{num}")
            maestro = it.get("maestro") or ("JESUS MARIO CARRILLO DURAN" if it.get("es_mario") else "Alaniso")
            dur = float(it.get("duracion_seg") or 0.0)
            if dur <= 0:
                audio_ref = it.get("audio_path") or (os.path.join(CARP_MED, f"yt_clean_{vid}.mp3") if vid else os.path.join(CARP_MED, f"meditacion_{num}.mp3"))
                if os.path.exists(audio_ref):
                    try:
                        from llamada import obtener_duracion_segundos
                        dur = obtener_duracion_segundos(audio_ref)
                    except Exception:
                        dur = 1800.0
            if dur <= 0:
                dur = 1800.0

            print(f"🎬 [Centinela GPU] Pre-renderizando video ({tag}) con NVENC ({dur:.1f}s)...")
            vid_out = astronomia_luna.generar_video_meditacion_luna(
                numero=num,
                titulo=tit,
                maestro=maestro,
                duracion_seg=dur,
                ruta_salida=ruta_mp4,
                tipo=tipo,
            )
            if vid_out and os.path.exists(vid_out) and os.path.getsize(vid_out) > 50000:
                print(f"   ✅ Video pre-renderizado con éxito: {ruta_mp4} ({round(os.path.getsize(ruta_mp4)/(1024*1024), 2)} MB).")
                videos_listos.append(ruta_mp4)
    except Exception as e:
        print(f"   Nota en pre-renderizado de video: {e}")
    return videos_listos

def ejecutar_ciclo(args) -> bool:
    os.makedirs(CARP_MED, exist_ok=True)
    db_reg = cargar_audios_registrados()

    from bot_comandos import descargar_audio_youtube_robusto
    from radar_youtube import CANALES_RADAR, extraer_videos_canal

    candidatos = []
    descargados_ok = []
    prioridad_ids = []

    # 1. Modo video específico
    if args.video:
        vid_esp = extraer_video_id(args.video)
        if not vid_esp:
            print(f"❌ No se pudo identificar un ID de YouTube válido en: {args.video}")
            return False
        candidatos.append({"id": vid_esp, "titulo": f"Video {vid_esp}", "canal": "Manual"})
        prioridad_ids.append(vid_esp)
    else:
        # 2. Modo escaneo de canales oficiales vía radar
        print(f"[{time.strftime('%H:%M:%S')}] 🔍 Escaneando canales oficiales de YouTube...")
        for canal in CANALES_RADAR:
            try:
                items = extraer_videos_canal(canal)
                print(f"   📡 {canal['nombre']}: {len(items)} videos detectados.")
                for idx, it in enumerate(items[:6]):
                    v_id = it.get("video_id") or it.get("id")
                    if not v_id:
                        continue
                    if v_id not in prioridad_ids:
                        prioridad_ids.append(v_id)

                    tit = it.get("titulo", f"Video {v_id}")
                    archivo_mp3 = os.path.join(CARP_MED, f"yt_clean_{v_id}.mp3")

                    # Si es uno de los 2 videos más recientes del canal y no tiene audio en disco:
                    if idx < 2 and (not os.path.exists(archivo_mp3) or os.path.getsize(archivo_mp3) < 1000):
                        if not any(c["id"] == v_id for c in candidatos):
                            candidatos.append({
                                "id": v_id,
                                "titulo": tit,
                                "canal": canal["nombre"]
                            })
            except Exception as e_ch:
                print(f"   ⚠️ Error escaneando {canal['nombre']}: {e_ch}")

    # 3. Detectar si hay audios existentes en disco que aún no se han registrado en el catálogo
    for f_clean in glob.glob(os.path.join(CARP_MED, "yt_clean_*.mp3")):
        m = re.search(r"yt_clean_([a-zA-Z0-9_-]{11})\.mp3$", f_clean)
        if m:
            v_id_disco = m.group(1)
            clave = f"YT_CLEAN_{v_id_disco}"
            if clave not in db_reg:
                db_reg[clave] = {
                    "video_id": f"CLEAN_{v_id_disco}",
                    "titulo": f"Video {v_id_disco}",
                    "fuente": "YOUTUBE",
                    "file_id": None
                }
                descargados_ok.append(v_id_disco)

    if candidatos:
        print(f"\n⚡ Se encontraron {len(candidatos)} video(s) recientes pendientes de precarga:")
        for c in candidatos:
            print(f"   • [{c['canal']}] {c['id']} - {c['titulo']}")

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
                else:
                    print(f"   ❌ No se pudo descargar el audio para {v_id}")
            except Exception as e_desc:
                print(f"   ❌ Error descargando {v_id}: {e_desc}")

        if descargados_ok:
            print(f"\n🎉 {len(descargados_ok)} audio(s) registrados con éxito.")
            try:
                for c in candidatos:
                    if c["id"] in descargados_ok:
                        clave = f"YT_CLEAN_{c['id']}"
                        if clave not in db_reg:
                            db_reg[clave] = {
                                "video_id": f"CLEAN_{c['id']}",
                                "titulo": c.get("titulo", f"Video {c['id']}"),
                                "fuente": "YOUTUBE",
                                "file_id": None
                            }
                guardar_audios_registrados(db_reg)
            except Exception as e_reg_db:
                print(f"Nota registrando en db: {e_reg_db}")
    else:
        print("✅ No hay videos nuevos pendientes de descarga.")

    if descargados_ok:
        guardar_audios_registrados(db_reg)

    # 4. Aplicar rotación determinista de caché caliente (Capped a `args.max_cache` audios más recientes)
    eliminados = rotar_audios_limpios(prioridad_ids=prioridad_ids, limite_max=args.max_cache)

    # 4b. Pre-renderizar videos de la cola con GPU (RTX 3060 Ti) si no existen
    vids_hoy = pre_renderizar_video_meditacion_hoy()
    for v_h in vids_hoy:
        if os.path.exists(v_h):
            subprocess.run(["git", "add", v_h], check=False)


    # 5. Sincronización con GitHub si hubo descargas, registros, rotaciones o videos pre-renderizados
    res_st_audios = subprocess.run(["git", "status", "--porcelain", CARP_MED, RUTA_AUDIOS_REG], capture_output=True, text=True)
    hay_cambios_locales = bool(res_st_audios.stdout.strip())
    hay_cambios = bool(descargados_ok or eliminados or vids_hoy or hay_cambios_locales)

    if hay_cambios and not args.no_push:
        print("\n🚀 Sincronizando repositorio con GitHub (origin/main)...")
        try:
            # Nota: centinela solo gestiona audios y catálogo; radar_vistos.json es exclusivo de radar_youtube.py
            if os.path.exists(RUTA_AUDIOS_REG):
                subprocess.run(["git", "add", RUTA_AUDIOS_REG], check=True)

            for f_mp3 in glob.glob(os.path.join(CARP_MED, "yt_clean_*.mp3")):
                if os.path.exists(f_mp3):
                    subprocess.run(["git", "add", f_mp3], check=True)

            partes = []
            if descargados_ok:
                partes.append(f"precarga de {len(descargados_ok)} audio(s)")
            elif hay_cambios_locales:
                partes.append("actualizacion de audios y catalogo")
            if eliminados:
                partes.append(f"rotacion de {len(eliminados)} audio(s) a catalogo permanente")
            if vids_hoy:
                partes.append(f"{len(vids_hoy)} video(s) pre-renderizado(s)")
            msg = f"chore(meditacion): {', '.join(partes)}"

            res_c = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
            if res_c.returncode == 0:
                print("   ✅ Commit creado localmente.")
            else:
                print(f"   ℹ️ Sin cambios pendientes para commit: {res_c.stdout.strip()}")
        except Exception as e_git:
            print(f"   ⚠️ Error preparando commit en Git: {e_git}")

    # Empujar a GitHub si no estamos en la ventana protegida de la videollamada
    if not args.no_push and hay_commits_pendientes_push():
        if en_ventana_protegida_llamada():
            print("\n⏸️ En ventana protegida de videollamada (7:15 PM - 8:15 PM Colombia).")
            print("   Se posterga el 'git push' a GitHub para no reiniciar el bot en Render.")
            print("   Se sincronizará automáticamente en el próximo ciclo después de las 8:15 PM.")
        else:
            print("\n🚀 Sincronizando repositorio con GitHub (origin/main)...")
            try:
                subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False)
                res_p = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
                if res_p.returncode == 0:
                    print("   ✅ Push exitoso a GitHub. Render comenzará el despliegue con el audio listo.")
                else:
                    print(f"   ⚠️ Error en git push: {res_p.stderr.strip()}")
            except Exception as e_push:
                print(f"   ⚠️ Error al hacer push: {e_push}")
    elif not hay_cambios and not hay_commits_pendientes_push():
        print("✨ El repositorio ya está en su estado óptimo. No se requirieron cambios.")

    return hay_cambios


def main():
    parser = argparse.ArgumentParser(description="Centinela local de precarga y rotación de audios de YouTube")
    parser.add_argument("--video", "-v", type=str, help="ID o URL de un video específico a descargar", default="")
    parser.add_argument("--no-push", action="store_true", help="No ejecutar git push al finalizar")
    parser.add_argument("--max-cache", "-m", type=int, default=21, help="Máximo de audios limpios en caché caliente (default: 21)")
    parser.add_argument("--daemon", "-d", action="store_true", help="Ejecutar en bucle continuo cada N minutos")
    parser.add_argument("--intervalo", "-i", type=int, default=15, help="Minutos entre cada escaneo en modo daemon (default: 15)")
    args = parser.parse_args()

    if args.daemon:
        print(f"🛡️ Centinela YouTube iniciado en modo continuo (escaneo cada {args.intervalo} minutos).")
        print("💡 Para detenerlo, presiona Ctrl+C.\n")
        while True:
            try:
                ejecutar_ciclo(args)
            except KeyboardInterrupt:
                print("\n🛑 Centinela detenido por el usuario.")
                break
            except Exception as e_loop:
                print(f"⚠️ Error en ciclo centinela: {e_loop}")
            print(f"\n⏳ Próximo escaneo en {args.intervalo} minutos ({time.strftime('%H:%M:%S')})...\n")
            time.sleep(args.intervalo * 60)
    else:
        ejecutar_ciclo(args)


if __name__ == "__main__":
    main()
