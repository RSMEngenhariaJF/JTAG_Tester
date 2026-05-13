"""Testes unitários do protocolo SWD — verifica bit-a-bit a conformidade com IHI0031C."""

from __future__ import annotations

from collections import deque

import pytest

from core.swd.errors import AckError, ParityError
from core.swd.protocol import (
    ACK_FAULT,
    ACK_OK,
    ACK_WAIT,
    AP_ADDR_CSW,
    AP_ADDR_DRW,
    DP_ADDR_CTRL_STAT,
    DP_ADDR_DPIDR,
    DP_ADDR_SELECT,
    SWDProtocol,
    _build_request,
    _even_parity,
)

# ===========================================================================
# MockTransport — grava writes, serve reads pré-configurados
# ===========================================================================


class MockTransport:
    def __init__(self) -> None:
        self.writes: list[tuple[int, int]] = []  # (value, count)
        self.turnarounds: int = 0
        self._reads: deque[int] = deque()

    def queue(self, *values: int) -> MockTransport:
        """Encadeia respostas para read_bits."""
        self._reads.extend(values)
        return self

    def write_bits(self, value: int, count: int) -> None:
        self.writes.append((value & ((1 << count) - 1), count))

    def read_bits(self, count: int) -> int:
        if not self._reads:
            raise RuntimeError("MockTransport: sem resposta na fila — configure com .queue()")
        return self._reads.popleft()

    def turnaround(self) -> None:
        self.turnarounds += 1

    # --- helpers de inspeção ---

    def total_high_bits(self) -> int:
        """Conta bits HIGH contíguos a partir do início (para validar line reset)."""
        count = 0
        for value, n in self.writes:
            expected = (1 << n) - 1
            if value == expected:
                count += n
            else:
                break
        return count

    def has_write(self, value: int, count: int) -> bool:
        return (value & ((1 << count) - 1), count) in self.writes

    def last_write(self) -> tuple[int, int]:
        return self.writes[-1]

    def request_byte(self) -> int:
        """Retorna o último byte de request de 8 bits enviado."""
        for value, count in reversed(self.writes):
            if count == 8:
                return value
        raise AssertionError("Nenhum write de 8 bits encontrado")


@pytest.fixture()
def t() -> MockTransport:
    return MockTransport()


@pytest.fixture()
def proto(t: MockTransport) -> SWDProtocol:
    return SWDProtocol(t)


# ===========================================================================
# Funções auxiliares
# ===========================================================================


class TestEvenParity:
    def test_all_zeros(self) -> None:
        assert _even_parity(0x0000_0000) == 0

    def test_all_ones(self) -> None:
        # 32 uns → parity = 0 (par)
        assert _even_parity(0xFFFF_FFFF) == 0

    def test_single_bit(self) -> None:
        assert _even_parity(0x0000_0001, 1) == 1

    def test_two_bits(self) -> None:
        assert _even_parity(0b11, 2) == 0

    def test_known_value(self) -> None:
        # 0xDEAD_BEEF: contar uns manualmente
        ones = bin(0xDEAD_BEEF).count("1")
        assert _even_parity(0xDEAD_BEEF) == ones % 2


class TestBuildRequest:
    def test_dpidr_read(self) -> None:
        # APnDP=0, RnW=1, A[3:2]=0b00 → parity=XOR(0,1,0,0)=1
        req = _build_request(apndp=0, rnw=1, addr=DP_ADDR_DPIDR)
        assert req & 0b1 == 1  # start
        assert (req >> 1) & 1 == 0  # DP
        assert (req >> 2) & 1 == 1  # read
        assert (req >> 3) & 1 == 0  # A2=0
        assert (req >> 4) & 1 == 0  # A3=0
        assert (req >> 5) & 1 == 1  # parity
        assert (req >> 6) & 1 == 0  # stop
        assert (req >> 7) & 1 == 1  # park
        assert req == 0xA5

    def test_ctrl_stat_read(self) -> None:
        # APnDP=0, RnW=1, addr=0x04 → A2=1, A3=0 → parity=XOR(0,1,1,0)=0
        req = _build_request(apndp=0, rnw=1, addr=DP_ADDR_CTRL_STAT)
        assert (req >> 3) & 1 == 1  # A2=1
        assert (req >> 4) & 1 == 0  # A3=0
        assert (req >> 5) & 1 == 0  # parity=0
        assert req == 0x8D

    def test_select_write(self) -> None:
        # APnDP=0, RnW=0, addr=0x08 → A2=0, A3=1 → parity=XOR(0,0,0,1)=1
        req = _build_request(apndp=0, rnw=0, addr=DP_ADDR_SELECT)
        assert (req >> 2) & 1 == 0  # write
        assert (req >> 4) & 1 == 1  # A3=1
        assert (req >> 5) & 1 == 1  # parity=1
        assert req == 0xB1

    def test_ap_read(self) -> None:
        # APnDP=1, RnW=1, addr=0x00 → A2=0, A3=0 → parity=XOR(1,1,0,0)=0
        req = _build_request(apndp=1, rnw=1, addr=AP_ADDR_CSW)
        assert (req >> 1) & 1 == 1  # AP
        assert (req >> 2) & 1 == 1  # read
        assert (req >> 5) & 1 == 0  # parity=0

    def test_park_always_set(self) -> None:
        for apndp in (0, 1):
            for rnw in (0, 1):
                for addr in (0x00, 0x04, 0x08, 0x0C):
                    req = _build_request(apndp, rnw, addr)
                    assert req & 0x80, f"Park bit ausente: apndp={apndp} rnw={rnw} addr={addr:#x}"

    def test_stop_always_clear(self) -> None:
        for apndp in (0, 1):
            for rnw in (0, 1):
                for addr in (0x00, 0x04, 0x08, 0x0C):
                    req = _build_request(apndp, rnw, addr)
                    assert not (req & 0x40), "Stop bit deve ser 0"


