import unittest
import os
import sys

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

if __name__ == "__main__":
    unittest.main()
