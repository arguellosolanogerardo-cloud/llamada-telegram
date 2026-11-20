import io

with io.open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

target_var = 'SEGUNDOS_INACTIVIDAD_MUTE = int(os.environ.get("SEGUNDOS_INACTIVIDAD_MUTE", "15"))'
rep_var = 'SEGUNDOS_INACTIVIDAD_MUTE = int(os.environ.get("SEGUNDOS_INACTIVIDAD_MUTE", "60"))'
content = content.replace(target_var, rep_var)

target_msg = 'avisar_con_bot(f"ðŸ”‡ **Micrófono silenciado:** {nombre} por inactividad. Se desbloqueará en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s para que puedas volver a hablar cuando desees.", es_efimero=True)'
rep_msg = 'avisar_con_bot(f"Hola **{nombre}** ðŸ‘‹, notamos que tu micrófono se quedó abierto en silencio por 60s, así que lo cerramos por ti para cuidar la sala de ruidos de fondo. ¡Siéntete libre de volver a abrirlo cuando gustes participar! ðŸ’–", es_efimero=True)'
content = content.replace(target_msg, rep_msg)

with io.open('llamada.py', 'w', encoding='utf-8') as f:
    f.write(content)