# ===========================================================================
# Line reset
# ===========================================================================


class TestLineReset:
    def test_at_least_50_high_bits(self, proto: SWDProtocol, t: MockTransport) -> None:
        proto.line_reset()
        assert t.total_high_bits() >= 50

    def test_ends_with_idle_byte(self, proto: SWDProtocol, t: MockTransport) -> None:
        proto.line_reset()
        assert t.last_write() == (0x00, 8)

    def test_exactly_56_high_plus_8_idle(self, proto: SWDProtocol, t: MockTransport) -> None:
        proto.line_reset()
        high = sum(n for v, n in t.writes if v == (1 << n) - 1)
        zeros = sum(n for v, n in t.writes if v == 0)
        assert high == 56
        assert zeros == 8


# ===========================================================================
# JTAG-to-SWD
# ===========================================================================


class TestJtagToSWD:
    def test_contains_magic_sequence(self, proto: SWDProtocol, t: MockTransport) -> None:
        proto.jtag_to_swd()
        assert t.has_write(0x9EE7, 16)

    def test_starts_with_line_reset(self, proto: SWDProtocol, t: MockTransport) -> None:
        proto.jtag_to_swd()
        assert t.total_high_bits() >= 50

    def test_ends_with_idle(self, proto: SWDProtocol, t: MockTransport) -> None:
        proto.jtag_to_swd()
        assert t.last_write() == (0x00, 8)

    def test_two_line_resets_present(self, proto: SWDProtocol, t: MockTransport) -> None:
        proto.jtag_to_swd()
        # Deve ter pelo menos 2x56 = 112 bits altos (dois resets)
        high = sum(n for v, n in t.writes if v == (1 << n) - 1)
        assert high >= 112

    def test_magic_between_resets(self, proto: SWDProtocol, t: MockTransport) -> None:
        proto.jtag_to_swd()
        idx_magic = next(i for i, (v, n) in enumerate(t.writes) if (v, n) == (0x9EE7, 16))
        # deve existir ao menos um write 0xFF antes e depois do magic
        before = any(v == 0xFF and n == 8 for v, n in t.writes[:idx_magic])
        after = any(v == 0xFF and n == 8 for v, n in t.writes[idx_magic + 1 :])
        assert before and after


# ===========================================================================
# read_dp
# ===========================================================================


class TestReadDP:
    def _ok_read(self, t: MockTransport, data: int) -> None:
        parity = _even_parity(data)
        t.queue(ACK_OK, data, parity)

    def test_returns_data(self, proto: SWDProtocol, t: MockTransport) -> None:
        self._ok_read(t, 0x2BA0_1477)
        result = proto.read_dp(DP_ADDR_DPIDR)
        assert result == 0x2BA0_1477

    def test_sends_correct_request_byte(self, proto: SWDProtocol, t: MockTransport) -> None:
        self._ok_read(t, 0x0)
        proto.read_dp(DP_ADDR_DPIDR)
        assert t.request_byte() == 0xA5  # pré-calculado em TestBuildRequest

    def test_one_turnaround_before_ack(self, proto: SWDProtocol, t: MockTransport) -> None:
        self._ok_read(t, 0x0)
        proto.read_dp(DP_ADDR_DPIDR)
        assert t.turnarounds >= 1

    def test_two_turnarounds_total(self, proto: SWDProtocol, t: MockTransport) -> None:
        # 1 antes do ACK + 1 após os dados (host retoma controle)
        self._ok_read(t, 0x0)
        proto.read_dp(DP_ADDR_DPIDR)
        assert t.turnarounds == 2

    def test_wait_ack_raises(self, proto: SWDProtocol, t: MockTransport) -> None:
        t.queue(ACK_WAIT)
        with pytest.raises(AckError) as exc:
            proto.read_dp(DP_ADDR_DPIDR)
        assert exc.value.ack == ACK_WAIT

    def test_fault_ack_raises(self, proto: SWDProtocol, t: MockTransport) -> None:
        t.queue(ACK_FAULT)
        with pytest.raises(AckError) as exc:
            proto.read_dp(DP_ADDR_DPIDR)
        assert exc.value.ack == ACK_FAULT

    def test_parity_error_raises(self, proto: SWDProtocol, t: MockTransport) -> None:
        data = 0xDEAD_BEEF
        wrong_parity = 1 - _even_parity(data)
        t.queue(ACK_OK, data, wrong_parity)
        with pytest.raises(ParityError) as exc:
            proto.read_dp(DP_ADDR_DPIDR)
        assert exc.value.data == data

    def test_zero_data_parity(self, proto: SWDProtocol, t: MockTransport) -> None:
        t.queue(ACK_OK, 0x0000_0000, 0)  # parity de 0 é 0
        assert proto.read_dp(DP_ADDR_DPIDR) == 0

    def test_all_ones_data_parity(self, proto: SWDProtocol, t: MockTransport) -> None:
        t.queue(ACK_OK, 0xFFFF_FFFF, 0)  # 32 uns → parity = 0
        assert proto.read_dp(DP_ADDR_DPIDR) == 0xFFFF_FFFF


