"""Gera DOC/GUIA_CRIACAO_DE_TESTES.docx — versao didatica completa."""

from docx import Document
from docx.shared import Pt, RGBColor, Cm, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

doc = Document()

# ── Margens ──────────────────────────────────────────────────────────────────
for section in doc.sections:
    section.top_margin    = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.left_margin   = Cm(3.0)
    section.right_margin  = Cm(2.5)

# ── Estilo base ───────────────────────────────────────────────────────────────
doc.styles['Normal'].font.name = 'Calibri'
doc.styles['Normal'].font.size = Pt(11)

# Cores
AZUL_ESCURO  = RGBColor(0x1F, 0x39, 0x64)
AZUL_MEDIO   = RGBColor(0x2E, 0x74, 0xB5)
CINZA_TEXTO  = RGBColor(0x55, 0x55, 0x55)
VERDE        = RGBColor(0x00, 0x70, 0x00)
ROXO         = RGBColor(0x80, 0x00, 0x80)
LARANJA      = RGBColor(0xC0, 0x50, 0x00)
PRETO        = RGBColor(0x00, 0x00, 0x00)
VERMELHO     = RGBColor(0xCC, 0x00, 0x00)
FUNDO_CODE   = 'F0F0F0'
FUNDO_HDR    = '1F3964'
FUNDO_ALT    = 'D6E4F0'
FUNDO_DICA   = 'FFF8DC'
FUNDO_AVISO  = 'FFF0F0'


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _shading(cell_or_para, fill_hex):
    el = cell_or_para if hasattr(cell_or_para, '_tc') else cell_or_para._p
    pPr = el.get_or_add_pPr() if hasattr(el, 'get_or_add_pPr') else el
    if hasattr(cell_or_para, '_tc'):
        pPr = cell_or_para._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_hex)
    pPr.append(shd)


def h1(text):
    p = doc.add_heading('', level=1)
    p.clear()
    r = p.add_run(text)
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = AZUL_ESCURO
    p.paragraph_format.space_before = Pt(18)
    p.paragraph_format.space_after  = Pt(6)
    return p


def h2(text):
    p = doc.add_heading('', level=2)
    p.clear()
    r = p.add_run(text)
    r.font.size = Pt(13)
    r.font.bold = True
    r.font.color.rgb = AZUL_MEDIO
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after  = Pt(4)
    return p


def h3(text):
    p = doc.add_heading('', level=3)
    p.clear()
    r = p.add_run(text)
    r.font.size = Pt(11)
    r.font.bold = True
    r.font.color.rgb = AZUL_MEDIO
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after  = Pt(2)
    return p


def para(text, bold=False, italic=False, color=None, size=11,
         space_before=0, space_after=6, align=None):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.size = Pt(size)
    r.font.color.rgb = color or PRETO
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after  = Pt(space_after)
    if align:
        p.alignment = align
    return p


def mixed_para(*parts, space_before=0, space_after=6):
    """parts = list of (text, bold, italic, color)"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after  = Pt(space_after)
    for text, bold, italic, color in parts:
        r = p.add_run(text)
        r.bold   = bold
        r.italic = italic
        r.font.size = Pt(11)
        r.font.color.rgb = color or PRETO
    return p


def bullet(text, level=0, bold_prefix=None):
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.left_indent = Cm(0.5 + level * 0.5)
    p.paragraph_format.space_after = Pt(3)
    if bold_prefix:
        r = p.add_run(bold_prefix + ' ')
        r.bold = True
        r.font.size = Pt(11)
    r2 = p.add_run(text)
    r2.font.size = Pt(11)
    return p


def numbered(text, bold_prefix=None):
    p = doc.add_paragraph(style='List Number')
    p.paragraph_format.space_after = Pt(4)
    if bold_prefix:
        r = p.add_run(bold_prefix + '  ')
        r.bold = True
        r.font.size = Pt(11)
        r.font.color.rgb = AZUL_MEDIO
    r2 = p.add_run(text)
    r2.font.size = Pt(11)
    return p


def box(text, fill=FUNDO_DICA, title=None, title_color=None):
    """Caixa de destaque (dica, aviso, nota)."""
    if title:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent  = Cm(0.8)
        p.paragraph_format.right_indent = Cm(0.8)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after  = Pt(0)
        r = p.add_run('  ' + title)
        r.bold = True
        r.font.size = Pt(10)
        r.font.color.rgb = title_color or AZUL_ESCURO
        _shading_p(p, fill)

    for line in text.split('\n'):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent  = Cm(0.8)
        p.paragraph_format.right_indent = Cm(0.8)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after  = Pt(0)
        r = p.add_run('  ' + line)
        r.font.size = Pt(10)
        r.font.color.rgb = PRETO
        _shading_p(p, fill)

    p_end = doc.add_paragraph()
    p_end.paragraph_format.space_after = Pt(8)


def _shading_p(p, fill_hex):
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_hex)
    pPr.append(shd)


def code_block(lines_with_tokens, caption=None):
    """
    lines_with_tokens: lista de linhas.
    Cada linha pode ser string pura ou lista de (texto, cor).
    """
    if caption:
        p = doc.add_paragraph()
        r = p.add_run('  ' + caption)
        r.italic = True
        r.font.size = Pt(9)
        r.font.color.rgb = CINZA_TEXTO
        p.paragraph_format.space_after = Pt(0)

    for line in lines_with_tokens:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent  = Cm(0.5)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after  = Pt(0)
        _shading_p(p, FUNDO_CODE)

        if isinstance(line, str):
            r = p.add_run(line if line else ' ')
            r.font.name  = 'Courier New'
            r.font.size  = Pt(9)
            r.font.color.rgb = PRETO
        elif not line:
            r = p.add_run(' ')
            r.font.name = 'Courier New'
            r.font.size = Pt(9)
        else:
            for item in line:
                if isinstance(item, tuple):
                    text, color = item
                else:
                    text, color = item, PRETO
                r = p.add_run(text if text else ' ')
                r.font.name  = 'Courier New'
                r.font.size  = Pt(9)
                r.font.color.rgb = color or PRETO

    doc.add_paragraph().paragraph_format.space_after = Pt(6)


# Atalho: código simples (string multiline → lista de linhas)
def code(text, caption=None):
    code_block(text.split('\n'), caption=caption)


# Tokens de sintaxe Python (coloracao manual)
KW  = lambda t: (t, RGBColor(0x00, 0x00, 0xCC))   # azul — keywords
STR = lambda t: (t, RGBColor(0xA0, 0x20, 0x00))   # vermelho-marrom — strings
CMT = lambda t: (t, RGBColor(0x00, 0x70, 0x00))   # verde — comentarios
NUM = lambda t: (t, RGBColor(0x09, 0x86, 0x58))   # verde-azul — numeros
DEF = lambda t: (t, RGBColor(0x1A, 0x5C, 0x86))   # azul — definicoes
TXT = lambda t: (t, PRETO)                         # texto normal


def table(headers, rows, widths=None):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = 'Table Grid'
    # Cabeçalho
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ''
        r = cell.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(10)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'), FUNDO_HDR)
        cell._tc.get_or_add_tcPr().append(shd)
    # Linhas
    for ri, row in enumerate(rows):
        cells = t.rows[ri + 1].cells
        for ci, val in enumerate(row):
            cells[ci].text = ''
            r = cells[ci].paragraphs[0].add_run(val)
            r.font.size = Pt(10)
            if ri % 2 == 0:
                shd = OxmlElement('w:shd')
                shd.set(qn('w:val'), 'clear')
                shd.set(qn('w:color'), 'auto')
                shd.set(qn('w:fill'), FUNDO_ALT)
                cells[ci]._tc.get_or_add_tcPr().append(shd)
    if widths:
        for row in t.rows:
            for ci, w in enumerate(widths):
                if ci < len(row.cells):
                    row.cells[ci].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return t


def sep():
    """Linha separadora visual."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after  = Pt(4)
    r = p.add_run('─' * 80)
    r.font.size  = Pt(7)
    r.font.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)


# ══════════════════════════════════════════════════════════════════════════════
# CAPA
# ══════════════════════════════════════════════════════════════════════════════
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(80)
r = p.add_run('Plataforma de Bring-up de Hardware')
r.bold = True; r.font.size = Pt(26)
r.font.color.rgb = AZUL_ESCURO

p2 = doc.add_paragraph()
p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
r2 = p2.add_run('Guia Completo para Criacao de Testes Personalizados')
r2.font.size = Pt(15); r2.bold = True
r2.font.color.rgb = AZUL_MEDIO

doc.add_paragraph()

p3 = doc.add_paragraph()
p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
r3 = p3.add_run('Do zero ate o teste rodando na placa — passo a passo')
r3.font.size = Pt(12); r3.italic = True
r3.font.color.rgb = CINZA_TEXTO

doc.add_paragraph()

for line in ['Versao: Sprint 16', 'Alvo: STM32F446RE (NUCLEO-F446RE)',
             'Autor: Rafael Macedo', 'Email: rafael.macedoengenharia@gmail.com']:
    px = doc.add_paragraph()
    px.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rx = px.add_run(line)
    rx.font.size = Pt(10)
    rx.font.color.rgb = CINZA_TEXTO

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# SUMARIO MANUAL
# ══════════════════════════════════════════════════════════════════════════════
h1('Sumario')
sumario = [
    ('1.',  'O que e a Plataforma de Bring-up?'),
    ('2.',  'Como a Plataforma Funciona por Dentro'),
    ('3.',  'BoardConfig — Portabilidade Entre Placas'),
    ('4.',  'Anatomia de um Teste — Padroes A e B'),
    ('5.',  'O PAL: sua interface com o hardware'),
    ('6.',  'Como Descobrir Nomes de Perifericos e Campos'),
    ('7.',  'Padroes Essenciais de Implementacao'),
    ('8.',  'Exemplos Completos por Periferico'),
    ('9.',  'Como Integrar seu Teste na Plataforma'),
    ('10.', 'pytest — Guia Completo'),
    ('11.', 'Desenvolvendo Sem Hardware (TDD)'),
    ('12.', 'Erros Comuns e Como Resolver'),
    ('13.', 'Checklist Final'),
]
for num, titulo in sumario:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r1 = p.add_run(num + '  ')
    r1.bold = True; r1.font.color.rgb = AZUL_MEDIO
    r2 = p.add_run(titulo)
    r2.font.size = Pt(11)
doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 1. O QUE E A PLATAFORMA
# ══════════════════════════════════════════════════════════════════════════════
h1('1. O que e a Plataforma de Bring-up?')

para(
    'Imagine que voce acabou de receber uma placa de circuito impresso recém-fabricada. '
    'Voce nao sabe se os perifericos estao funcionando corretamente, se os pinos estao '
    'conectados como esperado, ou se o microcontrolador responde ao depurador. '
    'O processo de verificar tudo isso se chama bring-up.',
    space_after=8
)
para(
    'Esta plataforma automatiza esse processo. Ela se conecta ao microcontrolador '
    'via ST-Link (o mesmo chip USB que existe na placa NUCLEO) usando o protocolo SWD '
    '(Serial Wire Debug), e executa testes Python que leem e escrevem diretamente nos '
    'registradores do STM32 — sem precisar compilar nenhum firmware de teste.',
    space_after=8
)

box(
    'Analogia: pense na plataforma como um multimetro programavel.\n'
    'Voce escreve em Python "verifique se o pino PA5 esta configurado como saida"\n'
    'e a plataforma vai la no chip e te diz se e verdade ou nao.',
    fill='E8F4F8',
    title='  Analogia',
    title_color=AZUL_MEDIO
)

h2('O que voce consegue fazer com ela:')
bullet('Verificar IDs de dispositivos (confirmar que e o chip certo)')
bullet('Checar configuracoes de clock e perifericos')
bullet('Testar GPIO: ligar LED, ler botao, checar direcao de pinos')
bullet('Fazer loopback de USART e SPI (enviar e receber de volta)')
bullet('Medir tensao interna de referencia do ADC')
bullet('Varrer o barramento I2C em busca de dispositivos')
bullet('Escrever e ler de volta a SRAM (teste de integridade de memoria)')
bullet('Criar qualquer teste customizado para seu proprio hardware')
bullet('Suportar multiplos microcontroladores com apenas um arquivo de configuracao')

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 2. COMO FUNCIONA POR DENTRO
# ══════════════════════════════════════════════════════════════════════════════
h1('2. Como a Plataforma Funciona por Dentro')

para(
    'A plataforma e organizada em camadas. Cada camada tem uma responsabilidade clara. '
    'Voce, como criador de testes, trabalha apenas na camada mais alta — o seu teste Python. '
    'As camadas abaixo sao gerenciadas automaticamente.',
    space_after=8
)

code(
    '  +--------------------------------------------------+\n'
    '  |        VOCE TRABALHA AQUI                        |\n'
    '  |   seu_teste.py  ->  class MeuTeste(BuiltinTest)  |\n'
    '  +--------------------------------------------------+\n'
    '  |  GUI (janela) / CLI (terminal)                   |\n'
    '  |  Selecao de placa + execucao + exporta JSON/CSV  |\n'
    '  +--------------------------------------------------+\n'
    '  |  BoardConfig (src/boards/<nome>.py)              |\n'
    '  |  Descreve pinos, clocks, perifericos da placa    |\n'
    '  +--------------------------------------------------+\n'
    '  |  TestRunnerService                               |\n'
    '  |  Executa os testes em ordem, captura erros       |\n'
    '  +--------------------------------------------------+\n'
    '  |  PAL — Peripheral Access Layer                   |\n'
    '  |  Traduz nomes (GPIOA.MODER.MODER5) em enderecos |\n'
    '  +--------------------------------------------------+\n'
    '  |  pyOCD + ST-Link                                 |\n'
    '  |  Comunicacao USB -> SWD -> registradores do chip |\n'
    '  +--------------------------------------------------+\n'
    '  |  STM32F446RE (o seu microcontrolador)            |\n'
    '  +--------------------------------------------------+'
)

h2('O ciclo de vida de um teste')
numbered('Voce seleciona a placa no ComboBox "Projeto" na GUI')
numbered('A plataforma chama set_active_board(BOARD) com os dados da placa')
numbered('Voce clica "Executar Suite" (ou roda o CLI)')
numbered('A plataforma chama  MeuTeste().run(pal)')
numbered('run() chama  _run(pal)  — o metodo que voce escreve')
numbered('Dentro de _run(), voce usa  pal.read_field()  e  pal.modify_field()')
numbered('O PAL consulta o SVD para achar o endereco do campo no STM32')
numbered('O pyOCD envia o comando via USB para o ST-Link')
numbered('O ST-Link acessa o registrador do chip via SWD em microssegundos')
numbered('O valor volta para o Python e voce decide: _pass() ou _fail()')
numbered('O resultado aparece colorido na tabela da GUI')

doc.add_paragraph()
box(
    'O arquivo SVD (devices/stm32f446/STM32F446.svd) e o mapa completo de todos\n'
    'os registradores do STM32F446. E um XML padrao da ARM que descreve cada\n'
    'periferico, cada registrador e cada campo de bit com seu nome e posicao.\n'
    'A plataforma le esse arquivo na inicializacao e usa os nomes como chaves.',
    fill='E8F4F8',
    title='  O arquivo SVD',
    title_color=AZUL_MEDIO
)

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 3. BOARDCONFIG — PORTABILIDADE
# ══════════════════════════════════════════════════════════════════════════════
h1('3. BoardConfig — Portabilidade Entre Placas')

para(
    'Um dos maiores desafios em plataformas de bring-up e ter que editar o codigo dos '
    'testes toda vez que se muda de hardware. A plataforma resolve isso com o conceito '
    'de BoardConfig: um unico arquivo Python que descreve toda a informacao especifica '
    'de uma placa. Os testes nao conhecem os pinos — eles perguntam ao BoardConfig.',
    space_after=8
)

h2('3.1 O que o BoardConfig descreve')

table(
    ['Campo', 'Tipo', 'Exemplo (NUCLEO-F446RE)'],
    [
        ['project_code',       'str',   '"2180.0720.00"'],
        ['name',               'str',   '"NUCLEO-F446RE"'],
        ['target',             'str',   '"stm32f446retx"  (pyOCD target)'],
        ['svd_path',           'str',   '"devices/stm32f446/STM32F446.svd"'],
        ['dbgmcu_idcode_addr', 'int',   '0xE0042000'],
        ['expected_dev_id',    'int',   '0x421  (STM32F446)'],
        ['sram_base',          'int',   '0x20000000'],
        ['led_port / led_pin', 'str/int', '"GPIOA", 5  (LED LD2)'],
        ['btn_port / btn_pin', 'str/int', '"GPIOC", 13  (botao azul)'],
        ['btn_active_low',     'bool',  'True  (pull-up, pressionado = 0)'],
        ['required_clocks',    'tuple', '(("AHB1ENR","GPIOAEN","GPIOA"),...)'],
        ['usart',              'UsartConfig', 'n=1, TX=PA9/AF7, RX=PA10/AF7'],
        ['spi',                'SpiConfig',   'n=1, SCK=PA5/AF5, MOSI=PA7/AF5'],
    ],
    widths=[4.5, 3, 8.5]
)

h2('3.2 O campo project_code — rastreabilidade')

para(
    'Cada BoardConfig tem um campo project_code (ex.: "2180.0720.00"). Ele aparece em:',
    space_after=4
)
bullet('Titulo da janela GUI: "Bring-up 2180.0720.00 — NUCLEO-F446RE"')
bullet('Arquivo exportado JSON/CSV: campo "project_code" em cada resultado')
bullet('Log de execucao CLI')

para(
    'Isso permite rastrear qual configuracao de placa estava ativa quando os '
    'resultados foram gerados — fundamental para documentacao de qualidade.',
    space_after=8
)

box(
    'Regra pratica: um project_code por revisao de hardware.\n'
    'Se a placa ganha um novo conector, crie 2180.0720.01 com replace().\n'
    'Os testes ficam identicos — apenas o arquivo de config muda.',
    fill='E8F4F8',
    title='  Rastreabilidade de revisao',
    title_color=AZUL_MEDIO
)

h2('3.3 Como criar o arquivo para uma nova placa')

para(
    'Crie o arquivo  src/boards/minha_placa.py  com o conteudo abaixo. '
    'A GUI detecta automaticamente qualquer arquivo .py nessa pasta que '
    'exponha uma variavel BOARD do tipo BoardConfig.',
    space_after=6
)

