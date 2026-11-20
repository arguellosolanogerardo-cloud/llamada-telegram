import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'print(f"Error al enviar mensaje a {chat_id}: {e}")' in line:
        lines.insert(i+1, '            import sys; sys.stdout.flush()\n')
    if 'print(f"Error re-enviando sin formato: {e2}")' in line:
        lines.insert(i+1, '                    import sys; sys.stdout.flush()\n')

with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
