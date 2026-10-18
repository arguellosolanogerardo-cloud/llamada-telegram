import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from radar_youtube import evaluar_recencia_texto, extraer_entradas_xml, CANALES_RADAR, obtener_info_oembed

class TestRadarRecencia(unittest.TestCase):

    def test_evaluar_recencia_texto_espanol(self):
        self.assertTrue(evaluar_recencia_texto("hace 1 hora"))
        self.assertTrue(evaluar_recencia_texto("hace 2 horas"))
        self.assertTrue(evaluar_recencia_texto("hace 1 h"))
        self.assertTrue(evaluar_recencia_texto("hace 15 minutos"))
        self.assertTrue(evaluar_recencia_texto("hace 35 min"))
        self.assertTrue(evaluar_recencia_texto("En vivo"))
        self.assertFalse(evaluar_recencia_texto("hace 3 horas"))
        self.assertFalse(evaluar_recencia_texto("hace 7 horas"))
        self.assertFalse(evaluar_recencia_texto("hace 11 horas"))
        self.assertFalse(evaluar_recencia_texto("hace 14 horas"))
        self.assertFalse(evaluar_recencia_texto("hace 2 días"))

    def test_evaluar_recencia_texto_ingles(self):
        self.assertTrue(evaluar_recencia_texto("1 hour ago"))
        self.assertTrue(evaluar_recencia_texto("2 hours ago"))
        self.assertTrue(evaluar_recencia_texto("1 hr ago"))
        self.assertTrue(evaluar_recencia_texto("streamed 1 hour ago"))
        self.assertTrue(evaluar_recencia_texto("15 minutes ago"))
        self.assertTrue(evaluar_recencia_texto("Live now"))
        self.assertFalse(evaluar_recencia_texto("3 hours ago"))
        self.assertFalse(evaluar_recencia_texto("7 hours ago"))
        self.assertFalse(evaluar_recencia_texto("16 hours ago"))
        self.assertFalse(evaluar_recencia_texto("3 days ago"))

    def test_oembed_mario_carrillo(self):
        info = obtener_info_oembed("v5zwtMKOj3A")
        self.assertTrue(bool(info.get("title")))
        self.assertIn("mario", info.get("author_name", "").lower())

    def test_extraer_entradas_xml(self):
        sample_xml = """<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015">
        <entry>
            <yt:videoId>v5zwtMKOj3A</yt:videoId>
            <title>Test Video Mario</title>
            <published>2026-10-16T14:48:02+00:00</published>
        </entry>
        </feed>"""
        entries = extraer_entradas_xml(sample_xml)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["video_id"], "v5zwtMKOj3A")
        self.assertIsNotNone(entries[0]["published_dt"])

    @patch("radar_youtube.extraer_videos_canal")
    @patch("radar_youtube.sincronizar_github_vistos")
    def test_chequear_canales_limite_un_anuncio_por_canal(self, mock_gh, mock_extraer):
        mock_extraer.return_value = [
            {"video_id": "BATCH_1", "titulo": "Video 1", "published_text": "hace 10 minutos", "published_dt": None, "link": "https://youtu.be/BATCH_1"},
            {"video_id": "BATCH_2", "titulo": "Video 2", "published_text": "hace 15 minutos", "published_dt": None, "link": "https://youtu.be/BATCH_2"},
            {"video_id": "BATCH_3", "titulo": "Video 3", "published_text": "hace 20 minutos", "published_dt": None, "link": "https://youtu.be/BATCH_3"},
        ]
        from radar_youtube import chequear_canales, _MEMORIA_LOCK, _VIDEOS_VISTOS_MEMORIA
        mensajes = []
        def mock_enviar(chat_id, txt, reply_markup=None):
            mensajes.append(txt)
            return 12345

        anunciados = chequear_canales(mock_enviar, 9999)
        # Debe anunciar a lo sumo 1 por canal y registrar el resto en silencio
        self.assertLessEqual(anunciados, 2)
        with _MEMORIA_LOCK:
            self.assertIn("BATCH_1", _VIDEOS_VISTOS_MEMORIA)
            self.assertIn("BATCH_2", _VIDEOS_VISTOS_MEMORIA)
            self.assertIn("BATCH_3", _VIDEOS_VISTOS_MEMORIA)

if __name__ == "__main__":
    unittest.main()

