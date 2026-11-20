import io

with io.open('escanear_youtube.py', 'r', encoding='utf-8') as f:
    c1 = f.read()
with io.open('descargar_subtitulos.py', 'r', encoding='utf-8') as f:
    c2 = f.read()

c1 = c1.replace('"yt-dlp",', '"python", "-m", "yt_dlp",')
c2 = c2.replace('"yt-dlp",', '"python", "-m", "yt_dlp",')

with io.open('escanear_youtube.py', 'w', encoding='utf-8') as f: f.write(c1)
with io.open('descargar_subtitulos.py', 'w', encoding='utf-8') as f: f.write(c2)
