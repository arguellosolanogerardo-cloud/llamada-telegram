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

    @patch("radar_youtube.precargar_audio_segundo_plano")
    @patch("radar_youtube.sincronizar_github_vistos")
    @patch("radar_youtube.obtener_url_miniatura", return_value="https://img.youtube.com/vi/NUEVO123456/hqdefault.jpg")
    @patch("radar_youtube.extraer_videos_canal")
    def test_chequear_canales_anuncia_video_reciente_incluso_en_arranque(self, mock_extraer, mock_thumb, mock_gh, mock_precarga):
        """Verifica que un video publicado hace 20 minutos se anuncie aunque es_arranque sea True."""
        ahora = datetime.now(timezone.utc)
        pub_20m_atras = ahora - timedelta(minutes=20)

        mock_extraer.return_value = [
            {
                "video_id": "NUEVO123456",
                "titulo": "Video Nuevo de Prueba",
                "published_text": "hace 20 minutos",
                "published_dt": pub_20m_atras,
                "link": "https://youtu.be/NUEVO123456",
                "source": "web"
            }
        ]

        mensajes = []
        def mock_enviar(chat_id, txt, reply_markup=None):
            mensajes.append(txt)
            return 88888

        # Ejecutando con es_arranque=True
        anunciados = chequear_canales(mock_enviar, 12345, es_arranque=True)
        self.assertEqual(anunciados, 1, "El video de hace 20 minutos debe anunciarse aun en arranque.")
        self.assertEqual(len(mensajes), 1)
        self.assertIn("NUEVO123456", mensajes[0])


if __name__ == "__main__":
    unittest.main()
