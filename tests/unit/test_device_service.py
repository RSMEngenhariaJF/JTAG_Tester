"""Testes unitários de DeviceService.

Usa unittest.mock para simular StLinkADIv5 e core.svd.parser.parse
— sem hardware real nem arquivo SVD em disco.

Execução:
    pytest tests/unit/test_device_service.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.device import DeviceService

_MOCK_DPIDR = 0x2BA01477
_PATCH_ADIV5 = "adapters.stlink.adiv5.StLinkADIv5"
_PATCH_PARSE  = "app.services.device.parse"   # parse() chamado dentro de connect()


@pytest.fixture
def svc(qtbot):
    """DeviceService com QApplication disponível via qtbot."""
    return DeviceService()


@pytest.fixture
def board():
    """BoardConfig mínimo para testes unitários."""
    from boards.nucleo_f446re import BOARD
    return BOARD


@pytest.fixture
def mock_adiv5():
    """Stub de StLinkADIv5 que simula conexão bem-sucedida."""
    adiv5 = MagicMock()
    adiv5.init.return_value = _MOCK_DPIDR
    return adiv5


@pytest.fixture
def mock_svd():
    return MagicMock()


# ===========================================================================
# Estado inicial
# ===========================================================================


class TestDeviceServiceInitial:
    def test_not_connected_initially(self, svc) -> None:
        assert not svc.is_connected

    def test_pal_is_none_initially(self, svc) -> None:
        assert svc.pal is None


# ===========================================================================
# connect() — sucesso
# ===========================================================================


class TestDeviceServiceConnect:
    def test_probe_connected_signal_emitted(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5):
                with qtbot.waitSignal(svc.probe_connected, timeout=2000) as sig:
                    svc.connect(board)
        assert len(sig.args) == 1

    def test_probe_connected_message_contains_dpidr(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5):
                with qtbot.waitSignal(svc.probe_connected, timeout=2000) as sig:
                    svc.connect(board)
        assert "2BA01477" in sig.args[0]

    def test_is_connected_after_connect(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5):
                with qtbot.waitSignal(svc.probe_connected, timeout=2000):
                    svc.connect(board)
        assert svc.is_connected

    def test_pal_not_none_after_connect(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5):
                with qtbot.waitSignal(svc.probe_connected, timeout=2000):
                    svc.connect(board)
        assert svc.pal is not None

    def test_connect_idempotent(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        """Segunda chamada a connect() não abre nova sessão."""
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5):
                with qtbot.waitSignal(svc.probe_connected, timeout=2000):
                    svc.connect(board)
                svc.connect(board)   # segunda chamada — não deve criar outro adiv5
        mock_adiv5._open.assert_called_once()

    def test_adiv5_open_called(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5):
                with qtbot.waitSignal(svc.probe_connected, timeout=2000):
                    svc.connect(board)
        mock_adiv5._open.assert_called_once()

    def test_adiv5_init_called(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5):
                with qtbot.waitSignal(svc.probe_connected, timeout=2000):
                    svc.connect(board)
        mock_adiv5.init.assert_called_once()

    def test_connect_passes_uid_to_adiv5(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5) as cls:
                with qtbot.waitSignal(svc.probe_connected, timeout=2000):
                    svc.connect(board, uid="DEADBEEF1234")
        _, kwargs = cls.call_args
        assert kwargs.get("uid") == "DEADBEEF1234"

    def test_connect_passes_target_to_adiv5(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5) as cls:
                with qtbot.waitSignal(svc.probe_connected, timeout=2000):
                    svc.connect(board)
        _, kwargs = cls.call_args
        assert kwargs.get("target") == board.target


# ===========================================================================
# connect() — falha
# ===========================================================================


class TestDeviceServiceConnectError:
    def test_probe_error_emitted_on_exception(self, qtbot, svc, board) -> None:
        with patch(_PATCH_PARSE, return_value=MagicMock()):
            with patch(_PATCH_ADIV5, side_effect=RuntimeError("USB não encontrado")):
                with qtbot.waitSignal(svc.probe_error, timeout=2000) as sig:
                    svc.connect(board)
        assert "USB não encontrado" in sig.args[0]

    def test_not_connected_after_error(self, qtbot, svc, board) -> None:
        with patch(_PATCH_PARSE, return_value=MagicMock()):
            with patch(_PATCH_ADIV5, side_effect=RuntimeError("boom")):
                with qtbot.waitSignal(svc.probe_error, timeout=2000):
                    svc.connect(board)
        assert not svc.is_connected

    def test_pal_none_after_error(self, qtbot, svc, board) -> None:
        with patch(_PATCH_PARSE, return_value=MagicMock()):
            with patch(_PATCH_ADIV5, side_effect=RuntimeError("boom")):
                with qtbot.waitSignal(svc.probe_error, timeout=2000):
                    svc.connect(board)
        assert svc.pal is None

    def test_open_fails_emits_error(self, qtbot, svc, board) -> None:
        mock = MagicMock()
        mock._open.side_effect = OSError("sem permissão USB")
        with patch(_PATCH_PARSE, return_value=MagicMock()):
            with patch(_PATCH_ADIV5, return_value=mock):
                with qtbot.waitSignal(svc.probe_error, timeout=2000) as sig:
                    svc.connect(board)
        assert "USB" in sig.args[0]


# ===========================================================================
# disconnect()
# ===========================================================================


class TestDeviceServiceDisconnect:
    def _connect(self, qtbot, svc, board, mock_adiv5, mock_svd):
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5):
                with qtbot.waitSignal(svc.probe_connected, timeout=2000):
                    svc.connect(board)

    def test_disconnected_signal_emitted(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        self._connect(qtbot, svc, board, mock_adiv5, mock_svd)
        with qtbot.waitSignal(svc.probe_disconnected, timeout=2000):
            svc.disconnect()

    def test_is_connected_false_after_disconnect(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        self._connect(qtbot, svc, board, mock_adiv5, mock_svd)
        svc.disconnect()
        assert not svc.is_connected

    def test_pal_none_after_disconnect(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        self._connect(qtbot, svc, board, mock_adiv5, mock_svd)
        svc.disconnect()
        assert svc.pal is None

    def test_adiv5_close_called(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        self._connect(qtbot, svc, board, mock_adiv5, mock_svd)
        svc.disconnect()
        mock_adiv5._close.assert_called_once()

    def test_disconnect_idempotent(self, svc) -> None:
        """Chamar disconnect() sem estar conectado não levanta exceção."""
        svc.disconnect()


# ===========================================================================
# list_probes()
# ===========================================================================


class TestListProbes:
    def test_returns_list(self) -> None:
        result = DeviceService.list_probes()
        assert isinstance(result, list)

    def test_returns_empty_on_exception(self) -> None:
        with patch("pyocd.core.helpers.ConnectHelper.get_all_connected_probes",
                   side_effect=RuntimeError("sem USB")):
            result = DeviceService.list_probes()
        assert isinstance(result, list)

    def test_returns_probe_infos(self) -> None:
        from app.services.device import ProbeInfo
        result = DeviceService.list_probes()
        assert all(isinstance(p, ProbeInfo) for p in result)


# ===========================================================================
# identify()
# ===========================================================================


def _id_mem(addr: int) -> int:
    """Memória do F446: CPUID Cortex-M4 + DBGMCU_IDCODE DEV_ID 0x421."""
    return {0xE000ED00: 0x410FC241, 0xE0042000: 0x10006421}[addr]


class TestIdentify:
    def test_identify_stlink_scans_access_ports(self, qtbot, svc) -> None:
        ap = MagicMock()
        ap.read_mem32.side_effect = _id_mem
        scan = MagicMock(dpidr=_MOCK_DPIDR, mem_aps=[ap])
        scan.__enter__.return_value = scan
        with patch("adapters.stlink.probe_reader.StLinkApScanner",
                   return_value=scan) as cls:
            with qtbot.waitSignal(svc.mcu_identified, timeout=2000) as sig:
                svc.identify()
        cls.assert_called_once_with(uid=None)
        assert sig.args[0].family == "STM32F446"
        assert not svc.is_connected   # sessão temporária fechada

    def test_identify_reuses_open_session(
        self, qtbot, svc, board, mock_adiv5, mock_svd
    ) -> None:
        mock_adiv5.read_mem32.side_effect = _id_mem
        with patch(_PATCH_PARSE, return_value=mock_svd):
            with patch(_PATCH_ADIV5, return_value=mock_adiv5) as cls:
                svc.connect(board)
                info = svc.identify()
        assert cls.call_count == 1
        assert info is not None and info.dev_id == 0x421
        assert svc.is_connected

    def test_identify_ft2232h_probe(self, qtbot, svc) -> None:
        from app.services.device import PROBE_FT2232H, ProbeInfo

        adiv5 = MagicMock()
        adiv5.init.return_value = _MOCK_DPIDR
        adiv5.read_mem32.side_effect = _id_mem
        probe = ProbeInfo("FT2232H", "ftdi://0x0403:0x6010:X/1", PROBE_FT2232H)
        with patch("adapters.ft2232h.FT2232HTransport") as transport_cls, \
             patch("core.adiv5.ADIv5", return_value=adiv5):
            info = svc.identify(probe)
        transport_cls.assert_called_once_with(url="ftdi://0x0403:0x6010:X/1")
        assert info is not None and info.family == "STM32F446"

    def test_identify_error_emits_probe_error(self, qtbot, svc) -> None:
        with patch("adapters.stlink.probe_reader.StLinkApScanner",
                   side_effect=RuntimeError("sem probe")):
            with qtbot.waitSignal(svc.probe_error, timeout=2000) as sig:
                assert svc.identify() is None
        assert "sem probe" in sig.args[0]
