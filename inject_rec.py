import io

with io.open('llamada.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''                except Exception as e_c:
                    print("Nota registrando input_call en PyTgCalls:", e_c)
            except Exception as e:
                print("Nota iniciando PyTgCalls:", e)'''

replacement = '''                except Exception as e_c:
                    print("Nota registrando input_call en PyTgCalls:", e_c)
                    
                # Iniciar grabación de audio pre-meditación
                try:
                    from pytgcalls.types.raw import Stream, AudioStream, AudioParameters
                    from ntgcalls import MediaSource
                    if not grabacion_cancelada:
                        ruta_pre_raw = ruta_grabacion_pre.rsplit(".", 1)[0] + ".raw"
                        stream_rec_pre = Stream(
                            speaker=AudioStream(
                                media_source=MediaSource.FILE,
                                path=os.path.abspath(ruta_pre_raw),
                                parameters=AudioParameters(48000, 2)
                            )
                        )
                        await tgcalls.play(destino, stream_rec_pre)
                        print("Grabación PRE-meditación iniciada correctamente.")
                except Exception as e:
                    print(f"Error iniciando grabación pre-meditación: {e}")
            except Exception as e:
                print("Nota iniciando PyTgCalls:", e)'''

if target in content:
    content = content.replace(target, replacement)
    with io.open('llamada.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Replaced!")
else:
    print("Target not found!")
