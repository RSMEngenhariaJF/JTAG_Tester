"""Agente de alvo: stubs de RAM executados no MCU, resultados por fila circular."""

from core.agent.agent import IAgentTarget, RingReader, TargetAgent
from core.agent.usart_sweep import StepResult, max_reliable_baud, run_sweep

__all__ = [
    "IAgentTarget",
    "RingReader",
    "StepResult",
    "TargetAgent",
    "max_reliable_baud",
    "run_sweep",
]