code_block([
    [CMT('# src/boards/minha_placa.py'), TXT('')],
    [KW('from '), TXT('core.board.config '), KW('import '), TXT('BoardConfig, PinConfig, UsartConfig, SpiConfig')],
    [''],
    [TXT('BOARD = BoardConfig(')],
    [TXT('    '), CMT('# Identificacao')],
    [TXT('    project_code = '), STR('"2180.0720.00"'), TXT(',      '), CMT('# codigo do projeto')],
    [TXT('    name         = '), STR('"Minha Placa XYZ"'), TXT(',')],
    [''],
    [TXT('    '), CMT('# Conexao pyOCD')],
    [TXT('    target   = '), STR('"stm32l476rgtx"'), TXT(',')],
    [TXT('    svd_path = '), STR('"devices/stm32l476/STM32L476.svd"'), TXT(',')],
    [''],
    [TXT('    '), CMT('# Chip identity')],
    [TXT('    dbgmcu_idcode_addr = '), NUM('0xE0042000'), TXT(',')],
    [TXT('    expected_dev_id    = '), NUM('0x415'), TXT(',       '), CMT('# STM32L476')],
    [''],
    [TXT('    '), CMT('# SRAM')],
    [TXT('    sram_base = '), NUM('0x20000000'), TXT(',')],
    [''],
    [TXT('    '), CMT('# LED (pino de saida de status)')],
    [TXT('    led_port        = '), STR('"GPIOB"'), TXT(',')],
    [TXT('    led_pin         = '), NUM('7'), TXT(',')],
    [TXT('    led_clock_reg   = '), STR('"AHB2ENR"'), TXT(',      '), CMT('# L4 usa AHB2')],
    [TXT('    led_clock_field = '), STR('"GPIOBEN"'), TXT(',')],
    [''],
    [TXT('    '), CMT('# Botao de usuario')],
    [TXT('    btn_port        = '), STR('"GPIOC"'), TXT(',')],
    [TXT('    btn_pin         = '), NUM('13'), TXT(',')],
    [TXT('    btn_clock_reg   = '), STR('"AHB2ENR"'), TXT(',')],
    [TXT('    btn_clock_field = '), STR('"GPIOCEN"'), TXT(',')],
    [TXT('    btn_active_low  = '), KW('True'), TXT(',')],
    [''],
    [TXT('    '), CMT('# Clocks que devem estar habilitados pelo firmware')],
    [TXT('    required_clocks = (')],
    [TXT('        ('), STR('"AHB2ENR"'), TXT(', '), STR('"GPIOBEN"'), TXT(', '), STR('"GPIOB"'), TXT('),')],
    [TXT('        ('), STR('"AHB2ENR"'), TXT(', '), STR('"GPIOCEN"'), TXT(', '), STR('"GPIOC"'), TXT('),')],
    [TXT('    ),')],
    [''],
    [TXT('    '), CMT('# USART para loopback')],
    [TXT('    usart = UsartConfig(')],
    [TXT('        n            = '), NUM('1'), TXT(',')],
    [TXT('        tx           = PinConfig(port='), STR('"GPIOA"'), TXT(', pin='), NUM('9'), TXT(',  af='), NUM('7'), TXT('),')],
    [TXT('        rx           = PinConfig(port='), STR('"GPIOA"'), TXT(', pin='), NUM('10'), TXT(', af='), NUM('7'), TXT('),')],
    [TXT('        clock_reg    = '), STR('"APB2ENR"'), TXT(',')],
    [TXT('        clock_field  = '), STR('"USART1EN"'), TXT(',')],
    [TXT('        loopback_baud = '), NUM('9600'), TXT(',')],
    [TXT('    ),')],
    [''],
    [TXT('    '), CMT('# SPI para loopback')],
    [TXT('    spi = SpiConfig(')],
    [TXT('        n           = '), NUM('1'), TXT(',')],
    [TXT('        sck         = PinConfig(port='), STR('"GPIOA"'), TXT(', pin='), NUM('5'), TXT(', af='), NUM('5'), TXT('),')],
    [TXT('        miso        = PinConfig(port='), STR('"GPIOA"'), TXT(', pin='), NUM('6'), TXT(', af='), NUM('5'), TXT('),')],
    [TXT('        mosi        = PinConfig(port='), STR('"GPIOA"'), TXT(', pin='), NUM('7'), TXT(', af='), NUM('5'), TXT('),')],
    [TXT('        clock_reg   = '), STR('"APB2ENR"'), TXT(',')],
    [TXT('        clock_field = '), STR('"SPI1EN"'), TXT(',')],
    [TXT('    ),')],
    [TXT(')')],
], caption='src/boards/minha_placa.py — template completo')

h2('3.4 Usar get_active_board() nos seus testes')

para(
    'Dentro do metodo _run(), chame get_active_board() para obter os dados '
    'da placa que foi selecionada na GUI. O teste nao precisa saber qual placa '
    'esta conectada — ele simplesmente pergunta.',
    space_after=6
)

code_block([
    [KW('from '), TXT('tests_builtin.base '), KW('import '), TXT('BuiltinTest, TestResult')],
    [''],
    [KW('class '), DEF('MeuTestePortavel'), TXT('(BuiltinTest):')],
    [TXT('    name = '), STR('"Meu Teste"')],
    [''],
    [KW('    def '), DEF('_run'), TXT('(self, pal) -> TestResult:')],
    [TXT('        '), CMT('# Sempre dentro de _run(), nunca no __init__')],
    [KW('        from '), TXT('core.board.config '), KW('import '), TXT('get_active_board')],
    [TXT('        cfg = get_active_board()')],
    [''],
    [TXT('        '), CMT('# Agora use os campos do BoardConfig')],
    [TXT('        pal.modify_field('), STR('"RCC"'), TXT(', cfg.led_clock_reg, cfg.led_clock_field, '), NUM('1'), TXT(')')],
    [TXT('        nivel = pal.read_field(cfg.led_port, '), STR('"ODR"'), TXT(', f'), STR('"ODR{cfg.led_pin}"'), TXT(')')],
    [''],
    [KW('        if '), TXT('nivel == '), NUM('1'), TXT(':')],
    [KW('            return '), TXT('self._pass('), STR('"LED ON"'), TXT(')')],
    [KW('        return '), TXT('self._fail('), STR('"LED nao subiu"'), TXT(')')],
], caption='Usando get_active_board() para portabilidade')

box(
    'Para trocar de placa: basta selecionar outro item no ComboBox "Projeto" na GUI.\n'
    'Nenhuma linha de codigo de teste precisa mudar.\n'
    'Para adicionar suporte a nova placa: crie src/boards/nova_placa.py com BOARD=BoardConfig(...).',
    fill='E8F4F8',
    title='  Regra de portabilidade',
    title_color=AZUL_MEDIO
)

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 4. ANATOMIA DE UM TESTE
# ══════════════════════════════════════════════════════════════════════════════
h1('4. Anatomia de um Teste — Padroes A e B')

para(
    'Existem dois padroes de teste na plataforma. Entender qual usar em cada '
    'situacao e fundamental para escrever testes corretos e portaveis.',
    space_after=10
)

h2('Padrao A — Teste Portavel (usa BoardConfig)')

para(
    'Use quando o teste exercita hardware da placa: LED, botao, USART para loopback, '
    'pinos de GPIO. Ao trocar de placa na GUI, o teste se adapta automaticamente '
    'sem nenhuma alteracao de codigo.',
    space_after=6
)

code_block([
    [KW('from '), TXT('tests_builtin.base '), KW('import '), TXT('BuiltinTest, TestResult')],
    [''],
    [KW('class '), DEF('TestePortavel'), TXT('(BuiltinTest):')],
    [TXT('    name        = '), STR('"Teste do LED"')],
    [TXT('    description = '), STR('"Verifica o LED da placa ativa — portavel entre placas"')],
    [''],
    [KW('    def '), DEF('_run'), TXT('(self, pal) -> TestResult:')],
    [TXT('        '), CMT('# 1. Obtem a configuracao da placa selecionada na GUI')],
    [KW('        from '), TXT('core.board.config '), KW('import '), TXT('get_active_board')],
    [TXT('        cfg = get_active_board()')],
    [''],
    [TXT('        '), CMT('# 2. Usa os campos — funciona para qualquer placa')],
    [TXT('        pal.modify_field('), STR('"RCC"'), TXT(', cfg.led_clock_reg, cfg.led_clock_field, '), NUM('1'), TXT(')')],
    [TXT('        orig = pal.read_field(cfg.led_port, '), STR('"MODER"'), TXT(', f'), STR('"MODER{cfg.led_pin}"'), TXT(')')],
    [''],
    [KW('        try'), TXT(':')],
    [TXT('            pal.modify_field(cfg.led_port, '), STR('"MODER"'), TXT(', f'), STR('"MODER{cfg.led_pin}"'), TXT(', '), NUM('0b01'), TXT(')')],
    [TXT('            pal.write_reg(cfg.led_port, '), STR('"BSRR"'), TXT(', '), NUM('1'), TXT(' << cfg.led_pin)')],
    [TXT('            nivel = pal.read_field(cfg.led_port, '), STR('"ODR"'), TXT(', f'), STR('"ODR{cfg.led_pin}"'), TXT(')')],
    [''],
    [KW('            if '), TXT('nivel == '), NUM('1'), TXT(':')],
    [KW('                return '), TXT('self._pass('), STR('"LED ON: OK"'), TXT(', measured=nivel, expected='), NUM('1'), TXT(')')],
    [KW('            return '), TXT('self._fail('), STR('"LED nao subiu"'), TXT(', measured=nivel, expected='), NUM('1'), TXT(')')],
    [''],
    [KW('        finally'), TXT(':')],
    [TXT('            pal.modify_field(cfg.led_port, '), STR('"MODER"'), TXT(', f'), STR('"MODER{cfg.led_pin}"'), TXT(', orig)')],
], caption='Padrao A: usa get_active_board() — portavel entre placas')

h2('Padrao B — Constantes Fixas (verifica firmware)')

para(
    'Use quando o teste verifica parametros configurados pelo firmware: baud rate, '
    'frequencia de PWM, canal DMA, modo de SPI. Esses valores sao da aplicacao, '
    'nao da placa fisica — portanto ficam como constantes no topo do arquivo.',
    space_after=6
)

code_block([
    [KW('from '), TXT('tests_builtin.base '), KW('import '), TXT('BuiltinTest, TestResult')],
    [''],
    [CMT('# ─── Constantes da aplicacao — altere conforme o firmware ──────────────────')],
    [TXT('PERIFERICO  = '), STR('"USART2"')],
    [TXT('REGISTRADOR = '), STR('"BRR"')],
    [TXT('CAMPO       = '), STR('"DIV_Mantissa"')],
    [TXT('VALOR_OK    = '), NUM('8'), TXT('          '), CMT('# BRR mant para 115200 @ 16 MHz')],
    [CMT('# ────────────────────────────────────────────────────────────────────────────')],
    [''],
    [KW('class '), DEF('UsartBaudCheck'), TXT('(BuiltinTest):')],
    [TXT('    name        = '), STR('"USART2 Baud Check"')],
    [TXT('    description = '), STR('"Verifica se firmware configurou USART2 para 115200 baud"')],
    [''],
    [KW('    def '), DEF('_run'), TXT('(self, pal) -> TestResult:')],
    [TXT('        valor = pal.read_field(PERIFERICO, REGISTRADOR, CAMPO)')],
    [''],
    [KW('        if '), TXT('valor == VALOR_OK:')],
    [KW('            return '), TXT('self._pass(')],
    [TXT('                '), STR('f"{PERIFERICO}.{CAMPO} = {valor} (OK)"'), TXT(',')],
    [TXT('                measured=valor, expected=VALOR_OK')],
    [TXT('            )')],
    [KW('        return '), TXT('self._fail(')],
    [TXT('            '), STR('f"{PERIFERICO}.{CAMPO} = {valor}, esperado {VALOR_OK}"'), TXT(',')],
    [TXT('            measured=valor, expected=VALOR_OK')],
    [TXT('        )')],
], caption='Padrao B: constantes fixas — verifica configuracao do firmware')

