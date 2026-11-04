import unittest
import os
from llamada import (
    obtener_sonido_campana_inicio,
    obtener_sonido_campana_salida,
    obtener_duracion_segundos,
)


class TestSonidosMeditacion(unittest.TestCase):

    def test_sonido_inicio_resuelve_pajaros(self):
        s_inicio = obtener_sonido_campana_inicio()
        self.assertTrue(os.path.exists(s_inicio), f"El archivo {s_inicio} debe existir")
        self.assertTrue(
            "sonido AL INICIO PAJAROS de meditacion.wav" in s_inicio,
            f"Se esperaba 'sonido AL INICIO PAJAROS de meditacion.wav', obtenido: {s_inicio}",
        )
        dur = obtener_duracion_segundos(s_inicio)
        self.assertGreater(dur, 10.0, "La duración del audio de inicio debe ser > 10s")
        self.assertLess(dur, 13.0, "La duración del audio de inicio debe ser < 13s")

    def test_sonido_salida_resuelve_pajaros(self):
        s_salida = obtener_sonido_campana_salida()
        self.assertTrue(os.path.exists(s_salida), f"El archivo {s_salida} debe existir")
        self.assertTrue(
            "sonido AL FINAL PAJAROS de meditacion.mp3.wav" in s_salida,
            f"Se esperaba 'sonido AL FINAL PAJAROS de meditacion.mp3.wav', obtenido: {s_salida}",
        )
        dur = obtener_duracion_segundos(s_salida)
        self.assertGreater(dur, 4.0, "La duración del audio de salida debe ser > 4s")
        self.assertLess(dur, 7.0, "La duración del audio de salida debe ser < 7s")


if __name__ == "__main__":
    unittest.main()
