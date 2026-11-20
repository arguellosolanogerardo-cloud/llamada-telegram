import io

with open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

lines[1211] = "# import threading\n"

with open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
