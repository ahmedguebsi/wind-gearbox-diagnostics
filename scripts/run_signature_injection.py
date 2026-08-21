"""Controlled signature-injection tests for ruleset v2 (ADR-050, scoped).

WHAT THIS IS — AND IS NOT. SYNTHETIC TEST SIGNALS — NOT VALID THESIS EVIDENCE
of diagnostic performance (LOCKED-08). Synthetic data cannot manufacture
real-world ground truth; injections are designed to satisfy the signatures
they target, so recovery proves the IMPLEMENTATION, never that real faults
produce these patterns. Per ADR-050 the tests are named controlled
signature-injection tests and answer exactly four questions:

1. SOFTWARE CORRECTNESS — does the intended rule fire when its defining
   conditions exist in realistic carrier noise?
2. STRUCTURAL IDENTIFIABILITY — can the layer distinguish idealised
   bearing-led, oil-led, common-mode and cold-side patterns from each other?
3. SENSITIVITY — at what injected magnitude does each signature class become
   recoverable through the frozen chain?
4. CROSS-TALK — does a single-channel injection incorrectly activate the
   common-mode rule (or a common injection the differential rules)?

Method. Idealised ramps are added to the RAW residuals of the healthy
VALIDATION stream (real autocorrelated carrier noise, in-support by
construction — the healthy-state power floor already applied). Every
statistic — standardization, mode normalization, EWMA limits — is fitted on
the CLEAN TRAINING partition, identical to the frozen ADR-050 chain; the
injection touches only the evaluated stream. One deterministic window per
turbine (start at 30% of its stream; 36-sample linear ramp to amplitude A,
then 108-sample hold; 24 h total), the same window for every class and
amplitude, plus one baseline pass (A = 0) so background episodes at those
windows are measured rather than assumed. Expected mode-space behaviour is
derivable in advance and recorded in the output BEFORE the per-pass results.

Reads STORED ARTIFACTS ONLY. Writes ``evaluation/signature_injection.json``.

Usage (from backend/):
    uv run python ../scripts/run_signature_injection.py --experiment EXP-YYYYMMDD-NNN
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import AppConfig  # noqa: E402
from app.core.versioning import capture_version_stamp  # noqa: E402
from app.data.schema import default_schema  # noqa: E402
from app.fmea.knowledge_base import FmeaKnowledgeBase, default_ruleset_path  # noqa: E402
from app.fmea.modes_v2 import (  # noqa: E402
    MODES_V2_VERSION,
    EpisodeInterpretation,
    ModeStateSeries,
    interpret_modes,
)
from app.residuals.engine import (  # noqa: E402
    NORMALIZED_RESIDUAL_COLUMN,
    RAW_RESIDUAL_COLUMN,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    TURBINE_COLUMN,
    ResidualFrame,
)
from app.residuals.ewma import (  # noqa: E402
    ControlLimitFormulation,
    ControlLimitSpec,
    EwmaDetector,
    GapHandling,
)
from app.residuals.modes import MODE_COMMON, MODE_DIFFERENTIAL, rotate_to_modes  # noqa: E402
from app.residuals.normalization import PartitionRef, SigmaNormalizer, make_normalizer  # noqa: E402

BEARING = "gearbox_bearing_temperature"
OIL = "gearbox_oil_temperature"

RAMP_SAMPLES = 36  # 6 h linear rise
HOLD_SAMPLES = 108  # 18 h hold
WINDOW_SAMPLES = RAMP_SAMPLES + HOLD_SAMPLES
WINDOW_START_FRACTION = 0.3
AMPLITUDES_C = (1.0, 2.0, 4.0, 8.0)

#: class -> (channels injected, sign, intended type, intended top rules)
CLASSES: dict[str, dict[str, Any]] = {
    "bearing_led": {
        "channels": (BEARING,),
        "sign": +1,
        "intended_type": "A_positive_candidate",
        "intended_top_rules": ("FMEA-002",),
    },
    "oil_led": {
        "channels": (OIL,),
        "sign": +1,
        "intended_type": "B_ambiguous_candidates",
        "intended_top_rules": ("FMEA-001", "FMEA-003"),
    },
    "common": {
        "channels": (BEARING, OIL),
        "sign": +1,
        "intended_type": "B_ambiguous_candidates",
        "intended_top_rules": ("FMEA-004",),
    },
    "cold_common": {
        "channels": (BEARING, OIL),
        "sign": -1,
        "intended_type": "C_no_candidate",
        "intended_top_rules": ("",),
    },
}

DESIGNED_EXPECTATIONS = (
    "Derivable in advance from the rotation algebra and recorded here before "
    "the results: a bearing-only ramp moves C and D at EQUAL rates, so 'D "
    "leads C' must emerge purely from D's tighter noise floor (training sd "
    "0.26 vs 1.39) — this is the structural-identifiability question, not an "
    "artefact. An oil-only ramp mirrors it with D negative. An equal joint "
    "ramp moves C only (D untouched, cross-talk check). A joint negative "
    "ramp must land in R5 (cold-side). Small amplitudes are expected to be "
    "unrecoverable: the chain's limits were never designed for 1 degC "
    "signatures under this carrier noise."
)


def _windows(frame: pd.DataFrame) -> dict[str, pd.Index]:
    """One deterministic window of WINDOW_SAMPLES timestamps per turbine."""
    windows: dict[str, pd.Index] = {}
    for turbine, group in frame.groupby(TURBINE_COLUMN):
        stamps = group[TIMESTAMP_COLUMN].drop_duplicates().sort_values().reset_index(drop=True)
        start = int(len(stamps) * WINDOW_START_FRACTION)
        if start + WINDOW_SAMPLES > len(stamps):
            raise SystemExit(f"Validation stream too short for a window on {turbine}")
        windows[str(turbine)] = pd.Index(stamps.iloc[start : start + WINDOW_SAMPLES])
    return windows


def _inject(
    frame: pd.DataFrame,
    windows: dict[str, pd.Index],
    channels: tuple[str, ...],
    amplitude: float,
    sign: int,
) -> pd.DataFrame:
    """Add the ramp-and-hold profile to the raw residuals inside each window."""
    injected = frame.copy()
    profile = np.concatenate(
        [
            np.linspace(0.0, amplitude, RAMP_SAMPLES, endpoint=False),
            np.full(HOLD_SAMPLES, amplitude),
        ]
    )
    for turbine, window in windows.items():
        offset = pd.Series(sign * profile, index=window)
        for channel in channels:
            mask = (
                (injected[TURBINE_COLUMN] == turbine)
                & (injected[TARGET_COLUMN] == channel)
                & (injected[TIMESTAMP_COLUMN].isin(window))
            )
            add = injected.loc[mask, TIMESTAMP_COLUMN].map(offset).to_numpy(dtype=float)
            injected.loc[mask, RAW_RESIDUAL_COLUMN] += add
    injected[NORMALIZED_RESIDUAL_COLUMN] = np.nan
    return injected


def _episodes_for(
    frame: pd.DataFrame,
    standardizer: SigmaNormalizer,
    normalizer: Any,
    detector: EwmaDetector,
    kb: FmeaKnowledgeBase,
    min_samples: int,
) -> list[EpisodeInterpretation]:
    """The frozen ADR-050 chain over one (possibly injected) validation frame."""
    modes, _ = rotate_to_modes(standardizer.transform(ResidualFrame(frame)))
    normalized = normalizer.transform(modes)
    ewma_series, detections = detector.detect(normalized)
    streams: dict[str, dict[str, Any]] = {}
    for detection, series in zip(detections, ewma_series, strict=True):
        streams.setdefault(detection.turbine, {})[detection.target] = (detection, series)
    series_list: list[ModeStateSeries] = []
    for turbine in sorted(streams):
        c_det, c_ewma = streams[turbine][MODE_COMMON]
        d_det, d_ewma = streams[turbine][MODE_DIFFERENTIAL]
        series_list.append(
            ModeStateSeries(
                turbine=turbine,
                timestamps=c_det.timestamps.reset_index(drop=True),
                c_states=c_det.states.to_numpy(dtype=int),
                d_states=d_det.states.to_numpy(dtype=int),
                c_values=c_ewma.values.to_numpy(dtype=float),
                d_values=d_ewma.values.to_numpy(dtype=float),
                # Healthy validation is in-support by construction (the
                # healthy-state power floor already removed sub-floor rows).
                eligible=np.ones(len(c_det.timestamps), dtype=bool),
            )
        )
    return list(interpret_modes(series_list, kb, min_samples).interpretations)


def _overlapping(
    interpretations: list[EpisodeInterpretation], turbine: str, window: pd.Index
) -> list[EpisodeInterpretation]:
    lo, hi = window[0], window[-1]
    return [
        i
        for i in interpretations
        if i.episode.turbine == turbine
        and i.episode.start_utc <= hi
        and i.episode.end_utc >= lo
    ]


def _signature(interp: EpisodeInterpretation) -> tuple[str, str]:
    top = interp.candidates[0].rule_id if interp.candidates else ""
    return (interp.output_type.value, top)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument("--experiment", default=None)
    args = parser.parse_args()

    experiment = args.experiment
    if experiment is None:
        candidates = sorted(p.name for p in args.artifacts.glob("EXP-*") if p.is_dir())
        if not candidates:
            raise SystemExit(f"No experiment directories under {args.artifacts}")
        experiment = candidates[-1]
    directory = args.artifacts / experiment

    config = AppConfig()
    kb = FmeaKnowledgeBase.load(default_ruleset_path())
    min_samples = config.detection.persistence_min_samples

    training = ResidualFrame(pd.read_parquet(directory / "residuals" / "training.parquet"))
    validation = pd.read_parquet(directory / "residuals" / "validation.parquet")

    # Clean-training statistics for the whole run (identical to ADR-050).
    standardizer = SigmaNormalizer()
    standardizer.fit(training, PartitionRef.HEALTHY_TRAINING)
    training_modes, _ = rotate_to_modes(standardizer.transform(training))
    normalizer = make_normalizer(config.residual.normalization)
    normalizer.fit(training_modes, PartitionRef.HEALTHY_TRAINING)
    detector = EwmaDetector(
        config.detection.ewma_lambda,
        ControlLimitSpec(
            sigma_multiplier=config.detection.control_limit_sigma,
            formulation=ControlLimitFormulation(config.detection.control_limit_formulation),
        ),
        gap_handling=GapHandling(config.detection.gap_handling),
    )
    detector.fit_control_limits(training_modes, PartitionRef.HEALTHY_TRAINING)

    windows = _windows(validation)

    # Baseline pass: background episodes at the same windows, measured.
    baseline = _episodes_for(validation, standardizer, normalizer, detector, kb, min_samples)
    background = {
        turbine: [_signature(i) for i in _overlapping(baseline, turbine, window)]
        for turbine, window in windows.items()
    }

    results: list[dict[str, Any]] = []
    for class_name, spec in CLASSES.items():
        for amplitude in AMPLITUDES_C:
            injected = _inject(
                validation, windows, spec["channels"], amplitude, spec["sign"]
            )
            interpretations = _episodes_for(
                injected, standardizer, normalizer, detector, kb, min_samples
            )
            for turbine, window in windows.items():
                overlapping = _overlapping(interpretations, turbine, window)
                signatures = [_signature(i) for i in overlapping]
                intended = [
                    s
                    for s in signatures
                    if s[0] == spec["intended_type"] and s[1] in spec["intended_top_rules"]
                ]
                new_signatures = [s for s in signatures if s not in background[turbine]]
                recovered = bool(intended)
                delay: int | None = None
                if recovered:
                    hits = [
                        i
                        for i in overlapping
                        if _signature(i)[0] == spec["intended_type"]
                        and _signature(i)[1] in spec["intended_top_rules"]
                    ]
                    first = min(h.episode.start_utc for h in hits)
                    delay = int((first - window[0]) / pd.Timedelta(minutes=10))
                cross_talk = sorted(
                    {
                        s[1]
                        for s in new_signatures
                        if s[1] not in spec["intended_top_rules"] and s[1] != ""
                    }
                )
                results.append(
                    {
                        "class": class_name,
                        "amplitude_c": amplitude,
                        "turbine": turbine,
                        "recovered": recovered,
                        "delay_samples_from_window_start": delay,
                        "episode_signatures_in_window": [list(s) for s in signatures],
                        "background_signatures_in_window": [
                            list(s) for s in background[turbine]
                        ],
                        "new_unintended_rules": cross_talk,
                    }
                )

    frame = pd.DataFrame(results)
    recovery_matrix = {
        class_name: {
            f"{amplitude:g}C": int(
                frame[(frame["class"] == class_name) & (frame["amplitude_c"] == amplitude)][
                    "recovered"
                ].sum()
            )
            for amplitude in AMPLITUDES_C
        }
        for class_name in CLASSES
    }
    minimal_amplitude = {
        class_name: next(
            (
                f"{a:g}C"
                for a in AMPLITUDES_C
                if recovery_matrix[class_name][f"{a:g}C"] == len(windows)
            ),
            "not reached on swept grid",
        )
        for class_name in CLASSES
    }
    cross_talk_counts = (
        frame[frame["new_unintended_rules"].map(len) > 0]
        .groupby("class")
        .size()
        .to_dict()
    )

    output = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": experiment,
        "status": (
            "CONTROLLED SIGNATURE-INJECTION TESTS (ADR-050) — synthetic, "
            "structural verification ONLY. NOT diagnostic validation: "
            "injections are designed to satisfy the signatures they target, "
            "so recovery proves the implementation, never that real faults "
            "produce these patterns (LOCKED-08)."
        ),
        "environment": capture_version_stamp(
            schema_version=default_schema().schema_version
        ).model_dump(),
        "design": {
            "modes_version": MODES_V2_VERSION,
            "knowledge_base": kb.ruleset_version,
            "carrier": "healthy VALIDATION residual streams (real noise)",
            "statistics_source": "clean TRAINING only (standardizer, mode normalizer, limits)",
            "window": {
                "per_turbine": 1,
                "start_fraction": WINDOW_START_FRACTION,
                "ramp_samples": RAMP_SAMPLES,
                "hold_samples": HOLD_SAMPLES,
            },
            "amplitudes_c": list(AMPLITUDES_C),
            "classes": {
                name: {
                    "channels": list(spec["channels"]),
                    "sign": spec["sign"],
                    "intended_type": spec["intended_type"],
                    "intended_top_rules": list(spec["intended_top_rules"]),
                }
                for name, spec in CLASSES.items()
            },
            "designed_expectations": DESIGNED_EXPECTATIONS,
        },
        "recovery_matrix_recovered_of_6": recovery_matrix,
        "minimal_fully_recovering_amplitude": minimal_amplitude,
        "injections_with_new_unintended_rules_by_class": cross_talk_counts,
        "per_injection": results,
        "standing_limits": (
            "Perfect recovery would not establish diagnostic accuracy on real "
            "faults: n(maintenance-confirmed) = 0 and synthetic signatures are "
            "designed, not observed. These tests verify software correctness, "
            "structural identifiability, sensitivity and cross-talk — nothing "
            "else (ADR-050)."
        ),
    }
    out_path = directory / "evaluation" / "signature_injection.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    summary_keys = (
        "recovery_matrix_recovered_of_6",
        "minimal_fully_recovering_amplitude",
        "injections_with_new_unintended_rules_by_class",
    )
    print(json.dumps({k: output[k] for k in summary_keys}, indent=2))
    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