table(
    ['Criterio', 'Padrao A (portavel)', 'Padrao B (fixo)'],
    [
        ['O que verifica',   'Hardware da placa (LED, botao, loopback)', 'Firmware da aplicacao (baud, PWM, DMA)'],
        ['Como obtem pinos', 'get_active_board() dentro de _run()',       'Constantes no topo do arquivo'],
        ['Ao trocar de placa', 'Funciona automaticamente',               'Constantes continuam as mesmas'],
        ['Quando usar',      'Teste de trazer-a-vida (bring-up)',        'Teste de configuracao de firmware'],
    ],
    widths=[4, 6, 6]
)

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 5. O PAL
# ══════════════════════════════════════════════════════════════════════════════
h1('5. O PAL: sua interface com o hardware')

para(
    'O PAL (Peripheral Access Layer) e o objeto que voce recebe como parametro "pal" '
    'no metodo _run(). Pense nele como um dicionario gigante que mapeia nomes em '
    'acoes de hardware. Voce nao precisa saber qual e o endereco de memoria do '
    'registrador MODER do GPIOA — o PAL descobre isso sozinho usando o SVD.',
    space_after=10
)

h2('5.1 read_field() — Ler um campo de registrador')

para(
    'Esta e a operacao mais comum. Voce informa o nome do periferico, do registrador '
    'e do campo, e recebe o valor numerico daquele campo especifico.',
    space_after=6
)

code_block([
    [CMT('# Sintaxe:'), TXT('')],
    [TXT('valor = pal.read_field('), STR('"PERIFERICO"'), TXT(', '), STR('"REGISTRADOR"'), TXT(', '), STR('"CAMPO"'), TXT(')')],
    [''],
    [CMT('# Exemplos praticos:'), TXT('')],
    [''],
    [CMT('# Verifica se o clock do GPIOA esta habilitado (campo de 1 bit):')],
    [TXT('clock_on = pal.read_field('), STR('"RCC"'), TXT(', '), STR('"AHB1ENR"'), TXT(', '), STR('"GPIOAEN"'), TXT(')')],
    [CMT('# clock_on sera 0 ou 1')],
    [''],
    [CMT('# Le o modo do pino 5 do GPIOA (campo de 2 bits):')],
    [TXT('modo = pal.read_field('), STR('"GPIOA"'), TXT(', '), STR('"MODER"'), TXT(', '), STR('"MODER5"'), TXT(')')],
    [CMT('# modo sera: 0=entrada, 1=saida, 2=AF, 3=analogico')],
    [''],
    [CMT('# Le o estado do botao (pino PC13):')],
    [TXT('botao = pal.read_field('), STR('"GPIOC"'), TXT(', '), STR('"IDR"'), TXT(', '), STR('"IDR13"'), TXT(')')],
    [CMT('# botao sera 1 (solto) ou 0 (pressionado, com pull-up)')],
])

box(
    'O PAL ja faz a mascara e o deslocamento para voce. Se o campo MODER5 fica\n'
    'nos bits [11:10] do registrador MODER, o PAL extrai esses 2 bits e retorna\n'
    'um valor entre 0 e 3 — voce nao precisa fazer "(valor >> 10) & 0x3" na mao.',
    fill='E8F4F8',
    title='  Sem contas de bit',
    title_color=AZUL_MEDIO
)

h2('5.2 modify_field() — Modificar um campo (Read-Modify-Write)')

para(
    'Esta operacao le o registrador inteiro, modifica apenas os bits do campo '
    'especificado e escreve o valor de volta. Os outros campos do registrador '
    'nao sao alterados.',
    space_after=6
)

code_block([
    [CMT('# Sintaxe:'), TXT('')],
    [TXT('pal.modify_field('), STR('"PERIFERICO"'), TXT(', '), STR('"REGISTRADOR"'), TXT(', '), STR('"CAMPO"'), TXT(', novo_valor)')],
    [''],
    [CMT('# Exemplos:'), TXT('')],
    [''],
    [CMT('# Configura PA5 como saida (MODER5 = 0b01):')],
    [TXT('pal.modify_field('), STR('"GPIOA"'), TXT(', '), STR('"MODER"'), TXT(', '), STR('"MODER5"'), TXT(', '), NUM('0b01'), TXT(')')],
    [''],
    [CMT('# Habilita o clock do GPIOA:')],
    [TXT('pal.modify_field('), STR('"RCC"'), TXT(', '), STR('"AHB1ENR"'), TXT(', '), STR('"GPIOAEN"'), TXT(', '), NUM('1'), TXT(')')],
    [''],
    [CMT('# Ou usando campos do BoardConfig (portavel):')],
    [TXT('cfg = get_active_board()')],
    [TXT('pal.modify_field('), STR('"RCC"'), TXT(', cfg.led_clock_reg, cfg.led_clock_field, '), NUM('1'), TXT(')')],
])

h2('5.3 read_reg() e write_reg() — Registrador Inteiro')

para(
    'Quando voce precisa ler ou escrever o registrador completo de 32 bits de uma vez. '
    'Util para registradores de status que sao lidos de uma vez (como USART SR) '
    'ou para o BSRR do GPIO (Bit Set/Reset Register).',
    space_after=6
)

code_block([
    [CMT('# Ler o registrador de status da USART1 por inteiro:')],
    [TXT('sr = pal.read_reg('), STR('"USART1"'), TXT(', '), STR('"SR"'), TXT(')')],
    [TXT('txe  = (sr >> '), NUM('7'), TXT(') & '), NUM('1'), TXT('   '), CMT('# extrai bit 7 manualmente')],
    [''],
    [CMT('# Escrever no BSRR para controlar pinos de saida:')],
    [TXT('pal.write_reg('), STR('"GPIOA"'), TXT(', '), STR('"BSRR"'), TXT(', '), NUM('1'), TXT(' << '), NUM('5'), TXT(')    '), CMT('# SET PA5')],
    [TXT('pal.write_reg('), STR('"GPIOA"'), TXT(', '), STR('"BSRR"'), TXT(', '), NUM('1'), TXT(' << ('), NUM('5'), TXT(' + '), NUM('16'), TXT('))'), CMT('# RESET PA5')],
])

h2('5.4 pal.mem — Acesso Direto por Endereco')

para(
    'Para situacoes especiais onde voce precisa acessar um endereco de memoria que '
    'nao esta no SVD (como registradores de debug da ARM ou regioes de SRAM).',
    space_after=6
)

code_block([
    [CMT('# Ler o ID do dispositivo no registrador DBGMCU_IDCODE:')],
    [TXT('idcode = pal.mem.read_mem32('), NUM('0xE0042000'), TXT(')')],
    [TXT('dev_id = idcode & '), NUM('0xFFF'), TXT('   '), CMT('# bits [11:0] = device ID')],
    [''],
    [CMT('# Ou usando o BoardConfig (portavel):')],
    [TXT('cfg    = get_active_board()')],
    [TXT('idcode = pal.mem.read_mem32(cfg.dbgmcu_idcode_addr)')],
    [TXT('dev_id = idcode & '), NUM('0xFFF')],
    [''],
    [CMT('# Escrever na SRAM (para teste de memoria):')],
    [TXT('pal.mem.write_mem32(cfg.sram_base, '), NUM('0xA5A5A5A5'), TXT(')')],
    [TXT('lido = pal.mem.read_mem32(cfg.sram_base)')],
])

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 6. DESCOBRINDO NOMES
# ══════════════════════════════════════════════════════════════════════════════
h1('6. Como Descobrir Nomes de Perifericos e Campos')

para(
    'A pergunta mais comum de quem comeca e: "Como eu sei o nome exato do periferico, '
    'do registrador e do campo que eu preciso usar?" A resposta e: consultando o SVD.',
    space_after=8
)

h2('6.1 Consultando via terminal (mais rapido)')

para('Abra o terminal do VS Code (Ctrl+`) e use os comandos abaixo:')

code_block([
    [CMT('# Primeiro, configure o PYTHONPATH:')],
    [TXT('$env:PYTHONPATH = '), STR('"src"')],
    [''],
    [CMT('# Ver todos os perifericos disponiveis:')],
    [TXT('.venv\\Scripts\\python.exe -c "'), TXT('')],
    [TXT('from core.svd.parser import parse; from pathlib import Path')],
    [TXT('svd = parse(Path(\'devices/stm32f446/STM32F446.svd\'))')],
    [TXT('print([p.name for p in svd.peripherals])')],
    [TXT('"')],
    [''],
    [CMT('# Listar registradores de um periferico (ex: USART1):')],
    [TXT('.venv\\Scripts\\python.exe -c "'), TXT('')],
    [TXT('from core.svd.parser import parse; from pathlib import Path')],
    [TXT('svd = parse(Path(\'devices/stm32f446/STM32F446.svd\'))')],
    [TXT('for r in svd.peripheral(\'USART1\').registers:')],
    [TXT('    print(f\'  {r.name:12} offset=0x{r.offset:02X}\')')],
    [TXT('"')],
    [''],
    [CMT('# Listar campos de um registrador (ex: USART1.CR1):')],
    [TXT('.venv\\Scripts\\python.exe -c "'), TXT('')],
    [TXT('from core.svd.parser import parse; from pathlib import Path')],
    [TXT('svd = parse(Path(\'devices/stm32f446/STM32F446.svd\'))')],
    [TXT('for f in svd.peripheral(\'USART1\').register(\'CR1\').fields:')],
    [TXT('    print(f\'  {f.name:12} bit[{f.bit_offset}:{f.bit_offset+f.bit_width-1}]\')')],
    [TXT('"')],
])

h2('6.2 Perifericos mais usados e seus clocks')

