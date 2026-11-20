"""
Prueba de ventana por tiempo vs ventana por filas.
"""
import sqlite3
from test_dedup import deduplicar_stream_video

conn = sqlite3.connect("backup_crudo/biblioteca_transcripciones_cruda_backup.db")
c = conn.cursor()

WINDOW_SECONDS = 47
STEP_SECONDS = 28

c.execute("SELECT distinct video_id FROM transcripciones WHERE texto NOT LIKE '[%]' LIMIT 50")
vids = [r[0] for r in c.fetchall()]

total_ventanas_tiempo = 0
total_filas_orig = 0
total_filas_limpias = 0

for vid in vids:
    c.execute("SELECT inicio_segundos, texto FROM transcripciones WHERE video_id = ? AND texto NOT LIKE '[%]' ORDER BY inicio_segundos", (vid,))
    filas = c.fetchall()
    total_filas_orig += len(filas)
    
    limpias = deduplicar_stream_video(filas)
    total_filas_limpias += len(limpias)
    if not limpias:
        continue
        
    t_min = limpias[0][0]
    t_max = limpias[-1][0]
    
    t_start = t_min
    while t_start <= t_max:
        t_end = t_start + WINDOW_SECONDS
        chunk = [txt for s, txt in limpias if t_start <= s < t_end]
        if chunk:
            total_ventanas_tiempo += 1
        t_start += STEP_SECONDS

print(f"50 videos analizados:")
print(f"  • Filas originales: {total_filas_orig}")
print(f"  • Filas tras deduplicar origen: {total_filas_limpias}")
print(f"  • Ventanas por tiempo (47s/28s): {total_ventanas_tiempo}")
print(f"  • Promedio ventanas por video: {total_ventanas_tiempo / len(vids):.1f}")
