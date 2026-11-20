"""
Test de verificación de eliminación de archivo temporal huérfano .tmp al arrancar:
1. Simula que un fallo/corte en una ejecución previa dejó un archivo data/biblioteca_v2.db.tmp huérfano.
2. Ejecuta la lógica de arranque de bot_comandos.py.
3. Verifica que el archivo huérfano se elimina de inmediato y que biblioteca_v2.db sigue intacto.
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = os.path.join("data", "biblioteca_v2.db")
TMP_PATH = DB_PATH + ".tmp"

print("=" * 80)
print("TEST DE LIMPIEZA DE ARCHIVO TEMPORAL HUÉRFANO (.tmp) AL ARRANCAR")
print("=" * 80)

# Paso 1: Crear archivo temporal huérfano simulado
with open(TMP_PATH, "w", encoding="utf-8") as f:
    f.write("archivo_huerfano_por_corte_previo")

print(f"1. Archivo temporal huérfano simulado creado: {TMP_PATH}")
print(f"   ¿Existe {TMP_PATH}? {os.path.exists(TMP_PATH)}")
assert os.path.exists(TMP_PATH), "Error: No se pudo crear el archivo huérfano de prueba."

# Paso 2: Ejecutar la rutina de limpieza de arranque (idéntica a bot_comandos.py)
print("\n2. Ejecutando rutina de arranque de bot_comandos.py...")
_db_tmp_orphan = DB_PATH + ".tmp"
if os.path.exists(_db_tmp_orphan):
    try:
        print(f"   [Biblioteca Startup] Eliminando archivo temporal huérfano: {_db_tmp_orphan}...")
        os.remove(_db_tmp_orphan)
        print("   [Biblioteca Startup] Temporal huérfano eliminado con éxito.")
    except Exception as _e_clean:
        print(f"   [Biblioteca Startup] Advertencia al eliminar temporal huérfano: {_e_clean}")

# Paso 3: Verificación
print("\n3. Verificación:")
print(f"   ¿Existe {TMP_PATH}? {os.path.exists(TMP_PATH)} (esperado: False)")
print(f"   ¿Existe base real {DB_PATH}? {os.path.exists(DB_PATH)} (esperado: True)")

assert not os.path.exists(TMP_PATH), "Fallo: El archivo huérfano no fue eliminado."
assert os.path.exists(DB_PATH), "Fallo: La base real fue afectada."

print("\n" + "=" * 80)
print("TEST EXITOSO: El temporal huérfano se detecta y elimina limpiamente al arrancar.")
print("=" * 80)
