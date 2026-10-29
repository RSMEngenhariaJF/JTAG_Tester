# Guia Completo — Como Criar e Integrar Testes na Plataforma de Bring-up

> **Versão:** Sprint 16  
> **Alvo de referência:** STM32F446RE (NUCLEO-F446RE)  
> **Autor:** Rafael Macedo

---

## 1. Visão Geral da Plataforma

A plataforma funciona em camadas. Você só precisa trabalhar na camada mais alta.

```
┌─────────────────────────────────────────────────────────────┐
│                     GUI / CLI                               │
│  Seleção de placa (BoardConfig) + probe + execução de suite │
├─────────────────────────────────────────────────────────────┤
│               TestRunnerService                             │
│         Executa testes em thread separada                   │
├──────────────────────┬──────────────────────────────────────┤
│   Suite Embutida     │   Plugins (seus testes)              │
│ (tests_builtin/)     │   (TESTES_PLATAFORMA/ ou qualquer    │
│  DeviceId, Clock,    │    pasta — carregados via GUI)       │
│  SRAM, Led, Button,  │                                      │
│  USART/SPI Loopback  │                                      │
├──────────────────────┴──────────────────────────────────────┤
│            BoardConfig (src/boards/<nome>.py)               │
│   project_code, pinos, clocks, target, svd_path...          │
├─────────────────────────────────────────────────────────────┤
│              PAL — Peripheral Access Layer                  │
│  pal.read_field() / pal.modify_field() / pal.read_reg()     │
├─────────────────────────────────────────────────────────────┤
│            pyOCD + ST-Link / FT2232H                        │
│              (acesso físico via SWD)                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. BoardConfig — Portabilidade Entre Placas

### 2.1 O que é

O `BoardConfig` é um arquivo Python em `src/boards/` que descreve **toda a informação
específica de uma placa**: pinos de LED e botão, periférico de USART e SPI para loopback,
endereço da SRAM, SVD a carregar e o `target` do pyOCD.

Quando você seleciona uma placa na GUI, a plataforma chama `set_active_board(BOARD)`.
A partir daí, qualquer teste que chamar `get_active_board()` recebe automaticamente
os parâmetros corretos para aquela placa — **sem alterar nenhuma linha de código de teste**.

### 2.2 O campo project_code

Cada `BoardConfig` tem um campo `project_code` (ex.: `"2180.0720.00"`). Ele aparece no:
- Título da janela da GUI: `Bring-up 2180.0720.00 — NUCLEO-F446RE`
- Arquivo exportado (JSON/CSV): campo `project_code`

Isso permite rastrear qual configuração estava ativa quando os resultados foram gerados.

### 2.3 Como criar o arquivo para uma nova placa

Crie `src/boards/minha_placa.py`:

```python
from core.board.config import BoardConfig, PinConfig, UsartConfig, SpiConfig

BOARD = BoardConfig(
    # Identificação
    project_code = "2180.0720.00",      # código do projeto
    name         = "Minha Placa XYZ",

    # Conexão pyOCD
    target   = "stm32l476rgtx",
    svd_path = "devices/stm32l476/STM32L476.svd",

    # Chip identity
    dbgmcu_idcode_addr = 0xE0042000,
    expected_dev_id    = 0x415,         # STM32L476

    # SRAM
    sram_base = 0x20000000,

    # LED (pino de saída de status)
    led_port        = "GPIOB",
    led_pin         = 7,
    led_clock_reg   = "AHB2ENR",        # L4 usa AHB2, não AHB1
    led_clock_field = "GPIOBEN",

    # Botão de usuário
    btn_port        = "GPIOC",
    btn_pin         = 13,
    btn_clock_reg   = "AHB2ENR",
    btn_clock_field = "GPIOCEN",
    btn_active_low  = True,

    # Clocks que devem estar habilitados pelo firmware
    required_clocks = (
        ("AHB2ENR", "GPIOBEN", "GPIOB"),
        ("AHB2ENR", "GPIOCEN", "GPIOC"),
    ),

    # USART loopback
    usart = UsartConfig(
        n            = 1,
        tx           = PinConfig(port="GPIOA", pin=9,  af=7),
        rx           = PinConfig(port="GPIOA", pin=10, af=7),
        clock_reg    = "APB2ENR",
        clock_field  = "USART1EN",
        loopback_baud = 9600,
    ),

    # SPI loopback
    spi = SpiConfig(
        n           = 1,
        sck         = PinConfig(port="GPIOA", pin=5, af=5),
        miso        = PinConfig(port="GPIOA", pin=6, af=5),
        mosi        = PinConfig(port="GPIOA", pin=7, af=5),
        clock_reg   = "APB2ENR",
        clock_field = "SPI1EN",
    ),
)
```

A GUI detecta o arquivo automaticamente — basta salvar e abrir a aplicação.

### 2.4 Derivar variante do mesmo projeto

Para o mesmo hardware com código de projeto diferente, use `dataclasses.replace`:

```python
from boards.nucleo_f446re import BOARD
import dataclasses

