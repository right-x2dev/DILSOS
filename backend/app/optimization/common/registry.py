"""Algorithm registry with solver-availability detection."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass

from app.optimization.common.contracts import SchedulingAlgorithm


@dataclass(frozen=True)
class AlgorithmInfo:
    name: str
    problem_types: tuple[str, ...]
    kind: str
    description: str
    requires: tuple[str, ...]
    stochastic: bool
    phase: str
    factory: Callable[[], SchedulingAlgorithm]

    @property
    def available(self) -> bool:
        return all(importlib.util.find_spec(m) is not None for m in self.requires)


_REGISTRY: dict[str, AlgorithmInfo] = {}


def register(
    name: str,
    problem_types: tuple[str, ...],
    kind: str,
    description: str,
    factory: Callable[[], SchedulingAlgorithm],
    requires: tuple[str, ...] = (),
    stochastic: bool = False,
    phase: str = "P1",
) -> None:
    _REGISTRY[name] = AlgorithmInfo(name, problem_types, kind, description, requires, stochastic, phase, factory)


def get(name: str) -> AlgorithmInfo:
    _ensure_loaded()
    if name not in _REGISTRY:
        raise KeyError(name)
    return _REGISTRY[name]


def all_algorithms() -> list[AlgorithmInfo]:
    _ensure_loaded()
    return sorted(_REGISTRY.values(), key=lambda a: (a.problem_types[0], a.phase, a.name))


_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from app.optimization import catalog  # noqa: F401  (registers everything)
