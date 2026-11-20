import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in [1154, 1269, 1270, 1377]:
    lines[i] = '# ' + lines[i]

with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
