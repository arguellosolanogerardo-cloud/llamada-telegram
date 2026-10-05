import asyncio
import csv
from datetime import datetime, timedelta
import json
import os
import random
import urllib.request
from zoneinfo import ZoneInfo

from telethon import TelegramClient, events
from telethon.errors import RPCError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.functions.phone import (
    CreateGroupCallRequest,
    DiscardGroupCallRequest,
    GetGroupCallRequest,
    ToggleGroupCallSettingsRequest,
)
from telethon.tl.types import Channel, ChannelParticipantsAdmins, Chat, PeerUser

try:
    from pytgcalls import PyTgCalls
    PYTGCALLS_AVAILABLE = True
except ImportError:
    PYTGCALLS_AVAILABLE = False

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
DURACION_MAXIMA_MINUTOS = int(os.environ.get("DURACION_MAXIMA_MINUTOS", "360"))  # Hasta 6 horas
INTERVALO_SONDEO_SEGUNDOS = int(os.environ.get("INTERVALO_SONDEO_SEGUNDOS", "20"))
MIN_MINUTOS_ASISTENCIA = int(os.environ.get("MIN_MINUTOS_ASISTENCIA", "10"))
AUTO_CIERRE_MIN_USUARIOS = int(os.environ.get("AUTO_CIERRE_MIN_USUARIOS", "2"))
AUTO_CIERRE_ESPERA_MINUTOS = int(os.environ.get("AUTO_CIERRE_ESPERA_MINUTOS", "45"))

RUTA_PUNTOS = os.path.join("data", "puntos.json")
CARPETA_ASISTENCIAS = os.path.join("data", "asistencias")
CARPETA_MEDITACIONES = os.path.join("data", "meditaciones")


def hora_california() -> str:
    bogota = ZoneInfo("America/Bogota")
    california = ZoneInfo("America/Los_Angeles")
    hoy = datetime.now(bogota).replace(hour=19, minute=56, second=0, microsecond=0)
    return hoy.astimezone(california).strftime("%I:%M %p").lstrip("0").lower()


async def obtener_url_llamada(client, entidad, full_chat) -> str | None:
    link_env = os.environ.get("GROUP_INVITE_LINK", "").strip()
    if link_env:
        return f"{link_env}?videochat" if not link_env.endswith("?videochat") else link_env

    if GRUPO.startswith("@"):
        return f"https://t.me/{GRUPO.lstrip('@')}?videochat"
    elif GRUPO.startswith("https://t.me/"):
        return f"{GRUPO}?videochat"

    # Si la entidad tiene username público
    username = getattr(entidad, "username", None)
    if username:
        return f"https://t.me/{username}?videochat"

    # Si el chat tiene enlace exportado
    exported = getattr(full_chat, "exported_invite", None)
    if exported and getattr(exported, "link", None):
        return f"{exported.link}?videochat"

    # Si no, exportar enlace de invitación con Telethon
    try:
        from telethon.tl.functions.messages import ExportChatInviteRequest
        inv = await client(ExportChatInviteRequest(peer=entidad))
        if getattr(inv, "link", None):
            return f"{inv.link}?videochat"
    except Exception as e:
        print("Nota resolviendo enlace de invitacion:", e)

    return None


