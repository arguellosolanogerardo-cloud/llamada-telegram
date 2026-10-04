import asyncio
import csv
from datetime import datetime, timedelta
import json
import os
import random
import urllib.request
from zoneinfo import ZoneInfo

from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.functions.phone import (
    CreateGroupCallRequest,
    DiscardGroupCallRequest,
    GetGroupCallRequest,
)
from telethon.tl.types import Channel, Chat, PeerUser

# Credenciales obligatorias
API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION = os.environ.get("TG_SESSION", "")
GRUPO = os.environ.get("TG_GROUP", "")  # @usuario, o id numérico (-100...)
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # opcional
CHAT_ID = os.environ.get("CHAT_ID", GRUPO)  # id del grupo para el bot
TITULO = os.environ.get("CALL_TITLE", "Llamada diaria")
AVISO = os.environ.get(
    "AVISO",
    "📞 ¡Empieza la llamada diaria! Entra al chat de voz del grupo.",
)

# Parámetros de monitoreo y asistencia
DURACION_MAXIMA_MINUTOS = int(os.environ.get("DURACION_MAXIMA_MINUTOS", "120"))  # 2 horas
INTERVALO_SONDEO_SEGUNDOS = int(os.environ.get("INTERVALO_SONDEO_SEGUNDOS", "20"))
MIN_MINUTOS_ASISTENCIA = int(os.environ.get("MIN_MINUTOS_ASISTENCIA", "10"))
AUTO_CIERRE_MIN_USUARIOS = int(os.environ.get("AUTO_CIERRE_MIN_USUARIOS", "2"))
AUTO_CIERRE_ESPERA_MINUTOS = int(os.environ.get("AUTO_CIERRE_ESPERA_MINUTOS", "60"))

RUTA_PUNTOS = os.path.join("data", "puntos.json")
CARPETA_ASISTENCIAS = os.path.join("data", "asistencias")


def hora_california() -> str:
    bogota = ZoneInfo("America/Bogota")
    california = ZoneInfo("America/Los_Angeles")
    hoy = datetime.now(bogota).replace(hour=19, minute=56, second=0, microsecond=0)
    return hoy.astimezone(california).strftime("%I:%M %p").lstrip("0").lower()


def avisar_con_bot(texto: str) -> None:
    if not BOT_TOKEN:
        return
    texto = texto.replace("{CA}", hora_california())
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    datos = json.dumps({"chat_id": CHAT_ID, "text": texto}).encode()
    req = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("Aviso del bot enviado:", r.status)
    except Exception as e:
        print("Error al enviar mensaje con el bot:", e)


def obtener_rango(puntos: int) -> str:
    if puntos >= 1800:
        return "💎 Diamante"
    if puntos >= 750:
        return "🥇 Oro"
    if puntos >= 250:
        return "🥈 Plata"
    return "🥉 Bronce"