BOARD_PROJETO_X = dataclasses.replace(BOARD, project_code="2180.0720.01")
```

---

## 3. Anatomia de um Teste

Todo teste é uma classe Python que herda de `BuiltinTest`. Existem dois padrões:

### Padrão A — Teste portável (usa BoardConfig)

Use quando o teste exercita hardware da placa (pinos, loopbacks, verificação de periférico
configurado pela placa). Ao trocar de placa na GUI, **o teste se adapta automaticamente**.

```python
from tests_builtin.base import BuiltinTest, TestResult

class MeuTestePortavel(BuiltinTest):
    name        = "Meu Teste"
    description = "Verifica o LED da placa ativa."

    def _run(self, pal) -> TestResult:
        from core.board.config import get_active_board
        cfg = get_active_board()                       # pinos da placa selecionada

        port        = cfg.led_port                     # ex.: "GPIOA"
        pin         = cfg.led_pin                      # ex.: 5
        clock_reg   = cfg.led_clock_reg                # ex.: "AHB1ENR"
        clock_field = cfg.led_clock_field              # ex.: "GPIOAEN"

        pal.modify_field("RCC", clock_reg, clock_field, 1)

        orig = pal.read_field(port, "MODER", f"MODER{pin}")
        try:
            pal.modify_field(port, "MODER", f"MODER{pin}", 0b01)
            pal.write_reg(port, "BSRR", 1 << pin)
            nivel = pal.read_field(port, "ODR", f"ODR{pin}")

            if nivel == 1:
                return self._pass(f"{port}.{pin} SET OK", measured=nivel, expected=1)
            return self._fail(f"{port}.{pin} ficou LOW após SET", measured=nivel, expected=1)
        finally:
            pal.modify_field(port, "MODER", f"MODER{pin}", orig)
```

### Padrão B — Teste com constantes fixas (verifica firmware/aplicação)

Use quando o teste verifica parâmetros configurados pelo **firmware** (baud rate, frequência
de PWM, configuração de canal DMA). Esses valores são da aplicação, não da placa física.

```python
from tests_builtin.base import BuiltinTest, TestResult
from instruments.usart import UsartInstrument, _baud_divider

EXPECTED_BAUD = 115200
F_CLK         = 16_000_000

class Usart2BaudCheck(BuiltinTest):
    name        = "USART2 Baud Check"
    description = f"Verifica se firmware configurou USART2 para {EXPECTED_BAUD} baud."

    def _run(self, pal) -> TestResult:
        exp_m, exp_f = _baud_divider(EXPECTED_BAUD, F_CLK)
        got_m = pal.read_field("USART2", "BRR", "DIV_Mantissa")
        got_f = pal.read_field("USART2", "BRR", "DIV_Fraction")

        if got_m == exp_m and got_f == exp_f:
            return self._pass(f"BRR correto para {EXPECTED_BAUD} baud")
        return self._fail(
            f"BRR errado: mant={got_m}/{exp_m}  frac={got_f}/{exp_f}",
            measured=(got_m, got_f), expected=(exp_m, exp_f),
        )
