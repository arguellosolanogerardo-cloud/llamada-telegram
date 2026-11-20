import io
import re

with open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

command_code = """
        @client.on(events.NewMessage(chats=entidad, pattern=r'(?i)^/soyadmin'))
        async def cmd_soyadmin(event):
            uid = event.sender_id
            try:
                perm = await client.get_permissions(entidad, uid)
                if getattr(perm, 'is_admin', False) or getattr(perm, 'is_creator', False):
                    admin_ids.add(uid)
                    await event.reply("✅ Listo. He forzado la actualización de tus permisos. Tu micrófono ya no se bloqueará.")
                else:
                    await event.reply("❌ Telegram dice que no eres administrador.")
            except Exception as e:
                await event.reply(f"⚠️ Error al verificar permisos: {e}")
                # Fallback: if they can see admin commands, maybe just add them anyway?
                # No, that's insecure.
"""

# Insert this after "async def comandos_naturales_admin"
content = re.sub(
    r'(async def comandos_naturales_admin\(event\):)', 
    command_code.strip() + '\n\n        @client.on(events.NewMessage(chats=entidad))\n        \\1', 
    content
)

with open('llamada.py', 'w', encoding='utf-8') as f:
    f.write(content)