def cargar_puntos() -> dict:
    if os.path.exists(RUTA_PUNTOS):
        try:
            with open(RUTA_PUNTOS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("Error leyendo puntos.json, inicializando nuevo:", e)
    return {"version": 1, "usuarios": {}}


def guardar_puntos(data: dict) -> None:
    os.makedirs(os.path.dirname(RUTA_PUNTOS), exist_ok=True)
    with open(RUTA_PUNTOS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def obtener_full_chat(client, entidad):
    if isinstance(entidad, Channel):
        full = await client(GetFullChannelRequest(entidad))
        return full.full_chat
    elif isinstance(entidad, Chat):
        full = await client(GetFullChatRequest(entidad.id))
        return full.full_chat
    return None


async def main() -> None:
    tz_col = ZoneInfo("America/Bogota")
    inicio_llamada = datetime.now(tz_col)
    fecha_hoy = inicio_llamada.strftime("%Y-%m-%d")
    fecha_ayer = (inicio_llamada - timedelta(days=1)).strftime("%Y-%m-%d")

    async with TelegramClient(StringSession(SESSION), API_ID, API_HASH) as client:
        await client.get_dialogs()
        try:
            destino = int(GRUPO)
        except ValueError:
            destino = GRUPO
        entidad = await client.get_entity(destino)

        full_chat = await obtener_full_chat(client, entidad)
        if not full_chat:
            print("No se pudo obtener información del chat.")
            return

        # 1. Crear o reutilizar la sala de voz
        if not full_chat.call:
            try:
                await client(
                    CreateGroupCallRequest(
                        peer=entidad,
                        random_id=random.randint(1, 2**31 - 1),
                        title=TITULO,
                    )
                )
                print("Chat de voz creado exitosamente.")
                await asyncio.sleep(2)
                full_chat = await obtener_full_chat(client, entidad)
            except RPCError as e:
                print("Error creando el chat de voz:", type(e).__name__, e)
        else:
            print("Ya existía un chat de voz activo en el grupo.")

        # Enviar aviso inicial
        avisar_con_bot(AVISO)

        if not full_chat or not full_chat.call:
            print("No hay llamada disponible para monitorear.")
            return

        input_call = full_chat.call
        print(f"Iniciando monitoreo de la sala (Máx: {DURACION_MAXIMA_MINUTOS} min)...")

        participantes = {}
        segundos_totales = 0
        tiempo_limite_segundos = DURACION_MAXIMA_MINUTOS * 60

        # 2. Bucle de Monitoreo en Vivo
        while segundos_totales < tiempo_limite_segundos:
            await asyncio.sleep(INTERVALO_SONDEO_SEGUNDOS)
            segundos_totales += INTERVALO_SONDEO_SEGUNDOS
            ahora = datetime.now(tz_col)

            try:
                call_info = await client(GetGroupCallRequest(call=input_call, limit=100))
            except RPCError as e:
                print("Llamada finalizada externamente o error:", type(e).__name__, e)
                break

            users_dict = {u.id: u for u in getattr(call_info, "users", [])}
            activos_en_tick = set()

            for p in getattr(call_info, "participants", []):
                if getattr(p, "left", False):
                    continue
                uid = getattr(p.peer, "user_id", None) if isinstance(getattr(p, "peer", None), PeerUser) else None
                if not uid:
                    continue

                activos_en_tick.add(uid)
                u = users_dict.get(uid)
                nombre = f"{u.first_name or ''} {u.last_name or ''}".strip() if u else "Usuario"
                username = u.username or "" if u else ""

                # Detección de micrófono
                hablo_ahora = False
                if getattr(p, "active_date", None):
                    hablo_ahora = True
                elif getattr(p, "muted", True) is False and getattr(p, "volume", 0) and getattr(p, "volume", 0) > 0:
                    hablo_ahora = True

                if uid not in participantes:
                    participantes[uid] = {
                        "id": uid,
                        "nombre": nombre,
                        "username": username,
                        "primera_entrada": ahora,
                        "ultima_salida": ahora,
                        "segundos_acumulados": 0.0,
                        "activo_ahora": True,
                        "ultimo_check": ahora,
                        "reconexiones": 0,
                        "hablo": hablo_ahora,
                        "orden_llegada": len(participantes) + 1,
                    }
                else:
                    part = participantes[uid]
                    if nombre != "Usuario" and part["nombre"] == "Usuario":
                        part["nombre"] = nombre
                    if username and not part["username"]:
                        part["username"] = username
                    if hablo_ahora:
                        part["hablo"] = True

                    if not part["activo_ahora"]:
                        part["reconexiones"] += 1
                        part["activo_ahora"] = True
                        part["ultimo_check"] = ahora
                    else:
                        delta = (ahora - part["ultimo_check"]).total_seconds()
                        part["segundos_acumulados"] += max(0.0, delta)
                        part["ultimo_check"] = ahora
                        part["ultima_salida"] = ahora

            # Marcar desconectados
            for uid, part in participantes.items():
                if uid not in activos_en_tick and part["activo_ahora"]:
                    part["activo_ahora"] = False
                    part["ultima_salida"] = ahora

            # Regla de Auto-Cierre por inactividad
            minutos_transcurridos = segundos_totales // 60
            if minutos_transcurridos >= AUTO_CIERRE_ESPERA_MINUTOS and len(activos_en_tick) < AUTO_CIERRE_MIN_USUARIOS:
                print(f"Auto-cierre: Menos de {AUTO_CIERRE_MIN_USUARIOS} usuarios tras {minutos_transcurridos} min.")
                break

        # 3. Finalización y Consolidación de Asistencia
        fin_llamada = datetime.now(tz_col)
        duracion_reunion_minutos = max(1, int(round((fin_llamada - inicio_llamada).total_seconds() / 60)))

        for uid, part in participantes.items():
            if part["activo_ahora"]:
                delta = (fin_llamada - part["ultimo_check"]).total_seconds()
                part["segundos_acumulados"] += max(0.0, delta)
                part["ultima_salida"] = fin_llamada
                part["activo_ahora"] = False

        # Intentar cerrar la sala de voz en Telegram
        try:
            await client(DiscardGroupCallRequest(call=input_call))
            print("Chat de voz cerrado al finalizar la reunión.")
        except Exception as e:
            print("Nota al cerrar llamada:", e)

        # 4. Procesamiento de Puntos y Gamificación
        db_puntos = cargar_puntos()
        usuarios_db = db_puntos.setdefault("usuarios", {})

        asistentes_validos = []
        visitas_fugaces = []

        for uid, part in participantes.items():
            mins = int(round(part["segundos_acumulados"] / 60))
            part["minutos"] = mins
            pct = int(round((part["segundos_acumulados"] / (duracion_reunion_minutos * 60)) * 100))
            part["porcentaje"] = min(100, pct)

            if mins >= MIN_MINUTOS_ASISTENCIA:
                # Cálculo de puntos
                minutos_desde_inicio = (part["primera_entrada"] - inicio_llamada).total_seconds() / 60
                pts_puntualidad = 25 if minutos_desde_inicio <= 5 else (15 if minutos_desde_inicio <= 10 else 5)
                pts_permanencia = 50 if pct >= 80 else (35 if mins >= 45 else (20 if mins >= 20 else 10))
                pts_voz = 20 if part["hablo"] else 0

                # Racha de días
                str_uid = str(uid)
                u_data = usuarios_db.get(str_uid, {
                    "id": uid,
                    "nombre": part["nombre"],
                    "username": part["username"],
                    "puntos_totales": 0,
                    "racha_actual": 0,
                    "mejor_racha": 0,
                    "ultima_fecha": "",
                    "asistencias_totales": 0,
                    "minutos_totales": 0,
                })

                ultima_f = u_data.get("ultima_fecha", "")
                racha = u_data.get("racha_actual", 0)
                if ultima_f == fecha_ayer:
                    racha += 1
                    pts_racha = min(racha * 5, 25)
                elif ultima_f == fecha_hoy:
                    pts_racha = 0
                else:
                    racha = 1
                    pts_racha = 0

                total_hoy = pts_puntualidad + pts_permanencia + pts_voz + pts_racha

                u_data["nombre"] = part["nombre"]
                u_data["username"] = part["username"]
                u_data["puntos_totales"] = u_data.get("puntos_totales", 0) + total_hoy
                u_data["racha_actual"] = racha
                u_data["mejor_racha"] = max(u_data.get("mejor_racha", 0), racha)
                u_data["ultima_fecha"] = fecha_hoy
                u_data["asistencias_totales"] = u_data.get("asistencias_totales", 0) + 1
                u_data["minutos_totales"] = u_data.get("minutos_totales", 0) + mins
                usuarios_db[str_uid] = u_data

                part["pts_hoy"] = total_hoy
                part["pts_totales"] = u_data["puntos_totales"]
                part["racha"] = racha
                part["rango"] = obtener_rango(u_data["puntos_totales"])
                part["desglose"] = (
                    f"⏰ Puntual +{pts_puntualidad} | "
                    f"🌟 Perm +{pts_permanencia}"
                    + (f" | 🎙️ Voz +{pts_voz}" if pts_voz else "")
                    + (f" | 🔥 Racha +{pts_racha}" if pts_racha else "")
                )
                asistentes_validos.append(part)
            else:
                visitas_fugaces.append(part)

        db_puntos["actualizado"] = fecha_hoy
        guardar_puntos(db_puntos)

        # 5. Generar Archivo CSV
        os.makedirs(CARPETA_ASISTENCIAS, exist_ok=True)
        ruta_csv = os.path.join(CARPETA_ASISTENCIAS, f"asistencia_{fecha_hoy}.csv")
        with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID", "Nombre", "Usuario", "Entrada", "Salida", "Minutos",
                "% Reunion", "Hablo", "Reconexiones", "Puntos Hoy", "Puntos Totales", "Rango"
            ])
            for part in asistentes_validos:
                writer.writerow([
                    part["id"], part["nombre"], f"@{part['username']}" if part["username"] else "",
                    part["primera_entrada"].strftime("%I:%M:%S %p"),
                    part["ultima_salida"].strftime("%I:%M:%S %p"),
                    part["minutos"], f"{part['porcentaje']}%",
                    "Si" if part["hablo"] else "No", part["reconexiones"],
                    part.get("pts_hoy", 0), part.get("pts_totales", 0), part.get("rango", "")
                ])
            for part in visitas_fugaces:
                writer.writerow([
                    part["id"], part["nombre"], f"@{part['username']}" if part["username"] else "",
                    part["primera_entrada"].strftime("%I:%M:%S %p"),
                    part["ultima_salida"].strftime("%I:%M:%S %p"),
                    part["minutos"], f"{part['porcentaje']}%",
                    "Si" if part["hablo"] else "No", part["reconexiones"],
                    0, usuarios_db.get(str(part["id"]), {}).get("puntos_totales", 0), "Visita Fugaz"
                ])

        # 6. Construir y Enviar Reportes
        asistentes_validos.sort(key=lambda x: x.get("pts_hoy", 0), reverse=True)
        podio_puntuales = sorted(participantes.values(), key=lambda x: x["primera_entrada"])[:3]

        # Top 5 General
        ranking_general = sorted(usuarios_db.values(), key=lambda x: x.get("puntos_totales", 0), reverse=True)[:5]

        # Reporte Público para el Grupo
        lineas_pub = [
            "📊 **REPORTE DE ASISTENCIA Y PUNTOS — LLAMADA DIARIA**",
            f"🗓️ Fecha: {inicio_llamada.strftime('%d/%m/%Y')}",
            f"⏱️ Duración: {duracion_reunion_minutos} min | 👥 Asistentes: {len(asistentes_validos)} personas\n",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "🏆 **PODIO DE PUNTUALIDAD:**",
        ]
        medallas = ["🥇", "🥈", "🥉"]
        for idx, p in enumerate(podio_puntuales):
            tag = f"(@{p['username']})" if p["username"] else ""
            lineas_pub.append(f"{medallas[idx]} {p['nombre']} {tag} — {p['primera_entrada'].strftime('%I:%M:%S %p')}")

        lineas_pub.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lineas_pub.append("🌟 **PUNTOS GANADOS HOY:**")
        if asistentes_validos:
            for p in asistentes_validos:
                tag = f"(@{p['username']})" if p["username"] else ""
                icono_voz = "🎙️" if p["hablo"] else "🎧"
                estrella = "⭐ " if p["porcentaje"] >= 80 else "• "
                lineas_pub.append(
                    f"{estrella}**{p['nombre']}** {tag} ➔ **+{p['pts_hoy']} pts** {icono_voz}\n"
                    f"   [{p['desglose']}] — Racha: 🔥 {p['racha']} días ({p['rango']})"
                )
        else:
            lineas_pub.append("No se registraron asistencias que cumplieran el tiempo mínimo hoy.")

        lineas_pub.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lineas_pub.append("🏆 **TOP 5 GENERAL DE LA COMUNIDAD:**")
        for i, u in enumerate(ranking_general, start=1):
            lineas_pub.append(f"{i}. {obtener_rango(u['puntos_totales'])} **{u['nombre']}** — {u['puntos_totales']} pts")

        lineas_pub.append("\n🎙️ = Participó hablando  |  🎧 = Oyente")
        lineas_pub.append("¡Gracias a todos por participar! Nos vemos mañana a las 7:56 PM.")

        reporte_publico = "\n".join(lineas_pub)
        avisar_con_bot(reporte_publico)

        # Reporte Privado para el Dueño
        lineas_priv = [
            "🔐 **REPORTE ADMINISTRATIVO DETALLADO (SOLO DUEÑO)**",
            f"📅 Fecha: {fecha_hoy} | ⏰ {inicio_llamada.strftime('%I:%M:%S %p')} – {fin_llamada.strftime('%I:%M:%S %p')}",
            f"⏱️ Duración total: {duracion_reunion_minutos} minutos",
            f"👥 Total que entraron: {len(participantes)} | ✅ Válidos: {len(asistentes_validos)} | ⚠️ Fugaces: {len(visitas_fugaces)}\n",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "📋 **DESGLOSE INDIVIDUAL DE ASISTENTES:**",
        ]
        for i, p in enumerate(asistentes_validos, start=1):
            tag = f"@{p['username']}" if p['username'] else "Sin alias"
            mic = "🎙️ Habló activamente" if p["hablo"] else "🎧 Solo oyente"
            lineas_priv.append(
                f"{i}. **{p['nombre']}** (ID: `{p['id']}` | {tag})\n"
                f"   • Conexión: {p['primera_entrada'].strftime('%I:%M:%S %p')} ➔ {p['ultima_salida'].strftime('%I:%M:%S %p')}\n"
                f"   • Tiempo: {p['minutos']} min ({p['porcentaje']}% de la sesión) | Caídas: {p['reconexiones']}\n"
                f"   • Micrófono: {mic} | Hoy: +{p['pts_hoy']} pts (Acumulado: {p['pts_totales']})"
            )

        if visitas_fugaces:
            lineas_priv.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lineas_priv.append(f"⚠️ **VISITAS FUGACES (<{MIN_MINUTOS_ASISTENCIA} min):**")
            for p in visitas_fugaces:
                tag = f"@{p['username']}" if p['username'] else "Sin alias"
                lineas_priv.append(f"• {p['nombre']} (ID: `{p['id']}` | {tag}) — {p['minutos']} min (Salió {p['ultima_salida'].strftime('%I:%M:%S %p')})")

        lineas_priv.append(f"\n📎 Se generó el archivo de auditoría: `{ruta_csv}`")
        reporte_privado = "\n".join(lineas_priv)

        # Enviar reporte y archivo privado al dueño (Mensajes Guardados)
        me = await client.get_me()
        if me:
            try:
                await client.send_message(me.id, reporte_privado)
                if os.path.exists(ruta_csv):
                    await client.send_file(
                        me.id,
                        ruta_csv,
                        caption=f"📊 Archivo de Asistencia y Puntos - {fecha_hoy}",
                    )
                print("Reporte privado y archivo CSV enviados a Mensajes Guardados del dueño.")
            except Exception as e:
                print("Error enviando reporte privado al dueño:", e)


if __name__ == "__main__":
    asyncio.run(main())
