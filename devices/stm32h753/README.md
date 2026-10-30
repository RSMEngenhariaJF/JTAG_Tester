# STM32H753

| Arquivo | Origem | Licença |
|---|---|---|
| `STM32H753.svd` | STM32CubeIDE 2.2.0 — `plugins/com.st.stm32cube.ide.mcu.productdb.debug_2.2.500/resources/cmsis/STMicroelectronics_CMSIS_SVD/` | Apache-2.0 (cabeçalho preservado no arquivo) |

Usado por `src/boards/nucleo_h753zi.py`.

Os campos de GPIO deste SVD usam os nomes novos (`MODE5`, `OD5`, `ID5`,
`AFSEL8`). O PAL aceita também os nomes do F4 (`MODER5`, `ODR5`, `IDR5`,
`AFRH8`) — ver `_FIELD_ALIASES` em `src/core/svd/model.py`.