```

### Campos obrigatórios

| Atributo | Descrição |
|---|---|
| `name` | Texto exibido na coluna "Teste" da tabela |
| `description` | Tooltip na lista de testes |
| `_run(self, pal)` | Lógica do teste; deve retornar `TestResult` |

### Métodos herdados de `BuiltinTest`

| Método | Quando usar |
|---|---|
| `self._pass(msg, measured=, expected=)` | Teste passou |
| `self._fail(msg, measured=, expected=)` | Teste falhou |
| `self._skip(reason)` | Pular (ex.: hardware opcional não presente) |

---

## 4. O PAL — Peripheral Access Layer

O `pal` é o acesso ao hardware. Usa o SVD para resolver nomes → endereços automaticamente.

### 4.1 Ler um campo de registrador

```python
valor = pal.read_field("GPIOA", "MODER", "MODER5")
# Retorna apenas os bits do campo (sem máscara manual)
```

### 4.2 Modificar um campo (Read-Modify-Write)

```python
pal.modify_field("GPIOA", "MODER", "MODER5", 0b01)  # só muda MODER5; resto intacto
```

### 4.3 Ler/escrever registrador inteiro (32 bits)

```python
sr = pal.read_reg("USART1", "SR")
txe = (sr >> 7) & 1

pal.write_reg("GPIOA", "BSRR", 1 << 5)   # SET PA5
```

### 4.4 Acesso direto por endereço

```python
idcode = pal.mem.read_mem32(0xE0042000)
pal.mem.write_mem32(0x20000000, 0xDEADBEEF)
```

---

## 5. Como descobrir nomes de periféricos e campos

Os nomes vêm do SVD indicado no `BoardConfig.svd_path`.

```powershell
$env:PYTHONPATH = "src"

# Listar todos os registradores de USART1
.venv\Scripts\python.exe -c "
from core.svd.parser import parse; from pathlib import Path
svd = parse(Path('devices/stm32f446/STM32F446.svd'))
for r in svd.peripheral('USART1').registers:
    print(f'  {r.name:10} offset=0x{r.offset:02X}')
"

# Listar campos de GPIOA.MODER
.venv\Scripts\python.exe -c "
from core.svd.parser import parse; from pathlib import Path
svd = parse(Path('devices/stm32f446/STM32F446.svd'))
for f in svd.peripheral('GPIOA').register('MODER').fields:
    print(f'  {f.name:10} bit[{f.bit_offset}:{f.bit_offset+f.bit_width-1}]')
"
```

### Campos de clock no RCC

| Periférico | Registrador RCC | Campo |
|---|---|---|
| GPIOA..H | AHB1ENR | GPIOAEN..GPIOHEN |
| USART1, USART6 | APB2ENR | USART1EN, USART6EN |
| USART2..5 | APB1ENR | USART2EN..UART5EN |
| SPI1, SPI4 | APB2ENR | SPI1EN, SPI4EN |
| SPI2, SPI3 | APB1ENR | SPI2EN, SPI3EN |
| I2C1..3 | APB1ENR | I2C1EN..I2C3EN |
| TIM1, TIM8 | APB2ENR | TIM1EN, TIM8EN |
| TIM2..7 | APB1ENR | TIM2EN..TIM7EN |
| ADC1..3 | APB2ENR | ADC1EN..ADC3EN |
| DMA1, DMA2 | AHB1ENR | DMA1EN, DMA2EN |

---

## 6. Padrões de implementação

### 6.1 Habilitar clock de periférico

```python
# Sempre antes de acessar qualquer periférico:
pal.modify_field("RCC", "AHB1ENR", "GPIOAEN", 1)    # GPIOA

# Ou, para portabilidade, use o campo do BoardConfig:
cfg = get_active_board()
pal.modify_field("RCC", cfg.led_clock_reg, cfg.led_clock_field, 1)
```

### 6.2 Salvar e restaurar estado (obrigatório)

```python
def _run(self, pal) -> TestResult:
    orig_moder = pal.read_field("GPIOA", "MODER", "MODER5")
    try:
        pal.modify_field("GPIOA", "MODER", "MODER5", 0b01)
        # ... testa ...
        return self._pass("OK")
    finally:
        pal.modify_field("GPIOA", "MODER", "MODER5", orig_moder)  # sempre restaura
```

### 6.3 Configurar pino como Alternate Function

```python
# Usando PinConfig (portável):
from core.board.config import get_active_board
cfg = get_active_board()
tx  = cfg.usart.tx                                           # PinConfig

