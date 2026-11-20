import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    content = f.read()

global_vars = '''COLA_LOGS = []'''
global_vars_rep = '''COLA_LOGS = []
_TAREA_FLOTANTE = {"msg_id": None, "contador": 0, "texto": "", "reply_markup": None, "chat_id": None}'''

loop_start = '''                msg = update.get("message")
                if not msg:
                    continue'''
loop_start_rep = '''                msg = update.get("message")
                if not msg:
                    continue
                
                # --- LOGICA MENSAJE FLOTANTE ---
                chat_id_msg = msg.get("chat", {}).get("id")
                if chat_id_msg and _TAREA_FLOTANTE["msg_id"] and chat_id_msg == _TAREA_FLOTANTE["chat_id"]:
                    from_id = msg.get("from", {}).get("id")
                    if not BOT_ID or from_id != BOT_ID:
                        from zoneinfo import ZoneInfo
                        from datetime import datetime
                        ahora_flot = datetime.now(ZoneInfo("America/Bogota"))
                        minutos_flot = ahora_flot.hour * 60 + ahora_flot.minute
                        # Solo flota hasta las 7:26 PM (19*60 + 26 = 1166)
                        if minutos_flot < 1166:
                            _TAREA_FLOTANTE["contador"] += 1
                            if _TAREA_FLOTANTE["contador"] >= 8:
                                eliminar_mensaje(chat_id_msg, _TAREA_FLOTANTE["msg_id"])
                                nuevo_id = enviar_mensaje(chat_id_msg, _TAREA_FLOTANTE["texto"], reply_markup=_TAREA_FLOTANTE["reply_markup"])
                                if nuevo_id:
                                    _TAREA_FLOTANTE["msg_id"] = nuevo_id
                                    _TAREA_FLOTANTE["contador"] = 0
                # -------------------------------
'''

tarea_cmd_1 = '''                            anuncio = generar_anuncio_tarea(audios_procesados if len(audios_procesados) > 1 else info_cat, fecha_admin)
                            teclado_actual = armar_teclado_audio(chat_id, msg_id_audio_final, numero_tarea=num, tipo_tarea=tipo_audio, audios_lista=audios_procesados)
                            enviar_mensaje(chat_id, anuncio, reply_markup=teclado_actual)'''
tarea_cmd_1_rep = '''                            anuncio = generar_anuncio_tarea(audios_procesados if len(audios_procesados) > 1 else info_cat, fecha_admin)
                            teclado_actual = armar_teclado_audio(chat_id, msg_id_audio_final, numero_tarea=num, tipo_tarea=tipo_audio, audios_lista=audios_procesados)
                            m_id = enviar_mensaje(chat_id, anuncio, reply_markup=teclado_actual)
                            if m_id:
                                _TAREA_FLOTANTE.update({"msg_id": m_id, "contador": 0, "texto": anuncio, "reply_markup": teclado_actual, "chat_id": chat_id})'''

tarea_cmd_2 = '''                            anuncio = generar_anuncio_tarea(info_cat, fecha_admin)
                            teclado = armar_teclado_audio(chat_id, msg_id_audio, numero_tarea=info_cat.get('numero'), tipo_tarea=info_cat.get('tipo'))
                            enviar_mensaje(chat_id, anuncio, reply_markup=teclado)'''
tarea_cmd_2_rep = '''                            anuncio = generar_anuncio_tarea(info_cat, fecha_admin)
                            teclado = armar_teclado_audio(chat_id, msg_id_audio, numero_tarea=info_cat.get('numero'), tipo_tarea=info_cat.get('tipo'))
                            m_id = enviar_mensaje(chat_id, anuncio, reply_markup=teclado)
                            if m_id:
                                _TAREA_FLOTANTE.update({"msg_id": m_id, "contador": 0, "texto": anuncio, "reply_markup": teclado, "chat_id": chat_id})'''

if global_vars in content and loop_start in content and tarea_cmd_1 in content and tarea_cmd_2 in content:
    content = content.replace(global_vars, global_vars_rep)
    content = content.replace(loop_start, loop_start_rep)
    content = content.replace(tarea_cmd_1, tarea_cmd_1_rep)
    content = content.replace(tarea_cmd_2, tarea_cmd_2_rep)
    with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Injected flotante successfully")
else:
    print("Could not find targets")
    if global_vars not in content: print("no global vars")
    if loop_start not in content: print("no loop start")
    if tarea_cmd_1 not in content: print("no tarea_cmd_1")
    if tarea_cmd_2 not in content: print("no tarea_cmd_2")
