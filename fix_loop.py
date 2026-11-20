import io

with open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = "if sender_id not in admin_ids or sender_id == me.id :"
replacement = "if sender_id not in admin_ids or sender_id == me.id or (BOT_ID and sender_id == BOT_ID):"
content = content.replace(target, replacement)

with open('llamada.py', 'w', encoding='utf-8') as f:
    f.write(content)
