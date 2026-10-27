import os
import unittest
from PIL import Image
from publicar_tarea import generar_tarjeta_audio

class TestTarjetaAudio(unittest.TestCase):
    def setUp(self):
        self.ruta_hd = os.path.join("data", "meditaciones", "test_tarjeta_hd.png")
        self.ruta_thumb = os.path.join("data", "meditaciones", "test_cover_thumb.jpg")
        self.info = {
            "numero": "1090",
            "titulo": "No frenen su evolucion con la falta de control de sus emociones",
            "maestro": "Alaniso y Azoes",
            "fecha": "08/21/20",
            "tipo": "MEDITACION"
        }

    def tearDown(self):
        for p in (self.ruta_hd, self.ruta_thumb):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_deberia_generar_tarjeta_hd_y_thumbnail_cuadrado(self):
        res = generar_tarjeta_audio(self.ruta_hd, self.ruta_thumb, self.info)
        self.assertIsNotNone(res)
        self.assertTrue(os.path.exists(self.ruta_hd))
        self.assertTrue(os.path.exists(self.ruta_thumb))
        self.assertGreater(os.path.getsize(self.ruta_hd), 1000)
        self.assertGreater(os.path.getsize(self.ruta_thumb), 1000)
        # Requisito de Telegram: thumbnail < 200 KB
        self.assertLess(os.path.getsize(self.ruta_thumb), 200 * 1024)

        # Dimensiones exactas
        with Image.open(self.ruta_hd) as img_hd:
            self.assertEqual(img_hd.size, (960, 560))
        with Image.open(self.ruta_thumb) as img_th:
            self.assertEqual(img_th.size, (320, 320))

if __name__ == "__main__":
    unittest.main()
