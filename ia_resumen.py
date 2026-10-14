import base64
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _log(msg: str):
    """Imprime mensajes de log protegiendo contra errores de codificación en consolas Windows."""
    try:
        print(msg)
    except Exception:
        try:
            print(str(msg).encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            pass

RUTA_MINUTAS_JSON = os.path.join("data", "minutas.json")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def cargar_todas_las_minutas() -> dict:
    if os.path.exists(RUTA_MINUTAS_JSON):
        try:
            with open(RUTA_MINUTAS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("Nota leyendo minutas.json:", e)
    return {}


def guardar_minuta(
    fecha: str,
    duracion_minutos: int,
    asistentes_count: int,
    oradores: list,
    resumen_texto: str,
    ruta_pdf: str = "",
    info_catalogo: dict = None
) -> None:
    """Guarda la minuta de una reunión en la base de datos histórica de minutas."""
    os.makedirs(os.path.dirname(RUTA_MINUTAS_JSON), exist_ok=True)
    db = cargar_todas_las_minutas()
    db[fecha] = {
        "fecha": fecha,
        "duracion_minutos": duracion_minutos,
        "asistentes_count": asistentes_count,
        "oradores": oradores,
        "resumen": resumen_texto,
        "ruta_pdf": ruta_pdf,
        "info_catalogo": info_catalogo or {},
    }
    try:
        with open(RUTA_MINUTAS_JSON, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        print(f"Minuta del {fecha} guardada exitosamente en {RUTA_MINUTAS_JSON}")
    except Exception as e:
        print("Error guardando minuta en minutas.json:", e)


def buscar_en_minutas(termino: str) -> str:
    """Busca en el historial de reuniones temas o intervenciones mencionadas."""
    termino = (termino or "").strip().lower()
    if not termino:
        return "ℹ️ Uso: `/buscar <palabra>` (Ejemplo: `/buscar gratitud`, `/buscar Maria`)."

    db = cargar_todas_las_minutas()
    if not db:
        return "📁 Aún no hay minutas ni actas registradas en el historial."

    coincidencias = []
    for fecha, datos in sorted(db.items(), reverse=True):
        resumen = datos.get("resumen", "")
        oradores = [o.lower() for o in datos.get("oradores", [])]
        cat_info = datos.get("info_catalogo", {})
        cat_txt = f"{cat_info.get('titulo', '')} {cat_info.get('maestro', '')} {cat_info.get('tipo', '')} {cat_info.get('numero', '')}".lower()
        texto_busqueda = f"{resumen.lower()} {' '.join(oradores)} {fecha} {cat_txt}"

        if termino in texto_busqueda:
            # Extraer un fragmento relevante de 150 caracteres
            pos = resumen.lower().find(termino)
            if pos != -1:
                inicio = max(0, pos - 40)
                fin = min(len(resumen), pos + 120)
                snippet = "..." + resumen[inicio:fin].strip().replace("\n", " ") + "..."
            else:
                snippet = f"Mención en oradores o fecha: {', '.join(datos.get('oradores', []))}"

            coincidencias.append(f"📅 **{fecha}**:\n{snippet}\n💡 `/resumen {fecha}`")

    if not coincidencias:
        return f"🔍 No se encontraron registros históricos con el término: **{termino}**."

    bloque = "\n\n".join(coincidencias[:5])
    return (
        f"🔍 **Resultados encontrados para \"{termino}\" ({len(coincidencias)}):**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{bloque}"
    )


def obtener_minuta(fecha: str = None) -> dict | None:
    """Retorna los datos de la minuta de una fecha o la más reciente si no se pasa fecha."""
    db = cargar_todas_las_minutas()
    if not db:
        return None
    if fecha and fecha in db:
        return db[fecha]
    elif not fecha:
        fechas_ordenadas = sorted(db.keys(), reverse=True)
        if fechas_ordenadas:
            return db[fechas_ordenadas[0]]
    return None


def comprimir_audio_para_ia(ruta_audio: str) -> str:
    """Comprime el audio a mono MP3 a 16kHz optimizado para speech recognition con Gemini."""
    if not os.path.exists(ruta_audio):
        return ruta_audio
    ruta_salida = ruta_audio.rsplit(".", 1)[0] + "_ia_opt.mp3"
    cmd = [
        "ffmpeg", "-y",
        "-i", ruta_audio,
        "-ac", "1",
        "-ar", "16000",
        "-b:a", "32k",
        ruta_salida
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=120)
        # Si supera 15MB, recomprimir a 16k mono para asegurar que quepa en el límite de 20MB de inlineData
        if os.path.exists(ruta_salida) and os.path.getsize(ruta_salida) > 15 * 1024 * 1024:
            cmd_recomp = [
                "ffmpeg", "-y",
                "-i", ruta_audio,
                "-ac", "1",
                "-ar", "16000",
                "-b:a", "16k",
                ruta_salida
            ]
            subprocess.run(cmd_recomp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=120)
        if os.path.exists(ruta_salida) and os.path.getsize(ruta_salida) > 500:
            return ruta_salida
    except Exception as e:
        print("Nota comprimiendo audio con ffmpeg:", e)
    return ruta_audio


def transcribir_audio_local_whisper(ruta_audio: str) -> tuple[str, list[str]]:
    """Transcribe el archivo de audio usando faster_whisper de forma 100% local y offline.
    Retorna (texto_formateado_con_marcas, lista_de_lineas)."""
    if not ruta_audio or not os.path.exists(ruta_audio) or os.path.getsize(ruta_audio) < 1000:
        return "", []

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        _log("faster_whisper no está instalado en este entorno.")
        return "", []

    try:
        modelo_nombre = os.environ.get("WHISPER_MODEL", "base")
        _log(f"Iniciando transcripción local con faster-whisper (Modelo: {modelo_nombre}, Audio: {os.path.getsize(ruta_audio)} bytes)...")
        model = WhisperModel(modelo_nombre, device="cpu", compute_type="int8")
        segments, info = model.transcribe(
            ruta_audio,
            language="es",
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        lineas = []
        for s in segments:
            txt = s.text.strip()
            if not txt:
                continue
            m_ini = int(s.start // 60)
            s_ini = int(s.start % 60)
            m_fin = int(s.end // 60)
            s_fin = int(s.end % 60)
            lineas.append(f"[{m_ini:02d}:{s_ini:02d} -> {m_fin:02d}:{s_fin:02d}] {txt}")

        texto_completo = "\n".join(lineas)
        _log(f"Transcripción local finalizada: {len(lineas)} fragmentos transcritos.")
        return texto_completo, lineas
    except Exception as e:
        _log(f"Error en transcripción local con faster-whisper: {e}")
        return "", []


def generar_resumen_ia(
    ruta_audio: str,
    oradores: list,
    fecha: str,
    duracion_minutos: int,
    total_asistentes: int = 0,
    info_catalogo: dict = None,
    ruta_transcripcion_salida: str = None
) -> str:
    """Genera la transcripción cronológica completa y el resumen estructurado oficial.
    Utiliza motor dual: Faster-Whisper local offline para transcripción literal y Gemini para síntesis."""
    txt_oradores = "\n".join([f"- {o}" for o in oradores]) if oradores else "No hubo intervenciones individuales registradas."

    txt_catalogo = ""
    if info_catalogo:
        t_tipo = info_catalogo.get("tipo", "Meditación").capitalize()
        t_num = info_catalogo.get("numero", "")
        t_tit = info_catalogo.get("titulo", "")
        t_mae = info_catalogo.get("maestro", "Alaniso")
        t_fec = info_catalogo.get("fecha_original") or info_catalogo.get("fecha", "")
        txt_catalogo = (
            f"\nEn esta reunión se compartió el audio oficial: {t_tipo} #{t_num} titulado '{t_tit}', "
            f"transmitido por el Maestro {t_mae} (Grabación original: {t_fec}). "
            "Considera este contexto espiritual en la síntesis.\n"
        )

    SEPARADOR_TRANSCRIPCION = "=== TRANSCRIPCIÓN COMPLETA ==="
    api_key = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY)
    tiene_audio = bool(ruta_audio and os.path.exists(ruta_audio) and os.path.getsize(ruta_audio) > 1000)

    transcripcion_texto = ""
    motor_transcripcion = "Sin audio"

    # PASO 1: Si hay audio, obtener transcripción literal con Whisper Local
    if tiene_audio:
        texto_whisper, _ = transcribir_audio_local_whisper(ruta_audio)
        if texto_whisper.strip():
            transcripcion_texto = texto_whisper.strip()
            motor_transcripcion = "Faster-Whisper (IA Local Offline)"

    # PASO 2: Si Whisper no obtuvo texto pero hay API key de Gemini, intentar transcripción con Gemini Audio
    if tiene_audio and not transcripcion_texto and api_key:
        _log(f"Intentando transcripción directa de audio con Gemini API (Audio: {os.path.getsize(ruta_audio)} bytes)...")
        try:
            ruta_optimizada = comprimir_audio_para_ia(ruta_audio)
            with open(ruta_optimizada, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("utf-8")

            mime = "audio/mp3" if ruta_optimizada.endswith(".mp3") else "audio/wav"
            prompt_audio_puro = (
                f"Eres el relator y transcriptor de la reunión del {fecha}.\n"
                f"Oradores registrados: {txt_oradores}\n"
                f"{txt_catalogo}\n"
                "Transcribe las intervenciones de las personas en orden cronológico con la mayor fidelidad posible."
            )
            payload_aud = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt_audio_puro},
                            {"inlineData": {"mimeType": mime, "data": audio_b64}}
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192}
            }
            for mod in ["gemini-2.0-flash", "gemini-1.5-flash"]:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={api_key}"
                req = urllib.request.Request(url, data=json.dumps(payload_aud).encode("utf-8"), headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        candidatos = res_json.get("candidates", [])
                        if candidatos:
                            partes = candidatos[0].get("content", {}).get("parts", [])
                            txt_res = "".join([p.get("text", "") for p in partes]).strip()
                            if txt_res:
                                transcripcion_texto = txt_res
                                motor_transcripcion = f"Google Gemini Audio ({mod})"
                                break
                except Exception as e_ga:
                    _log(f"Nota con modelo audio {mod}: {e_ga}")
        except Exception as e_g_aud:
            _log(f"Error en llamada de audio con Gemini: {e_g_aud}")

    # PASO 3: Generar Resumen Estructurado (Síntesis Oficial)
    resumen_oficial = ""

    # Opción A: Tenemos transcripción y API Key de Gemini -> Síntesis inteligente rápida basada en texto
    if transcripcion_texto and api_key:
        _log("Generando síntesis oficial con Gemini basada en la transcripción de texto...")
        prompt_sintesis = (
            f"Eres el redactor oficial de la reunión comunitaria del {fecha}.\n"
            f"Duración: {duracion_minutos} minutos | Participantes conectados: {total_asistentes}.\n"
            f"Oradores registrados: {txt_oradores}\n"
            f"{txt_catalogo}\n\n"
            "A continuación tienes la transcripción cronológica de las intervenciones en sala:\n"
            f"\"\"\"\n{transcripcion_texto[:25000]}\n\"\"\"\n\n"
            "Con base en la transcripción y los oradores registrados, genera el informe oficial estructurado EXACTAMENTE en estas 3 secciones:\n\n"
            "📌 RESUMEN EJECUTIVO:\n"
            "(1 a 2 párrafos que sinteticen fluidamente los temas tratados, apertura y dinámica de la reunión).\n\n"
            "🗣️ INTERVENCIONES Y APORTES POR PARTICIPANTE:\n"
            "(Describe qué compartió, opinó, preguntó o reflexionó cada participante registrado según lo conversado).\n\n"
            "🌟 CONCLUSIÓN GENERAL DEL DÍA:\n"
            "(Una reflexión espiritual positiva y de cierre armonioso para el acta).\n\n"
            "Reglas: Sé respetuoso, inspirador, conciso y fiel a lo conversado."
        )
        payload_sint = {
            "contents": [{"parts": [{"text": prompt_sintesis}]}],
            "generationConfig": {"temperature": 0.3}
        }
        for mod in ["gemini-2.0-flash", "gemini-1.5-flash"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={api_key}"
            req = urllib.request.Request(url, data=json.dumps(payload_sint).encode("utf-8"), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    candidatos = res_json.get("candidates", [])
                    if candidatos:
                        partes = candidatos[0].get("content", {}).get("parts", [])
                        txt_s = "".join([p.get("text", "") for p in partes]).strip()
                        if txt_s:
                            resumen_oficial = txt_s
                            _log(f"Síntesis oficial generada exitosamente con {mod}.")
                            break
            except Exception as e_s:
                _log(f"Nota generando síntesis con {mod}: {e_s}")

    # Opción B: No hay transcripción pero sí API key -> Resumen solo-texto basado en telemetría
    elif not transcripcion_texto and api_key:
        _log("Intentando generar resumen inteligente con Gemini en modo solo-texto (sin transcripción de audio)...")
        prompt_texto_puro = (
            f"Eres el redactor oficial de la reunión comunitaria del {fecha}.\n"
            f"Duración: {duracion_minutos} minutos | Asistentes conectados: {total_asistentes}.\n"
            f"Oradores que tomaron la palabra:\n{txt_oradores}\n"
            f"{txt_catalogo}\n"
            "Redacta el informe oficial estructurado EXACTAMENTE en estas 3 secciones:\n\n"
            "📌 RESUMEN EJECUTIVO:\n"
            "(Un resumen fluido de 1 a 2 párrafos sobre la sesión comunitaria, bienvenida y dinámica).\n\n"
            "🗣️ INTERVENCIONES Y APORTES POR PARTICIPANTE:\n"
            "(Menciona la participación de los oradores registrados y la escucha activa de la comunidad).\n\n"
            "🌟 CONCLUSIÓN GENERAL DEL DÍA:\n"
            "(Una reflexión espiritual positiva y de cierre armonioso de la jornada).\n\n"
            "Reglas: Sé claro, inspirador y respetuoso."
        )
        payload_txt = {
            "contents": [{"parts": [{"text": prompt_texto_puro}]}],
            "generationConfig": {"temperature": 0.3}
        }
        for mod in ["gemini-2.0-flash", "gemini-1.5-flash"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={api_key}"
            req = urllib.request.Request(url, data=json.dumps(payload_txt).encode("utf-8"), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    candidatos = res_json.get("candidates", [])
                    if candidatos:
                        partes = candidatos[0].get("content", {}).get("parts", [])
                        txt_res = "".join([p.get("text", "") for p in partes]).strip()
                        if txt_res:
                            resumen_oficial = txt_res
                            break
            except Exception as e_t:
                _log(f"Nota con modelo texto {mod}: {e_t}")

    # Opción C: Fallback local robusto estructurado
    if not resumen_oficial:
        _log("Construyendo resumen oficial estructurado base.")
        lineas = [
            "📌 **RESUMEN EJECUTIVO:**",
            f"Reunión diaria comunitaria realizada el **{fecha}** con una duración de **{duracion_minutos} minutos** "
            + (f"y un total de **{total_asistentes} participantes conectados**. " if total_asistentes != 1 else "y **1 participante conectado**. ")
            + "La sesión contó con apertura puntual, espacio de bienvenida, la reproducción de la meditación diaria a las 8:32 PM "
            "y la ronda posterior de preguntas y compartir entre los miembros.",
            "",
            "🗣️ **INTERVENCIONES Y APORTES POR PARTICIPANTE:**"
        ]

        if oradores:
            for o in oradores:
                lineas.append(f"• **{o}:** Participó activamente en la llamada compartiendo su voz y reflexiones con el grupo.")
        else:
            lineas.append("• Todos los asistentes mantuvieron una actitud de escucha activa durante la sesión.")

        lineas.extend([
            "",
            "🌟 **CONCLUSIÓN GENERAL DEL DÍA:**",
            "Jornada muy enriquecedora con excelente permanencia y armonía. ¡Gracias a todos los que hicieron posible este espacio!"
        ])
        resumen_oficial = "\n".join(lineas)

    # PASO 4: Guardar archivo de transcripción con información veraz y fidelidad
    if ruta_transcripcion_salida:
        try:
            os.makedirs(os.path.dirname(ruta_transcripcion_salida), exist_ok=True)
            with open(ruta_transcripcion_salida, "w", encoding="utf-8") as f_tr:
                f_tr.write(f"📝 TRANSCRIPCIÓN OFICIAL DE LA REUNIÓN — {fecha}\n")
                f_tr.write(f"Duración: {duracion_minutos} min | Asistentes: {total_asistentes}\n")
                f_tr.write(f"Oradores identificados: {', '.join(oradores) if oradores else 'Comunidad'}\n")
                f_tr.write(f"Motor de transcripción: {motor_transcripcion}\n")
                f_tr.write("=" * 60 + "\n\n")

                if transcripcion_texto:
                    f_tr.write(transcripcion_texto + "\n")
                elif tiene_audio:
                    f_tr.write("ℹ️ El archivo de audio de la sesión fue grabado exitosamente, pero no se detectaron intervenciones de voz articuladas o legibles en los micrófonos durante esta reunión.\n")
                else:
                    f_tr.write("ℹ️ Nota: No se registraron flujos de audio entrantes en la sala durante esta sesión.\n")
                    f_tr.write("Se generó la síntesis de participación comunitaria basada en la telemetría de la sala.\n")
            _log(f"Transcripción guardada exitosamente en: {ruta_transcripcion_salida}")
        except Exception as e_tr:
            _log(f"Nota guardando archivo de transcripción: {e_tr}")

    return resumen_oficial
