"""
Pruebas de regresión y validación para la diferenciación robusta
entre MEDITACIÓN y MENSAJE en carátulas, videos, paneles y catálogos.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Añadir ruta raíz al PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from catalogo_audios import identificar_audio_catalogo, formatear_info_audio
import astronomia_luna
import llamada


class TestDiferenciarMeditacionMensaje(unittest.TestCase):

    def test_catalogo_identifica_tipo_correcto(self):
        """Verifica que el catálogo distingue entre Mensaje 729 y Meditación 1092."""
        info_729 = identificar_audio_catalogo("mensaje 729")
        self.assertIsNotNone(info_729)
        self.assertEqual(info_729.get("tipo"), "MENSAJE")
        self.assertEqual(int(info_729.get("numero")), 729)

        info_1092 = identificar_audio_catalogo("meditacion 1092")
        self.assertIsNotNone(info_1092)
        self.assertEqual(info_1092.get("tipo"), "MEDITACION")
        self.assertEqual(int(info_1092.get("numero")), 1092)

    def test_formatear_info_audio_distingue_mensaje_y_meditacion(self):
        """Verifica que formatear_info_audio usa iconos y textos propios para cada tipo."""
        info_msg = {
            "numero": 729,
            "tipo": "MENSAJE",
            "titulo": "Mensaje del 19 jun 2015",
            "maestro": "Alaniso y Alan",
            "fecha": "19 jun 2015"
        }
        txt_msg = formatear_info_audio(info_msg)
        self.assertIn("📜✨ **MENSAJE #729:**", txt_msg)
        self.assertNotIn("MEDITACIÓN #729", txt_msg)

        info_med = {
            "numero": 1092,
            "tipo": "MEDITACION",
            "titulo": "Vivir para conocer al Padre",
            "maestro": "Aliestro",
            "fecha": "12/04/20"
        }
        txt_med = formatear_info_audio(info_med)
        self.assertIn("🧘✨ **MEDITACIÓN #1092:**", txt_med)
        self.assertNotIn("MENSAJE #1092", txt_med)

    def test_generar_caratula_luna_cabecera_mensaje(self):
        """Verifica que generar_caratula_meditacion_luna dibuja MENSAJE #729 y no MEDITACIÓN #729."""
        textos_dibujados = []

        # Interceptar ImageDraw.Draw.text para capturar los textos que se dibujan en la carátula
        with patch("astronomia_luna.crear_universo_con_orion") as mock_crear:
            from PIL import Image
            mock_crear.return_value = Image.new("RGB", (1280, 720), (0, 0, 0))

            with patch("PIL.ImageDraw.ImageDraw.text") as mock_text:
                def fake_text(xy, text, *args, **kwargs):
                    textos_dibujados.append(text)

                mock_text.side_effect = fake_text

                ruta_out = os.path.join("data", "meditaciones", "test_caratula_729.jpg")
                try:
                    astronomia_luna.generar_caratula_meditacion_luna(
                        numero="729",
                        titulo="Mensaje del 19 jun 2015",
                        maestro="Alaniso y Alan",
                        duracion_seg=600.0,
                        progreso_seg=0.0,
                        ruta_salida=ruta_out,
                        tipo="MENSAJE"
                    )
                finally:
                    if os.path.exists(ruta_out):
                        os.remove(ruta_out)

                # Comprobar que en la cabecera se usó MENSAJE #729
                self.assertIn("MENSAJE #729", textos_dibujados)
                self.assertNotIn("MEDITACIÓN #729", textos_dibujados)

    def test_generar_caratula_luna_cabecera_meditacion(self):
        """Verifica que generar_caratula_meditacion_luna dibuja MEDITACIÓN #1092 para meditaciones."""
        textos_dibujados = []

        with patch("astronomia_luna.crear_universo_con_orion") as mock_crear:
            from PIL import Image
            mock_crear.return_value = Image.new("RGB", (1280, 720), (0, 0, 0))

            with patch("PIL.ImageDraw.ImageDraw.text") as mock_text:
                def fake_text(xy, text, *args, **kwargs):
                    textos_dibujados.append(text)

                mock_text.side_effect = fake_text

                ruta_out = os.path.join("data", "meditaciones", "test_caratula_1092.jpg")
                try:
                    astronomia_luna.generar_caratula_meditacion_luna(
                        numero="1092",
                        titulo="Vivir para conocer al Padre",
                        maestro="Aliestro",
                        duracion_seg=600.0,
                        progreso_seg=0.0,
                        ruta_salida=ruta_out,
                        tipo="MEDITACION"
                    )
                finally:
                    if os.path.exists(ruta_out):
                        os.remove(ruta_out)

                self.assertIn("MEDITACIÓN #1092", textos_dibujados)
                self.assertNotIn("MENSAJE #1092", textos_dibujados)

    def test_aislamiento_cache_caratula_video(self):
        """Verifica que generar_caratula_meditacion aísla las rutas de caché por tipo y número."""
        with patch("astronomia_luna.generar_video_meditacion_luna") as mock_vid:
            mock_vid.return_value = "data/meditaciones/caratula_mensaje_729.mp4"

            with patch("os.path.exists", return_value=False):
                llamada.generar_caratula_meditacion(
                    numero="729",
                    titulo="Mensaje del 19 jun 2015",
                    maestro="Alaniso",
                    duracion_seg=900.0,
                    tipo="MENSAJE"
                )

                # Verificar llamada a generar_video_meditacion_luna con ruta y tipo adecuados
                mock_vid.assert_called_once()
                args, kwargs = mock_vid.call_args
                self.assertEqual(kwargs.get("tipo"), "MENSAJE")
                self.assertIn("caratula_mensaje_729.mp4", kwargs.get("ruta_salida"))

    def test_inferencia_tipo_por_titulo_si_falta(self):
        """Verifica que si no hay tipo explícito pero el título dice 'Mensaje', se clasifica como MENSAJE."""
        with patch("astronomia_luna.generar_video_meditacion_luna") as mock_vid:
            mock_vid.return_value = "data/meditaciones/caratula_mensaje_729.mp4"

            with patch("os.path.exists", return_value=False):
                llamada.generar_caratula_meditacion(
                    numero="729",
                    titulo="Mensaje del 19 jun 2015",
                    maestro="Alaniso",
                    duracion_seg=900.0,
                    tipo="MENSAJE"  # Deducido
                )
                args, kwargs = mock_vid.call_args
                self.assertEqual(kwargs.get("tipo"), "MENSAJE")


if __name__ == "__main__":
    unittest.main()
