import os

# 1. Recuperar el archivo limpio antes del commit e682cd6 (el commit b1c4273 tiene la última versión sana)
os.system("git checkout b1c4273 -- bot_comandos.py")

with open("bot_comandos.py", "r", encoding="utf-8") as f:
    content = f.read()

# 2. Re-aplicar las pequeñas correcciones estructurales posteriores:
# Fix: flush stdout
content = content.replace('print("Error en bucle de comandos:", e)\n            time.sleep(3)', 
                          'print("Error en bucle de comandos:", e)\n            import sys; sys.stdout.flush()\n            time.sleep(3)')
content = content.replace('print(f"Error enviando mensaje a {chat_id}:", e)',
'''print(f"Error enviando mensaje a {chat_id}:", e)
        import sys; sys.stdout.flush()
        if "parse_mode" in payload:
            del payload["parse_mode"]
            datos = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    res_data = json.loads(r.read().decode())
                    m_id = res_data.get("result", {}).get("message_id")
                    if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                        registrar_msg_bot(m_id)
                    return m_id
            except Exception as e2:
                print(f"Error re-enviando sin formato a {chat_id}:", e2)
                sys.stdout.flush()''')

# Fix: check webhook endpoint
content = content.replace('url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"', 'url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"')

# Add diag endpoint
diag_code = '''
        if self.path == "/diag":
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            t_len = len(BOT_TOKEN) if BOT_TOKEN else 0
            diag_txt = (
                f"=== DIAGNOSTICO DEL ENTORNO ===\\n"
                f"BOT_TOKEN set: {bool(BOT_TOKEN)} (len: {t_len})\\n"
                f"TG_API_ID set: {bool(TG_API_ID)}\\n"
                f"TG_API_HASH set: {bool(TG_API_HASH)}\\n"
                f"CHAT_ID: {CHAT_ID}\\n"
                f"TG_GROUP: {TG_GROUP}\\n"
            )
            self.wfile.write(diag_txt.encode("utf-8"))
            return
'''
content = content.replace('        if self.path in ("/aviso", "/aviso_previo", "/recordatorio"):', diag_code.lstrip('\n') + '        if self.path in ("/aviso", "/aviso_previo", "/recordatorio"):')

with open("bot_comandos.py", "w", encoding="utf-8") as f:
    f.write(content)
