import io

with open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Revert non_admin_cache logic
bad_logic = """                # Moderación de micrófonos en vivo
                if uid not in admin_ids and uid not in non_admin_cache:
                    try:
                        perm = await client.get_permissions(entidad, uid)
                        if getattr(perm, 'is_admin', False) or getattr(perm, 'is_creator', False):
                            admin_ids.add(uid)
                        else:
                            non_admin_cache.add(uid)
                    except Exception:
                        non_admin_cache.add(uid)

                if uid in admin_ids:"""

good_logic = """                # Moderación de micrófonos en vivo
                if uid in admin_ids:"""

content = content.replace(bad_logic, good_logic)
content = content.replace('admin_ids = set()\n        non_admin_cache = set()', 'admin_ids = set()')

# Now add a background task to refresh admins periodically.
# Let's find "async def main_loop():" or similar, or just before "try:" block of the main loop.
# Wait, we can add it around line 1085 (after initial admin load).

admin_loop_code = """
        async def background_admin_refresher():
            while True:
                await asyncio.sleep(120)
                try:
                    if isinstance(entidad, (Channel, Chat)):
                        async for admin in client.iter_participants(entidad, filter=ChannelParticipantsAdmins):
                            admin_ids.add(admin.id)
                except Exception:
                    pass
        client.loop.create_task(background_admin_refresher())
"""

# Let's insert it after print("Nota obteniendo administradores:", e)
insert_target = """        except Exception as e:
            print("Nota obteniendo administradores:", e)"""

content = content.replace(insert_target, insert_target + admin_loop_code)

with open('llamada.py', 'w', encoding='utf-8') as f:
    f.write(content)
