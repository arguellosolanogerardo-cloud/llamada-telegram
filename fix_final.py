with open('bot_comandos.py', 'r', encoding='utf-8') as f:
    text = f.read()

replacements = {
    'ðŸ¤– Bot de comandos iniciado': '🤖 Bot de comandos iniciado',
    'ðŸ\x9d\x8d Buscando audio para': '🔍 Buscando audio para',
    'ðŸ” *Buscando en la Biblioteca': '🔍 *Buscando en la Biblioteca',
    'ðŸ” Buscando audio para': '🔍 Buscando audio para',
    'ðŸ•Šï¸\x8f TAREA DEL DÃ\x8dA': '🕊️ TAREA DEL DÍA',
    'ðŸ•Šï¸\x8f': '🕊️',
    'ðŸ\x99': '🙏',
    'ðŸ“„': '📄',
    'ðŸŽ™ï¸\x8f': '🎙️',
    'âœ‹': '✋',
    'ðŸ¤': '🤝',
    'ðŸ”‡': '🔇',
    'ðŸ“‹': '📋',
    'ðŸ”‹': '🔋',
    'ðŸ“¶': '📶',
    'âš™ï¸\x8f': '⚙️',
    'ðŸ”': '🔁',
    'ðŸŽ§': '🎧',
    'âœ¨': '✨',
    'ðŸ‘¤': '👤',
    'ðŸ—“ï¸\x8f': '🗓️',
    'ðŸ†': '🏆',
    'ðŸ¥‡': '🥇',
    'ðŸ¥ˆ': '🥈',
    'ðŸ¥‰': '🥉',
    'ðŸ’¡': '💡',
    'â„¹ï¸\x8f': 'ℹ️',
    'ðŸ“': '📝',
    'ðŸ§˜': '🧘',
    'â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”': '━━━━━━━━━━━━━━━━━━━━━━━━━━━━',
    'ðŸ”” RECORDATORIO: SALA DE VOZ EN 30 MINUTOS â°': '🔔 RECORDATORIO: SALA DE VOZ EN 30 MINUTOS ⏰',
    'ðŸ•— Apertura de sala:': '🕗 Apertura de sala:'
}

for bad, good in replacements.items():
    text = text.replace(bad, good)

with open('bot_comandos.py', 'w', encoding='utf-8', newline='') as f:
    f.write(text)
print('Done replacements!')
