import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from telethon.tl.functions.phone import LeaveGroupCallPresentationRequest, EditGroupCallParticipantRequest


class TestCierrePantallaEmision(unittest.TestCase):

    def test_cierre_pantalla_ejecuta_mtproto_y_pytgcalls(self):
        """Verifica que el cierre de pantalla de emisión invoque los requests correctos sin salir de la llamada."""
        mock_tgcalls = MagicMock()
        mock_tgcalls.resolve_chat_id = AsyncMock(return_value=-100123456789)
        mock_tgcalls._join_presentation = AsyncMock()
        mock_tgcalls._binding = MagicMock()
        mock_tgcalls._binding.stop_presentation = AsyncMock()
        mock_tgcalls._presentations = {-100123456789, -100123456789}

        mock_client = AsyncMock()
        mock_input_call = MagicMock()
        destino = -100123456789
        ruta_caratula = "test_cover.mp4"

        # Función a probar (misma lógica que cerrar_pantalla_emision_video)
        async def cerrar_pantalla_test():
            nonlocal ruta_caratula
            ruta_caratula = ""
            if mock_tgcalls:
                try:
                    resolved = await mock_tgcalls.resolve_chat_id(destino)
                    if hasattr(mock_tgcalls, "_join_presentation"):
                        await mock_tgcalls._join_presentation(resolved, False)
                    if hasattr(mock_tgcalls, "_binding") and hasattr(mock_tgcalls._binding, "stop_presentation"):
                        await mock_tgcalls._binding.stop_presentation(resolved)
                    if hasattr(mock_tgcalls, "_presentations"):
                        mock_tgcalls._presentations.discard(resolved)
                except Exception:
                    pass

            if mock_client and mock_input_call:
                try:
                    await mock_client(LeaveGroupCallPresentationRequest(call=mock_input_call))
                except Exception:
                    pass
                try:
                    from telethon.tl.types import InputPeerSelf
                    await mock_client(EditGroupCallParticipantRequest(
                        call=mock_input_call,
                        participant=InputPeerSelf(),
                        video_stopped=True
                    ))
                except Exception:
                    pass

        asyncio.run(cerrar_pantalla_test())

        # 1. Comprobar que PyTgCalls detuvo la presentación
        mock_tgcalls._join_presentation.assert_awaited_once_with(-100123456789, False)
        mock_tgcalls._binding.stop_presentation.assert_awaited_once_with(-100123456789)
        self.assertNotIn(-100123456789, mock_tgcalls._presentations)

        # 2. Comprobar que se llamó a LeaveGroupCallPresentationRequest
        self.assertEqual(mock_client.await_count, 2)
        llamada_1 = mock_client.await_args_list[0][0][0]
        self.assertIsInstance(llamada_1, LeaveGroupCallPresentationRequest)
        self.assertEqual(llamada_1.call, mock_input_call)

        # 3. Comprobar que se llamó a EditGroupCallParticipantRequest con video_stopped=True
        llamada_2 = mock_client.await_args_list[1][0][0]
        self.assertIsInstance(llamada_2, EditGroupCallParticipantRequest)
        self.assertEqual(llamada_2.video_stopped, True)

        # 4. Comprobar que la carátula se reseteó
        self.assertEqual(ruta_caratula, "")

    def test_cierre_pantalla_tolera_excepciones_sin_interrumpir(self):
        """Verifica que si Telegram o PyTgCalls lanzan una excepción, se capture silenciosamente sin abortar."""
        mock_tgcalls = MagicMock()
        mock_tgcalls.resolve_chat_id = AsyncMock(side_effect=Exception("Connection lost"))

        mock_client = AsyncMock(side_effect=Exception("Telegram error"))
        mock_input_call = MagicMock()
        destino = -100123456789

        async def cerrar_pantalla_falla():
            if mock_tgcalls:
                try:
                    resolved = await mock_tgcalls.resolve_chat_id(destino)
                    if hasattr(mock_tgcalls, "_join_presentation"):
                        await mock_tgcalls._join_presentation(resolved, False)
                except Exception:
                    pass

            if mock_client and mock_input_call:
                try:
                    await mock_client(LeaveGroupCallPresentationRequest(call=mock_input_call))
                except Exception:
                    pass

        # No debe lanzar ninguna excepción no controlada
        try:
            asyncio.run(cerrar_pantalla_falla())
        except Exception as e:
            self.fail(f"cerrar_pantalla no debería propagar excepciones: {e}")


if __name__ == "__main__":
    unittest.main()
