import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'print(f"Error enviando mensaje a {chat_id}:", e)' in line:
        fallback_code = """        print(f"Error enviando mensaje a {chat_id}:", e)
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
                sys.stdout.flush()
"""
        lines[i] = fallback_code
        break

with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