def obtener_username_bot() -> str | None:
    if not BOT_TOKEN:
        return None
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        req = urllib.request.Request(url, headers={"User-Agent": "BotLlamadas"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            if data.get("ok"):
                return data["result"].get("username")
    except Exception as e:
        print("Nota obteniendo username del bot:", e)
    return None


def avisar_con_bot(texto: str, boton_url: str = None) -> None:
    if not BOT_TOKEN:
        return
    texto = texto.replace("{CA}", hora_california())
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": texto}

    if boton_url:
        inline_keyboard = [
            [{"text": "🟢 ¡SALA EN VIVO! TOCAR PARA ENTRAR 🎙️", "url": boton_url}]
        ]
        bot_user = obtener_username_bot()
        if bot_user:
            inline_keyboard.append([
                {"text": "🏆 Ver Ranking", "url": f"https://t.me/{bot_user}?start=ranking"},
                {"text": "📜 Reglas y Puntos", "url": f"https://t.me/{bot_user}?start=reglas"}
            ])
        payload["reply_markup"] = {"inline_keyboard": inline_keyboard}

    datos = json.dumps(payload).encode()
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
    return {"version": 2, "usuarios": {}}


def guardar_puntos(data: dict) -> None:
    os.makedirs(os.path.dirname(RUTA_PUNTOS), exist_ok=True)
    with open(RUTA_PUNTOS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generar_texto_miperfil(user_id: int, db_puntos: dict, user_nombre: str = "", username: str = "") -> str:
    usuarios = db_puntos.get("usuarios", {})
    str_uid = str(user_id)
    u = usuarios.get(str_uid)
    if not u:
        nombre = user_nombre or "Compañero"
        return (
            f"👤 **Perfil de Asistencia:** {nombre}\n\n"
            f"Aún no registras asistencias válidas en las llamadas.\n"
            f"¡Únete hoy a las 7:56 PM para ganar tus primeros puntos y subir de rango!"
        )
    nombre = u.get("nombre", user_nombre or "Usuario")
    pts_mes = u.get("puntos_mes", u.get("puntos_totales", 0))
    pts_tot = u.get("puntos_totales", 0)
    rango = obtener_rango(pts_tot)
    racha = u.get("racha_actual", 0)
    asistencias_mes = u.get("asistencias_mes", 0)
    asistencias_tot = u.get("asistencias_totales", 0)
    medallas = u.get("medallas", [])
    txt_medallas = "\n• " + "\n• ".join(medallas) if medallas else "Ninguna aún"

    return (
        f"👤 **FICHA DE USUARIO: {nombre}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎖️ **Rango actual:** {rango}\n"
        f"🏆 **Puntos del mes:** {pts_mes} pts\n"
        f"⭐ **Puntos históricos:** {pts_tot} pts\n"
        f"🔥 **Racha actual:** {racha} días consecutivos\n"
        f"📅 **Asistencias:** {asistencias_mes} este mes ({asistencias_tot} en total)\n\n"
        f"🏅 **Medallas obtenidas:**{txt_medallas}"
    )


def generar_texto_ranking(db_puntos: dict) -> str:
    usuarios = db_puntos.get("usuarios", {})
    if not usuarios:
        return "🏆 **Ranking Mensual:** Aún no hay registros de asistencia este mes."

    top = sorted(usuarios.values(), key=lambda x: x.get("puntos_mes", x.get("puntos_totales", 0)), reverse=True)[:10]
    lineas = [
        "🏆 **TOP 10 DE ASISTENCIA Y PUNTOS (ESTE MES)** 🏆",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    medallas_top = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
    for i, u in enumerate(top):
        pts = u.get("puntos_mes", u.get("puntos_totales", 0))
        rango = obtener_rango(u.get("puntos_totales", 0))
        medallas = " ".join([m.split()[0] for m in u.get("medallas", [])])
        lineas.append(f"{medallas_top[i]} {rango} **{u['nombre']}** — {pts} pts {medallas}".strip())

    lineas.append("\n💡 Escribe `/puntos` para ver tus estadísticas personales.")
    return "\n".join(lineas)


def generar_texto_reglas() -> str:
    return (
        "📜 **SISTEMA DE PUNTOS Y REGLAS DE LA COMUNIDAD**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Cada noche a las 7:56 PM se abre la llamada diaria. ¡Participa y suma puntos!\n\n"
        "⏰ **PUNTUALIDAD:**\n"
        "• Entrar en los primeros 5 min: **+25 pts**\n"
        "• Entrar entre min 5 y 10: **+15 pts**\n\n"
        "🌟 **PERMANENCIA:**\n"
        "• Asistencia completa (>= 80% de la sesión): **+50 pts**\n"
        "• Asistencia parcial: **+20 a +35 pts**\n\n"
        "🎙️ **MICRÓFONO / VOZ:**\n"
        "• Hablar y aportar activamente: **+20 pts**\n\n"
        "🧘 **MEDITACIÓN DIARIA (8:32 PM):**\n"
        "• Participar en la meditación: **+30 pts**\n\n"
        "🔥 **RACHAS:**\n"
        "• Asistir días seguidos: **+5 pts extra por día consecutivo**\n\n"
        "🏅 **MEDALLAS ESPECIALES:**\n"
        "• 🛡️ *Puntualidad de Hierro:* 5 días seguidos en el podio (Top 3 primeros).\n"
        "• 🎙️ *Voz de la Comunidad:* Hablar en 7 llamadas consecutivas.\n"
        "• 👑 *Centinela:* Asistir a más del 90% de las reuniones del mes.\n\n"
        "💎 **RANGOS:** Bronce (<250) | Plata (250+) | Oro (750+) | Diamante (1800+)\n"
        "¡Los 3 primeros del mes reciben mención de honor!"
    )


async def obtener_full_chat(client, entidad):
    if isinstance(entidad, Channel):
        full = await client(GetFullChannelRequest(entidad))
        return full.full_chat
    elif isinstance(entidad, Chat):
        full = await client(GetFullChatRequest(entidad.id))
        return full.full_chat
    return None


async def buscar_audio_meditacion(client, entidad, admin_ids) -> str | None:
    """Busca en los últimos 60 mensajes del grupo un audio de tarea publicado por administradores."""
    try:
        async for msg in client.iter_messages(entidad, limit=60):
            sender_id = msg.sender_id
            if sender_id not in admin_ids:
                continue

            texto = (msg.raw_text or "").upper()
            if "MEDITACION DE TAREA" in texto or "MEDITACIÓN DE TAREA" in texto:
                target_msg = msg
                es_audio = False
                if target_msg.audio or target_msg.voice:
                    es_audio = True
                elif target_msg.document and (
                    (target_msg.document.mime_type and "audio" in target_msg.document.mime_type)
                    or any(getattr(a, "file_name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")) for a in getattr(target_msg.document, "attributes", []))
                ):
                    es_audio = True
                elif target_msg.is_reply:
                    reply = await target_msg.get_reply_message()
                    if reply and (reply.audio or reply.voice or (reply.document and (
                        (reply.document.mime_type and "audio" in reply.document.mime_type)
                        or any(getattr(a, "file_name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")) for a in getattr(reply.document, "attributes", []))
                    ))):
                        target_msg = reply
                        es_audio = True

                if es_audio:
                    os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
                    ruta = os.path.join(CARPETA_MEDITACIONES, "meditacion_hoy.mp3")
                    print(f"Descargando audio de meditación del mensaje ID {target_msg.id}...")
                    await client.download_media(target_msg, file=ruta)
                    print("Audio de meditación descargado exitosamente en:", ruta)
                    return ruta
    except Exception as e:
        print("Nota buscando audio de meditación:", e)
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

        # 0. Obtener IDs de Administradores
        admin_ids = set()
        me = await client.get_me()
        if me:
            admin_ids.add(me.id)
        if hasattr(entidad, "id"):
            admin_ids.add(entidad.id)

        try:
            if isinstance(entidad, (Channel, Chat)):
                async for admin in client.iter_participants(entidad, filter=ChannelParticipantsAdmins):
                    admin_ids.add(admin.id)
        except Exception as e:
            print("Nota obteniendo administradores:", e)

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

        # Enviar aviso inicial con panel interactivo
        url_llamada = await obtener_url_llamada(client, entidad, full_chat)
        print("Enlace de llamada obtenido para el botón:", url_llamada)
        avisar_con_bot(AVISO, boton_url=url_llamada)

        if not full_chat or not full_chat.call:
            print("No hay llamada disponible para monitorear.")
            return

        input_call = full_chat.call
        print(f"Iniciando monitoreo de la sala (Máx: {DURACION_MAXIMA_MINUTOS} min)...")

        # Iniciar servicio PyTgCalls si está disponible
        tgcalls = None
        if PYTGCALLS_AVAILABLE:
            try:
                tgcalls = PyTgCalls(client)
                await tgcalls.start()
                print("Servicio de audio PyTgCalls iniciado exitosamente.")
            except Exception as e:
                print("Nota iniciando PyTgCalls:", e)

        # Buscar si ya existe un audio de meditación subido hoy por administradores
        ruta_meditacion = await buscar_audio_meditacion(client, entidad, admin_ids)
        reproduciendo_meditacion = False
        reproduccion_iniciada = False
        aviso_meditacion_enviado = False
        meditacion_activa_hoy = False

        async def reproducir_meditacion():
            nonlocal reproduciendo_meditacion, meditacion_activa_hoy
            if not tgcalls or not ruta_meditacion or not os.path.exists(ruta_meditacion):
                return False
            try:
                # Silenciar a nuevos participantes para evitar ruidos de fondo
                try:
                    await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=True))
                except Exception:
                    pass

                await tgcalls.play(destino, ruta_meditacion)
                reproduciendo_meditacion = True
                meditacion_activa_hoy = True
                avisar_con_bot("▶️ **Iniciando reproducción de la meditación diaria en la sala de voz.**\n🧘 Por favor disfruten de su sesión en silencio.")
                return True
            except Exception as e:
                print("Error reproduciendo meditación:", e)
                return False

        # Configurar evento de fin de audio en PyTgCalls
        if tgcalls:
            try:
                from pytgcalls.types import StreamEnded
                @tgcalls.on_update()
                async def manejar_fin_stream(client_call, update):
                    if isinstance(update, StreamEnded):
                        nonlocal reproduciendo_meditacion
                        if reproduciendo_meditacion:
                            reproduciendo_meditacion = False
                            print("Reproducción de meditación concluida automáticamente.")
                            try:
                                await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
                            except Exception:
                                pass
                            avisar_con_bot("🧘✨ **La meditación ha concluido.**\nLos micrófonos han sido restablecidos. ¡Esperamos que hayan tenido una gran sesión!")
            except Exception as e:
                print("Nota configurando StreamEnded handler:", e)

        # Escuchar comandos de usuarios (/puntos, /ranking, /reglas, /ayuda)
        @client.on(events.NewMessage(pattern=r"^/(puntos|miperfil|ranking|top|ayuda|reglas|start)"))
        async def responder_comandos_en_vivo(event):
            partes = event.raw_text.strip().split()
            texto_cmd = partes[0].lower().split("@")[0]
            param = partes[1].lower() if len(partes) > 1 else ""
            db = cargar_puntos()
            sender = await event.get_sender()
            uid = sender.id if sender else event.sender_id
            nom = f"{getattr(sender, 'first_name', '') or ''} {getattr(sender, 'last_name', '') or ''}".strip()
            usr = getattr(sender, "username", "") or ""

            if texto_cmd in ("/puntos", "/miperfil"):
                resp = generar_texto_miperfil(uid, db, nom, usr)
            elif texto_cmd in ("/ranking", "/top") or (texto_cmd == "/start" and param == "ranking"):
                resp = generar_texto_ranking(db)
            else:
                resp = generar_texto_reglas()

            await event.reply(resp)

        # Escuchar controles de meditación exclusivos para administradores
        @client.on(events.NewMessage(pattern=r"^/(reproducir|play|pausar|pause|continuar|resume|detener|stop)"))
        async def controlar_meditacion_admin(event):
            sender = await event.get_sender()
            uid = sender.id if sender else event.sender_id
            if uid not in admin_ids:
                await event.reply("⛔ Solo los administradores pueden controlar la reproducción de la meditación.")
                return

            cmd = event.raw_text.strip().split()[0].lower().split("@")[0]
            if cmd in ("/reproducir", "/play"):
                nonlocal ruta_meditacion
                if not ruta_meditacion or not os.path.exists(ruta_meditacion):
                    ruta_meditacion = await buscar_audio_meditacion(client, entidad, admin_ids)
                if tgcalls and ruta_meditacion and os.path.exists(ruta_meditacion):
                    ok = await reproducir_meditacion()
                    if ok:
                        await event.reply("▶️ Reproduciendo meditación en la sala de voz...")
                    else:
                        await event.reply("❌ Error iniciando la reproducción de la meditación.")
                else:
                    await event.reply("⚠️ No se encontró ningún archivo de meditación de tarea disponible.")
            elif cmd in ("/pausar", "/pause"):
                if tgcalls:
                    try:
                        await tgcalls.pause(destino)
                        await event.reply("⏸️ Meditación pausada.")
                    except Exception as e:
                        await event.reply(f"Error al pausar: {e}")
            elif cmd in ("/continuar", "/resume"):
                if tgcalls:
                    try:
                        await tgcalls.resume(destino)
                        await event.reply("▶️ Meditación reanudada.")
                    except Exception as e:
                        await event.reply(f"Error al reanudar: {e}")
            elif cmd in ("/detener", "/stop"):
                if tgcalls:
                    try:
                        await tgcalls.leave_call(destino)
                        reproduciendo_meditacion = False
                        try:
                            await client(ToggleGroupCallSettingsRequest(call=input_call, join_muted=False))
                        except Exception:
                            pass
                        await event.reply("⏹️ Reproducción finalizada. Micrófonos restablecidos.")
                    except Exception as e:
                        await event.reply(f"Error al detener: {e}")

        # Escuchar si un admin sube la meditación de tarea en vivo
        @client.on(events.NewMessage(chats=entidad))
        async def detectar_nueva_meditacion(event):
            nonlocal ruta_meditacion
            sender_id = event.sender_id
            if sender_id not in admin_ids:
                return

            texto = (event.raw_text or "").upper()
            if "MEDITACION DE TAREA" in texto or "MEDITACIÓN DE TAREA" in texto:
                target_msg = event.message
                es_audio = False
                if target_msg.audio or target_msg.voice:
                    es_audio = True
                elif target_msg.document and (
                    (target_msg.document.mime_type and "audio" in target_msg.document.mime_type)
                    or any(getattr(a, "file_name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")) for a in getattr(target_msg.document, "attributes", []))
                ):
                    es_audio = True
                elif target_msg.is_reply:
                    reply = await target_msg.get_reply_message()
                    if reply and (reply.audio or reply.voice or (reply.document and (
                        (reply.document.mime_type and "audio" in reply.document.mime_type)
                        or any(getattr(a, "file_name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")) for a in getattr(reply.document, "attributes", []))
                    ))):
                        target_msg = reply
                        es_audio = True

                if es_audio:
                    os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
                    ruta = os.path.join(CARPETA_MEDITACIONES, "meditacion_hoy.mp3")
                    await client.download_media(target_msg, file=ruta)
                    ruta_meditacion = ruta
                    print("Nueva meditación recibida y guardada:", ruta)
                    await event.reply("✅ Meditación recibida. Programada para reproducirse hoy a las 8:32 PM en la sala de voz.")

        participantes = {}
        segundos_totales = 0
        tiempo_limite_segundos = DURACION_MAXIMA_MINUTOS * 60
        consecutivos_vacio = 0
        consecutivos_menos_de_dos = 0
        cerrado_por_admin = False
        motivo_cierre = "tiempo_limite"

        # 2. Bucle de Monitoreo en Vivo
        while segundos_totales < tiempo_limite_segundos:
            await asyncio.sleep(INTERVALO_SONDEO_SEGUNDOS)
            segundos_totales += INTERVALO_SONDEO_SEGUNDOS
            ahora = datetime.now(tz_col)

            # Control de hora para la Meditación Automática
            hora_col = ahora.hour
            min_col = ahora.minute

            if hora_col == 20 and min_col == 31 and not aviso_meditacion_enviado and ruta_meditacion and os.path.exists(ruta_meditacion):
                avisar_con_bot("🧘 **En 1 minuto dará inicio la meditación diaria.**\nPor favor silencien sus micrófonos y tomen una postura cómoda.")
                aviso_meditacion_enviado = True

            if hora_col == 20 and min_col >= 32 and not reproduccion_iniciada and ruta_meditacion and os.path.exists(ruta_meditacion):
                reproduccion_iniciada = True
                await reproducir_meditacion()

            try:
                call_info = await client(GetGroupCallRequest(call=input_call, limit=100))
            except RPCError as e:
                print("Llamada finalizada por un administrador o cerrada externamente:", type(e).__name__, e)
                cerrado_por_admin = True
                motivo_cierre = "admin"
                break
            except Exception as e:
                print("Error de conexión al consultar llamada:", e)
                await asyncio.sleep(2)
                try:
                    call_info = await client(GetGroupCallRequest(call=input_call, limit=100))
                except Exception:
                    cerrado_por_admin = True
                    motivo_cierre = "admin"
                    break

            if not getattr(call_info, "call", None):
                print("La llamada ya no se encuentra activa en Telegram.")
                cerrado_por_admin = True
                motivo_cierre = "admin"
                break

            # Cada 10 ciclos (~3 min), verificar el estado de la llamada en el chat
            if (segundos_totales // INTERVALO_SONDEO_SEGUNDOS) % 10 == 0:
                try:
                    fc = await obtener_full_chat(client, entidad)
                    if not fc or not fc.call or getattr(fc.call, "id", None) != getattr(input_call, "id", None):
                        print("El chat de voz fue finalizado por un administrador.")
                        cerrado_por_admin = True
                        motivo_cierre = "admin"
                        break
                except Exception as e:
                    print("Nota verificando chat:", e)

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
                        "meditacion_completada": reproduciendo_meditacion,
                    }
                else:
                    part = participantes[uid]
                    if nombre != "Usuario" and part["nombre"] == "Usuario":
                        part["nombre"] = nombre
                    if username and not part["username"]:
                        part["username"] = username
                    if hablo_ahora:
                        part["hablo"] = True
                    if reproduciendo_meditacion:
                        part["meditacion_completada"] = True

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

            # Reglas de Auto-Cierre inteligente:
            num_activos = len(activos_en_tick)
            minutos_transcurridos = segundos_totales // 60

            # Regla 1: Sala completamente vacía durante 2 min continuos (tras primeros 5 min)
            if minutos_transcurridos >= 5:
                if num_activos == 0:
                    consecutivos_vacio += 1
                    if consecutivos_vacio >= (120 // INTERVALO_SONDEO_SEGUNDOS):
                        print(f"Auto-cierre: Sala vacía durante 2 min continuos tras {minutos_transcurridos} min.")
                        motivo_cierre = "sala_vacia"
                        break
                else:
                    consecutivos_vacio = 0

            # Regla 2: Menos de 2 personas conectadas durante 3 min continuos (tras 45 min)
            if minutos_transcurridos >= AUTO_CIERRE_ESPERA_MINUTOS:
                if num_activos < AUTO_CIERRE_MIN_USUARIOS:
                    consecutivos_menos_de_dos += 1
                    if consecutivos_menos_de_dos >= (180 // INTERVALO_SONDEO_SEGUNDOS):
                        print(f"Auto-cierre: Menos de {AUTO_CIERRE_MIN_USUARIOS} usuarios tras {minutos_transcurridos} min.")
                        motivo_cierre = "pocos_usuarios"
                        break
                else:
                    consecutivos_menos_de_dos = 0

        # 3. Finalización y Consolidación de Asistencia
        fin_llamada = datetime.now(tz_col)
        duracion_reunion_minutos = max(1, int(round((fin_llamada - inicio_llamada).total_seconds() / 60)))

        for uid, part in participantes.items():
            if part["activo_ahora"]:
                delta = (fin_llamada - part["ultimo_check"]).total_seconds()
                part["segundos_acumulados"] += max(0.0, delta)
                part["ultima_salida"] = fin_llamada
                part["activo_ahora"] = False

        # Desconectar reproductor de PyTgCalls y cerrar sala
        if tgcalls:
            try:
                await tgcalls.leave_call(destino)
            except Exception:
                pass

        if not cerrado_por_admin:
            try:
                await client(DiscardGroupCallRequest(call=input_call))
                print("Chat de voz cerrado automáticamente por el bot al terminar la sesión.")
            except Exception as e:
                print("Nota al cerrar llamada:", e)

        # 4. Procesamiento de Puntos, Medallas, Meditación y Temporada Mensual
        db_puntos = cargar_puntos()
        mes_actual = inicio_llamada.strftime("%Y-%m")

        if db_puntos.get("mes_actual") != mes_actual:
            db_puntos["mes_actual"] = mes_actual
            db_puntos["total_llamadas_mes"] = 0
            for u in db_puntos.get("usuarios", {}).values():
                u["puntos_mes"] = 0
                u["asistencias_mes"] = 0
                u["minutos_mes"] = 0

        db_puntos["total_llamadas_mes"] = db_puntos.get("total_llamadas_mes", 0) + 1
        total_llamadas_mes = db_puntos["total_llamadas_mes"]

        usuarios_db = db_puntos.setdefault("usuarios", {})
        podio_puntuales = sorted(participantes.values(), key=lambda x: x["primera_entrada"])[:3]
        ids_podio = {p["id"] for p in podio_puntuales}

        asistentes_validos = []
        visitas_fugaces = []

        for uid, part in participantes.items():
            mins = int(round(part["segundos_acumulados"] / 60))
            part["minutos"] = mins
            pct = int(round((part["segundos_acumulados"] / (duracion_reunion_minutos * 60)) * 100))
            part["porcentaje"] = min(100, pct)

            if mins >= MIN_MINUTOS_ASISTENCIA:
                minutos_desde_inicio = (part["primera_entrada"] - inicio_llamada).total_seconds() / 60
                pts_puntualidad = 25 if minutos_desde_inicio <= 5 else (15 if minutos_desde_inicio <= 10 else 5)
                pts_permanencia = 50 if pct >= 80 else (35 if mins >= 45 else (20 if mins >= 20 else 10))
                pts_voz = 20 if part["hablo"] else 0
                pts_meditacion = 30 if part.get("meditacion_completada") else 0

                str_uid = str(uid)
                u_data = usuarios_db.get(str_uid, {
                    "id": uid,
                    "nombre": part["nombre"],
                    "username": part["username"],
                    "puntos_mes": 0,
                    "puntos_totales": 0,
                    "racha_actual": 0,
                    "mejor_racha": 0,
                    "racha_podio": 0,
                    "racha_voz": 0,
                    "asistencias_mes": 0,
                    "asistencias_totales": 0,
                    "minutos_mes": 0,
                    "minutos_totales": 0,
                    "medallas": [],
                    "ultima_fecha": "",
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

                if uid in ids_podio:
                    u_data["racha_podio"] = u_data.get("racha_podio", 0) + 1
                else:
                    u_data["racha_podio"] = 0

                if part["hablo"]:
                    u_data["racha_voz"] = u_data.get("racha_voz", 0) + 1
                else:
                    u_data["racha_voz"] = 0

                medallas_set = set(u_data.get("medallas", []))
                nuevas_medallas = []

                if u_data["racha_podio"] >= 5 and "🛡️ Puntualidad de Hierro" not in medallas_set:
                    medallas_set.add("🛡️ Puntualidad de Hierro")
                    nuevas_medallas.append("🛡️ Puntualidad de Hierro")

                if u_data["racha_voz"] >= 7 and "🎙️ Voz de la Comunidad" not in medallas_set:
                    medallas_set.add("🎙️ Voz de la Comunidad")
                    nuevas_medallas.append("🎙️ Voz de la Comunidad")

                asistencias_mes_actual = u_data.get("asistencias_mes", 0) + 1
                if total_llamadas_mes >= 10 and (asistencias_mes_actual / total_llamadas_mes) >= 0.90:
                    if "👑 Centinela" not in medallas_set:
                        medallas_set.add("👑 Centinela")
                        nuevas_medallas.append("👑 Centinela")

                u_data["medallas"] = list(medallas_set)

                total_hoy = pts_puntualidad + pts_permanencia + pts_voz + pts_racha + pts_meditacion

                u_data["nombre"] = part["nombre"]
                u_data["username"] = part["username"]
                u_data["puntos_mes"] = u_data.get("puntos_mes", 0) + total_hoy
                u_data["puntos_totales"] = u_data.get("puntos_totales", 0) + total_hoy
                u_data["racha_actual"] = racha
                u_data["mejor_racha"] = max(u_data.get("mejor_racha", 0), racha)
                u_data["ultima_fecha"] = fecha_hoy
                u_data["asistencias_mes"] = asistencias_mes_actual
                u_data["asistencias_totales"] = u_data.get("asistencias_totales", 0) + 1
                u_data["minutos_mes"] = u_data.get("minutos_mes", 0) + mins
                u_data["minutos_totales"] = u_data.get("minutos_totales", 0) + mins
                usuarios_db[str_uid] = u_data

                part["pts_hoy"] = total_hoy
                part["pts_mes"] = u_data["puntos_mes"]
                part["pts_totales"] = u_data["puntos_totales"]
                part["racha"] = racha
                part["rango"] = obtener_rango(u_data["puntos_totales"])
                part["nuevas_medallas"] = nuevas_medallas
                part["desglose"] = (
                    f"⏰ Puntual +{pts_puntualidad} | "
                    f"🌟 Perm +{pts_permanencia}"
                    + (f" | 🎙️ Voz +{pts_voz}" if pts_voz else "")
                    + (f" | 🧘 Medit +{pts_meditacion}" if pts_meditacion else "")
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
                "% Reunion", "Hablo", "Meditacion", "Reconexiones", "Puntos Hoy",
                "Puntos Mes", "Puntos Totales", "Rango", "Medallas"
            ])
            for part in asistentes_validos:
                u_info = usuarios_db.get(str(part["id"]), {})
                writer.writerow([
                    part["id"], part["nombre"], f"@{part['username']}" if part["username"] else "",
                    part["primera_entrada"].strftime("%I:%M:%S %p"),
                    part["ultima_salida"].strftime("%I:%M:%S %p"),
                    part["minutos"], f"{part['porcentaje']}%",
                    "Si" if part["hablo"] else "No",
                    "Si" if part.get("meditacion_completada") else "No",
                    part["reconexiones"],
                    part.get("pts_hoy", 0), part.get("pts_mes", 0),
                    part.get("pts_totales", 0), part.get("rango", ""),
                    " / ".join(u_info.get("medallas", []))
                ])
            for part in visitas_fugaces:
                writer.writerow([
                    part["id"], part["nombre"], f"@{part['username']}" if part["username"] else "",
                    part["primera_entrada"].strftime("%I:%M:%S %p"),
                    part["ultima_salida"].strftime("%I:%M:%S %p"),
                    part["minutos"], f"{part['porcentaje']}%",
                    "Si" if part["hablo"] else "No", "No", part["reconexiones"],
                    0, 0, usuarios_db.get(str(part["id"]), {}).get("puntos_totales", 0), "Visita Fugaz", ""
                ])

        # 6. Construir y Enviar Reportes
        asistentes_validos.sort(key=lambda x: x.get("pts_hoy", 0), reverse=True)
        ranking_mes = sorted(usuarios_db.values(), key=lambda x: x.get("puntos_mes", 0), reverse=True)[:5]
        es_fin_de_mes = (inicio_llamada + timedelta(days=1)).month != inicio_llamada.month

        lineas_pub = [
            "📊 **REPORTE DE ASISTENCIA Y PUNTOS — LLAMADA DIARIA**",
            f"🗓️ Fecha: {inicio_llamada.strftime('%d/%m/%Y')}",
            f"⏱️ Duración: {duracion_reunion_minutos} min | 👥 Asistentes: {len(asistentes_validos)} personas\n",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "🏆 **PODIO DE PUNTUALIDAD:**",
        ]
        medallas_podio = ["🥇", "🥈", "🥉"]
        for idx, p in enumerate(podio_puntuales):
            tag = f"(@{p['username']})" if p["username"] else ""
            lineas_pub.append(f"{medallas_podio[idx]} {p['nombre']} {tag} — {p['primera_entrada'].strftime('%I:%M:%S %p')}")

        lineas_pub.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lineas_pub.append("🌟 **PUNTOS GANADOS HOY:**")
        if asistentes_validos:
            for p in asistentes_validos:
                tag = f"(@{p['username']})" if p["username"] else ""
                icono_voz = "🎙️" if p["hablo"] else "🎧"
                estrella = "⭐ " if p["porcentaje"] >= 80 else "• "
                aviso_medalla = f"\n   🎉 ¡Nueva medalla: {', '.join(p['nuevas_medallas'])}!" if p.get("nuevas_medallas") else ""
                lineas_pub.append(
                    f"{estrella}**{p['nombre']}** {tag} ➔ **+{p['pts_hoy']} pts** {icono_voz}\n"
                    f"   [{p['desglose']}] — Racha: 🔥 {p['racha']} días ({p['rango']}){aviso_medalla}"
                )
        else:
            lineas_pub.append("No se registraron asistencias que cumplieran el tiempo mínimo hoy.")

        if es_fin_de_mes:
            lineas_pub.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lineas_pub.append("👑 **🏆 CUADRO DE HONOR — CAMPEONES DEL MES 🏆** 👑")
            campeones_mes = sorted(usuarios_db.values(), key=lambda x: x.get("puntos_mes", 0), reverse=True)[:3]
            titulos = ["🥇 CAMPEÓN DEL MES", "🥈 SUBCAMPEÓN", "🥉 TERCER PUESTO"]
            for idx, c in enumerate(campeones_mes):
                lineas_pub.append(f"{titulos[idx]}: **{c['nombre']}** con {c.get('puntos_mes', 0)} pts")
            lineas_pub.append("✨ ¡Felicitaciones a los ganadores de la temporada!")

        lineas_pub.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lineas_pub.append("🏆 **TOP 5 DEL MES (TABLA GENERAL):**")
        for i, u in enumerate(ranking_mes, start=1):
            meds = " ".join([m.split()[0] for m in u.get("medallas", [])])
            lineas_pub.append(f"{i}. {obtener_rango(u.get('puntos_totales', 0))} **{u['nombre']}** — {u.get('puntos_mes', 0)} pts {meds}".strip())

        lineas_pub.append("\n🎙️ = Participó hablando  |  🎧 = Oyente | 🧘 = Meditación")
        lineas_pub.append("💡 Comandos disponibles: `/puntos` | `/ranking` | `/reglas`")
        lineas_pub.append("¡Gracias a todos por participar! Nos vemos mañana a las 7:56 PM.")

        reporte_publico = "\n".join(lineas_pub)
        avisar_con_bot(reporte_publico)

        # Enviar notificación privada personalizada a cada asistente
        if BOT_TOKEN and asistentes_validos:
            print("Enviando resúmenes individuales privados a asistentes...")
            for p in asistentes_validos:
                try:
                    meds_p = p.get("nuevas_medallas", [])
                    txt_nuevas_meds = f"\n🎖️ **¡Nueva medalla desbloqueada!** {', '.join(meds_p)}" if meds_p else ""
                    txt_privado_usuario = (
                        f"👋 ¡Hola **{p['nombre']}**!\n\n"
                        f"🎉 **Resumen de tu llamada de hoy:**\n"
                        f"• Tiempo conectado: **{p['minutos']} min** ({p['porcentaje']}% de la sesión)\n"
                        f"• Puntos sumados hoy: **+{p['pts_hoy']} pts**\n"
                        f"  _{p['desglose']}_\n"
                        f"• Puntos del mes: **{p['pts_mes']} pts** (Histórico: {p['pts_totales']})\n"
                        f"• Rango actual: **{p['rango']}**\n"
                        f"• Racha diaria: **🔥 {p['racha']} días consecutivos**\n"
                        f"{txt_nuevas_meds}\n"
                        f"✨ ¡Gracias por tu compromiso y asistencia! Nos vemos mañana a las 7:56 PM."
                    )
                    url_usr = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                    datos_usr = json.dumps({
                        "chat_id": p["id"],
                        "text": txt_privado_usuario,
                        "parse_mode": "Markdown",
                    }).encode()
                    req_usr = urllib.request.Request(url_usr, data=datos_usr, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req_usr, timeout=5) as r:
                        pass
                except Exception:
                    pass

        # Reporte Privado para el Dueño
        lineas_priv = [
            "🔐 **REPORTE ADMINISTRATIVO DETALLADO (SOLO DUEÑO)**",
            f"📅 Fecha: {fecha_hoy} | ⏰ {inicio_llamada.strftime('%I:%M:%S %p')} – {fin_llamada.strftime('%I:%M:%S %p')}",
            f"⏱️ Duración total: {duracion_reunion_minutos} minutos (Motivo cierre: {motivo_cierre})",
            f"🧘 Meditación diaria reproducida: {'Sí' if meditacion_activa_hoy else 'No'}",
            f"👥 Total que entraron: {len(participantes)} | ✅ Válidos: {len(asistentes_validos)} | ⚠️ Fugaces: {len(visitas_fugaces)}\n",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "📋 **DESGLOSE INDIVIDUAL DE ASISTENTES:**",
        ]
        for i, p in enumerate(asistentes_validos, start=1):
            tag = f"@{p['username']}" if p['username'] else "Sin alias"
            mic = "🎙️ Habló activamente" if p["hablo"] else "🎧 Solo oyente"
            med_txt = " | 🧘 Asistió a meditación" if p.get("meditacion_completada") else ""
            u_info = usuarios_db.get(str(p["id"]), {})
            meds_txt = ", ".join(u_info.get("medallas", [])) or "Ninguna"
            lineas_priv.append(
                f"{i}. **{p['nombre']}** (ID: `{p['id']}` | {tag})\n"
                f"   • Conexión: {p['primera_entrada'].strftime('%I:%M:%S %p')} ➔ {p['ultima_salida'].strftime('%I:%M:%S %p')}\n"
                f"   • Tiempo: {p['minutos']} min ({p['porcentaje']}% de sesión) | Caídas: {p['reconexiones']}\n"
                f"   • Micrófono: {mic}{med_txt} | Hoy: +{p['pts_hoy']} pts (Mes: {p['pts_mes']} | Histórico: {p['pts_totales']})\n"
                f"   • Medallas: {meds_txt}"
            )

        if visitas_fugaces:
            lineas_priv.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lineas_priv.append(f"⚠️ **VISITAS FUGACES (<{MIN_MINUTOS_ASISTENCIA} min):**")
            for p in visitas_fugaces:
                tag = f"@{p['username']}" if p['username'] else "Sin alias"
                lineas_priv.append(f"• {p['nombre']} (ID: `{p['id']}` | {tag}) — {p['minutos']} min (Salió {p['ultima_salida'].strftime('%I:%M:%S %p')})")

        lineas_priv.append(f"\n📎 Se generó el archivo de auditoría: `{ruta_csv}`")
        reporte_privado = "\n".join(lineas_priv)

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
