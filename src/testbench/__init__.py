"""Testbench modular: estímulo → drivers → hardware → monitores → decisões.

    from testbench import ComposedTest, Testbench
    from testbench.gpio import GpioOutputDriver, GpioLatchMonitor
    from testbench.stimulus import Toggle
    from testbench.decision import FollowsDrive

Ver testbench.core para o fluxo de execução.
"""

from testbench.core import (
    ComposedTest,
    Decision,
    Driver,
    Monitor,
    Observation,
    Step,
    Stimulus,
    Testbench,
    Trace,
    Verdict,
)

__all__ = [
    "ComposedTest",
    "Decision",
    "Driver",
    "Monitor",
    "Observation",
    "Step",
    "Stimulus",
    "Testbench",
    "Trace",
    "Verdict",
]