# ===========================================================================
# write_dp
# ===========================================================================


class TestWriteDP:
    def test_sends_correct_request_byte(self, proto: SWDProtocol, t: MockTransport) -> None:
        t.queue(ACK_OK)
        proto.write_dp(DP_ADDR_SELECT, 0x00)
        assert t.request_byte() == 0xB1  # SELECT write

    def test_sends_data_after_ack(self, proto: SWDProtocol, t: MockTransport) -> None:
        value = 0x1234_5678
        t.queue(ACK_OK)
        proto.write_dp(DP_ADDR_SELECT, value)
        assert t.has_write(value, 32)

    def test_sends_correct_parity(self, proto: SWDProtocol, t: MockTransport) -> None:
        value = 0xDEAD_BEEF
        t.queue(ACK_OK)
        proto.write_dp(DP_ADDR_SELECT, value)
        assert t.has_write(_even_parity(value), 1)

    def test_truncates_to_32bit(self, proto: SWDProtocol, t: MockTransport) -> None:
        t.queue(ACK_OK)
        proto.write_dp(DP_ADDR_SELECT, 0x1_FFFF_FFFF)
        assert t.has_write(0xFFFF_FFFF, 32)

    def test_wait_ack_raises(self, proto: SWDProtocol, t: MockTransport) -> None:
        t.queue(ACK_WAIT)
        with pytest.raises(AckError):
            proto.write_dp(DP_ADDR_SELECT, 0)

    def test_fault_ack_raises(self, proto: SWDProtocol, t: MockTransport) -> None:
        t.queue(ACK_FAULT)
        with pytest.raises(AckError):
            proto.write_dp(DP_ADDR_SELECT, 0)

    def test_turnarounds(self, proto: SWDProtocol, t: MockTransport) -> None:
        # 1 antes do ACK + 1 após o ACK (host retoma controle)
        t.queue(ACK_OK)
        proto.write_dp(DP_ADDR_SELECT, 0)
        assert t.turnarounds == 2


# ===========================================================================
# read_ap / write_ap
# ===========================================================================


class TestReadAP:
    def test_sets_ap_bit_in_request(self, proto: SWDProtocol, t: MockTransport) -> None:
        t.queue(ACK_OK, 0x0, 0)
        proto.read_ap(AP_ADDR_CSW)
        req = t.request_byte()
        assert (req >> 1) & 1 == 1  # APnDP = AP

    def test_returns_data(self, proto: SWDProtocol, t: MockTransport) -> None:
        data = 0xCAFE_BABE
        t.queue(ACK_OK, data, _even_parity(data))
        assert proto.read_ap(AP_ADDR_CSW) == data


class TestWriteAP:
    def test_sets_ap_bit_in_request(self, proto: SWDProtocol, t: MockTransport) -> None:
        t.queue(ACK_OK)
        proto.write_ap(AP_ADDR_DRW, 0x0)
        req = t.request_byte()
        assert (req >> 1) & 1 == 1  # APnDP = AP

    def test_sends_data(self, proto: SWDProtocol, t: MockTransport) -> None:
        value = 0xABCD_EF01
        t.queue(ACK_OK)
        proto.write_ap(AP_ADDR_DRW, value)
        assert t.has_write(value, 32)


# ===========================================================================
# AckError e ParityError
# ===========================================================================


class TestErrorMessages:
    def test_ack_error_wait_message(self) -> None:
        err = AckError(ACK_WAIT)
        assert "WAIT" in str(err)

    def test_ack_error_fault_message(self) -> None:
        err = AckError(ACK_FAULT)
        assert "FAULT" in str(err)

    def test_parity_error_message(self) -> None:
        err = ParityError(0xDEAD_BEEF, 0, 1)
        assert "DEAD" in str(err).upper()
