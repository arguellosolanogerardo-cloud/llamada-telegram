import unittest
from unittest.mock import patch, MagicMock
import json
import bot_comandos

class TestPermisosBotones(unittest.TestCase):
    def test_admin_fijo_es_admin(self):
        """Los IDs oficiales fijos siempre son reconocidos como administradores."""
        for admin_id in (8204833441, 8278899029, 8916842088, 8384683142, 1779560581, 6902578190, 8953593022):
            self.assertTrue(bot_comandos.es_usuario_admin(admin_id))

    def test_usuario_normal_no_es_admin(self):
        """Un usuario normal NO es administrador."""
        id_normal = 999888777
        self.assertFalse(bot_comandos.es_usuario_admin(id_normal))

    def test_chat_privado_no_concede_admin(self):
        """Interactuar en chat privado jamás debe convertir a un usuario normal en admin."""
        id_normal = 999888777
        admins = bot_comandos.obtener_admin_ids(target_chat=id_normal)
        self.assertNotIn(id_normal, admins)
        self.assertFalse(bot_comandos.es_usuario_admin(id_normal, chat_id=id_normal))

    def test_procesar_programacion_bloquea_no_admin(self):
        """procesar_programacion_yttarea aborta si el usuario no es admin."""
        with patch("bot_comandos.descargar_audio_youtube_robusto") as mock_dl:
            bot_comandos.procesar_programacion_yttarea("fake_vid_123", u_admin_id=999888777, chat_destino=-100123)
            # No debió llamar a descargar
            mock_dl.assert_not_called()

    def test_admin_autorizado_puede_programar(self):
        """Un administrador oficial sí puede programar tareas."""
        self.assertTrue(bot_comandos.es_usuario_admin(8204833441, chat_id=-100123))

if __name__ == "__main__":
    unittest.main()
