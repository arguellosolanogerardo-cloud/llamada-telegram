"""
Verificación de ventanas por tiempo en 5 videos.
"""
import sqlite3
from test_dedup import deduplicar_stream_video

conn = sqlite3.connect("backup_crudo/biblioteca_transcripciones_cruda_backup.db")
c = conn.cursor()

WINDOW_SECONDS = 47
STEP_SECONDS = 28

c.execute("SELECT distinct video_id FROM transcripciones WHERE texto NOT LIKE '[%]' LIMIT 5")
vids = [r[0] for r in c.fetchall()]

for vid in vids:
    c.execute("SELECT inicio_segundos, texto FROM transcripciones WHERE video_id = ? AND texto NOT LIKE '[%]' ORDER BY inicio_segundos", (vid,))
    filas = c.fetchall()
    limpias = deduplicar_stream_video(filas)
    if not limpias: continue
    
    t_min = limpias[0][0]
    t_max = limpias[-1][0]
    
    print(f"\nVideo {vid}: {len(limpias)} filas limpias | De {t_min}s a {t_max}s")
    
    ventanas = []
    t_start = t_min
    idx_fila = 0
    n_filas = len(limpias)
    
    while t_start <= t_max and idx_fila < n_filas:
        # Si la fila actual está más adelante que t_start + WINDOW_SECONDS, avanzar t_start
        if limpias[idx_fila][0] >= t_start + WINDOW_SECONDS:
            t_start = limpias[idx_fila][0]
            
        t_end = t_start + WINDOW_SECONDS
        
        # Recoger filas dentro del intervalo [t_start, t_end)
        filas_en_ventana = []
        for s, txt in limpias:
            if s >= t_end:
                break
            if s >= t_start:
                filas_en_ventana.append((s, txt))
                
        if filas_en_ventana:
            txt_completo = " ".join(txt for _, txt in filas_en_ventana)
            ventanas.append((t_start, t_end, len(filas_en_ventana), txt_completo))
            
        t_start += STEP_SECONDS
        
    print(f"  Total ventanas generadas: {len(ventanas)}")
    for ini, fin, n_f, txt in ventanas[:3]:
        print(f"    [{ini}s - {fin}s] ({n_f} filas, {len(txt.split())} pal): {txt[:80]}...")
