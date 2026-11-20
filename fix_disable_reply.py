import io

with open('llamada.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

lines[2382] = "                                # " + lines[2382].lstrip()
lines[2383] = "                                # " + lines[2383].lstrip()
lines[2387] = "                                # " + lines[2387].lstrip()
lines[2388] = "                                # " + lines[2388].lstrip()

with open('llamada.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