pal.modify_field(tx.port, "MODER", tx.moder_field, 0b10)   # AF mode
pal.modify_field(tx.port, tx.afr_reg, tx.afr_field, tx.af) # AF value

# Ou manualmente (fixo):
pal.modify_field("GPIOA", "MODER", "MODER9",  0b10)   # PA9 → AF mode
pal.modify_field("GPIOA", "AFRH",  "AFRH9",   7)      # AF7 = USART1
```

### 6.4 Aguardar flag com timeout

```python
import time

def _wait(pal, periph, reg, field, expected=1, timeout_ms=100) -> bool:
    deadline = time.perf_counter() + timeout_ms / 1000
    while pal.read_field(periph, reg, field) != expected:
        if time.perf_counter() > deadline:
            return False
    return True

if not _wait(pal, "USART1", "SR", "RXNE"):
    return self._fail("Timeout aguardando RXNE")
```

### 6.5 Usar os instrumentos prontos (USART e SPI)

```python
from instruments.usart import UsartInstrument
from instruments.spi   import SpiInstrument, SpiBaudDiv
from instruments.rcc_helper import detect_pclk2
from core.board.config import get_active_board

def _run(self, pal) -> TestResult:
    cfg   = get_active_board()
    f_clk = detect_pclk2(pal)           # detecta PCLK2 real via RCC

    usart = UsartInstrument(cfg.usart.n, pal)
    usart.configure(baud=cfg.usart.loopback_baud, f_clk=f_clk)
    usart.enable()
    usart.send_byte(0xAA)
    eco = usart.receive_byte(timeout_ms=200)
    usart.disable()
```

---

## 7. Integrar na Plataforma (3 formas)

### Forma 1 — Plugin via GUI (recomendada para testes de produto)

1. Selecione a placa no ComboBox "Projeto" (painel esquerdo da GUI)
2. Conecte o probe → "Conectar"
3. Clique **"Carregar Plugin..."** → selecione seu `.py`
4. Clique **"Executar Suite"** — seu teste roda junto com os embutidos
5. Clique **"Exportar..."** para salvar JSON ou CSV com o `project_code` incluso

### Forma 2 — Suite Embutida (para testes que sempre rodam)

Edite `src/tests_builtin/__init__.py`:

```python
from tests_builtin.meu_modulo import MeuTeste

STANDARD_SUITE: tuple[BuiltinTest, ...] = (
    DeviceIdTest(),
    ClockTest(),
    SRAMTest(),
    LedTest(),
    ButtonTest(),
    UsartLoopbackTest(),
    SpiLoopbackTest(),
    MeuTeste(),          # seu teste aqui
)
```

Ou use `build_suite(cfg)` para instanciar com placa explícita (útil em testes unitários):

```python
from tests_builtin import build_suite
from boards.nucleo_f446re import BOARD

suite = build_suite(BOARD)   # todos os testes com cfg injetado
```

### Forma 3 — CLI (automação / CI)

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe src/app/cli/main.py run --json > resultado.json

# Verificar resultado:
python -c "
import json, sys
data = json.load(open('resultado.json'))
fails = [r for r in data['results'] if r['status'] != 'PASS']
print(data['project_code'], data['board'])
sys.exit(1 if fails else 0)
"
```

---

## 8. Desenvolvendo Sem Hardware (TDD)

Use `FakeMemory` para testar a lógica antes de conectar a placa.

