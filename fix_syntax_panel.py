import io

with open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if '**PANEL DE CONTROL DE SALA**' in line and not line.strip().endswith('"""') and not '\\n' in line:
        if i+2 < len(lines):
            lines[i] = '                            enviar_mensaje(chat_id, "ðŸŽ› **PANEL DE CONTROL DE SALA**\\n*(Solo funciona durante la llamada)*\\nPresiona los botones para controlar el bot en tiempo real:", reply_markup=teclado_panel)\n'
            lines[i+1] = ""
            lines[i+2] = ""
        break

with open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
