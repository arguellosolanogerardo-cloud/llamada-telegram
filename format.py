import re
import io

with io.open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Alerta oradores simultaneos (grey box)
content = content.replace(
    'avisar_con_bot(f"⚠️ **{nombre}**, ya hay {MAX_ORADORES_SIMULTANEOS} personas hablando a la vez. Tu micrófono se desbloqueará en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s y te hemos añadido a la lista de turnos para no interrumpir.", es_efimero=True)',
    'avisar_con_bot(f"`⚠️ LÍMITE DE ORADORES:\\n{nombre}, ya hay {MAX_ORADORES_SIMULTANEOS} personas hablando a la vez. Te hemos añadido a la lista de turnos y tu micrófono se desbloqueará en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s.`", es_efimero=True)'
)

# 2. Inactividad mute (grey box)
content = content.replace(
    'avisar_con_bot(f"🔒 **Micrófono silenciado:** {nombre} por inactividad. Se desbloqueará en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s para que puedas volver a hablar cuando desees.", es_efimero=True)',
    'avisar_con_bot(f"`🔒 SILENCIO POR INACTIVIDAD:\\n{nombre}, tu micrófono quedó abierto. Se desbloqueará en {DURACION_BLOQUEO_MUTE_SEGUNDOS}s.`", es_efimero=True)'
)

# 3. Turno de palabra (blockquote)
content = content.replace(
    'avisar_con_bot(f"🗣️ **Turno de palabra:** ¡Adelante **{s_nom}**! Por favor abre tu micrófono para compartir.", es_efimero=True)',
    'avisar_con_bot(f"> 🗣️ **TURNO DE PALABRA**\\n> ¡Adelante **{s_nom}**! Por favor abre tu micrófono para compartir.", es_efimero=True)'
)

with io.open('llamada.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
