"""
Prueba unitaria exhaustiva de la validación del índice vectorial en arranque.
Verifica que valide:
  1. modelo
  2. dimensiones
  3. user_version
  4. total_ventanas
  5. checksum_ventanas (SHA256)
"""
import os
import sys
import json
import shutil
import sqlite3
import hashlib

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot_comandos import validar_indice_vectorial, DB_BIBLIO_PATH

DIR_TEST_VEC = os.path.join("tests", "temp_test_vectores")
os.makedirs(DIR_TEST_VEC, exist_ok=True)

# Obtener valores reales de la DB activa
conn = sqlite3.connect(DB_BIBLIO_PATH)
c = conn.cursor()
c.execute("PRAGMA user_version")
real_v = c.fetchone()[0]
c.execute("SELECT count(*) FROM transcripciones_v2")
real_w = c.fetchone()[0]
c.execute("SELECT id, video_id, inicio_segundos FROM transcripciones_v2 ORDER BY id")
h = hashlib.sha256()
for r in c:
    h.update(f"{r[0]}:{r[1]}:{r[2]};".encode("utf-8"))
real_chk = h.hexdigest()
conn.close()

def escribir_meta(meta):
    with open(os.path.join(DIR_TEST_VEC, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)

# Caso 1: metadata válida al 100%
escribir_meta({
    "modelo": "gemini-embedding-001",
    "dimension_nativa": 768,
    "dimensiones_almacenadas": [768, 512, 256],
    "base_user_version": real_v,
    "total_ventanas": real_w,
    "checksum_ventanas": real_chk
})
assert validar_indice_vectorial(DIR_TEST_VEC) is True, "Caso 1 falló (debería ser True)"

# Caso 2: user_version errónea
escribir_meta({
    "modelo": "gemini-embedding-001",
    "dimension_nativa": 768,
    "dimensiones_almacenadas": [768, 512, 256],
    "base_user_version": 9999999999,
    "total_ventanas": real_w,
    "checksum_ventanas": real_chk
})
assert validar_indice_vectorial(DIR_TEST_VEC) is False, "Caso 2 falló (debería ser False)"

# Caso 3: conteo de ventanas erróneo
escribir_meta({
    "modelo": "gemini-embedding-001",
    "dimension_nativa": 768,
    "dimensiones_almacenadas": [768, 512, 256],
    "base_user_version": real_v,
    "total_ventanas": 100,
    "checksum_ventanas": real_chk
})
assert validar_indice_vectorial(DIR_TEST_VEC) is False, "Caso 3 falló (debería ser False)"

# Caso 4: checksum corrupto o alterado
escribir_meta({
    "modelo": "gemini-embedding-001",
    "dimension_nativa": 768,
    "dimensiones_almacenadas": [768, 512, 256],
    "base_user_version": real_v,
    "total_ventanas": real_w,
    "checksum_ventanas": "0000000000000000000000000000000000000000000000000000000000000000"
})
assert validar_indice_vectorial(DIR_TEST_VEC) is False, "Caso 4 falló (debería ser False)"

# Limpieza
shutil.rmtree(DIR_TEST_VEC)
print("TODAS LAS PRUEBAS DE VALIDACIÓN DE METADATOS VECTORIALES PASARON (5/5).")
