# Plataforma de Bring-up de Hardware via JTAG

Aplicação desktop com interface gráfica para automação do *bring-up* de placas
eletrônicas baseadas em microcontroladores, utilizando JTAG (IEEE 1149.1) como
meio principal de teste e diagnóstico.

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
│   ├── adapters/          # I/O (Ports & Adapters)
│   ├── instruments/       # drivers de instrumentos (PyVISA)
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
de JTAG/plugins entram a partir do Sprint 03+. Plano completo de sprints
mantido fora do repositório (em `privada/doc/SPRINTS.md`).

## Licença

A definir.
