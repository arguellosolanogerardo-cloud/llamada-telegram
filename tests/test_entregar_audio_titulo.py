import unittest
from unittest.mock import patch, MagicMock
import os
import bot_comandos

class TestEntregarAudioTitulo(unittest.TestCase):
    @patch("bot_comandos.enviar_audio")
    @patch("bot_comandos.enviar_mensaje")
    def test_encuentra_audio_por_titulo_yt_clean(self, mock_msg, mock_audio):
        mock_audio.return_value = (True, 111, "file_id_test")
        
        info = {
            "tipo": "MENSAJE",
            "titulo": "La guerra está próxima contra el mal",
            "maestro": "JESUS MARIO CARRILLO DURAN"
        }
        
        bot_comandos.entregar_audio_meditacion(123456, info)
        
        self.assertTrue(mock_audio.called)
        args, kwargs = mock_audio.call_args
        # kwargs or args[1] should be the local path
        ruta_enviada = kwargs.get("ruta_audio") or args[1]
        self.assertTrue(ruta_enviada.endswith("yt_clean_OM0QRqRAqAQ.mp3") or ruta_enviada == "file_id_test")

    @patch("bot_comandos.enviar_audio", return_value=(False, None, None))
    @patch("bot_comandos.enviar_mensaje")
    def test_formato_limpio_cuando_no_hay_audio_ni_numero(self, mock_msg, mock_audio):
        info = {
            "tipo": "MENSAJE",
            "titulo": "Mensaje Inexistente Desconocido 999xyz",
            "maestro": "Maestro Desconocido"
        }
        
        bot_comandos.entregar_audio_meditacion(123456, info)
        
        self.assertTrue(mock_msg.called)
        texto = mock_msg.call_args[0][1]
        # No debe contener "Mensaje #:" ni "meditación #."
        self.assertNotIn("Mensaje #:", texto)
        self.assertNotIn("meditación #.", texto)
        self.assertIn("**Mensaje:** «Mensaje Inexistente Desconocido 999xyz»", texto)

if __name__ == "__main__":
    unittest.main()
