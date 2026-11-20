import json
from datetime import datetime

# 1. Asegurar meta_hoy.json con fecha de hoy
meta_hoy = {
    "numero": 1089,
    "tipo": "MEDITACION",
    "titulo": "Estamos anunciando que estamos aquí",
    "fecha": "08/14/20",
    "maestro": "Alan",
    "detectado_como": "MEDITACION",
    "fecha_tarea_admin": "28/10/2026",
    "fecha_iso": "2026-10-28"
}
with open('data/meditaciones/meta_hoy.json', 'w', encoding='utf-8') as f:
    json.dump(meta_hoy, f, ensure_ascii=False, indent=2)
print("OK: data/meditaciones/meta_hoy.json actualizado para hoy.")

# 2. Asegurar que reproducciones_log.json tenga el registro de hoy 28/10/2026
with open('data/reproducciones_log.json', 'r', encoding='utf-8') as f:
    log = json.load(f)

# Remover duplicados de hoy si hubiese y dejar 1 solo registro
log = [e for e in log if not str(e.get("fecha_iso")) == "2026-10-28" and not str(e.get("fecha", "")).startswith("2026-10-28")]
log.append({
    "fecha": "2026-10-28 03:00:00",
    "numero": 1089,
    "titulo": "Estamos anunciando que estamos aquí",
    "indice": 21,
    "fecha_iso": "2026-10-28"
})
with open('data/reproducciones_log.json', 'w', encoding='utf-8') as f:
    json.dump(log, f, ensure_ascii=False, indent=2)
print("OK: data/reproducciones_log.json actualizado con fecha de hoy.")