table(
    ['Periferico', 'Clock em', 'Campo no RCC'],
    [
        ['GPIOA, GPIOB, GPIOC...', 'AHB1ENR', 'GPIOAEN, GPIOBEN, GPIOCEN...'],
        ['USART1, USART6', 'APB2ENR', 'USART1EN, USART6EN'],
        ['USART2, USART3, UART4, UART5', 'APB1ENR', 'USART2EN, USART3EN, UART4EN, UART5EN'],
        ['SPI1, SPI4', 'APB2ENR', 'SPI1EN, SPI4EN'],
        ['SPI2, SPI3', 'APB1ENR', 'SPI2EN, SPI3EN'],
        ['I2C1, I2C2, I2C3', 'APB1ENR', 'I2C1EN, I2C2EN, I2C3EN'],
        ['TIM1, TIM8', 'APB2ENR', 'TIM1EN, TIM8EN'],
        ['TIM2..TIM7', 'APB1ENR', 'TIM2EN, TIM3EN...'],
        ['ADC1, ADC2, ADC3', 'APB2ENR', 'ADC1EN, ADC2EN, ADC3EN'],
        ['DMA1, DMA2', 'AHB1ENR', 'DMA1EN, DMA2EN'],
    ],
    widths=[5, 3.5, 7.5]
)

h2('6.3 Alternate Functions mais usadas (NUCLEO-F446RE)')

table(
    ['Sinal', 'Pino', 'Label CN9', 'Campo AFR', 'Valor AF'],
    [
        ['USART1_TX', 'PA9',  'D8',  'GPIOA.AFRH.AFRH9',   'AF7'],
        ['USART1_RX', 'PA10', 'D2',  'GPIOA.AFRH.AFRH10',  'AF7'],
        ['SPI1_SCK',  'PA5',  'D13', 'GPIOA.AFRL.AFRL5',   'AF5'],
        ['SPI1_MISO', 'PA6',  'D12', 'GPIOA.AFRL.AFRL6',   'AF5'],
        ['SPI1_MOSI', 'PA7',  'D11', 'GPIOA.AFRL.AFRL7',   'AF5'],
        ['I2C1_SCL',  'PB8',  'D15', 'GPIOB.AFRH.AFRH8',   'AF4'],
        ['I2C1_SDA',  'PB9',  'D14', 'GPIOB.AFRH.AFRH9',   'AF4'],
        ['TIM3_CH1',  'PA6',  'D12', 'GPIOA.AFRL.AFRL6',   'AF2'],
    ],
    widths=[3, 2, 2.5, 5, 2.5]
)

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 7. PADROES ESSENCIAIS
# ══════════════════════════════════════════════════════════════════════════════
h1('7. Padroes Essenciais de Implementacao')

h2('7.1 Sempre Habilite o Clock Antes de Acessar um Periferico')

para(
    'No STM32, todo periferico tem seu clock desabilitado por padrao para economizar '
    'energia. Se voce tentar ler ou escrever em um registrador de periferico sem '
    'habilitar o clock, o valor lido sera sempre 0 e escritas serao ignoradas '
    '— o que leva a testes que passam mas nao testam nada de verdade.',
    space_after=6
)

code_block([
    [CMT('# ERRADO — nao habilita clock antes de usar GPIOA:')],
    [KW('def '), DEF('_run'), TXT('(self, pal):')],
    [TXT('    modo = pal.read_field('), STR('"GPIOA"'), TXT(', '), STR('"MODER"'), TXT(', '), STR('"MODER5"'), TXT(')')],
    [TXT('    '), CMT('# modo sempre sera 0 se o clock nao estiver ligado!')],
    [''],
    [CMT('# CORRETO — habilita clock primeiro:')],
    [KW('def '), DEF('_run'), TXT('(self, pal):')],
    [TXT('    pal.modify_field('), STR('"RCC"'), TXT(', '), STR('"AHB1ENR"'), TXT(', '), STR('"GPIOAEN"'), TXT(', '), NUM('1'), TXT(')')],
    [TXT('    modo = pal.read_field('), STR('"GPIOA"'), TXT(', '), STR('"MODER"'), TXT(', '), STR('"MODER5"'), TXT(')')],
    [TXT('    '), CMT('# agora sim o valor e real')],
])

h2('7.2 O Padrao Salvar / Modificar / Restaurar')

para(
    'Este e o padrao mais importante de toda a plataforma. Se o seu teste '
    'modifica registradores, ele DEVE restaurar o estado original ao terminar '
    '— independentemente de ter passado ou falhado. Isso garante que os proximos '
    'testes nao sejam afetados. Use sempre o bloco try/finally.',
    space_after=6
)

code_block([
    [KW('def '), DEF('_run'), TXT('(self, pal):')],
    [''],
    [TXT('    '), CMT('# PASSO 1: salve o estado original ANTES de qualquer alteracao')],
    [TXT('    estado_moder5 = pal.read_field('), STR('"GPIOA"'), TXT(', '), STR('"MODER"'), TXT(', '), STR('"MODER5"'), TXT(')')],
    [TXT('    estado_odr5   = pal.read_field('), STR('"GPIOA"'), TXT(', '), STR('"ODR"'), TXT(',   '), STR('"ODR5"'), TXT(')')],
    [''],
    [KW('    try'), TXT(':')],
    [TXT('        '), CMT('# PASSO 2: faca suas alteracoes e testes aqui')],
    [TXT('        pal.modify_field('), STR('"GPIOA"'), TXT(', '), STR('"MODER"'), TXT(', '), STR('"MODER5"'), TXT(', '), NUM('0b01'), TXT(')')],
    [TXT('        pal.write_reg('), STR('"GPIOA"'), TXT(', '), STR('"BSRR"'), TXT(', '), NUM('1'), TXT(' << '), NUM('5'), TXT(')')],
    [TXT('        nivel = pal.read_field('), STR('"GPIOA"'), TXT(', '), STR('"ODR"'), TXT(', '), STR('"ODR5"'), TXT(')')],
    [''],
    [KW('        if '), TXT('nivel == '), NUM('1'), TXT(':')],
    [KW('            return '), TXT('self._pass('), STR('"PA5 foi para HIGH"'), TXT(')')],
    [KW('        return '), TXT('self._fail('), STR('"PA5 nao subiu para HIGH"'), TXT(', measured=nivel, expected='), NUM('1'), TXT(')')],
    [''],
    [KW('    finally'), TXT(':')],
    [TXT('        '), CMT('# PASSO 3: restaure SEMPRE — mesmo se der excecao acima')],
    [TXT('        pal.modify_field('), STR('"GPIOA"'), TXT(', '), STR('"MODER"'), TXT(', '), STR('"MODER5"'), TXT(', estado_moder5)')],
    [TXT('        pal.modify_field('), STR('"GPIOA"'), TXT(', '), STR('"ODR"'), TXT(',   '), STR('"ODR5"'), TXT(',   estado_odr5)')],
])

h2('7.3 Aguardar uma Condicao com Timeout')

para(
    'Perifericos como USART e SPI nao ficam prontos instantaneamente. Voce precisa '
    'esperar que certas flags se tornem 1 antes de prosseguir. Sempre coloque um '
    'timeout para evitar loop infinito caso algo de errado.',
    space_after=6
)

code_block([
    [KW('import '), TXT('time')],
    [''],
    [KW('def '), DEF('_aguardar_flag'), TXT('(pal, periferico, reg, campo, esperado='), NUM('1'), TXT(', timeout_ms='), NUM('100'), TXT('):')],
    [TXT('    prazo = time.perf_counter() + timeout_ms / '), NUM('1000')],
    [KW('    while '), TXT('pal.read_field(periferico, reg, campo) != esperado:')],
    [KW('        if '), TXT('time.perf_counter() > prazo:')],
    [KW('            return '), KW('False')],
    [KW('    return '), KW('True')],
    [''],
    [CMT('# Usando no seu teste:')],
    [KW('def '), DEF('_run'), TXT('(self, pal):')],
    [TXT('    pal.write_reg('), STR('"USART1"'), TXT(', '), STR('"DR"'), TXT(', '), NUM('0xAA'), TXT(')')],
    [KW('    if not '), TXT('_aguardar_flag(pal, '), STR('"USART1"'), TXT(', '), STR('"SR"'), TXT(', '), STR('"RXNE"'), TXT(', timeout_ms='), NUM('200'), TXT('):')],
    [KW('        return '), TXT('self._fail('), STR('"Timeout! Verifique o fio entre TX e RX"'), TXT(')')],
    [TXT('    eco = pal.read_reg('), STR('"USART1"'), TXT(', '), STR('"DR"'), TXT(') & '), NUM('0xFF')],
])

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 8. EXEMPLOS COMPLETOS
# ══════════════════════════════════════════════════════════════════════════════
h1('8. Exemplos Completos por Periferico')

h2('8.1 Exemplo: Teste de LED Portavel (Padrao A)')

para(
    'Objetivo: configurar o pino do LED da placa ativa como saida, ligar, verificar '
    'que foi para nivel alto, apagar e verificar nivel baixo. Funciona em qualquer '
    'placa configurada no BoardConfig.',
    space_after=6
)

