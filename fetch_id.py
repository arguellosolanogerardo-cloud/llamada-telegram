import urllib.request
import re

html = urllib.request.urlopen('https://www.youtube.com/@mariocarrillo7919').read().decode('utf-8')
m = re.search(r'channel_id=([^\"]+)', html)
if m:
    print(m.group(1).split('&')[0])