```python
# tests/unit/test_meu_teste.py
from pathlib import Path
import pytest
from core.board.config import set_active_board
from core.pal.access import PeripheralAccessLayer
from core.svd.parser import parse

class FakeMemory:
    def __init__(self):
        self._mem = {}
    def read_mem32(self, addr):
        return self._mem.get(addr & ~3, 0)
    def write_mem32(self, addr, value):
        self._mem[addr & ~3] = value & 0xFFFFFFFF

@pytest.fixture(autouse=True)
def board():
    from boards.nucleo_f446re import BOARD
    set_active_board(BOARD)            # necessário para get_active_board()

@pytest.fixture
def pal(board):
    svd = parse(Path("devices/stm32f446/STM32F446.svd"))
    return PeripheralAccessLayer(FakeMemory(), svd)

def test_meu_teste_passa(pal):
    pal.modify_field("RCC", "AHB1ENR", "GPIOAEN", 1)

    from meu_teste import MeuTestePortavel
    from tests_builtin.base import TestStatus
    result = MeuTestePortavel().run(pal)
    assert result.status == TestStatus.PASS
```

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m pytest tests/unit/ -v
```

---

## 9. pytest — Guia Completo

### 9.1 Metodologia

pytest é o framework de testes unitários do projeto. Ele serve para testar
**o código da plataforma em si** — não o hardware. Os testes em `tests/`
verificam se o PAL, os `BuiltinTest`, o runner e a GUI se comportam
corretamente usando memória falsa (`FakeMemory`) ou um probe simulado
(`SimulatedProbe`), sem precisar de placa física.

A metodologia seguida é **TDD (Test-Driven Development)** aplicado em dois
momentos distintos:

```
Você escreve MeuTeste          Você escreve test_meu_teste.py
(BuiltinTest)                  (pytest)
      │                               │
      ▼                               ▼
Roda na GUI/CLI           Roda com: pytest tests/unit/ -v
com hardware real         com FakeMemory — sem hardware
```

**Regra prática:** antes de conectar a placa, o teste pytest deve:
1. Passar com `FakeMemory` pré-configurada com valores corretos
2. Falhar com `FakeMemory` configurada com valores errados

Se ambos os casos funcionam, a lógica está certa. O hardware só entra depois.

---

### 9.2 Como o pytest descobre testes

O pytest segue convenções automáticas de descoberta — nenhuma configuração
extra é necessária:

| Convenção | Exemplo |
|---|---|
| Arquivos começam com `test_` | `test_builtins.py` |
| Classes começam com `Test` | `class TestLed:` |
| Funções começam com `test_` | `def test_pass_com_clock_ligado(pal):` |
| Subclasses de `unittest.TestCase` | também são reconhecidas |

```python
# pytest encontra e executa automaticamente:
class TestDeviceId:                         # classe começa com Test
    def test_pass_with_correct_idcode(self, pal):   # método começa com test_
        ...
    def test_fail_with_wrong_devid(self, pal):
        ...

def test_standalone():                      # função standalone também funciona
    assert 1 + 1 == 2
```

---

### 9.3 Fixtures — Injeção de Dependência

Fixtures são funções que preparam recursos para os testes (memória, PAL, SVD,
conexão com hardware). O pytest injeta automaticamente pelo nome do parâmetro.

#### Fixture simples

```python
import pytest

@pytest.fixture
def fake_mem():
    return FakeMemory()         # criado antes de cada teste

@pytest.fixture
def pal(fake_mem, svd):         # injeta fake_mem e svd automaticamente
    return PeripheralAccessLayer(fake_mem, svd)

def test_clock(pal):            # pytest injeta pal → que injeta fake_mem e svd
    pal.modify_field("RCC", "AHB1ENR", "GPIOAEN", 1)
    assert pal.read_field("RCC", "AHB1ENR", "GPIOAEN") == 1
```

#### Escopos de fixture — controle de ciclo de vida

| Escopo | Criado/destruído | Quando usar |
|---|---|---|
| `function` (padrão) | a cada teste | recursos baratos, estado que não deve vazar |
| `class` | uma vez por classe `Test` | estado compartilhado entre métodos da classe |
| `module` | uma vez por arquivo `.py` | SVD parsing (lento, imutável) |
| `session` | uma vez por execução completa | conexão USB com hardware real |

```python
@pytest.fixture(scope="module")    # SVD parseado 1× por arquivo de teste
def svd():
    return parse(Path("devices/stm32f446/STM32F446.svd"))

@pytest.fixture(scope="session")   # ST-Link aberto 1× por sessão inteira
def stlink_adiv5(request):
    adiv5 = StLinkADIv5(target="stm32f446retx", mode="halt")
    adiv5._open()
    yield adiv5          # yield: teardown acontece APÓS todos os testes
    adiv5._close()       # roda mesmo se os testes falharem