code_block([
    [KW('from '), TXT('tests_builtin.base '), KW('import '), TXT('BuiltinTest, TestResult')],
    [''],
    [KW('class '), DEF('LedVerificacaoTest'), TXT('(BuiltinTest):')],
    [TXT('    name        = '), STR('"LED da Placa Ativa"')],
    [TXT('    description = '), STR('"Liga e apaga o LED; adapta-se automaticamente ao BoardConfig"')],
    [''],
    [KW('    def '), DEF('_run'), TXT('(self, pal) -> TestResult:')],
    [KW('        from '), TXT('core.board.config '), KW('import '), TXT('get_active_board')],
    [TXT('        cfg  = get_active_board()')],
    [TXT('        port = cfg.led_port')],
    [TXT('        pin  = cfg.led_pin')],
    [''],
    [TXT('        pal.modify_field('), STR('"RCC"'), TXT(', cfg.led_clock_reg, cfg.led_clock_field, '), NUM('1'), TXT(')')],
    [TXT('        orig_moder = pal.read_field(port, '), STR('"MODER"'), TXT(', f'), STR('"MODER{pin}"'), TXT(')')],
    [''],
    [KW('        try'), TXT(':')],
    [TXT('            pal.modify_field(port, '), STR('"MODER"'), TXT(', f'), STR('"MODER{pin}"'), TXT(', '), NUM('0b01'), TXT(')')],
    [TXT('            pal.write_reg(port, '), STR('"BSRR"'), TXT(', '), NUM('1'), TXT(' << pin)            '), CMT('# SET')],
    [TXT('            alto  = pal.read_field(port, '), STR('"ODR"'), TXT(', f'), STR('"ODR{pin}"'), TXT(')')],
    [TXT('            pal.write_reg(port, '), STR('"BSRR"'), TXT(', '), NUM('1'), TXT(' << (pin + '), NUM('16'), TXT('))  '), CMT('# RESET')],
    [TXT('            baixo = pal.read_field(port, '), STR('"ODR"'), TXT(', f'), STR('"ODR{pin}"'), TXT(')')],
    [''],
    [KW('            if '), TXT('alto == '), NUM('1'), KW(' and '), TXT('baixo == '), NUM('0'), TXT(':')],
    [KW('                return '), TXT('self._pass('), STR('f"{port}{pin}: SET=1 RESET=0 OK"'), TXT(')')],
    [KW('            return '), TXT('self._fail(')],
    [TXT('                '), STR('f"SET={alto} RESET={baixo} (esperado 1 e 0)"'), TXT(',')],
    [TXT('                measured=(alto, baixo), expected=('), NUM('1'), TXT(', '), NUM('0'), TXT(')')],
    [TXT('            )')],
    [KW('        finally'), TXT(':')],
    [TXT('            pal.modify_field(port, '), STR('"MODER"'), TXT(', f'), STR('"MODER{pin}"'), TXT(', orig_moder)')],
], caption='LED portavel usando get_active_board()')

h2('8.2 Exemplo: Verificar Configuracao de USART pelo Firmware (Padrao B)')

para(
    'Objetivo: sem modificar nada, checar se o firmware ja configurou a USART2 '
    'com 115200 baud, TX e RX habilitados.',
    space_after=6
)

code_block([
    [KW('from '), TXT('tests_builtin.base '), KW('import '), TXT('BuiltinTest, TestResult')],
    [KW('from '), TXT('instruments.usart '), KW('import '), TXT('UsartInstrument, _baud_divider')],
    [''],
    [KW('class '), DEF('Usart2ConfigCheck'), TXT('(BuiltinTest):')],
    [TXT('    name          = '), STR('"USART2 Config Check"')],
    [TXT('    BAUD_ESPERADO = '), NUM('115200')],
    [TXT('    F_CLK         = '), NUM('16_000_000')],
    [''],
    [KW('    def '), DEF('_run'), TXT('(self, pal) -> TestResult:')],
    [TXT('        u = UsartInstrument('), NUM('2'), TXT(', pal)')],
    [KW('        if not '), TXT('u.is_enabled:')],
    [KW('            return '), TXT('self._fail('), STR('"USART2 nao habilitada (UE=0)"'), TXT(')')],
    [''],
    [TXT('        exp_m, exp_f = _baud_divider(self.BAUD_ESPERADO, self.F_CLK)')],
    [TXT('        got_m = pal.read_field('), STR('"USART2"'), TXT(', '), STR('"BRR"'), TXT(', '), STR('"DIV_Mantissa"'), TXT(')')],
    [TXT('        got_f = pal.read_field('), STR('"USART2"'), TXT(', '), STR('"BRR"'), TXT(', '), STR('"DIV_Fraction"'), TXT(')')],
    [''],
    [KW('        if '), TXT('got_m == exp_m '), KW('and '), TXT('got_f == exp_f:')],
    [KW('            return '), TXT('self._pass('), STR('f"USART2 OK: {self.BAUD_ESPERADO} baud"'), TXT(')')],
    [KW('        return '), TXT('self._fail(')],
    [TXT('            '), STR('f"BRR: mant={got_m}/{exp_m} frac={got_f}/{exp_f}"'), TXT(',')],
    [TXT('            measured=(got_m, got_f), expected=(exp_m, exp_f)')],
    [TXT('        )')],
], caption='USART config check — constantes fixas (Padrao B)')

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 9. COMO INTEGRAR
# ══════════════════════════════════════════════════════════════════════════════
h1('9. Como Integrar seu Teste na Plataforma')

para(
    'Ha tres formas de integrar um teste, dependendo de quantas vezes ele deve '
    'rodar e se faz parte de um produto especifico ou da plataforma geral.',
    space_after=10
)

h2('Forma 1 — Plugin via GUI (Recomendada para testes de produto)')

para(
    'Esta e a forma mais rapida e nao requer nenhuma alteracao no codigo da plataforma. '
    'Ideal quando o teste e especifico para um produto ou cliente.',
    space_after=6
)

table(
    ['Passo', 'Acao'],
    [
        ['1', 'No painel esquerdo, selecione a placa no ComboBox "Projeto"'],
        ['2', 'Clique "Conectar" para conectar ao probe ST-Link'],
        ['3', 'Clique "Carregar Plugin..." no painel esquerdo'],
        ['4', 'Selecione o arquivo .py do seu teste'],
        ['5', 'O nome do teste aparece na lista "Plugins" no painel esquerdo'],
        ['6', 'Clique "Executar Suite" — seu teste roda junto com os embutidos'],
        ['7', 'Clique "Exportar..." para salvar os resultados em JSON ou CSV'],
        ['8', 'O arquivo exportado inclui o campo "project_code" do BoardConfig'],
    ],
    widths=[1.5, 14.5]
)

box(
    'O project_code aparece automaticamente no titulo da janela e no arquivo exportado.\n'
    'Isso permite saber exatamente qual configuracao de placa gerou cada resultado.\n'
    'Exemplo: "Bring-up 2180.0720.00 — NUCLEO-F446RE"',
    fill='E8F4F8',
    title='  Rastreabilidade automatica',
    title_color=AZUL_MEDIO
)

h2('Forma 2 — Suite Embutida (Para testes que sempre devem rodar)')

para(
    'Use esta forma quando o teste faz parte do processo padrao de verificacao '
    'e deve rodar automaticamente em toda execucao da plataforma.',
    space_after=6
)

code_block([
    [CMT('# src/tests_builtin/__init__.py')],
    [KW('from '), TXT('tests_builtin.meu_teste '), KW('import '), TXT('MeuTeste')],
    [''],
    [TXT('STANDARD_SUITE: tuple[BuiltinTest, ...] = (')],
    [TXT('    DeviceIdTest(),')],
    [TXT('    ClockTest(),')],
    [TXT('    SRAMTest(),')],
    [TXT('    LedTest(),')],
    [TXT('    ButtonTest(),')],
    [TXT('    UsartLoopbackTest(),')],
    [TXT('    SpiLoopbackTest(),')],
    [TXT('    MeuTeste(),    '), CMT('# <- seu teste aqui')],
    [TXT(')')],
    [''],
    [CMT('# Ou use build_suite(cfg) para testes unitarios com placa explicita:')],
    [KW('from '), TXT('tests_builtin '), KW('import '), TXT('build_suite')],
    [KW('from '), TXT('boards.nucleo_f446re '), KW('import '), TXT('BOARD')],
    [TXT('suite = build_suite(BOARD)     '), CMT('# todos os testes com cfg injetado')],
], caption='src/tests_builtin/__init__.py')

h2('Forma 3 — CLI para Automacao (CI/CD)')

code_block([
    [TXT('$env:PYTHONPATH = '), STR('"src"')],
    [TXT('.venv\\Scripts\\python.exe src/app/cli/main.py run --json > resultado.json')],
    [''],
    [CMT('# Verificar resultado (inclui project_code e board):')],
    [TXT('.venv\\Scripts\\python.exe -c "'), TXT('')],
    [TXT('import json, sys')],
    [TXT('data = json.load(open(\'resultado.json\'))')],
    [TXT('print(data[\'project_code\'], data[\'board\'])')],
    [TXT('falhas = [r for r in data[\'results\'] if r[\'status\'] != \'PASS\']')],
    [KW('if '), TXT('falhas:')],
    [TXT('    sys.exit('), NUM('1'), TXT(')')],
    [TXT('"')],
], caption='Automacao via CLI com rastreamento de project_code')

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 10. PYTEST — GUIA COMPLETO
# ══════════════════════════════════════════════════════════════════════════════
h1('10. pytest — Guia Completo')

para(
    'pytest e o framework de testes unitarios do projeto. Ele testa o CODIGO '
    'DA PLATAFORMA em si — nao o hardware. Os testes em tests/ verificam se o '
    'PAL, os BuiltinTest, o runner e a GUI se comportam corretamente, usando '
    'FakeMemory (sem placa fisica).',
    space_after=8
)

h2('10.1 Metodologia — TDD')

para(
    'A metodologia seguida e Test-Driven Development (TDD). Antes de conectar a '
    'placa, o teste pytest deve: (1) passar com FakeMemory configurada com valores '
    'corretos e (2) falhar com valores errados. Se ambos funcionam, a logica esta '
    'certa. O hardware so entra depois.',
    space_after=6
)

code(
    '  Voce escreve MeuTeste          Voce escreve test_meu_teste.py\n'
    '  (BuiltinTest)                  (pytest)\n'
    '        |                               |\n'
    '        v                               v\n'
    '  Roda na GUI/CLI           Roda com: pytest tests/unit/ -v\n'
    '  com hardware real         com FakeMemory — sem hardware'
)

h2('10.2 Como o pytest descobre testes')

para(
    'O pytest segue convencoes automaticas — nenhuma configuracao extra e necessaria:',
    space_after=4
)

table(
    ['Convencao', 'Exemplo'],
    [
        ['Arquivos comecam com test_',       'test_builtins.py'],
        ['Classes comecam com Test',          'class TestLed:'],
        ['Funcoes/metodos comecam com test_', 'def test_pass_com_clock_ligado(pal):'],
    ],
    widths=[6, 10]
)

h2('10.3 Fixtures — Injecao de Dependencia')

para(
    'Fixtures preparam recursos para os testes (FakeMemory, PAL, SVD, conexao '
    'com hardware). O pytest injeta automaticamente pelo nome do parametro.',
    space_after=6
)

