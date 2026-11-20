with open('bot_comandos.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Fix 1: fallback plain text in enviar_mensaje
old_enviar = '''    except Exception as e:
        print(f"Error enviando mensaje a {chat_id}:", e)
        return None'''
new_enviar = '''    except Exception as e:
        print(f"Error enviando mensaje a {chat_id}:", e)
        import sys; sys.stdout.flush()
        if "parse_mode" in payload:
            del payload["parse_mode"]
            datos = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    res_data = json.loads(r.read().decode())
                    m_id = res_data.get("result", {}).get("message_id")
                    if m_id and CHAT_ID and str(chat_id) == str(CHAT_ID):
                        registrar_msg_bot(m_id)
                    return m_id
            except Exception as e2:
                print(f"Error re-enviando sin formato a {chat_id}:", e2)
                sys.stdout.flush()
        return None'''
if old_enviar in text:
    text = text.replace(old_enviar, new_enviar)
else:
    print("WARNING: Fix 1 not found")

# Fix 2: /panel multiline string
old_panel = '''enviar_mensaje(chat_id, "🎛 **PANEL DE CONTROL DE SALA**
*(Solo funciona durante la llamada)*
Presiona los botones para controlar el bot en tiempo real:", reply_markup=teclado_panel)'''
new_panel = '''enviar_mensaje(chat_id, "🎛 **PANEL DE CONTROL DE SALA**\\n*(Solo funciona durante la llamada)*\\nPresiona los botones para controlar el bot en tiempo real:", reply_markup=teclado_panel)'''
if old_panel in text:
    text = text.replace(old_panel, new_panel)
else:
    print("WARNING: Fix 2 not found")

# Fix 3: main exception handler
old_main_exc = '''        except Exception as e:
            print("Error en bucle de comandos:", e)
            time.sleep(3)'''
new_main_exc = '''        except Exception as e:
            print("Error en bucle de comandos:", e)
            import sys; sys.stdout.flush()
            time.sleep(3)'''
if old_main_exc in text:
    text = text.replace(old_main_exc, new_main_exc)
else:
    print("WARNING: Fix 3 not found")

# Fix 4: librarian continue indentation
old_continue = '''                        else:
                            enviar_mensaje(chat_id_priv, "🚧 La Biblioteca Aún se está construyendo. Intenta más tarde.")
                    continue
                # ------------------------------------'''
new_continue = '''                        else:
                            enviar_mensaje(chat_id_priv, "🚧 La Biblioteca Aún se está construyendo. Intenta más tarde.")
                        continue
                # ------------------------------------'''
if old_continue in text:
    text = text.replace(old_continue, new_continue)
else:
    print("WARNING: Fix 4 not found")

with open('bot_comandos.py', 'w', encoding='utf-8', newline='\n') as f:
    f.write(text)

print("Patched successfully")
