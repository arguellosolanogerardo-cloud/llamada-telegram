import base64
import json
import os
import subprocess
import urllib.request
import urllib.error

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
    """Comprime el audio a mono 32kbps a 16kHz para subirlo rápido a Gemini."""
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
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=90)
        if os.path.exists(ruta_salida) and os.path.getsize(ruta_salida) > 500:
            return ruta_salida
    except Exception as e:
        print("Nota comprimiendo audio con ffmpeg:", e)
    return ruta_audio


def generar_resumen_ia(
    ruta_audio: str,
    oradores: list,
    fecha: str,
    duracion_minutos: int,
    total_asistentes: int = 0,
    info_catalogo: dict = None
) -> str:
    """Transcribe y genera el resumen oficial con atribución de oradores (Diarización) usando Gemini."""
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

    prompt_instrucciones = (
        f"Eres el redactor oficial de la reunión comunitaria del {fecha}.\n"
        f"Duración: {duracion_minutos} minutos. Participantes con uso de la palabra:\n{txt_oradores}\n"
        f"{txt_catalogo}\n"
        "Se ha extraído el audio de la llamada excluyendo la meditación para analizar únicamente las intervenciones de las personas.\n\n"
        "Redacta el informe oficial estructurado EXACTAMENTE en estas 3 secciones:\n\n"
        "📌 RESUMEN EJECUTIVO:\n"
        "(Un resumen fluido de 1 a 2 párrafos sobre los temas centrales y bienvenida de la reunión).\n\n"
        "🗣️ INTERVENCIONES Y APORTES POR PARTICIPANTE:\n"
        "(Describe qué compartió, opinó, preguntó o reflexionó cada participante, atribuyendo con precisión el nombre de la persona según la lista de oradores).\n\n"
        "🌟 CONCLUSIÓN GENERAL DEL DÍA:\n"
        "(La reflexión central o mensaje final con el que cerró la comunidad hoy).\n\n"
        "Reglas: Sé claro, respetuoso, directo y evita inventar información no presente en la sesión."
    )

    api_key = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY)

    # 1. Intentar con Gemini API si hay clave y archivo de audio
    if api_key and ruta_audio and os.path.exists(ruta_audio) and os.path.getsize(ruta_audio) > 1000:
        try:
            ruta_optimizada = comprimir_audio_para_ia(ruta_audio)
            with open(ruta_optimizada, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("utf-8")

            mime = "audio/mp3" if ruta_optimizada.endswith(".mp3") else "audio/wav"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt_instrucciones},
                            {
                                "inlineData": {
                                    "mimeType": mime,
                                    "data": audio_b64
                                }
                            }
                        ]
                    }
                ]
            }

            modelos = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.5-flash"]
            for mod in modelos:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={api_key}"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                try:
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        candidatos = res_json.get("candidates", [])
                        if candidatos:
                            partes = candidatos[0].get("content", {}).get("parts", [])
                            texto_resultado = "".join([p.get("text", "") for p in partes]).strip()
                            if texto_resultado:
                                print(f"Resumen con IA generado exitosamente usando {mod}.")
                                return texto_resultado
                except urllib.error.HTTPError as he:
                    print(f"Error {he.code} con modelo {mod}:", he.read().decode("utf-8")[:200])
                    continue
                except Exception as e:
                    print(f"Nota consultando modelo {mod}:", e)
                    continue
        except Exception as e:
            print("Error procesando audio con Gemini:", e)

    # 2. Resumen Estructurado Base (Fallback si no hay API key o no se grabó audio)
    print("Generando resumen estructurado base sin transcripción de audio.")
    lineas = [
        "📌 **RESUMEN EJECUTIVO:**",
        f"Reunión diaria comunitaria realizada el **{fecha}** con una duración de **{duracion_minutos} minutos** "
        f"y un total de **{total_asistentes} participantes conectados**. "
        "La sesión contó con apertura puntual, espacio de bienvenida, la reproducción de la meditación diaria a las 8:32 PM "
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

    return "\n".join(lineas)
