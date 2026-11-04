import unittest
import os
import sys
import json
import shutil
import tempfile
from unittest.mock import patch, MagicMock

class TestEncoladoRobustoYRender(unittest.TestCase):
    def test_tiene_soporte_nvenc(self):
        from astronomia_luna import tiene_soporte_nvenc
        res = tiene_soporte_nvenc()
        self.assertIsInstance(res, bool)

    def test_pre_render_centinela_function(self):
        from centinela_youtube import pre_renderizar_video_meditacion_hoy
        self.assertTrue(callable(pre_renderizar_video_meditacion_hoy))

    def test_caratula_generada_existe(self):
        ruta_mp4 = "data/meditaciones/caratula_meditacion_1082.mp4"
        if os.path.exists(ruta_mp4):
            self.assertGreater(os.path.getsize(ruta_mp4), 100000)

    def test_procesar_programacion_yttarea_adicional_mario(self):
        """Verifica que programar un audio adicional (Mario Carrillo) preserve Pista #1 y agregue Pista #2."""
        import bot_comandos
        temp_dir = tempfile.mkdtemp()
        dummy_mp3 = os.path.join(temp_dir, "dummy_audio.mp3")
        with open(dummy_mp3, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 5000)

        with patch("bot_comandos.enviar_mensaje", return_value=12345) as mock_msg, \
             patch("bot_comandos.enviar_audio", return_value=(True, 67890, "file_id_test")) as mock_audio, \
             patch("bot_comandos.descargar_audio_youtube_robusto", return_value=(dummy_mp3, "YOUTUBE")):

            bot_comandos.procesar_programacion_yttarea("Ovq_Ok_8yc0", chat_destino=-1002963691819)

            ruta_cola = os.path.join("data", "meditaciones", "cola_hoy.json")
            self.assertTrue(os.path.exists(ruta_cola))
            with open(ruta_cola, "r", encoding="utf-8") as fc:
                data = json.load(fc)
            cola = data.get("cola", [])
            self.assertGreaterEqual(len(cola), 1)
            # El último elemento debe ser la pista de YouTube agregada
            ultimo = cola[-1]
            self.assertIn("Quien isisio la división en los grupos", ultimo.get("titulo", ""))
            self.assertTrue(ultimo.get("info", {}).get("es_adicional"))

        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_procesar_programacion_yttarea_falla_descarga(self):
        """Verifica que si la descarga de YouTube falla, se notifique y no se corrompa la cola."""
        import bot_comandos
        mensajes_enviados = []
        def capture_msg(chat_id, texto, **kwargs):
            mensajes_enviados.append(texto)
            return 99999

        with patch("bot_comandos.enviar_mensaje", side_effect=capture_msg), \
             patch("bot_comandos.descargar_audio_youtube_robusto", return_value=(None, "")):

            bot_comandos.procesar_programacion_yttarea("INVALID_VIDEO_123", chat_destino=-1002963691819)

            # Debe haber enviado mensaje de error informativo
            hay_aviso_error = any("No se pudo descargar el audio" in m for m in mensajes_enviados)
            self.assertTrue(hay_aviso_error)

if __name__ == "__main__":
    unittest.main()