code_block([
    [TXT('@pytest.fixture')],
    [KW('def '), DEF('fake_mem'), TXT('():')],
    [KW('    return '), TXT('FakeMemory()              '), CMT('# criado antes de cada teste')],
    [''],
    [TXT('@pytest.fixture')],
    [KW('def '), DEF('pal'), TXT('(fake_mem, svd):   '), CMT('# injeta fake_mem e svd automaticamente')],
    [KW('    return '), TXT('PeripheralAccessLayer(fake_mem, svd)')],
    [''],
    [KW('def '), DEF('test_clock'), TXT('(pal):         '), CMT('# pytest injeta pal (que injeta fake_mem e svd)')],
    [TXT('    pal.modify_field('), STR('"RCC"'), TXT(', '), STR('"AHB1ENR"'), TXT(', '), STR('"GPIOAEN"'), TXT(', '), NUM('1'), TXT(')')],
    [TXT('    assert pal.read_field('), STR('"RCC"'), TXT(', '), STR('"AHB1ENR"'), TXT(', '), STR('"GPIOAEN"'), TXT(') == '), NUM('1')],
], caption='Fixture simples: injecao automatica por nome')

h3('Escopos de fixture')

table(
    ['Escopo', 'Criado / destruido', 'Quando usar'],
    [
        ['function (padrao)', 'A cada teste',              'Estado que nao deve vazar entre testes'],
        ['class',             'Uma vez por classe Test',   'Estado compartilhado entre metodos da classe'],
        ['module',            'Uma vez por arquivo .py',   'SVD parsing (lento, imutavel)'],
        ['session',           'Uma vez por execucao',      'Conexao USB com hardware real'],
    ],
    widths=[3.5, 5, 7.5]
)

code_block([
    [TXT('@pytest.fixture(scope='), STR('"module"'), TXT(')    '), CMT('# SVD parseado 1x por arquivo de teste')],
    [KW('def '), DEF('svd'), TXT('():')],
    [KW('    return '), TXT('parse(Path('), STR('"devices/stm32f446/STM32F446.svd"'), TXT('))')],
    [''],
    [TXT('@pytest.fixture(scope='), STR('"session"'), TXT(')   '), CMT('# ST-Link aberto 1x por sessao inteira')],
    [KW('def '), DEF('stlink_adiv5'), TXT('(request):')],
    [TXT('    adiv5 = StLinkADIv5(target='), STR('"stm32f446retx"'), TXT(', mode='), STR('"halt"'), TXT(')')],
    [TXT('    adiv5._open()')],
    [KW('    yield '), TXT('adiv5          '), CMT('# yield: teardown acontece APOS todos os testes')],
    [TXT('    adiv5._close()    '), CMT('# roda mesmo se os testes falharem')],
], caption='Escopos: module para SVD, session para hardware')

h3('yield — setup e teardown em uma fixture')

code_block([
    [TXT('@pytest.fixture')],
    [KW('def '), DEF('pal_com_clock'), TXT('(pal):')],
    [TXT('    pal.modify_field('), STR('"RCC"'), TXT(', '), STR('"AHB1ENR"'), TXT(', '), STR('"GPIOAEN"'), TXT(', '), NUM('1'), TXT(')  '), CMT('# setup')],
    [KW('    yield '), TXT('pal                                             '), CMT('# teste roda aqui')],
    [TXT('    pal.modify_field('), STR('"RCC"'), TXT(', '), STR('"AHB1ENR"'), TXT(', '), STR('"GPIOAEN"'), TXT(', '), NUM('0'), TXT(')  '), CMT('# teardown (sempre)')],
])

h3('autouse=True — fixture aplicada sem declarar')

code_block([
    [TXT('@pytest.fixture(autouse='), KW('True'), TXT(')')],
    [KW('def '), DEF('_active_board'), TXT('():')],
    [KW('    from '), TXT('boards.nucleo_f446re '), KW('import '), TXT('BOARD')],
    [TXT('    set_active_board(BOARD)   '), CMT('# roda antes de cada teste do modulo')],
    [CMT('                               # sem precisar declarar o parametro')],
])

h3('conftest.py — fixtures compartilhadas entre arquivos')

para(
    'O conftest.py e carregado automaticamente. Fixtures definidas nele ficam '
    'disponiveis para todos os arquivos da mesma pasta e subpastas, sem import:',
    space_after=4
)

code(
    'tests/\n'
    '├── conftest.py              <- fixtures disponiveis em tests/ inteiro\n'
    '│   (probe, probe_raw, probe_jtag)\n'
    '└── hardware/\n'
    '    ├── conftest.py          <- fixtures extras so para tests/hardware/\n'
    '    │   (stlink_adiv5, pal_stlink, hw_url, hw_freq)\n'
    '    └── test_pal_stlink.py  <- usa pal_stlink sem importar conftest'
)

h2('10.4 Marks — Metadados e Controle de Execucao')

h3('@pytest.mark.parametrize — multiplos cenarios em um teste')

para(
    'Evita duplicar codigo para testar a mesma logica com entradas diferentes. '
    'O pytest gera um teste separado (com nome proprio) para cada combinacao:',
    space_after=6
)

code_block([
    [TXT('@pytest.mark.parametrize('), STR('"dev_id, status_esperado"'), TXT(', [')],
    [TXT('    ('), NUM('0x10000421'), TXT(', '), STR('"PASS"'), TXT('),    '), CMT('# F446 correto')],
    [TXT('    ('), NUM('0x10000123'), TXT(', '), STR('"FAIL"'), TXT('),    '), CMT('# chip errado')],
    [TXT('    ('), NUM('0x00000000'), TXT(', '), STR('"FAIL"'), TXT('),    '), CMT('# memoria zerada')],
    [TXT('])')],
    [KW('def '), DEF('test_device_id'), TXT('(pal, fake_mem, dev_id, status_esperado):')],
    [TXT('    fake_mem._mem['), NUM('0xE0042000'), TXT('] = dev_id')],
    [TXT('    result = DeviceIdTest().run(pal)')],
    [TXT('    assert result.status.name == status_esperado')],
    [''],
    [CMT('# Saida:')],
    [CMT('# test_device_id[0x10000421-PASS]  PASSED')],
    [CMT('# test_device_id[0x10000123-FAIL]  PASSED')],
    [CMT('# test_device_id[0x00000000-FAIL]  PASSED')],
], caption='parametrize: 3 cenarios, 3 testes separados')

h3('@pytest.mark.timeout — limite de tempo')

code_block([
    [CMT('# Instalar: .venv\\Scripts\\pip install pytest-timeout')],
    [''],
    [TXT('@pytest.mark.timeout('), NUM('5'), TXT(')   '), CMT('# falha se demorar mais de 5 segundos')],
    [KW('def '), DEF('test_loopback_nao_trava'), TXT('(pal_stlink):')],
    [TXT('    result = UsartLoopbackTest().run(pal_stlink)')],
    [TXT('    assert result.status != TestStatus.ERROR')],
    [''],
    [CMT('# Ou globalmente em pytest.ini:')],
    [CMT('# [pytest]')],
    [CMT('# timeout = 30    ; todos os testes tem limite de 30 s')],
])

h3('@pytest.mark.skip e skipif')

code_block([
    [TXT('@pytest.mark.skip(reason='), STR('"ainda nao implementado"'), TXT(')')],
    [KW('def '), DEF('test_exportar_pdf'), TXT('():  ...')],
    [''],
    [TXT('@pytest.mark.skipif(sys.platform == '), STR('"win32"'), TXT(', reason='), STR('"so Linux"'), TXT(')')],
    [KW('def '), DEF('test_ftdi_url'), TXT('():  ...')],
    [''],
    [CMT('# Mark customizado (registrado em conftest.py):')],
    [TXT('@pytest.mark.hardware')],
    [KW('def '), DEF('test_led_real'), TXT('(pal_stlink):')],
    [TXT('    result = LedTest().run(pal_stlink)')],
    [TXT('    assert result.status == TestStatus.PASS')],
])

h2('10.5 Assertions')

code_block([
    [CMT('# assert puro — o mais comum:')],
    [TXT('assert result.status  == TestStatus.PASS')],
    [TXT('assert result.measured == '), NUM('0x421')],
    [TXT('assert '), STR('"1000"'), KW(' in '), TXT('result.message')],
    [''],
    [CMT('# pytest.raises — verificar excecao:')],
    [KW('def '), DEF('test_sem_placa'), TXT('():')],
    [TXT('    set_active_board('), KW('None'), TXT(')')],
    [KW('    with '), TXT('pytest.raises(RuntimeError, match='), STR('"Nenhuma placa"'), TXT('):')],
    [TXT('        get_active_board()')],
    [''],
    [CMT('# pytest.approx — floats com tolerancia:')],
    [TXT('assert freq_medida == pytest.approx('), NUM('1000.0'), TXT(', rel='), NUM('0.01'), TXT(')')],
    [CMT('                                              # ±1% de tolerancia')],
], caption='As tres formas de assertion mais usadas')

h2('10.6 Testando codigo com threads — Filas')

para(
    'O TestRunnerService executa testes em uma thread separada e emite sinais Qt '
    'com os resultados. Para testar isso sem a GUI, use queue.Queue como ponte '
    'thread-safe: a thread do runner coloca resultados na fila (put) e a thread '
    'do teste retira (get) com timeout — sem race condition, sem sleep, sem polling.',
    space_after=6
)

code_block([
    [KW('import '), TXT('queue')],
    [''],
    [KW('def '), DEF('test_runner_emite_resultado'), TXT('(svd):')],
    [KW('    from '), TXT('app.services.runner '), KW('import '), TXT('TestRunnerService')],
    [KW('    from '), TXT('boards.nucleo_f446re '), KW('import '), TXT('BOARD')],
    [''],
    [TXT('    mem  = FakeMemory({'), NUM('0xE0042000'), TXT(': '), NUM('0x10000421'), TXT('})')],
    [TXT('    pal  = PeripheralAccessLayer(mem, svd)')],
    [TXT('    fila = queue.Queue()')],
    [''],
    [TXT('    svc = TestRunnerService()')],
    [TXT('    svc.result_ready.connect(fila.put)       '), CMT('# sinal Qt -> fila Python')],
    [TXT('    svc.start(pal, BOARD)')],
    [''],
    [TXT('    primeiro = fila.get(timeout='), NUM('5'), TXT(')           '), CMT('# aguarda ate 5 s')],
    [TXT('    assert primeiro.name   == '), STR('"DeviceId"')],
    [TXT('    assert primeiro.status == TestStatus.PASS')],
], caption='queue.Queue como ponte entre thread do runner e thread do teste')

