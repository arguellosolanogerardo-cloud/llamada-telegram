import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'print("Error en bucle de comandos:", e)' in line:
        lines.insert(i+1, '        import sys; sys.stdout.flush()\n')
        break

with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
