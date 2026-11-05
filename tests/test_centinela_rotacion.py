import unittest
import inspect
from centinela_youtube import rotar_audios_limpios, main
import argparse

class TestCentinelaRotacion(unittest.TestCase):
    def test_default_limite_max_es_21(self):
        """Verifica que el parámetro por defecto de rotar_audios_limpios sea 21."""
        sig = inspect.signature(rotar_audios_limpios)
        self.assertEqual(sig.parameters['limite_max'].default, 21)

    def test_cli_argument_default_es_21(self):
        """Verifica que el argumento CLI --max-cache tenga default 21."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--max-cache", "-m", type=int, default=21)
        args = parser.parse_args([])
        self.assertEqual(args.max_cache, 21)

if __name__ == "__main__":
    unittest.main()