```

#### `yield` — setup e teardown em uma fixture

```python
@pytest.fixture
def pal_com_clock(pal):
    pal.modify_field("RCC", "AHB1ENR", "GPIOAEN", 1)   # setup
    yield pal                                            # teste roda aqui
    pal.modify_field("RCC", "AHB1ENR", "GPIOAEN", 0)   # teardown (sempre)
```

#### `autouse=True` — fixture aplicada em todos os testes sem declarar

```python
@pytest.fixture(autouse=True)
def _active_board():
    from boards.nucleo_f446re import BOARD
    set_active_board(BOARD)     # roda antes de cada teste do módulo
                                # sem precisar declarar o parâmetro
```

#### `conftest.py` — fixtures compartilhadas entre arquivos

O `conftest.py` é carregado automaticamente pelo pytest. Fixtures definidas
nele ficam disponíveis para todos os arquivos de teste na mesma pasta e
subpastas, sem necessidade de import:

```
tests/
├── conftest.py              ← fixtures disponíveis em tests/ inteiro
│   └── probe, probe_raw, probe_jtag
├── unit/
│   └── test_builtins.py    ← usa probe, svd, pal sem importar conftest
└── hardware/
    ├── conftest.py          ← fixtures extras só para tests/hardware/
    │   └── stlink_adiv5, pal_stlink, hw_url
    └── test_pal_stlink.py  ← usa pal_stlink definido no conftest local
```

---

### 9.4 Marks — Metadados e Controle de Execução

Marks são anotações aplicadas a testes com `@pytest.mark.<nome>`.

#### `@pytest.mark.skip` e `@pytest.mark.skipif`

```python
@pytest.mark.skip(reason="funcionalidade ainda não implementada")
def test_exportar_pdf():
    ...

@pytest.mark.skipif(sys.platform == "win32", reason="só funciona no Linux")
def test_ftdi_url():
    ...
```

#### `@pytest.mark.parametrize` — múltiplos cenários em um teste

Evita duplicar código para testar a mesma lógica com entradas diferentes.
O pytest gera um teste separado (com nome próprio) para cada combinação:

```python
@pytest.mark.parametrize("dev_id, status_esperado", [
    (0x10000421, "PASS"),    # F446 correto
    (0x10000123, "FAIL"),    # chip errado
    (0x00000000, "FAIL"),    # memória zerada
])
def test_device_id(pal, fake_mem, dev_id, status_esperado):
    fake_mem._mem[0xE0042000] = dev_id
    result = DeviceIdTest().run(pal)
    assert result.status.name == status_esperado
```

```powershell
# Saída:
# test_device_id[0x10000421-PASS]  PASSED
# test_device_id[0x10000123-FAIL]  PASSED
# test_device_id[0x00000000-FAIL]  PASSED
```

Parametrize com múltiplas variáveis:

```python
@pytest.mark.parametrize("reg, campo, valor", [
    ("AHB1ENR", "GPIOAEN", 1),
    ("AHB1ENR", "GPIOCEN", 1),
    ("APB2ENR", "USART1EN", 1),
])
def test_clocks_necessarios(pal, reg, campo, valor):
    pal.modify_field("RCC", reg, campo, valor)
    assert pal.read_field("RCC", reg, campo) == valor
```

#### `@pytest.mark.timeout` — limite de tempo por teste

Requer o plugin `pytest-timeout` (já instalado no projeto):

```python
@pytest.mark.timeout(5)    # falha se demorar mais de 5 segundos
def test_loopback_nao_trava(pal_stlink):
    result = UsartLoopbackTest().run(pal_stlink)
    assert result.status != TestStatus.ERROR
```

Também pode ser configurado globalmente em `pytest.ini`:

```ini
[pytest]
timeout = 30    # todos os testes têm limite de 30 s por padrão
```

#### Marks customizados — separar testes por categoria

```python
# tests/hardware/conftest.py — registra o mark:
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "hardware: requer hardware real conectado"
    )

# Uso:
@pytest.mark.hardware
def test_led_real(pal_stlink):
    result = LedTest().run(pal_stlink)
    assert result.status == TestStatus.PASS
