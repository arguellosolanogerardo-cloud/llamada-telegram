import io
import re

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    content = f.read()

target_loop = '''            for update in res.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg:
                    continue'''

replacement_loop = '''            for update in res.get("result", []):
                offset = update["update_id"] + 1
                
                if "callback_query" in update:
                    import json
                    cb = update["callback_query"]
                    cb_id = cb.get("id")
                    cb_data = cb.get("data", "")
                    msg_cb = cb.get("message", {})
                    chat_id_cb = msg_cb.get("chat", {}).get("id")
                    
                    if cb_data.startswith("panel_"):
                        import urllib.request
                        import time
                        accion = cb_data.split("_")[1]
                        comando = ""
                        if accion == "play": comando = "/reproducir"
                        elif accion == "pausa": comando = "/pausar"
                        elif accion == "nextaudio": comando = "/saltaraudio"
                        elif accion == "nextturno": comando = "/siguiente"
                        elif accion == "desmutear": comando = "/desmuteartodos"
                        elif accion == "limpiar": comando = "/limpiarsala"
                        elif accion == "stoprec": comando = "/detenergrabacion"
                        
                        if comando and chat_id_cb:
                            m_id_cmd = enviar_mensaje(chat_id_cb, comando)
                            if m_id_cmd:
                                time.sleep(0.5)
                                eliminar_mensaje(chat_id_cb, m_id_cmd)
                        
                        try:
                            url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                            req_ans = urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": f"Ejecutado: {comando}"}).encode(), headers={"Content-Type": "application/json"})
                            urllib.request.urlopen(req_ans, timeout=10)
                        except Exception:
                            pass
                    continue
                
                msg = update.get("message")
                if not msg:
                    continue'''

panel_cmd = '''                elif cmd in ("/aviso", "/recordatorio", "/preparacion", "/aviso30min"):'''
panel_cmd_replacement = '''                elif cmd == "/panel":
                    if not es_mensaje_de_admin(msg, chat_id):
                        enviar_mensaje(chat_id, "🚫 Solo los administradores pueden usar el panel de control.", reply_to_message_id=msg_id)
                        continue
                    teclado_panel = {
                        "inline_keyboard": [
                            [{"text": "▶️ Play", "callback_data": "panel_play"}, {"text": "⏸️ Pausa", "callback_data": "panel_pausa"}, {"text": "⏭️ Siguiente", "callback_data": "panel_nextaudio"}],
                            [{"text": "🎤 Sig. Turno", "callback_data": "panel_nextturno"}, {"text": "🔓 Abrir Micros", "callback_data": "panel_desmutear"}],
                            [{"text": "🧹 Limpiar Sala", "callback_data": "panel_limpiar"}, {"text": "⏹️ Fin Grabación", "callback_data": "panel_stoprec"}]
                        ]
                    }
                    enviar_mensaje(chat_id, "🎛 **PANEL DE CONTROL DE SALA**\n*(Solo funciona durante la llamada)*\nPresiona los botones para controlar el bot en tiempo real:", reply_markup=teclado_panel)
                    eliminar_mensaje(chat_id, msg_id)
                elif cmd in ("/aviso", "/recordatorio", "/preparacion", "/aviso30min"):'''

if target_loop in content and panel_cmd in content:
    content = content.replace(target_loop, replacement_loop)
    content = content.replace(panel_cmd, panel_cmd_replacement)
    with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Injected successfully")
else:
    print("Could not find targets")
