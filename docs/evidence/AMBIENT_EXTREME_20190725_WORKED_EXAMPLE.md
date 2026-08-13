# Worked example: distinguishing a genuine extreme from a sensor artefact

**Kept on file for Chapter 5's data-quality discussion (author-directed,
2026-08-13).** Illustrates cross-turbine consistency as an artefact-screening
principle, applied to the monitoring period's ambient maximum. Companion to
LIM-018 (no automated artefact screening on predictor channels — this check
was manual).

## The question

The EXP-20260813-001 seasonal-coverage report put the monitoring period's
ambient maximum at **43.99 °C** — 6.4 °C above the training maximum
(37.58 °C). Is that a plausible summer reading or a sensor artefact? The
channel is "Ambient temperature (converter)" (the M-07 mapping's ambient
choice, flagged at approval as reading near the converter cabinet).

## The evidence

The maximum occurred **2019-07-25 16:10 UTC on Kelmarsh 6** — the day of the
UK's then-record July 2019 heatwave (~38.7 °C air-temperature record). Three
independent signatures separate a genuine extreme from an artefact:

**1. Fleet coherence.** At the peak, all six turbines read high
simultaneously, with stable inter-turbine offsets:

| Time (UTC) | K1 | K2 | K3 | K4 | K5 | K6 |
|---|---|---|---|---|---|---|
| 15:50 | 40.16 | 42.28 | 40.42 | 39.79 | 43.40 | 43.64 |
| 16:00 | 40.44 | 42.60 | 41.00 | 40.27 | 43.57 | 43.96 |
| 16:10 | 40.57 | 42.68 | 41.35 | 40.41 | 43.73 | **43.99** |
| 16:20 | 40.40 | 42.85 | 41.31 | 40.30 | 43.76 | 43.95 |
| 16:30 | 40.19 | 42.76 | 41.13 | 40.15 | 43.47 | 43.71 |

The ordering (K5/K6 warmest, K4 coolest) is persistent — siting and sensor
offsets, not noise.

**2. Smooth ramping.** The fleet crossed 40 °C over a 6.5-hour afternoon
spell (12:50 → 19:20), rising and falling with the diurnal cycle. A stuck or
faulted signal produces a step and a plateau (compare the generator_speed
artefact: 269 *identical* −576.6 RPM readings over 39.7 h on a stationary
rotor — ADR-020).

**3. External corroboration.** The date is a documented national record
heatwave day; a converter-cabinet sensor reading a few degrees above the
~38–39 °C air temperature is physically expected. A smaller coherent spell
recurs 2020-07-31 (three turbines, max 42.3 °C).

## The principle

An artefact lives in one channel of one machine; weather lives in every
machine at once. Cross-turbine consistency — same excursion, same time,
stable offsets, smooth ramps — is therefore a discriminating screen for
plausible-but-extreme predictor values that no per-channel range check can
classify. The generator_speed counter-example fails all three signatures:
single machine, identical repeated values, rotor stationary.

## Provenance

Measured 2026-08-13 from the raw Kelmarsh holdings (Zenodo
10.5281/zenodo.5841833, CC-BY-4.0), all 36 turbine-data files, monitoring
period 2019-02-01 → 2021-06-30; 593 of 757,683 monitoring rows (0.078%)
exceed the training maximum, on 10 distinct July–August days; zero fall in
the ADR-017 match window (ambient range there: 4.1–22.2 °C). See LIM-013
(narrowed), LIM-018, ADR-020, ADR-023.
