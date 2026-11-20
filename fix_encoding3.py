import io
import re

with open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Dictionary of direct replacements
replacements = {
    'Â¡SALA EN VIVO! TOCAR PARA ENTRAR': '¡SALA EN VIVO! TOCAR PARA ENTRAR',
    'ðŸ †': '🏆',
    'ðŸ“œ': '📜',
    'ORACIÃ“N': 'ORACIÓN',
    'ðŸŽ§': '🎧',
    'ðŸ“–': '📖',
    'GUÃ A': 'GUÍA',
    'DÃ A': 'DÍA',
    'ðŸ¤«': '🤫',
    'oraciÃ³n': 'oración',
    'micrÃ³fonos': 'micrófonos',
    'concentraciÃ³n': 'concentración',
    'â€¢': '•',
    'â€“': '–',
    'Â«': '«',
    'Â»': '»',
    'ðŸ’¬': '💬'
}

# Regex to catch the weird clock and hourglass things with hidden bytes
content = re.sub(r'â.*?°', '⏰', content)
content = re.sub(r'â.*?³', '⏳', content)

for k, v in replacements.items():
    content = content.replace(k, v)

with open('llamada.py', 'w', encoding='utf-8') as f:
    f.write(content)
