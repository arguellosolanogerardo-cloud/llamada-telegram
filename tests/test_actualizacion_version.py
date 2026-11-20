"""
Prueba de simulación de actualización y control de versión:
- Caso 1: DB existe en versión antigua (v1) y llega un zip nuevo (v2). -> Re-descomprime.
- Caso 2: DB y zip están en la misma versión. -> No re-descomprime (rápido).
- Caso 3: mtime del zip es más reciente. -> Re-descomprime.
"""
import os
import sys
import json
import shutil
import zipfile
import sqlite3
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEMP_DIR = os.path.join("tests", "temp_version_sim")
os.makedirs(TEMP_DIR, exist_ok=True)

test_db = os.path.join(TEMP_DIR, "biblioteca_v2.db")
test_zip = os.path.join(TEMP_DIR, "biblioteca_v2.zip")

def logica_arranque_actualizacion(db_path, zip_path):
    descomprimio = False
    if not os.path.exists(zip_path):
        return False
    debe_descomprimir = False
    if not os.path.exists(db_path):
        debe_descomprimir = True
    else:
        if os.path.getmtime(zip_path) > os.path.getmtime(db_path):
            debe_descomprimir = True
        else:
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    if "version.json" in zf.namelist():
                        v_zip = int(json.loads(zf.read("version.json").decode("utf-8")).get("version", 0))
                    else:
                        v_zip = 0
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                c.execute("PRAGMA user_version")
                v_db = c.fetchone()[0]
                conn.close()
                if v_zip > 0 and v_db != v_zip:
                    debe_descomprimir = True
            except Exception:
                pass
    if debe_descomprimir:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(os.path.dirname(db_path))
        descomprimio = True
    return descomprimio

print("=" * 75)
print("TEST DE CONTROL DE VERSIÓN Y ACTUALIZACIÓN AUTOMÁTICA")
print("=" * 75)

# Paso 1: Crear DB inicial con versión 1
conn = sqlite3.connect(test_db)
conn.execute("PRAGMA user_version = 1")
conn.execute("CREATE TABLE IF NOT EXISTS info (txt TEXT)")
conn.execute("INSERT INTO info VALUES ('version_1_original')")
conn.commit()
conn.close()

# Crear DB versión 2 y empaquetar en test_zip
db_v2_temp = os.path.join(TEMP_DIR, "db_v2_temp.db")
conn_v2 = sqlite3.connect(db_v2_temp)
conn_v2.execute("PRAGMA user_version = 2")
conn_v2.execute("CREATE TABLE IF NOT EXISTS info (txt TEXT)")
conn_v2.execute("INSERT INTO info VALUES ('version_2_actualizada')")
conn_v2.commit()
conn_v2.close()

with zipfile.ZipFile(test_zip, 'w') as zf:
    zf.write(db_v2_temp, arcname="biblioteca_v2.db")
    zf.writestr("version.json", json.dumps({"version": 2, "name": "2.0.0"}))
os.remove(db_v2_temp)

# Igualar mtime para probar la detección por versión PRAGMA
now = time.time()
os.utime(test_db, (now, now))
os.utime(test_zip, (now - 100, now - 100)) # zip con mtime anterior a propósito

print("\nCaso 1: DB en disco tiene user_version=1 y ZIP tiene version=2 (mtime zip más viejo)")
descomprimio = logica_arranque_actualizacion(test_db, test_zip)
conn = sqlite3.connect(test_db)
c = conn.cursor()
c.execute("PRAGMA user_version")
uv = c.fetchone()[0]
c.execute("SELECT txt FROM info")
contenido = c.fetchone()[0]
conn.close()

print(f"  • ¿Re-descomprimió? {descomprimio}")
print(f"  • user_version en DB ahora: {uv} (esperado: 2)")
print(f"  • Contenido en DB ahora: '{contenido}' (esperado: 'version_2_actualizada')")
assert uv == 2 and contenido == "version_2_actualizada", "Fallo en Caso 1"
print("  => CASO 1 EXITOSO.")

print("\nCaso 2: DB y ZIP en la misma versión (v2)")
os.utime(test_zip, (now - 100, now - 100))
descomprimio = logica_arranque_actualizacion(test_db, test_zip)
print(f"  • ¿Re-descomprimió? {descomprimio} (esperado: False, para no perder tiempo al reiniciar)")
assert not descomprimio, "Fallo en Caso 2"
print("  => CASO 2 EXITOSO.")

print("\nCaso 3: mtime del ZIP es más reciente")
os.utime(test_zip, (now + 50, now + 50))
descomprimio = logica_arranque_actualizacion(test_db, test_zip)
print(f"  • ¿Re-descomprimió? {descomprimio} (esperado: True)")
assert descomprimio, "Fallo en Caso 3"
print("  => CASO 3 EXITOSO.")

shutil.rmtree(TEMP_DIR)
print("\n" + "=" * 75)
print("TODAS LAS PRUEBAS DE CONTROL DE VERSIÓN PASARON CON ÉXITO.")
print("=" * 75)
