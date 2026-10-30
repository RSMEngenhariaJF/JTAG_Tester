# Plataforma de Bring-up de Hardware via SWD/JTAG

Aplicação desktop com interface gráfica para automação do *bring-up* de placas
eletrônicas baseadas em microcontroladores, utilizando **SWD** (Serial Wire Debug)
e **JTAG** (IEEE 1149.1) como meios de teste e diagnóstico.

SWD é implementado primeiro (Fase 1) por ser mais simples (2 fios) e entregar
debug ARM (memória, registradores, halt/resume) mais cedo; JTAG vem na Fase 2
para Boundary Scan e cadeias multi-dispositivo.

A aplicação é projetada como **plataforma reutilizável** entre múltiplos
projetos de hardware, com extensibilidade por plugins, cobertura de teste
configurável por projeto, integração nativa a equipamentos de medição e
arquitetura modular/testável.

- **Repositório:** <https://github.com/RSMEngenhariaJF/JTAG_Tester>
- **Autor:** Rafael Macedo — <rafael.macedoengenharia@gmail.com>
- **Especificação:** v0.5 (maio/2026)
- **Status:** rascunho de trabalho — Sprint 01 em andamento.

## Estrutura do repositório

A estrutura segue a especificação §6.5.1:

```
.
├── src/
│   ├── core/              # lógica de domínio (puro Python)
│   │   └── agent/         # agente na RAM do MCU (stubs .bin + fila circular)
│   ├── hal/               # periféricos por família (UART, SPI, I2C, EXTI, CAN, ETH)
│   ├── testbench/         # estímulo, drivers, monitores e decisões (testes compostos)
│   ├── adapters/          # I/O (Ports & Adapters)
│   ├── instruments/       # drivers (VISA/serial/socket), modelos (Rigol, R&S), descoberta
│   ├── app/
│   │   ├── services/      # serviços de aplicação
│   │   ├── viewmodels/    # ViewModels (MVVM)
│   │   ├── gui/           # Views PyQt6
│   │   ├── cli/           # interface de linha de comando
│   │   └── api/           # API Python pública
│   ├── sim/               # mocks (SimulatedProbe/DUT/Instrument)
│   ├── tests_builtin/     # testes built-in da plataforma
│   └── plugin_api/        # API estável de plugin (SemVer)
├── tests/
│   ├── unit/              # ~70%
│   ├── integration/       # ~15%
│   ├── viewmodel/         # ~10% (Qt off-screen)
│   ├── gui/               # ~3%  (pytest-qt)
│   ├── hardware/          # ~2%  (HIL — runner dedicado)
│   └── characterization/  # sessões longas
├── TESTES_PLATAFORMA/     # biblioteca de testes; BLOCOS/ = blocos parametrizáveis
├── stubs/                 # fontes C dos stubs de RAM + build_stubs.py
├── tools/                 # scripts de bancada (ex.: agent_usart_sweep.py)
├── installers/            # PyInstaller specs por SO
├── docs/                  # documentação Sphinx
└── .github/workflows/     # CI (Linux, Windows, macOS)
```

## Pilares da arquitetura

- **GUI como meio principal** (PyQt6/PySide6), com CLI e API Python como apoio.
- **MVVM**: ViewModels testáveis sem instanciar widgets.
- **Ports & Adapters**: domínio independente de I/O.
- **Plugins por projeto**: cada placa é um pacote Python externo, descoberto
  via Python entry points ou carregado dinamicamente por pasta.
- **Mocks first-class**: `sim/` permite desenvolvimento e CI sem hardware.
- **Pirâmide de testes** com gates de cobertura em CI.

## Stack técnica

Python 3.11+ · **PySide6** · pytest · pyftdi · PyVISA · NumPy/SciPy/pandas ·
pyqtgraph · qtconsole · CMSIS-SVD · SQLite/SQLAlchemy · pydantic · ruff · mypy.

> GUI: PySide6 (LGPL). A especificação v0.5 listava "PyQt6 (avaliar PySide6)";
> a decisão por PySide6 fecha a Q-04 do §14.2.

## Como rodar (Sprint 01)

Pré-requisito: Python 3.11+.

### Caminho rápido (mínimo para abrir a GUI)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install PySide6
python run.py
```

### Caminho completo (recomendado — adiciona CLI, testes e lint)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

bringup-gui                 # abre a GUI
bringup --version           # CLI placeholder
pytest                      # smoke tests
ruff check src tests        # lint
mypy src                    # type-check
```

### Formas equivalentes de abrir a GUI

| Comando | Quando usar |
| --- | --- |
| `python run.py` | Mais simples; só precisa do `PySide6` instalado |
| `python -m app` | Idiomático Python; precisa do `app` no path (já configurado se rodar da raiz) |
| `bringup-gui` | Após `pip install -e .` — vira comando global no venv |

Em ambientes de CI, exporte `QT_QPA_PLATFORM=offscreen` antes do `pytest`.

## Testes de alta velocidade (agente na RAM)

Para tráfego contínuo, vazão e BER, o SWD sai do caminho crítico: um stub em C
é carregado na RAM do MCU, roda na velocidade do núcleo e devolve resultados
por uma fila circular, que o host esvazia numa `queue.Queue`.

