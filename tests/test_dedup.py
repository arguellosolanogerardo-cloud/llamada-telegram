"""
Prueba del algoritmo de deduplicación en el origen:
1. Deduplicación intra-línea (frases repetidas, palabras repetidas >= 3 veces).
2. Deduplicación inter-línea (solapamiento al inicio de una línea con el final de la anterior).
3. Respeto a repeticiones legítimas ('muy muy bien', 'casi casi').
"""
import re
import sqlite3

def deduplicar_frases_intra_linea(texto):
    """
    Deduplica repeticiones de frases y palabras dentro de una misma línea de subtítulo.
    - Frases (k >= 2 palabras): Si se repite inmediatamente, colapsa a 1.
    - Palabras solas (k = 1): 
        - Si aparece 2 veces ('muy muy bien'): se PERMITE (énfasis natural).
        - Si aparece >= 3 veces ('para para para para'): se colapsa a 1.
    """
    palabras = texto.split()
    if not palabras:
        return ""
    
    # 1. Colapsar palabras individuales repetidas >= 3 veces
    palabras_limpias = []
    i = 0
    n = len(palabras)
    while i < n:
        w = palabras[i]
        # Contar cuántas veces se repite w consecutivamente (case-insensitive)
        j = i + 1
        while j < n and palabras[j].lower() == w.lower():
            j += 1
        repeticiones = j - i
        if repeticiones >= 3:
            # Es tartamudeo VTT claro ('para para para para') -> dejar solo 1
            palabras_limpias.append(w)
        elif repeticiones == 2:
            # Énfasis legítimo ('muy muy bien') -> conservar ambas
            palabras_limpias.append(w)
            palabras_limpias.append(palabras[i+1])
        else:
            palabras_limpias.append(w)
        i = j

    palabras = palabras_limpias
    
    # 2. Detección iterativa de repeticiones de frases (k de 2 a 30 palabras)
    cambio = True
    while cambio:
        cambio = False
        n = len(palabras)
        resultado = []
        i = 0
        while i < n:
            encontrado_rep = False
            max_k = min(30, (n - i) // 2)
            for k in range(max_k, 1, -1):  # Solo k >= 2 para no tocar palabras solas ya evaluadas
                frase1 = palabras[i:i+k]
                frase2 = palabras[i+k:i+2*k]
                if [w.lower() for w in frase1] == [w.lower() for w in frase2]:
                    resultado.extend(frase1)
                    i += 2 * k
                    # Si se repite una 3ra o 4ta vez
                    while i + k <= n and [w.lower() for w in palabras[i:i+k]] == [w.lower() for w in frase1]:
                        i += k
                    encontrado_rep = True
                    cambio = True
                    break
            if not encontrado_rep:
                resultado.append(palabras[i])
                i += 1
        palabras = resultado

    return " ".join(palabras)

def deduplicar_stream_video(filas_video):
    """
    Deduplica una secuencia de filas (inicio_segundos, texto) de un mismo video.
    Aplica deduplicación intra-línea a cada fila, y además elimina el solapamiento
    inicial de la fila i si coincide con el final de la fila i-1.
    Retorna lista de (inicio_segundos, texto_limpio).
    """
    resultado = []
    palabras_previas = []

    for seg, txt in filas_video:
        txt_intra = deduplicar_frases_intra_linea(txt)
        palabras_actuales = txt_intra.split()
        if not palabras_actuales:
            continue

        # Detectar solapamiento con el final de la línea previa
        if palabras_previas:
            # Buscar el mayor solapamiento de sufijo de previas con prefijo de actuales
            # Probamos solapamientos de tamaño min(len(palabras_previas), len(palabras_actuales)) hasta 2 palabras
            max_overlap = min(len(palabras_previas), len(palabras_actuales), 25)
            overlap_encontrado = 0
            for k in range(max_overlap, 1, -1):
                sufijo_prev = [w.lower() for w in palabras_previas[-k:]]
                prefijo_act = [w.lower() for w in palabras_actuales[:k]]
                if sufijo_prev == prefijo_act:
                    overlap_encontrado = k
                    break
            
            if overlap_encontrado > 0:
                palabras_actuales = palabras_actuales[overlap_encontrado:]

        if palabras_actuales:
            txt_final = " ".join(palabras_actuales)
            resultado.append((seg, txt_final))
            palabras_previas.extend(palabras_actuales)
            # Mantener buffer de palabras previas en un tamaño razonable para no ralentizar
            if len(palabras_previas) > 50:
                palabras_previas = palabras_previas[-50:]

    return resultado

if __name__ == "__main__":
    conn = sqlite3.connect("backup_crudo/biblioteca_transcripciones_cruda_backup.db")
    c = conn.cursor()
    c.execute("SELECT inicio_segundos, texto FROM transcripciones WHERE video_id = '-0vhbQQErKo' ORDER BY inicio_segundos LIMIT 6")
    filas = c.fetchall()
    
    print("=== DEDUPLICACIÓN EN EL ORIGEN (VIDEO -0vhbQQErKo) ===")
    limpias = deduplicar_stream_video(filas)
    for seg, txt in limpias:
        print(f"[{seg}s]: {txt}")
    
    print("\n--- PRUEBA DE REGRESIÓN DE FRASES LEGÍTIMAS ---")
    frases_prueba = [
        "esto está muy muy bien hecho",
        "casi casi llegamos a la meta",
        "para para para para los amigos venezolanos",
        "el 17 de julio del 2017 es un mensaje el 17 de julio del 2017 es un mensaje",
        "vamos vamos muchachos que se puede",
        "de verdad de verdad te digo esto de verdad de verdad te digo esto"
    ]
    for fp in frases_prueba:
        res = deduplicar_frases_intra_linea(fp)
        print(f"Original:   '{fp}'")
        print(f"Deduplicado: '{res}'\n")
