import io

with open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add non_admin_cache = set() below admin_ids = set()
content = content.replace(
    'admin_ids = set()',
    'admin_ids = set()\n        non_admin_cache = set()'
)

# 2. Add dynamic check before line "if uid in admin_ids:"
check_logic = """                # Moderación de micrófonos en vivo
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

content = content.replace(
    '                # Moderación de micrófonos en vivo\n                if uid in admin_ids:',
    check_logic
)

with open('llamada.py', 'w', encoding='utf-8') as f:
    f.write(content)
