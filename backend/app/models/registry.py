"""Model registry (M-15): configured name → model class, kind mandatory.

The registry refuses kind-less registrations by construction and refuses a
second model of the same name. A meta-test asserts the registry holds
exactly two models — one THESIS, one BASELINE (ADR-002/ADR-003; M-17
acceptance 2) — so a third comparator cannot appear without an ADR.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ConfigError
from app.models.base import ModelKind, NormalBehaviourModel


@dataclass(frozen=True)
class ModelRegistration:
    name: str
    cls: type[NormalBehaviourModel]
    kind: ModelKind


_REGISTRY: dict[str, ModelRegistration] = {}


def register_model(name: str, cls: type[NormalBehaviourModel], kind: ModelKind) -> None:
    """Register a model class under a config-resolvable name."""
    if name in _REGISTRY:
        raise ConfigError("Model name already registered", name=name)
    _REGISTRY[name] = ModelRegistration(name=name, cls=cls, kind=kind)


def resolve(name: str) -> ModelRegistration:
    if name not in _REGISTRY:
        raise ConfigError("Unknown model name", name=name, known=sorted(_REGISTRY))
    return _REGISTRY[name]


def registered() -> dict[str, ModelRegistration]:
    """A copy of the registry (read-only view for meta-tests and tables)."""
    return dict(_REGISTRY)


def create(name: str, **kwargs: object) -> NormalBehaviourModel:
    """Instantiate a registered model, passing construction kwargs when the
    class accepts them. The baseline takes none by design (ADR-002: nothing
    tunable), so kwargs fall away for it."""
    cls = resolve(name).cls
    try:
        return cls(**kwargs)
    except TypeError:
        return cls()
