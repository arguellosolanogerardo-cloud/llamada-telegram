import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

insert_idx = 0
for i, line in enumerate(lines):
    if 'if self.path in ("/aviso", "/aviso_previo", "/recordatorio"):' in line:
        insert_idx = i
        break

code_to_insert = """        if self.path == "/diag":
            import urllib.request, json
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as r:
                    res = json.loads(r.read().decode())
                texto = f"Token_Start: {BOT_TOKEN[:8] if BOT_TOKEN else 'None'} | Bot: {res}"
            except Exception as e:
                texto = f"Token_Start: {BOT_TOKEN[:8] if BOT_TOKEN else 'None'} | Error: {e}"
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(texto.encode("utf-8"))
            return
"""

if insert_idx > 0:
    lines.insert(insert_idx, code_to_insert)

with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
