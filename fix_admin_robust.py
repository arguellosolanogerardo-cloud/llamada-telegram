import io

with open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add checked_admins_cache
content = content.replace('admin_ids = set()', 'admin_ids = set()\n        checked_admins_cache = set()')

new_logic = """                # Moderación de micrófonos en vivo
                if uid not in admin_ids and uid not in checked_admins_cache:
                    checked_admins_cache.add(uid)
                    try:
                        perm = await client.get_permissions(entidad, uid)
                        if getattr(perm, 'is_admin', False) or getattr(perm, 'is_creator', False):
                            admin_ids.add(uid)
                    except Exception:
                        pass
                
                if uid in admin_ids:"""

content = content.replace('                # Moderación de micrófonos en vivo\n                if uid in admin_ids:', new_logic)

with open('llamada.py', 'w', encoding='utf-8') as f:
    f.write(content)
