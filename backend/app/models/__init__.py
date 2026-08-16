"""Normal Behaviour Modelling layer (M-15…M-18).

Importing this package registers the complete thesis model set: the
multi-target XGBoost NBM (THESIS, LOCKED-01) and two BASELINE comparators
— multiple linear regression (ADR-002) and multi-task Elastic Net
(ADR-032). Exactly three models, one THESIS and two BASELINE; a fourth
registration requires an ADR (M-17 acceptance 2).

OLS is retained alongside Elastic Net because it is the only reference
with zero hyperparameters, so it contributes nothing to the multiple-
comparison count. Elastic Net separates non-linearity from regularisation
as the explanation for the thesis model's advantage.
"""

from app.models import (  # noqa: F401  (registration side effect)
    baselines,
    elastic_net,
    xgboost_nbm,
)
