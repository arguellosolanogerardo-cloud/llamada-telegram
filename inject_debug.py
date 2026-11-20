import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

lines.insert(1136, '                print("Recibido update:", update.get("update_id"))\n')

with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
