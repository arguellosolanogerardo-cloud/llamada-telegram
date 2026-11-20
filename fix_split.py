import io

with io.open('escanear_youtube.py', 'r', encoding='utf-8') as f:
    content = f.read()

bad_split = '''    for line in result.stdout.strip().split("\\n"):
        if not line: continue
        try:
            data = json.loads(line)'''
good_split = '''    # Fix splitting logic using regex or strict splitlines
    import re
    # Encontramos todos los objetos JSON separados por \n o \r\n
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line: continue
        if not line.startswith('{') or not line.endswith('}'): continue
        try:
            data = json.loads(line)'''

if bad_split in content:
    content = content.replace(bad_split, good_split)
    with io.open('escanear_youtube.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed split logic")
else:
    print("Could not find targets")
