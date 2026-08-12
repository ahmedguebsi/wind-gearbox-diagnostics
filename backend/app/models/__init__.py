"""Normal Behaviour Modelling layer (M-15…M-18).

Importing this package registers the complete thesis model set: the
multi-target XGBoost NBM (THESIS, LOCKED-01) and the multiple linear
regression comparator (BASELINE, ADR-002). Exactly two models — a third
registration requires an ADR (M-17 acceptance 2).
"""

from app.models import baselines, xgboost_nbm  # noqa: F401  (registration side effect)
