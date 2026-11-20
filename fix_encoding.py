import io

with open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

replacements = {
    'ðŸŽ™ï¸': '🎙️',
    'â”': '▬',
    'ðŸ“…': '📅',
    'â°': '⏰',
    'ðŸ‘¥': '👥',
    'â³': '⏳',
    'ðŸ’¬': '💬',
    'ðŸ§˜': '🧘',
    'ðŸŸ¢': '🟢',
    'botÃ³n': 'botón',
    'dinÃ¡mico': 'dinámico',
    'PreparaciÃ³n': 'Preparación',
    'meditaciÃ³n': 'meditación',
    'MeditaciÃ³n': 'Meditación',
    'OraciÃ³n': 'Oración',
    'ðŸ•Šï¸': '🕊️'
}

for k, v in replacements.items():
    content = content.replace(k, v)

with open('llamada.py', 'w', encoding='utf-8') as f:
    f.write(content)
