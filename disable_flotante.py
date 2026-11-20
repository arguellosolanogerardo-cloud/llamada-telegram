import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = 'if _TAREA_FLOTANTE["contador"] >= 8:'
replacement = 'if False:'
content = content.replace(target, replacement)

with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.write(content)