```

```powershell
pytest tests/ -m "not hardware"    # só testes sem hardware
pytest tests/ -m hardware          # só testes com hardware
```

---

### 9.5 Assertions — Como verificar resultados

#### `assert` puro — o mais comum

```python
def test_resultado(pal, fake_mem):
    fake_mem._mem[0xE0042000] = 0x10000421
    result = DeviceIdTest().run(pal)

    assert result.status  == TestStatus.PASS
    assert result.measured == 0x421
    assert result.expected == 0x421
    assert result.duration_ms >= 0
    assert "1000" in result.message     # REV_ID no texto
```

#### `pytest.raises` — verificar que exceção é lançada

```python
def test_sem_placa_configurada():
    from core.board.config import set_active_board, get_active_board
    set_active_board(None)
    with pytest.raises(RuntimeError, match="Nenhuma placa configurada"):
        get_active_board()
```

#### `pytest.approx` — comparar floats com tolerância

```python
def test_frequencia_pwm(pal):
    freq_medida = calcular_freq(pal, "TIM2")
    assert freq_medida == pytest.approx(1000.0, rel=0.01)   # ±1%
```

---

### 9.6 Testando código com threads — Filas

O `TestRunnerService` executa testes em uma thread separada e emite sinais Qt
com os resultados. Para testar isso sem a GUI, use `queue.Queue` como ponte:

```python
import queue

def test_runner_emite_resultado(svd):
    from app.services.runner import TestRunnerService
    from boards.nucleo_f446re import BOARD

    mem   = FakeMemory({0xE0042000: 0x10000421})
    pal   = PeripheralAccessLayer(mem, svd)
    fila  = queue.Queue()

    svc = TestRunnerService()
    svc.result_ready.connect(fila.put)      # sinal Qt → fila Python
    svc.start(pal, BOARD)

    primeiro = fila.get(timeout=5)          # aguarda até 5 s
    assert primeiro.name == "DeviceId"
    assert primeiro.status == TestStatus.PASS
```

`queue.Queue` é **thread-safe**: a thread do runner coloca resultados na fila
(`put`), e a thread do teste retira (`get`) com timeout — sem race condition,
sem `sleep`, sem polling.

---

### 9.7 Opções de linha de comando

```powershell
$env:PYTHONPATH = "src"

# Rodar todos os testes unitários com saída detalhada
.venv\Scripts\python.exe -m pytest tests/unit/ -v

# Rodar apenas um arquivo
.venv\Scripts\python.exe -m pytest tests/unit/test_builtins.py -v

# Rodar apenas testes cujo nome contém "led"
.venv\Scripts\python.exe -m pytest tests/unit/ -k "led" -v

# Parar no primeiro erro (fail-fast)
.venv\Scripts\python.exe -m pytest tests/unit/ -x

# Mostrar os 5 testes mais lentos
.venv\Scripts\python.exe -m pytest tests/unit/ --durations=5

# Rodar com hardware ST-Link (opção customizada do projeto)
.venv\Scripts\python.exe -m pytest tests/hardware/ --stlink -v

# Rodar com FT2232H
.venv\Scripts\python.exe -m pytest tests/hardware/ --hw-url ftdi://ftdi:2232h/1 -v

# Gerar relatório HTML (requer pytest-html)
.venv\Scripts\python.exe -m pytest tests/unit/ --html=relatorio.html
```

---

### 9.8 As duas camadas no projeto

```
tests/
├── unit/           ← sem hardware; FakeMemory; rápidos (< 1 s cada)
│   ├── test_builtins.py       testa DeviceIdTest, LedTest, etc. com FakeMemory
│   ├── test_pal.py            testa read_field / modify_field
│   ├── test_runner_service.py testa a execução da suite
│   └── test_main_window.py   testa a GUI com FakeDevice
│
└── hardware/       ← requer placa; scope=session; mais lentos
    ├── test_builtins_stlink.py   mesmos testes, mas com PAL real
    ├── test_loopback.py          USART e SPI loopback no hardware
    └── test_pal_stlink.py        read/write em registradores reais
