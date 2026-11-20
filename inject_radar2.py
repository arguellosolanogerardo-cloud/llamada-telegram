import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    content = f.read()

cb_logic = '''                    if cb_data.startswith("panel_"):'''
cb_logic_rep = '''                    if cb_data.startswith("ytmp3_"):
                        vid = cb_data.split("_")[1]
                        url_yt = f"https://www.youtube.com/watch?v={vid}"
                        import urllib.request
                        try:
                            url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                            urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "⏳ Descargando MP3 desde YouTube... (Esto tomará 1 minuto)", "show_alert": True}).encode(), headers={"Content-Type": "application/json"}), timeout=10)
                        except: pass
                        
                        def descargar_y_enviar():
                            import subprocess
                            import os
                            tmp_path = os.path.join("data", f"tmp_{vid}.mp3")
                            cmd = ["python", "-m", "yt_dlp", "-x", "--audio-format", "mp3", "--audio-quality", "5", "-o", tmp_path, url_yt]
                            subprocess.run(cmd)
                            if os.path.exists(tmp_path):
                                try:
                                    url_doc = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
                                    import requests
                                    with open(tmp_path, "rb") as f_aud:
                                        requests.post(url_doc, data={"chat_id": update["callback_query"]["from"].get("id"), "caption": "🎧 Aquí tienes el audio solicitado."}, files={"document": f_aud})
                                    os.remove(tmp_path)
                                except: pass
                        import threading
                        threading.Thread(target=descargar_y_enviar).start()
                        continue

                    elif cb_data.startswith("yttarea_"):
                        vid = cb_data.split("_")[1]
                        url_yt = f"https://www.youtube.com/watch?v={vid}"
                        user_id_cb = update["callback_query"]["from"].get("id")
                        if user_id_cb not in admins_set:
                            try:
                                url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                                urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "🚫 Solo administradores.", "show_alert": True}).encode(), headers={"Content-Type": "application/json"}), timeout=10)
                            except: pass
                        else:
                            try:
                                url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                                urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "✅ Programando audio para esta noche..."}).encode(), headers={"Content-Type": "application/json"}), timeout=10)
                            except: pass
                            enviar_mensaje(chat_id_cb, f"/tarea {url_yt}")
                        continue
                    
                    elif cb_data.startswith("panel_"):'''

start_logic = '''        print("Iniciando bot de comandos en polling...")'''
start_logic_rep = '''        print("Iniciando bot de comandos en polling...")
        try:
            from radar_youtube import iniciar_radar
            iniciar_radar(enviar_mensaje, CHAT_ID)
        except Exception as e:
            print("No se pudo iniciar el radar:", e)'''

if cb_logic in content and start_logic in content:
    content = content.replace(cb_logic, cb_logic_rep)
    content = content.replace(start_logic, start_logic_rep)
    with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Injected radar successfully")
else:
    print("Could not find targets")
