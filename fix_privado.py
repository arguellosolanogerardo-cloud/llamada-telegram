with open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if line.strip() == 'continue' and '# ------------------------------------' in lines[i+1]:
        if len(line) - len(line.lstrip()) == 20: # Unindented continue
            lines[i] = '                        continue\n'
            break

with open('bot_comandos.py', 'w', encoding='utf-8', newline='') as f:
    for line in lines:
        f.write(line)