```

A separação é feita pelo mark `@pytest.mark.hardware` e pelas opções
`--stlink` / `--hw-url`. Sem essas flags, testes de hardware são pulados
automaticamente pelo `conftest.py` via `pytest_collection_modifyitems`.

---

## 10. Estrutura de Arquivos de Referência

```
JTAG_Tester/
├── src/
│   ├── boards/                     ← UM ARQUIVO POR PLACA SUPORTADA
│   │   ├── __init__.py
│   │   └── nucleo_f446re.py        ← BOARD = BoardConfig(project_code=..., ...)
│   │
│   ├── core/board/
│   │   ├── config.py               ← BoardConfig, PinConfig, get/set_active_board()
│   │   └── loader.py               ← find_boards() — varredura automática
│   │
│   ├── tests_builtin/              ← testes que sempre rodam (usam get_active_board)
│   │   ├── base.py                 ← BuiltinTest, TestResult, TestStatus
│   │   ├── device_id.py
│   │   ├── clocks.py
│   │   ├── led.py
│   │   ├── button.py
│   │   ├── sram.py
│   │   ├── usart_loopback.py
│   │   ├── spi_loopback.py
│   │   └── loader.py               ← PluginLoader.load_from_file()
│   │
│   └── instruments/
│       ├── usart.py                ← UsartInstrument
│       ├── spi.py                  ← SpiInstrument
│       └── rcc_helper.py           ← detect_pclk2()
│
├── TESTES_PLATAFORMA/              ← seus testes de produto (plugins)
│   ├── IO/
│   ├── UART/
│   ├── SPI/
│   ├── I2C/
│   ├── TIMERS/
│   ├── PWM/
│   ├── ADC/
│   ├── DMA/
│   └── MEMORIA/
│
└── DOC/
    ├── GUIA_CRIACAO_DE_TESTES.md   ← este arquivo
    ├── GUIA_CRIACAO_DE_TESTES.docx ← versão Word
    └── TEMPLATE_TESTE.py           ← template comentado para copiar
```

---

## 11. Checklist para Novo Teste

**Estrutura obrigatória:**
- [ ] Classe herda de `BuiltinTest`
- [ ] `name` e `description` definidos como atributos de classe
- [ ] Método `_run(self, pal)` implementado (não `run()`)
- [ ] Todo caminho retorna `self._pass()`, `self._fail()` ou `self._skip()`

**Boas práticas:**
- [ ] Estado original dos registradores salvo antes de qualquer alteração
- [ ] Bloco `finally` restaura tudo (inclusive em caso de exceção)
- [ ] Clock do periférico habilitado via RCC antes de acessar
- [ ] Loops de espera têm timeout com `time.perf_counter()`

**Portabilidade:**
- [ ] Hardware-específico lido de `get_active_board()` (Padrão A)
- [ ] Constantes de firmware em variáveis no topo do arquivo (Padrão B)

**Qualidade:**
- [ ] Testado com `FakeMemory` antes de conectar hardware
- [ ] `measured` e `expected` preenchidos em `_pass` / `_fail`

---

## 12. Exemplos em TESTES_PLATAFORMA

| Arquivo | Padrão | O que demonstra |
|---|---|---|
| `IO/teste_gpio_output.py` | A | Saída GPIO via `cfg.led_*` do BoardConfig |
| `IO/teste_gpio_input.py` | A | Entrada GPIO via `cfg.btn_*` do BoardConfig |
| `UART/teste_uart_loopback.py` | A | Re-exporta `UsartLoopbackTest` (usa board config) |
| `UART/teste_uart_config.py` | B | Verifica BRR/UE/TE/RE configurados pelo firmware |
| `SPI/teste_spi_loopback.py` | A | Re-exporta `SpiLoopbackTest` (usa board config) |
| `SPI/teste_spi_config.py` | B | Verifica modo e SPE configurados pelo firmware |
| `I2C/teste_i2c_scan.py` | B | Scan de dispositivos no barramento I2C1 |
| `TIMERS/teste_timer_prescaler.py` | B | Verifica PSC e ARR do TIM2 |
| `PWM/teste_pwm_config.py` | B | Verifica freq. e duty-cycle de PWM |
| `ADC/teste_adc_vref.py` | B | Mede VREFINT interno (~1.21 V) |
| `DMA/teste_dma_config.py` | B | Verifica direção e tamanho de dados do DMA |
| `MEMORIA/teste_ram_march.py` | A | March-C- com endereço base do `cfg.sram_base` |
