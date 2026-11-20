import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re
injection = '''import os
import zipfile

db_path = os.path.join("data", "biblioteca_conocimiento_universal.db")
zip_path = os.path.join("data", "biblioteca.zip")
if not os.path.exists(db_path) and os.path.exists(zip_path):
    try:
        print("Descomprimiendo la Biblioteca del Conocimiento Universal...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall("data")
    except Exception as e:
        print("Error descomprimiendo BD:", e)

import asyncio'''

content = content.replace("import asyncio", injection)

with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Injected unzip logic!")