h2('10.7 Linha de comando')

code(
    '$env:PYTHONPATH = "src"\n'
    '\n'
    '# Rodar todos os testes unitarios\n'
    '.venv\\Scripts\\python.exe -m pytest tests/unit/ -v\n'
    '\n'
    '# So os testes cujo nome contem "led"\n'
    '.venv\\Scripts\\python.exe -m pytest tests/unit/ -k "led" -v\n'
    '\n'
    '# Parar no primeiro erro\n'
    '.venv\\Scripts\\python.exe -m pytest tests/unit/ -x\n'
    '\n'
    '# Mostrar os 5 testes mais lentos\n'
    '.venv\\Scripts\\python.exe -m pytest tests/unit/ --durations=5\n'
    '\n'
    '# Com hardware ST-Link (opcao customizada do projeto)\n'
    '.venv\\Scripts\\python.exe -m pytest tests/hardware/ --stlink -v\n'
    '\n'
    '# So testes sem hardware\n'
    '.venv\\Scripts\\python.exe -m pytest tests/ -m "not hardware"'
)

h2('10.8 As duas camadas no projeto')

table(
    ['Pasta', 'Usa hardware?', 'Scope tipico', 'O que testa'],
    [
        ['tests/unit/',     'Nao — FakeMemory',    'function / module', 'Logica dos BuiltinTest, PAL, runner, GUI'],
        ['tests/hardware/', 'Sim — ST-Link / FT2232H', 'session',       'Comportamento real em registradores do STM32'],
    ],
    widths=[4, 4, 3.5, 4.5]
)

box(
    'Sem --stlink ou --hw-url, os testes de hardware sao pulados automaticamente\n'
    'pelo conftest.py via pytest_collection_modifyitems. Isso permite rodar\n'
    'pytest tests/ -v em qualquer maquina sem hardware conectado.',
    fill='E8F4F8',
    title='  Skip automatico sem hardware',
    title_color=AZUL_MEDIO
)

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 11. TDD
# ══════════════════════════════════════════════════════════════════════════════
h1('11. Desenvolvendo Sem Hardware (TDD)')

para(
    'Voce nao precisa ter a placa conectada para desenvolver e testar seu teste. '
    'A plataforma permite substituir o hardware real por uma memoria falsa em Python '
    '(FakeMemory) que armazena os valores em um dicionario.',
    space_after=6
)
bullet('Desenvolver o teste no notebook, sem a placa')
bullet('Verificar se a logica de pass/fail esta correta')
bullet('Simular falhas (escrever valores errados e ver se o teste detecta)')
bullet('Rodar automaticamente em CI sem hardware')

doc.add_paragraph()
para('Crie o arquivo  tests/unit/test_meu_teste.py:')

code_block([
    [KW('from '), TXT('pathlib '), KW('import '), TXT('Path')],
    [KW('import '), TXT('pytest')],
    [KW('from '), TXT('core.board.config '), KW('import '), TXT('set_active_board')],
    [KW('from '), TXT('core.pal.access '), KW('import '), TXT('PeripheralAccessLayer')],
    [KW('from '), TXT('core.svd.parser '), KW('import '), TXT('parse')],
    [''],
    [KW('class '), DEF('FakeMemory'), TXT(':')],
    [KW('    def '), DEF('__init__'), TXT('(self): self._mem = {}')],
    [KW('    def '), DEF('read_mem32'), TXT('(self, addr): '), KW('return '), TXT('self._mem.get(addr & ~'), NUM('3'), TXT(', '), NUM('0'), TXT(')')],
    [KW('    def '), DEF('write_mem32'), TXT('(self, addr, value): self._mem[addr & ~'), NUM('3'), TXT('] = value & '), NUM('0xFFFFFFFF')],
    [''],
    [CMT('# Fixture obrigatoria para testes que usam get_active_board()')],
    [TXT('@pytest.fixture(autouse='), KW('True'), TXT(')')],
    [KW('def '), DEF('board'), TXT('():')],
    [KW('    from '), TXT('boards.nucleo_f446re '), KW('import '), TXT('BOARD')],
    [TXT('    set_active_board(BOARD)')],
    [''],
    [TXT('@pytest.fixture')],
    [KW('def '), DEF('pal'), TXT('():')],
    [TXT('    svd = parse(Path('), STR('"devices/stm32f446/STM32F446.svd"'), TXT('))')],
    [KW('    return '), TXT('PeripheralAccessLayer(FakeMemory(), svd)')],
    [''],
    [KW('def '), DEF('test_led_passa'), TXT('(pal):')],
    [TXT('    pal.modify_field('), STR('"RCC"'), TXT(', '), STR('"AHB1ENR"'), TXT(', '), STR('"GPIOAEN"'), TXT(', '), NUM('1'), TXT(')')],
    [KW('    from '), TXT('meu_teste '), KW('import '), TXT('LedVerificacaoTest')],
    [KW('    from '), TXT('tests_builtin.base '), KW('import '), TXT('TestStatus')],
    [TXT('    result = LedVerificacaoTest().run(pal)')],
    [CMT('    # Pode passar ou falhar dependendo do FakeMemory')],
    [TXT('    assert result.status ', ), KW('in'), TXT(' (TestStatus.PASS, TestStatus.FAIL)')],
], caption='tests/unit/test_meu_teste.py')

para('Para rodar os testes unitarios:')
code(
    '$env:PYTHONPATH = "src"\n'
    '.venv\\Scripts\\python.exe -m pytest tests/unit/ -v'
)

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 12. ERROS COMUNS
# ══════════════════════════════════════════════════════════════════════════════
h1('12. Erros Comuns e Como Resolver')

table(
    ['Sintoma', 'Causa Provavel', 'Solucao'],
    [
        [
            'RuntimeError: Nenhuma placa configurada',
            'get_active_board() chamado sem selecionar placa na GUI',
            'Selecione uma placa no ComboBox "Projeto" antes de conectar; '
            'em testes unitarios, use set_active_board(BOARD) via fixture autouse'
        ],
        [
            'KeyError: Campo X',
            'Nome de periferico, registrador ou campo incorreto',
            'Consulte o SVD com o comando Python da secao 6.1'
        ],
        [
            'read_field() sempre retorna 0',
            'Clock do periferico nao habilitado',
            'Adicione pal.modify_field("RCC", "AHBxENR", "XXXEN", 1) antes de acessar'
        ],
        [
            'Timeout no receive_byte()',
            'Fio de loopback nao conectado ou pino nao como AF',
            'Verifique a conexao fisica e confirme MODER=10 e AF correto'
        ],
        [
            'Teste passa mas o proximo falha',
            'O teste anterior nao restaurou o estado dos pinos',
            'Use try/finally e salve/restaure todos os campos que modifica'
        ],
        [
            'Teste nao aparece apos "Carregar Plugin"',
            'Classe nao herda de BuiltinTest ou e abstrata',
            'Verifique: class MeuTeste(BuiltinTest) e que _run() esta implementado'
        ],
    ],
    widths=[4.5, 4.5, 7]
)

doc.add_page_break()


# ══════════════════════════════════════════════════════════════════════════════
# 12. CHECKLIST
# ══════════════════════════════════════════════════════════════════════════════
h1('13. Checklist Final — Antes de Executar no Hardware')

para('Antes de conectar a placa e rodar o teste, confirme cada item:', space_after=10)

items = [
    ('Estrutura basica', [
        'A classe herda de BuiltinTest',
        'Os atributos "name" e "description" estao definidos',
        'O metodo "_run(self, pal)" esta implementado (com underscore)',
        'Todo caminho de execucao retorna self._pass(), self._fail() ou self._skip()',
    ]),
    ('Boas praticas', [
        'O estado original dos registradores e salvo antes de qualquer alteracao',
        'O bloco finally restaura os registradores modificados',
        'O clock do periferico e habilitado via RCC antes de usar',
        'Todos os loops de espera tem timeout com time.perf_counter()',
    ]),
    ('Portabilidade', [
        'Pinos/clocks lidos de get_active_board() em testes de hardware (Padrao A)',
        'Constantes de firmware definidas no topo do arquivo (Padrao B)',
        'Teste nao usa enderecos/nomes hardcoded que mudariam ao trocar de placa',
    ]),
    ('Qualidade', [
        'O teste foi testado com FakeMemory (sem hardware) primeiro',
        'Fixture autouse chama set_active_board(BOARD) nos testes unitarios',
        'Os parametros "measured" e "expected" estao preenchidos no _pass/_fail',
    ]),
]

for titulo, subitems in items:
    para(titulo, bold=True, color=AZUL_MEDIO, space_before=8, space_after=2)
    for item in subitems:
        p = doc.add_paragraph(style='List Bullet')
        p.paragraph_format.space_after = Pt(2)
        p.add_run(item).font.size = Pt(11)

doc.add_paragraph()

box(
    'Arquivo de template pronto para copiar: DOC/TEMPLATE_TESTE.py\n'
    'Exemplos funcionais: TESTES_PLATAFORMA/ (IO, UART, SPI, I2C, ADC, etc.)\n'
    'Arquivo de configuracao de placa: src/boards/nucleo_f446re.py\n'
    'Duvidas ou sugestoes: rafael.macedoengenharia@gmail.com',
    fill='E8F4F8',
    title='  Recursos',
    title_color=AZUL_MEDIO
)


# ══════════════════════════════════════════════════════════════════════════════
# Salvar
# ══════════════════════════════════════════════════════════════════════════════
out = 'DOC/GUIA_CRIACAO_DE_TESTES.docx'
doc.save(out)
print(f'Criado: {out}')
