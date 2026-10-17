import unittest
import threading
import time
import tempfile
import os
import json
from unittest.mock import patch
import radar_youtube
from radar_youtube import _RADAR_LOCK, _MEMORIA_LOCK, _VIDEOS_EN_PROCESO, _VIDEOS_VISTOS_MEMORIA, anunciar_video_manual, chequear_canales


class TestRadarAntiDuplicados(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db = os.path.join(self.temp_dir.name, "radar_vistos_test.json")
        with open(self.temp_db, "w", encoding="utf-8") as f:
            json.dump(["INITIAL_1", "INITIAL_2"], f)
        
        self.orig_db_path = radar_youtube.RADAR_DB_PATH
        radar_youtube.RADAR_DB_PATH = self.temp_db

        with _MEMORIA_LOCK:
            _VIDEOS_EN_PROCESO.clear()
            _VIDEOS_VISTOS_MEMORIA.clear()
            _VIDEOS_VISTOS_MEMORIA.add("INITIAL_1")
            _VIDEOS_VISTOS_MEMORIA.add("INITIAL_2")

    def tearDown(self):
        radar_youtube.RADAR_DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()
        with _MEMORIA_LOCK:
            _VIDEOS_EN_PROCESO.clear()
            _VIDEOS_VISTOS_MEMORIA.clear()

    def test_radar_lock_evita_ejecucion_concurrente(self):
        """Si un hilo tiene adquirido el lock, otro hilo que intente chequear_canales retorna 0 de inmediato."""
        adquirido = _RADAR_LOCK.acquire(blocking=False)
        self.assertTrue(adquirido, "El lock debería poder adquirirse.")

        # Desde otro hilo o llamada concurrente, chequear_canales debe retornar 0
        resultado_concurrente = chequear_canales(lambda *args, **kwargs: 1, 12345)
        self.assertEqual(resultado_concurrente, 0, "No debe ejecutar chequeo si ya hay uno en curso.")

        _RADAR_LOCK.release()

    @patch("radar_youtube.sincronizar_github_vistos")
    @patch("radar_youtube.obtener_info_oembed", return_value={"title": "Video de Prueba AntiDuplicado", "author_name": "ALANISO 2012"})
    def test_en_proceso_evita_doble_envio_simultaneo(self, mock_oembed, mock_gh):
        """Verifica que dos llamadas simultáneas a anunciar_video_manual para el mismo video no envíen duplicado."""
        mensajes_enviados = []

        def mock_enviar_foto(chat, url, caption, reply_markup=None):
            time.sleep(0.15)  # Simular latencia de red en Telegram
            mensajes_enviados.append(caption)
            return 99999

        vid_test = f"TEST_VID_{int(time.time() * 1000)}"

        t1 = threading.Thread(target=anunciar_video_manual, args=(vid_test, None, 12345, mock_enviar_foto, False))
        t2 = threading.Thread(target=anunciar_video_manual, args=(vid_test, None, 12345, mock_enviar_foto, False))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Solo debe haberse enviado 1 mensaje a Telegram
        self.assertEqual(len(mensajes_enviados), 1, f"Se esperaba 1 solo mensaje enviado, pero se enviaron {len(mensajes_enviados)}")

        # El video debe haber quedado en _VIDEOS_VISTOS_MEMORIA y fuera de _VIDEOS_EN_PROCESO
        with _MEMORIA_LOCK:
            self.assertIn(vid_test, _VIDEOS_VISTOS_MEMORIA)
            self.assertNotIn(vid_test, _VIDEOS_EN_PROCESO)


if __name__ == "__main__":
    unittest.main()
