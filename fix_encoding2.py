import io

with open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

replacements = {
    'â °': '⏰',
    'â ³': '⏳',
    '▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ▬ ': '▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬'
}

for k, v in replacements.items():
    content = content.replace(k, v)

with open('llamada.py', 'w', encoding='utf-8') as f:
    f.write(content)
