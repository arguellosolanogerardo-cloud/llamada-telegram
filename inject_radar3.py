import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re
content = re.sub(r'(\s+)if cb_data\.startswith\("panel_"\):', r'''\1if cb_data.startswith("ytmp3_"):
\1    vid = cb_data.split("_")[1]
\1    url_yt = f"https://www.youtube.com/watch?v={vid}"
\1    import urllib.request
\1    try:
\1        url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
\1        urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "⏳ Descargando MP3 desde YouTube... (Esto tomará 1 minuto)", "show_alert": True}).encode(), headers={"Content-Type": "application/json"}), timeout=10)
\1    except: pass
\1    def descargar_y_enviar(user_id):
\1        import subprocess
\1        import os
\1        tmp_path = os.path.join("data", f"tmp_{vid}.mp3")
\1        cmd = ["python", "-m", "yt_dlp", "-x", "--audio-format", "mp3", "--audio-quality", "5", "-o", tmp_path, url_yt]
\1        subprocess.run(cmd)
\1        if os.path.exists(tmp_path):
\1            try:
\1                url_doc = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
\1                import requests
\1                with open(tmp_path, "rb") as f_aud:
\1                    requests.post(url_doc, data={"chat_id": user_id, "caption": "🎧 Aquí tienes el audio solicitado."}, files={"document": f_aud})
\1                os.remove(tmp_path)
\1            except: pass
\1    import threading
\1    threading.Thread(target=descargar_y_enviar, args=(update["callback_query"]["from"].get("id"),)).start()
\1    continue
\1elif cb_data.startswith("yttarea_"):
\1    vid = cb_data.split("_")[1]
\1    url_yt = f"https://www.youtube.com/watch?v={vid}"
\1    user_id_cb = update["callback_query"]["from"].get("id")
\1    if user_id_cb not in admins_set:
\1        try:
\1            url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
\1            urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "🚫 Solo administradores.", "show_alert": True}).encode(), headers={"Content-Type": "application/json"}), timeout=10)
\1        except: pass
\1    else:
\1        try:
\1            url_ans = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
\1            urllib.request.urlopen(urllib.request.Request(url_ans, data=json.dumps({"callback_query_id": cb_id, "text": "✅ Programando audio para esta noche..."}).encode(), headers={"Content-Type": "application/json"}), timeout=10)
\1        except: pass
\1        enviar_mensaje(chat_id_cb, f"/tarea {url_yt}")
\1    continue
\1elif cb_data.startswith("panel_"):''', content)

start_logic = '''        print("Iniciando bot de comandos en polling...")'''
start_logic_rep = '''        print("Iniciando bot de comandos en polling...")
        try:
            from radar_youtube import iniciar_radar
            iniciar_radar(enviar_mensaje, CHAT_ID)
        except Exception as e:
            print("No se pudo iniciar el radar:", e)'''

content = content.replace(start_logic, start_logic_rep)

with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Injected via regex!")
