"""
Módulo de normalización y stemming unificado para la Biblioteca del Conocimiento Universal.
Garantiza que la normalización sea 100% idéntica al indexar y al consultar.
"""
import re

try:
    import snowballstemmer
    _stemmer = snowballstemmer.stemmer('spanish')
    def stem_palabra(palabra: str) -> str:
        return _stemmer.stemWord(palabra)
except ImportError:
    try:
        from nltk.stem.snowball import SpanishStemmer
        _nltk_stemmer = SpanishStemmer()
        def stem_palabra(palabra: str) -> str:
            return _nltk_stemmer.stem(palabra)
    except Exception:
        def stem_palabra(palabra: str) -> str:
            return palabra

# Lista estándar canónica de Stopwords en Español (ISO / NLTK) + palabras de disparo del bot
STOPWORDS_ESPANOL = {
    # Pronombres, artículos, preposiciones y conjunciones estándar
    "a", "al", "algo", "algunas", "algunos", "ante", "antes", "como", "con", "contra",
    "cual", "cuales", "cuando", "de", "del", "desde", "donde", "durante", "e", "el",
    "ella", "ellas", "ellos", "en", "entre", "era", "erais", "eran", "eras", "eres",
    "es", "esa", "esas", "ese", "eso", "esos", "esta", "estaba", "estabais", "estaban",
    "estabas", "estad", "estada", "estadas", "estado", "estados", "estais", "estamos",
    "estan", "estando", "estar", "estara", "estaran", "estaras", "estare", "estareis",
    "estaremos", "estaria", "estariais", "estariamos", "estarian", "estarias", "estas",
    "este", "esteis", "estemos", "esten", "estes", "esto", "estos", "estoy", "estuve",
    "estuviera", "estuvierais", "estuvieran", "estuvieras", "estuvieron", "estuviese",
    "estuvieseis", "estuviesen", "estuvieses", "estuvimos", "estuviste", "estuvisteis",
    "estuvo", "fue", "fuera", "fuerais", "fueran", "fueras", "fueron", "fuese",
    "fueseis", "fuesen", "fueses", "fui", "fuimos", "fuiste", "fuisteis", "ha",
    "habeis", "habia", "habiais", "habiamo", "habian", "habias", "habida", "habidas",
    "habido", "habidos", "habiendo", "habra", "habran", "habras", "habre", "habreis",
    "habremos", "habria", "habriais", "habriamos", "habrian", "habrias", "han",
    "has", "hasta", "hay", "haya", "hayais", "hayamos", "hayan", "hayas", "he",
    "hemos", "hube", "hubiera", "hubierais", "hubieran", "hubieras", "hubieron",
    "hubiese", "hubieseis", "hubiesen", "hubieses", "hubimos", "hubiste", "hubisteis",
    "hubo", "la", "las", "le", "les", "lo", "los", "me", "mi", "mia", "mias",
    "mio", "mios", "mis", "mucho", "muchos", "muy", "nada", "ni", "no", "nos",
    "nosotras", "nosotros", "nuestra", "nuestras", "nuestro", "nuestros", "o", "os",
    "otra", "otras", "otro", "otros", "para", "pero", "poco", "por", "porque",
    "que", "quien", "quienes", "se", "sea", "seais", "seamos", "sean", "seas",
    "sere", "seran", "seras", "sereis", "seremos", "seria", "seriais", "seriamos",
    "serian", "serias", "si", "sido", "siendo", "sin", "sobre", "sois", "somos",
    "son", "soy", "su", "sus", "suya", "suyas", "suyo", "suyos", "tambien",
    "tanto", "te", "tendra", "tendran", "tendras", "tendre", "tendreis", "tendremos",
    "tendria", "tendriais", "tendriamos", "tendrian", "tendrias", "tened", "tendria",
    "tenemos", "tenga", "tengais", "tengamos", "tengan", "tengas", "tengo", "tengas",
    "tenia", "teniais", "teniamos", "tenian", "tenias", "tenida", "tenidas", "tenido",
    "tenidos", "teniendo", "teneis", "ti", "tiene", "tienen", "tienes", "todo",
    "todos", "tu", "tus", "tuve", "tuviera", "tuvierais", "tuvieran", "tuvieras",
    "tuvieron", "tuviese", "tuvieseis", "tuviesen", "tuvieses", "tuvimos", "tuviste",
    "tuvisteis", "tuvo", "tuya", "tuyas", "tuyo", "tuyos", "un", "una", "unas",
    "uno", "unos", "vosotras", "vosotros", "vuestra", "vuestras", "vuestro", "vuestros",
    "y", "ya",
    # Stopwords de dominio conversacional y disparadores del bot
    "biblioteca", "conocimiento", "universal", "toby", "asistente", "busca", "buscame",
    "donde", "habla", "sobre", "dice", "dime", "cuentame", "explica", "explicame",
    "pregunta", "encuentra", "video", "videos", "tema", "ensenanza", "ensenanzas",
    "favor", "porfa"
}

def normalizar_cadena(texto: str) -> str:
    """Convierte a minúsculas y elimina diacríticos/acentos de forma consistente."""
    if not texto:
        return ""
    t = texto.lower()
    t = (t.replace('á', 'a')
          .replace('é', 'e')
          .replace('í', 'i')
          .replace('ó', 'o')
          .replace('ú', 'u')
          .replace('ü', 'u')
          .replace('ñ', 'n'))
    return t

def extraer_tokens_normalizados(texto: str, filtrar_stopwords: bool = True) -> list[str]:
    """
    Normaliza el texto y extrae las raíces (stems) usando el algoritmo Snowball.
    Devuelve lista de tokens con longitud mínima de 2 caracteres.
    """
    t = normalizar_cadena(texto)
    palabras = re.findall(r'\b[a-z0-9]{2,}\b', t)
    
    tokens = []
    for w in palabras:
        if filtrar_stopwords and w in STOPWORDS_ESPANOL:
            continue
        token_stem = stem_palabra(w)
        if token_stem and len(token_stem) >= 2:
            tokens.append(token_stem)
            
    return tokens

def texto_a_stems(texto: str) -> str:
    """Convierte un fragmento completo a una cadena de stems para indexación en FTS5."""
    tokens = extraer_tokens_normalizados(texto, filtrar_stopwords=True)
    return " ".join(tokens)
