import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    content = f.read()

progreso_cmd = '''                elif cmd == "/panel":'''
progreso_cmd_rep = '''                elif cmd in ("/progreso",):
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "🚫 Solo admins.", reply_to_message_id=msg_id)
                        continue
                    estado_path = os.path.join("data", "estado_descarga.json")
                    if os.path.exists(estado_path):
                        import json
                        try:
                            with open(estado_path, "r", encoding="utf-8") as f_est:
                                st = json.load(f_est)
                            barra = "█" * int(st['porcentaje'] / 5) + "░" * (20 - int(st['porcentaje'] / 5))
                            msg_prog = f"📊 **Progreso Biblioteca Universal**\\n\\n"
                            msg_prog += f"[{barra}] {st['porcentaje']}%\\n\\n"
                            msg_prog += f"✅ **Completados:** {st['completados']} / {st['total']}\\n"
                            msg_prog += f"⏳ **Tiempo restante:** {st['tiempo_estimado_restante']}\\n"
                            msg_prog += f"⚠️ **Imprevistos (Errores):** {st['errores']}\\n"
                            msg_prog += f"🔄 **Última actualización:** {st['ultima_actualizacion']}"
                            enviar_mensaje(chat_id, msg_prog, reply_to_message_id=msg_id)
                        except:
                            enviar_mensaje(chat_id, "⚠️ Error leyendo el estado de la descarga.", reply_to_message_id=msg_id)
                    else:
                        enviar_mensaje(chat_id, "⏳ El escáner aún no ha generado el archivo de progreso. Posiblemente siga en la Fase 1 (Inventario).", reply_to_message_id=msg_id)
                    continue
                elif cmd == "/panel":'''

if progreso_cmd in content:
    content = content.replace(progreso_cmd, progreso_cmd_rep)
    with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Injected /progreso successfully")
else:
    print("Could not find targets")
