import io

with open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

lines[1723] = '                    enviar_mensaje(chat_id, "ðŸŽ› **PANEL DE CONTROL DE SALA**\\n*(Solo funciona durante la llamada)*\\nPresiona los botones para controlar el bot en tiempo real:", reply_markup=teclado_panel)\n'

with open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
