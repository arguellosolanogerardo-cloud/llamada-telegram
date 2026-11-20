"""
Prueba de descompresión atómica simulando corte/interrupción a mitad de extracción:
1. DB existente funcional con user_version = 1.
2. Se simula una caída inesperada / corte de energía a mitad del streaming del zip a .tmp.
3. Se verifica que la base original sigue 100% INTACTA y accesible con user_version = 1.
4. Se ejecuta una extracción completa y se verifica el reemplazo atómico a user_version = 2.
"""
import os
import sys
import json
import shutil
import zipfile
import sqlite3

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEMP_DIR = os.path.join("tests", "temp_atomic_test")
os.makedirs(TEMP_DIR, exist_ok=True)

test_db = os.path.join(TEMP_DIR, "biblioteca_v2.db")
test_tmp = os.path.join(TEMP_DIR, "biblioteca_v2.db.tmp")
test_zip = os.path.join(TEMP_DIR, "biblioteca_v2.zip")

print("=" * 80)
print("TEST DE DESCOMPRESIÓN ATÓMICA CON CORTE A MITAD DE EXTRACCIÓN")
print("=" * 80)

# Paso 1: Crear DB existente con versión 1 y datos
conn = sqlite3.connect(test_db)
conn.execute("PRAGMA user_version = 1")
conn.execute("CREATE TABLE mensajes (id INTEGER PRIMARY KEY, texto TEXT)")
conn.execute("INSERT INTO mensajes VALUES (1, 'base_original_v1_intacta')")
conn.commit()
conn.close()

# Crear DB versión 2 y empaquetar en test_zip
db_v2_temp = os.path.join(TEMP_DIR, "temp_v2.db")
conn_v2 = sqlite3.connect(db_v2_temp)
conn_v2.execute("PRAGMA user_version = 2")
conn_v2.execute("CREATE TABLE mensajes (id INTEGER PRIMARY KEY, texto TEXT)")
conn_v2.execute("INSERT INTO mensajes VALUES (1, 'base_actualizada_v2')")
conn_v2.commit()
conn_v2.close()

with zipfile.ZipFile(test_zip, 'w') as zf:
    zf.write(db_v2_temp, arcname="biblioteca_v2.db")
    zf.writestr("version.json", json.dumps({"version": 2, "name": "2.0.0"}))
os.remove(db_v2_temp)

print("1. Estado inicial:")
print(f"   • DB activa: {test_db} (user_version = 1)")
print(f"   • Zip nuevo: {test_zip} (version = 2)")

# Paso 2: Simulación de fallo/corte a mitad del proceso de descompresión
print("\n2. Simulando corte abrupto (falla a mitad de descompresión)...")

def intento_extraccion_con_corte_simulado(db_path, zip_path, simular_corte=False):
    db_tmp = db_path + ".tmp"
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            with zip_ref.open("biblioteca_v2.db") as source, open(db_tmp, "wb") as target:
                # Leer solo los primeros 100 bytes y simular corte violento
                chunk = source.read(100)
                target.write(chunk)
                if simular_corte:
                    raise IOError("¡CORTE DE PROCESO / ENERGÍA SIMULADO A MITAD DE EXTRACCIÓN!")
                shutil.copyfileobj(source, target)

            if "version.json" in zip_ref.namelist():
                zip_ref.extract("version.json", os.path.dirname(db_path))

        # Verificación estricta
        conn_verif = sqlite3.connect(db_tmp)
        c_verif = conn_verif.cursor()
        c_verif.execute("PRAGMA quick_check")
        chk_status = c_verif.fetchone()[0]
        c_verif.execute("PRAGMA user_version")
        v_extraida = c_verif.fetchone()[0]
        conn_verif.close()

        if chk_status != "ok":
            raise ValueError(f"Integridad SQLite corrupta: {chk_status}")

        os.replace(db_tmp, db_path)
        return True, "Reemplazo atómico completado."
    except Exception as e:
        if os.path.exists(db_tmp):
            try:
                os.remove(db_tmp)
            except Exception:
                pass
        return False, f"Error capturado: {e}"

# Ejecutar con corte simulado
exito, msg = intento_extraccion_con_corte_simulado(test_db, test_zip, simular_corte=True)
print(f"   • Resultado de la operación fallida: {msg}")

# Verificar que la base original NO fue dañada y sigue en v1
conn_check = sqlite3.connect(test_db)
c_chk = conn_check.cursor()
c_chk.execute("PRAGMA user_version")
uv_post_corte = c_chk.fetchone()[0]
c_chk.execute("SELECT texto FROM mensajes")
txt_post_corte = c_chk.fetchone()[0]
conn_check.close()

print("\n3. Verificación post-corte de la base activa:")
print(f"   • ¿Archivo temporal .tmp quedó borrado? {not os.path.exists(test_tmp)}")
print(f"   • user_version en DB activa: {uv_post_corte} (esperado: 1)")
print(f"   • Contenido en DB activa:    '{txt_post_corte}' (esperado: 'base_original_v1_intacta')")

assert uv_post_corte == 1 and txt_post_corte == "base_original_v1_intacta", "¡Error crítico: La base previa se corrompió!"
print("   => VERIFICACIÓN DE SEGURIDAD EXITOSA: La base previa no sufrió daño alguno.")

# Paso 3: Ejecutar ahora la extracción completa y comprobar reemplazo atómico
print("\n4. Ejecutando extracción completa limpia (sin corte)...")
exito_ok, msg_ok = intento_extraccion_con_corte_simulado(test_db, test_zip, simular_corte=False)
print(f"   • Resultado de la operación limpia: {msg_ok}")

conn_final = sqlite3.connect(test_db)
c_fin = conn_final.cursor()
c_fin.execute("PRAGMA user_version")
uv_final = c_fin.fetchone()[0]
c_fin.execute("SELECT texto FROM mensajes")
txt_final = c_fin.fetchone()[0]
conn_final.close()

print("\n5. Verificación de la base actualizada:")
print(f"   • user_version en DB activa: {uv_final} (esperado: 2)")
print(f"   • Contenido en DB activa:    '{txt_final}' (esperado: 'base_actualizada_v2')")

assert uv_final == 2 and txt_final == "base_actualizada_v2", "¡Error: El reemplazo atómico no actualizó la base!"
print("   => REEMPLAZO ATÓMICO EXITOSO: Actualización confirmada.")

shutil.rmtree(TEMP_DIR)
print("\n" + "=" * 80)
print("TEST COMPLETADO: Descompresión atómica 100% robusta ante cortes.")
print("=" * 80)
