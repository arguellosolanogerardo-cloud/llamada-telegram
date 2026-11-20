import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from normalizador_biblioteca import extraer_tokens_normalizados

conn = sqlite3.connect("data/biblioteca_v2.db")
c = conn.cursor()

terminos = [
    "dios", "mundo", "hombre", "tierra", "vida", "hacer", "bien", "decir", "cosas",
    "alaniso", "pleyades", "144000", "kundalini", "arcangel", "nebadon", "pineal", "chakra"
]

print("DOCUMENT FREQUENCY (DF) EN transcripciones_fts (Total docs: 87,613):")
for t in terminos:
    tok = extraer_tokens_normalizados(t, filtrar_stopwords=False)
    if not tok: continue
    stem = tok[0]
    c.execute("SELECT count(*) FROM transcripciones_fts WHERE transcripciones_fts MATCH ?", (f'"{stem}"*',))
    df = c.fetchone()[0]
    pct = (df / 87613) * 100
    print(f"  {t:12} -> stem: {stem:10} | DF: {df:5d} ({pct:5.2f}%)")

conn.close()
