import unittest
import os
import tempfile
import json
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
import radar_youtube
from radar_youtube import cargar_vistos, chequear_canales, _MEMORIA_LOCK, _VIDEOS_VISTOS_MEMORIA, _VIDEOS_EN_PROCESO


class TestRadarDesacoplamiento(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db = os.path.join(self.temp_dir.name, "radar_vistos.json")
        with open(self.temp_db, "w", encoding="utf-8") as f:
            json.dump(["ANUNCIADO_1", "ANUNCIADO_2"], f)

        self.orig_db_path = radar_youtube.RADAR_DB_PATH
        radar_youtube.RADAR_DB_PATH = self.temp_db

        with _MEMORIA_LOCK:
            _VIDEOS_EN_PROCESO.clear()
            _VIDEOS_VISTOS_MEMORIA.clear()
            _VIDEOS_VISTOS_MEMORIA.add("ANUNCIADO_1")
            _VIDEOS_VISTOS_MEMORIA.add("ANUNCIADO_2")

    def tearDown(self):
        radar_youtube.RADAR_DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()
        with _MEMORIA_LOCK:
            _VIDEOS_EN_PROCESO.clear()
            _VIDEOS_VISTOS_MEMORIA.clear()

    @patch("urllib.request.urlopen")
    def test_cargar_vistos_no_contamina_con_archivos_disco(self, mock_urlopen):
        """Verifica que audios en disco no se marquen automáticamente como anunciados si no están en la BD."""
        vistos = cargar_vistos()
        self.assertIn("ANUNCIADO_1", vistos)
        self.assertIn("ANUNCIADO_2", vistos)
        self.assertNotIn("VID_SOLO_DISCO_NO_ANUNCIADO", vistos)

    @patch("radar_youtube.extraer_videos_canal")
    def test_chequear_canales_arranque_sincroniza_silencioso_sin_duplicar(self, mock_extraer):
        """Verifica que en arranque (deploy/reinicio), se registren los videos existentes en silencio para no duplicar."""
        ahora = datetime.now(timezone.utc)
        pub_5m_atras = ahora - timedelta(minutes=5)

        mock_extraer.return_value = [
            {
                "video_id": "VID_RECENT_FEED",
                "titulo": "Video en Feed Previo",
                "published_text": "hace 5 minutos",
                "published_dt": pub_5m_atras,
                "link": "https://youtu.be/VID_RECENT_FEED",
                "source": "web"
            }
        ]

        mensajes = []
        def mock_enviar(chat_id, txt, reply_markup=None):
            mensajes.append(txt)
            return 88888

        # En arranque: debe sincronizar sin enviar a Telegram
        anunciados = chequear_canales(mock_enviar, 12345, es_arranque=True)
        self.assertEqual(anunciados, 0, "En arranque no debe disparar anuncios para evitar duplicados de despliegue.")
        self.assertEqual(len(mensajes), 0)
        with _MEMORIA_LOCK:
            self.assertIn("VID_RECENT_FEED", _VIDEOS_VISTOS_MEMORIA)

    @patch("radar_youtube.precargar_audio_segundo_plano")
    @patch("radar_youtube.sincronizar_github_vistos")
    @patch("radar_youtube.obtener_url_miniatura", return_value="https://img.youtube.com/vi/VID_NUEVO_OPERACION/hqdefault.jpg")
    @patch("radar_youtube.extraer_videos_canal")
    def test_chequear_canales_en_operacion_anuncia_nuevo_video(self, mock_extraer, mock_thumb, mock_gh, mock_precarga):
        """Verifica que en operación normal (es_arranque=False), un nuevo video sí se anuncie a Telegram."""
        ahora = datetime.now(timezone.utc)
        pub_2m_atras = ahora - timedelta(minutes=2)

        mock_extraer.return_value = [
            {
                "video_id": "VIDNUEVOOPERACION",
                "titulo": "Nuevo Video en Operacion",
                "published_text": "hace 2 minutos",
                "published_dt": pub_2m_atras,
                "link": "https://youtu.be/VIDNUEVOOPERACION",
                "source": "web"
            }
        ]

        mensajes = []
        def mock_enviar(chat_id, txt, reply_markup=None):
            mensajes.append(txt)
            return 88888

        anunciados = chequear_canales(mock_enviar, 12345, es_arranque=False)
        self.assertEqual(anunciados, 1, "En operación normal el video nuevo debe anunciarse.")
        self.assertEqual(len(mensajes), 1)
        self.assertIn("VIDNUEVOOPERACION", mensajes[0])


if __name__ == "__main__":
    unittest.main()
