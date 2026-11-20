import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

conn = sqlite3.connect("data/biblioteca_v2.db")
c = conn.cursor()

print("1. Ejecutando PRAGMA integrity_check...")
c.execute("PRAGMA integrity_check")
res_pragma = c.fetchall()
print("   Resultado:", res_pragma)

print("\n2. Ejecutando FTS5 integrity-check...")
try:
    c.execute("INSERT INTO transcripciones_fts(transcripciones_fts) VALUES('integrity-check')")
    print("   Resultado: OK (Éxito absoluto sin excepciones)")
except Exception as e:
    print("   Resultado ERROR:", e)

conn.close()
