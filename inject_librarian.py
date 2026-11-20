import io
import re

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    content = f.read()

loop_start = '''                msg = update.get("message")
                if not msg:
                    continue
                
                # --- LOGICA MENSAJE FLOTANTE ---'''

loop_start_rep = '''                msg = update.get("message")
                if not msg:
                    continue
                
                # --- LOGICA BIBLIOTECARIO PRIVADO ---
                chat_type = msg.get("chat", {}).get("type")
                if chat_type == "private":
                    texto = msg.get("text", "")
                    msg_id_priv = msg.get("message_id")
                    chat_id_priv = msg.get("chat", {}).get("id")
                    
                    if texto and not texto.startswith("/"):
                        enviar_mensaje(chat_id_priv, "🔍 *Buscando en la Biblioteca Conocimiento Universal...*", reply_to_message_id=msg_id_priv)
                        
                        # Guardar auditorA-a
                        import json
                        auditoria_path = os.path.join("data", "auditoria_consultas.json")
                        consultas = []
                        if os.path.exists(auditoria_path):
                            try:
                                with open(auditoria_path, "r", encoding="utf-8") as f_aud:
                                    consultas = json.load(f_aud)
                            except: pass
                        consultas.append({
                            "fecha": datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d %H:%M:%S"),
                            "usuario_id": from_user.get("id"),
                            "nombre": from_user.get("first_name", "Usuario"),
                            "pregunta": texto
                        })
                        with open(auditoria_path, "w", encoding="utf-8") as f_aud:
                            json.dump(consultas, f_aud, indent=4, ensure_ascii=False)
                            
                        # Buscar en SQLite
                        import sqlite3
                        db_path = os.path.join("data", "biblioteca_conocimiento_universal.db")
                        if os.path.exists(db_path):
                            try:
                                conn = sqlite3.connect(db_path)
                                c = conn.cursor()
                                palabras = texto.lower().replace("buscame", "").replace("donde", "").replace("habla", "").replace("sobre", "").strip().split()
                                query = "SELECT v.titulo, t.inicio_segundos, t.texto, v.video_id FROM transcripciones t INNER JOIN videos v ON t.video_id = v.video_id WHERE "
                                conditions = []
                                params = []
                                for p in palabras:
                                    if len(p) > 3:
                                        conditions.append("t.texto LIKE ?")
                                        params.append(f"%{p}%")
                                if not conditions:
                                    # Fallback
                                    conditions = ["t.texto LIKE ?"]
                                    params = [f"%{texto.strip()}%"]
                                    
                                query += " AND ".join(conditions) + " LIMIT 3"
                                c.execute(query, params)
                                resultados = c.fetchall()
                                conn.close()
                                
                                if resultados:
                                    resp = "📚 **Aquí tienes lo que encontré en la Biblioteca:**\\n\\n"
                                    for idx, (titulo, seg, txt_frag, vid) in enumerate(resultados):
                                        m = seg // 60
                                        s = seg % 60
                                        url = f"https://youtu.be/{vid}?t={seg}"
                                        resp += f"**{idx+1}. {titulo}**\\n"
                                        resp += f"⏱️ *Minuto:* [{m:02d}:{s:02d}]({url})\\n"
                                        resp += f"💬 \\"{txt_frag[:100]}...\\"\\n\\n"
                                    
                                    enviar_mensaje(chat_id_priv, resp)
                                else:
                                    enviar_mensaje(chat_id_priv, "😔 No encontré ninguna enseñanza exacta con esas palabras. Intenta usar otras palabras clave.")
                            except Exception as e:
                                enviar_mensaje(chat_id_priv, f"⚠️ Error buscando: {e}")
                        else:
                            enviar_mensaje(chat_id_priv, "⏳ La Biblioteca Aon se estA¡ construyendo. Intenta mAs tarde.")
                    continue
                # ------------------------------------

                # --- LOGICA MENSAJE FLOTANTE ---'''

if loop_start in content:
    content = content.replace(loop_start, loop_start_rep)
    with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Injected private chat logic successfully")
else:
    print("Could not find targets")
