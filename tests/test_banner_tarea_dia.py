"""
Pruebas unitarias para la generación de la tarjeta gráfica oficial de la Tarea del Día (3 AM).
Verifica que generar_banner_tarea_dia renderiza correctamente meditaciones y mensajes,
ajustando dinámicamente títulos largos, números y datos del catálogo.
"""
import os
import sys
import unittest

# Añadir ruta raíz al PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from publicar_tarea import generar_banner_tarea_dia, enviar_foto

class TestBannerTareaDia(unittest.TestCase):

    def setUp(self):
        self.ruta_out = os.path.join("data", "meditaciones", "test_banner_unit.png")
        if os.path.exists(self.ruta_out):
            try:
                os.remove(self.ruta_out)
            except Exception:
                pass

    def tearDown(self):
        if os.path.exists(self.ruta_out):
            try:
                os.remove(self.ruta_out)
            except Exception:
                pass

    def test_generar_banner_meditacion_1090(self):
        """Verifica la generación exitosa para la meditación #1090 con fecha y maestro."""
        info = {
            "numero": 1090,
            "tipo": "MEDITACION",
            "titulo": "No frenen su evolucion con la falta de control de sus emociones",
            "maestro": "Alaniso y Azoes",
            "fecha": "08/21/20"
        }
        res = generar_banner_tarea_dia(self.ruta_out, info, dia_semana="MARTES", fecha_str="27/10/2026")
        self.assertIsNotNone(res)
        self.assertTrue(os.path.exists(self.ruta_out))
        self.assertGreater(os.path.getsize(self.ruta_out), 50000)

    def test_generar_banner_mensaje_largo(self):
        """Verifica la adaptación tipográfica cuando el título es extenso y es de tipo MENSAJE."""
        info = {
            "numero": 729,
            "tipo": "MENSAJE",
            "titulo": "Preparamos este mensaje para convertirlos en Maestros que solo sepan Amar con toda devoción y entrega hacia el Padre Creador",
            "maestro": "JESUS MARIO CARRILLO DURAN",
            "fecha": "19 jun 2015"
        }
        res = generar_banner_tarea_dia(self.ruta_out, info, dia_semana="MIÉRCOLES", fecha_str="28/10/2026")
        self.assertIsNotNone(res)
        self.assertTrue(os.path.exists(self.ruta_out))
        self.assertGreater(os.path.getsize(self.ruta_out), 50000)

    def test_enviar_foto_retorna_falso_si_no_existe_archivo(self):
        """Verifica que enviar_foto maneja rutas inexistentes sin lanzar excepciones no controladas."""
        ok, mid, fid = enviar_foto("12345", "ruta_inexistente_12345.png")
        self.assertFalse(ok)
        self.assertIsNone(mid)

if __name__ == '__main__':
    unittest.main()
