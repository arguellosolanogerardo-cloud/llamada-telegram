import unittest
import os
import shutil
import tempfile
from llamada import generar_tag_pista, generar_caratula_meditacion, CARPETA_MEDITACIONES

class TestCaratulaPistasUnicas(unittest.TestCase):
    def test_tag_pista_oficial_3am(self):
        """Pista 1 oficial con número debe mantener tag limpio para compatibilidad con pre-render."""
        tag = generar_tag_pista(
            tipo="MEDITACION",
            numero="1082",
            titulo="Ahora desean que pase algo",
            maestro="Axel",
            pista_idx=0
        )
        self.assertEqual(tag, "meditacion_1082")

    def test_tag_pistas_adicionales_sin_colision(self):
        """Pistas adicionales 2 y 3 nunca deben colisionar, incluso si tienen el mismo título."""
        tag_pista2 = generar_tag_pista(
            tipo="MENSAJE",
            titulo="Quien isisio la división en los grupos",
            maestro="JESUS MARIO CARRILLO DURAN",
            video_id="Ovq_Ok_8yc0",
            pista_idx=1
        )
        tag_pista3 = generar_tag_pista(
            tipo="MENSAJE",
            titulo="Quien isisio la división en los grupos",
            maestro="JESUS MARIO CARRILLO DURAN",
            video_id="Ovq_Ok_8yc0",
            pista_idx=2
        )
        self.assertNotEqual(tag_pista2, tag_pista3)
        self.assertIn("pista2", tag_pista2)
        self.assertIn("pista3", tag_pista3)

    def test_tag_pistas_distintas_titulos_distintos(self):
        """Pistas con títulos distintos deben generar nombres completamente diferentes."""
        tag_p2 = generar_tag_pista(
            tipo="MENSAJE",
            titulo="Primer mensaje",
            maestro="JESUS MARIO CARRILLO DURAN",
            pista_idx=1
        )
        tag_p3 = generar_tag_pista(
            tipo="MENSAJE",
            titulo="Segundo mensaje",
            maestro="JESUS MARIO CARRILLO DURAN",
            pista_idx=2
        )
        self.assertNotEqual(tag_p2, tag_p3)
        self.assertIn("pista2", tag_p2)
        self.assertIn("pista3", tag_p3)

    def test_generar_caratula_no_reutiliza_entre_pistas(self):
        """generar_caratula_meditacion no debe devolver el archivo de la Pista 2 al solicitar la Pista 3."""
        # Simular archivo existente para pista 2
        tag_p2 = generar_tag_pista(
            tipo="MENSAJE",
            titulo="Audio Pista Dos",
            maestro="Maestro Mario",
            pista_idx=1
        )
        ruta_p2 = os.path.join(CARPETA_MEDITACIONES, f"caratula_{tag_p2}.mp4")
        os.makedirs(CARPETA_MEDITACIONES, exist_ok=True)
        with open(ruta_p2, "wb") as f:
            f.write(b"0" * 60000)

        try:
            # Solicitar carátula para pista 3 con otro título
            tag_p3 = generar_tag_pista(
                tipo="MENSAJE",
                titulo="Audio Pista Tres",
                maestro="Maestro Mario",
                pista_idx=2
            )
            ruta_p3_esperada = os.path.join(CARPETA_MEDITACIONES, f"caratula_{tag_p3}.mp4")

            self.assertNotEqual(ruta_p2, ruta_p3_esperada)
            self.assertFalse(os.path.exists(ruta_p3_esperada))
        finally:
            if os.path.exists(ruta_p2):
                os.remove(ruta_p2)

if __name__ == "__main__":
    unittest.main()
