"""Gera as capturas de tela da GUI usadas no guia (DOC/img/gui_*.png).

Usa DeviceService/TestRunnerService simulados: não precisa de probe nem placa.
Rodar a partir da raiz do repositório, antes de DOC/_gerar_word.py:
    python DOC/_gerar_capturas.py
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "DOC" / "img"
OUT.mkdir(parents=True, exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication(sys.argv)

from app.gui import main_window as mw_mod  # noqa: E402
from app.gui import project_dialog as pd_mod  # noqa: E402
from app.services.device import ProbeInfo  # noqa: E402
from core.target import STM32_DEV_IDS, McuInfo  # noqa: E402
from tests_builtin.base import TestResult, TestStatus  # noqa: E402

IOC_PATH = Path(tempfile.gettempdir()) / "PLACA_TESTE.ioc"
PLUGIN = ROOT / "TESTES_PLATAFORMA" / "IO" / "teste_gpio_output.py"


def pump():
    for _ in range(5):
        app.processEvents()


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeDevice(QObject):
    probe_connected    = Signal(str)
    probe_disconnected = Signal()
    probe_error        = Signal(str)
    mcu_identified     = Signal(object)

    def __init__(self):
        super().__init__()
        self._connected = False
        self.mcu = McuInfo(0x2BA01477, 0x410FC241, "STMicroelectronics", 0x10006421, 0xE0042000)

    @property
    def is_connected(self):
        return self._connected

    @property
    def pal(self):
        return None

    def list_probes(self):
        return [ProbeInfo("STMicroelectronics STLINK-V3", "SIMULADO0001")]

    def identify(self, probe=None):
        self.mcu_identified.emit(self.mcu)
        return self.mcu

    def connect(self, board=None, uid=None):
        self._connected = True
        self.probe_connected.emit(f"ST-Link  DPIDR=0x2BA01477  alvo={board.target}")

    def disconnect(self):
        self._connected = False
        self.probe_disconnected.emit()


F446 = STM32_DEV_IDS.get(0x421, "STM32F446")
RESULTS = {
    "DeviceId":       (TestStatus.PASS, 0.9, f"{F446}  DEV_ID=0x421  REV_ID=0x1000"),
    "Clocks":         (TestStatus.PASS, 1.2, "Clocks habilitados: HSI, PLL"),
    "SRAM":           (TestStatus.PASS, 2.4, "0x20000000: R/W OK (padrão 0xA5A5A5A5)"),
    "LED":            (TestStatus.PASS, 3.1, "LED GPIOA5: SET=1 RESET=0 via BSRR OK"),
    "Button":         (TestStatus.PASS, 0.8, "GPIOC13 legível: solto"),
    "USART Loopback": (TestStatus.FAIL, 52.6,
                       "timeout — verifique fio GPIOA9→GPIOA10: RXNE não ativou"),
    "SPI Loopback":   (TestStatus.PASS, 4.7, "eco OK 0xA5  (DIV_256)"),
    "GPIO Output":    (TestStatus.PASS, 2.2, "GPIOA5 saída push-pull: SET/RESET OK"),
}


class FakeRunner(QObject):
    test_started   = Signal(str)
    test_finished  = Signal(object)
    suite_started  = Signal(int)
    suite_finished = Signal(object)

    def __init__(self, device, parent=None):
        super().__init__(parent)
        self._running = False

    @property
    def is_running(self):
        return self._running

    def run(self, tests):
        tests = list(tests)
        self._running = True
        self.suite_started.emit(len(tests))
        out = []
        for t in tests:
            self.test_started.emit(t.name)
            st, ms, msg = RESULTS.get(t.name, (TestStatus.PASS, 1.0, "ok"))
            r = TestResult(name=t.name, status=st, message=msg, duration_ms=ms)
            self.test_finished.emit(r)
            out.append(r)
        self._running = False
        self.suite_finished.emit(out)

    def abort(self):
        self._running = False


# ── Anotação ─────────────────────────────────────────────────────────────────

RED = QColor(0xD0, 0x10, 0x10)


def rect_of(widget, top):
    return QRect(widget.mapTo(top, QPoint(0, 0)), widget.size())


def annotate(pix, marks, pad=3):
    """marks: lista de (QRect, numero). Desenha contorno e circulo numerado."""
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont("Segoe UI", 10)
    font.setBold(True)
    p.setFont(font)
    for r, n in marks:
        r = r.adjusted(-pad, -pad, pad, pad)
        p.setPen(QPen(RED, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 4, 4)
        d = 22
        c = QRect(r.left() - d // 2, r.top() - d // 2, d, d)
        c.moveLeft(max(c.left(), 1))
        c.moveTop(max(c.top(), 1))
        p.setBrush(RED)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c)
        p.setPen(QColor("white"))
        p.drawText(c, Qt.AlignmentFlag.AlignCenter, str(n))
    p.end()
    return pix


def save(pix, name):
    pix.save(str(OUT / name))
    print("salvo", name, pix.width(), "x", pix.height())


# ── Patches de diálogos (sem janelas modais) ─────────────────────────────────

def fake_open(*args, **kwargs):
    title = args[1] if len(args) > 1 else ""
    if "ioc" in title.lower() or "CubeMX" in title:
        return str(IOC_PATH), ""
    return str(PLUGIN), ""


mw_mod.QFileDialog.getOpenFileName = staticmethod(fake_open)
pd_mod.QFileDialog.getOpenFileName = staticmethod(fake_open)


class CapturingBox(QMessageBox):
    @staticmethod
    def question(parent, title, text, *a, **k):
        box = QMessageBox(QMessageBox.Icon.Question, title, text,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                          parent)
        box.show()
        pump()
        save(box.grab(), "gui_ioc_confirmacao.png")
        box.close()
        return QMessageBox.StandardButton.Yes


pd_mod.QMessageBox = CapturingBox


def main():
    from tests.unit.test_project_ioc import _IOC  # .ioc sintético dos testes
    IOC_PATH.write_text(_IOC, encoding="utf-8")

    dev = FakeDevice()
    win = mw_mod.MainWindow(device=dev, runner=FakeRunner(dev))
    win.resize(1180, 680)
    win.move(40, 40)
    win.show()
    pump()

    tabs = win._combo_projects.parentWidget()
    while tabs is not None and tabs.metaObject().className() != "QTabWidget":
        tabs = tabs.parentWidget()

    # 1) Identificar MCU — confere
    win._refresh_probes()
    win._identify_mcu()
    pump()
    left = tabs
    save(left.grab(), "gui_mcu_confere.png")

    # 2) Identificar MCU — não confere (chip diferente da placa do projeto)
    dev.mcu = McuInfo(0x6BA02477, 0x411FC271, "STMicroelectronics", 0x20036450, 0x5C001000)
    win._identify_mcu()
    pump()
    save(left.grab(), "gui_mcu_nao_confere.png")
    dev.mcu = McuInfo(0x2BA01477, 0x410FC241, "STMicroelectronics", 0x10006421, 0xE0042000)
    win._identify_mcu()

    # 3) Conectar, carregar plugin, executar suite
    win._toggle_connect()
    win._load_plugin()
    pump()
    win._run_suite()
    pump()
    win.statusBar().clearMessage()
    pump()

    pix = win.grab()
    marks = [
        (rect_of(win._combo_projects, win), 1),
        (rect_of(win._combo_probes, win).united(rect_of(win._btn_refresh, win)), 2),
        (rect_of(win._btn_identify, win).united(rect_of(win._btn_connect, win)), 3),
        (rect_of(tabs.tabBar(), win), 4),
        (rect_of(win._table, win), 5),
        (rect_of(win._btn_report, win).united(rect_of(win._btn_export, win)), 6),
        (rect_of(win._btn_run, win), 7),
        (rect_of(win._sb_board, win).united(rect_of(win._sb_suite, win)), 8),
    ]
    save(annotate(pix, marks), "gui_visao_geral.png")

    # 4) Aba Testes com plugin carregado
    tabs.setCurrentIndex(2)
    pump()
    pix = tabs.grab()
    marks = [
        (rect_of(win._suite_list, tabs), 1),
        (rect_of(win._btn_load_plugin, tabs), 2),
        (rect_of(win._plugin_list, tabs), 3),
    ]
    save(annotate(pix, marks), "gui_aba_testes.png")
    tabs.setCurrentIndex(0)

    # 5) Editor de projeto + importação .ioc
    dlg = pd_mod.ProjectEditorDialog(win)
    dlg.move(80, 60)
    dlg.show()
    pump()
    dlg._code.setText("PLACA-001")
    btn_ioc = next(b for b in dlg.findChildren(pd_mod.QPushButton)
                   if "ioc" in b.text().lower())
    dlg._import_ioc()
    dlg._pin_table.scrollToTop()
    pump()
    pix = dlg.grab()
    marks = [(rect_of(btn_ioc, dlg), 1), (rect_of(dlg._pin_table, dlg), 2)]
    save(annotate(pix, marks), "gui_ioc_pinout.png")
    dlg.close()

    # 6) Instrumentos: detecção VISA e gerenciador (aparelhos simulados)
    from datetime import date, timedelta

    from app.gui import instrument_dialog as id_mod
    from core.instruments.registry import InstrumentRegistry
    from instruments.discovery import DiscoveredInstrument

    found = [
        DiscoveredInstrument("TCPIP::192.168.1.50::INSTR",
                             "RIGOL TECHNOLOGIES,MSO8104,MS8A000000001,00.01.03.00.02"),
        DiscoveredInstrument("TCPIP::192.168.1.51::INSTR",
                             "Rohde&Schwarz,FPC1500,1328.6660K15/100001,V1.70"),
        DiscoveredInstrument("TCPIP::192.168.1.60::INSTR", error="VI_ERROR_TMO"),
    ]
    det = id_mod._DetectDialog(found, set(), set(), win)
    det.show()
    pump()
    save(det.grab(), "gui_instr_detectar.png")
    reg = InstrumentRegistry.instance()
    added = det.selected_configs()
    det.close()
    for cfg in added:
        reg.add_config(cfg)
    today = date.today()
    reg.config("osc").params.update(asset_id="PAT-0001",
                                    calibration_due=str(today + timedelta(days=300)))
    reg.config("sa").params.update(asset_id="PAT-0002",
                                   calibration_due=str(today + timedelta(days=12)))
    mgr = id_mod.InstrumentManagerDialog(win)
    mgr.resize(820, 300)
    mgr.show()
    pump()
    pix = mgr.grab()
    marks = [(rect_of(mgr._btn_detect, mgr), 1), (rect_of(mgr._table, mgr), 2)]
    save(annotate(pix, marks), "gui_instr_gerenciar.png")
    mgr.close()
    for cfg in added:                    # não grava os simulados no instruments.json
        reg.remove_config(cfg.name)

    # 7) Plano de testes (projeto da NUCLEO-H753ZI), bloco de UART selecionado
    from app.gui.test_plan_editor import _AddTestDialog
    from core.project.loader import find_projects
    from tests_builtin.plan import list_library

    proj = next(p for p in find_projects() if p.project_code == "NUCLEO-H753-001")
    ped = pd_mod.ProjectEditorDialog(win, proj)
    ped.resize(1000, 600)
    ped.open_plan()
    ped.show()
    pump()
    plan = ped._plan_editor
    row = next(i for i, e in enumerate(plan.entries()) if "USART3 VCP" in e.label)
    plan._list.setCurrentRow(row)
    pump()
    pix = ped.grab()
    marks = [(rect_of(plan._list, ped), 1), (rect_of(plan._scroll, ped), 2)]
    add_btn = next(b for b in plan.findChildren(pd_mod.QPushButton) if "Adicionar" in b.text())
    marks.append((rect_of(add_btn, ped), 3))
    save(annotate(pix, marks), "gui_plano_testes.png")
    ped.close()

    # 8) Biblioteca de blocos agrupada por categoria
    add = _AddTestDialog(list_library, win)
    add.resize(760, 520)
    add.show()
    pump()
    save(add.grab(), "gui_adicionar_teste.png")
    add.close()

    # 9) Janela de logs com registros de exemplo (buffer próprio, não o da sessão)
    import logging

    from app.gui.log_window import LogWindow
    from app.log_buffer import LogBuffer

    buf = LogBuffer()
    demo = logging.getLogger("demo.capturas")
    demo.propagate = False
    demo.setLevel(logging.DEBUG)
    demo.addHandler(buf)

    def rec(level, name, msg, exc=None):
        r = logging.LogRecord(name, level, __file__, 0, msg, None, exc)
        buf.handle(r)

    rec(logging.INFO, "app.services.device", "Probe conectado: ST-Link DPIDR=0x6BA02477 "
        "alvo=stm32h753zitx")
    rec(logging.INFO, "app.gui.main_window", "Projeto selecionado: Nucleo H753 — Básico")
    rec(logging.WARNING, "app.gui.main_window", "Teste FAIL: Button — GPIOC13 não está em modo "
        "INPUT (MODER13=0b11, esperado 0b00)")
    try:
        raise TimeoutError("USART3: nenhum byte recebido em 200 ms")
    except TimeoutError:
        import sys as _sys
        rec(logging.ERROR, "app.gui.main_window", "Teste ERROR: UART — Loopback — fio TX→RX",
            _sys.exc_info())
    rec(logging.INFO, "app.gui.main_window", "Suite concluída com 2 falha(s).")
    logw = LogWindow(win, buffer=buf)
    logw.resize(980, 460)
    logw.show()
    pump()
    logw._table.selectRow(3)
    pump()
    pix = logw.grab()
    marks = [(rect_of(logw._level, logw).united(rect_of(logw._search, logw)), 1),
             (rect_of(logw._table, logw), 2), (rect_of(logw._detail, logw), 3)]
    btns = [b for b in logw.findChildren(pd_mod.QPushButton) if b.text() in ("Salvar...", "Limpar")]
    marks.append((rect_of(btns[0], logw).united(rect_of(btns[-1], logw)), 4))
    save(annotate(pix, marks), "gui_logs.png")
    logw.close()

    win.close()


if __name__ == "__main__":
    main()
