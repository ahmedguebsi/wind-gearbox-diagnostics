# LIMITATIONS.md — Living Register of Threats to Validity

Every known threat to validity discovered during development is recorded here:
data quality issues, small event counts, seasonal coverage shortfalls, sensor
artefacts, evaluation caveats. This file feeds the thesis limitations and
discussion chapters directly (PROJECT.md §1).

Automated producers append entries here as they come online: validation
step-change findings (M-10), seasonal coverage warnings (M-13), EWMA
in-control inflation findings (M-20), small-n constraints and
conclusion-flipping sensitivity parameters (M-27/M-28).

Entry template:

```text
## LIM-NNN — <short title>
Date discovered:    YYYY-MM-DD
Description:        <what the threat is and how it was found>
Affected RQ(s):     RQ1 | RQ2 | RQ3
Mitigation status:  OPEN | MITIGATED (<how>) | ACCEPTED (<why>)
Source:             <module/report/manual>
```

---

*(No entries yet. The register is seeded empty at Phase 0; the first
candidates are expected from the Phase 0.5 dataset census — e.g., the 2016
Kelmarsh status logs have a 100%-missing maintenance-commentary column, and
candidate gearbox events are status-log-derived rather than
maintenance-confirmed.)*