```powershell
python tools/agent_usart_sweep.py --bytes 4096   # NUCLEO-H743ZI, sem fio externo
python stubs/build_stubs.py                      # só ao alterar um stub (.c)
```

Detalhes: [`stubs/README.md`](stubs/README.md) e seção 12 do
`DOC/GUIA_CRIACAO_DE_TESTES.docx`.

## Instrumentos de medição

Osciloscópio e analisador de espectro entram nos testes por função, não por
modelo: `get_oscilloscope("osc")`, `get_spectrum_analyzer("sa")`. O modelo é
escolhido pelo `*IDN?` (hoje: Rigol MSO8000 e R&S FPC1000/1500 — este último
conceitual; nenhum dos dois validado em bancada ainda).

```powershell
pip install -e ".[hardware]"     # inclui pyvisa + pyvisa-py (LAN sem NI-VISA)
```

Na GUI: aba **Instrumentos → Gerenciar... → Detectar VISA...**. Patrimônio e
validade de calibração do cadastro vão para a seção "Instrumentos utilizados"
dos relatórios. Detalhes: seção 13 do `DOC/GUIA_CRIACAO_DE_TESTES.docx`.

## Plano de testes e blocos reutilizáveis

Um bloco é um teste escrito uma vez, sem pinos fixos: declara `params`
(sinais do Pinout, periférico, números, opções) e uma `category`. No editor do
projeto, aba **Plano de testes** (ou **Testes → Editar plano de testes...** na
janela principal), cada instância escolhe pinos/periférico e valores; o plano
fica no JSON do projeto e roda com **Executar Suite**.

Blocos em `TESTES_PLATAFORMA/BLOCOS/`: GPIO (nível, pull/curto, loopback),
interrupção EXTI, UART, SPI, I2C, CAN (loopback interno) e Ethernet (PHY por
MDIO). Validados na NUCLEO-H753ZI; o caminho F4 da HAL ainda não foi executado
em placa. Detalhes: seção 14 do `DOC/GUIA_CRIACAO_DE_TESTES.docx`.

## Testbench modular

Testes montados por papéis reutilizáveis (`src/testbench/`): **estímulo** (o que
fazer, passo a passo) → **drivers** (aplicam no hardware) → **monitores**
(observam) → **decisões** (comparam com o esperado e registram métricas com
limite ajustável pelo perfil de critérios). Um `ComposedTest` só implementa
`build()`; executar, restaurar os pinos (mesmo com erro) e decidir é do
framework. Os scripts de GPIO (Piscar LED, GPIO Input/Output e os blocos de
`BLOCOS/gpio.py`) usam esse modelo. Detalhes e diagramas: seção 15 do guia.

## Placas

| Placa | Arquivo | Observação |
|---|---|---|
| NUCLEO-F446RE | `src/boards/nucleo_f446re.py` | conexão `halt` |
| NUCLEO-H753ZI | `src/boards/nucleo_h753zi.py` | conexão `under-reset` com retomada do firmware; SVD em `devices/stm32h753/` |

O PAL aceita os nomes de campo de GPIO das duas gerações de SVD
(`MODER5`/`MODE5`, `ODR5`/`OD5`, `AFRH8`/`AFSEL8`).

## Relatórios

Após executar a suite: **Exportar PDF** (A4, gerado pelo próprio Qt — sem
dependência extra), **Relatório ▾** (HTML, Word, PDF) ou **Exportar...** (JSON,
CSV). A janela de salvar abre na última pasta usada (Documentos na primeira
vez). O relatório Word requer `pip install python-docx`.

O perfil de critérios do projeto (`analysis_configs/`) vence o limite escrito no
teste; cada medida registra nominal, origem do limite e margem, e o relatório
traz a seção "Critérios de análise".

## Janela de logs

**Exibir → Logs** (Ctrl+L) ou o contador na barra de status. Filtro por nível,
busca, traceback, **Salvar** (`.log` ou `.jsonl` — JSON Lines com o contexto da
sessão, pensado para análise automática), **Copiar** e **Limpar**. Caminhos com
a pasta do usuário aparecem como `~`.

## Logs de desenvolvimento

Em modo dev (rodando de checkout local), a aplicação grava logs em
`privada/logs/bringup_YYYYMMDD_HHMMSS.log` — útil para depuração. A pasta
`privada/` inteira está no `.gitignore`, portanto nenhum log sobe para o
GitHub. Detalhes e como ligar/desligar: [`privada/logs/README.md`](privada/logs/README.md).

Controle rápido:

```powershell
$env:BRINGUP_DEV = "0"   # só console, não grava arquivo
$env:BRINGUP_DEV = "1"   # força modo dev (arquivo + console em DEBUG)
```

## Status

**Sprint 01 — Bootstrap & Esqueleto GUI** em andamento. Funcionalidades reais
entram a partir do Sprint 03+ (SWD primeiro, JTAG a seguir). Plano completo de
sprints mantido fora do repositório (em `privada/doc/SPRINTS.md`).

## Licença

A definir.
