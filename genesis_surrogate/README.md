# Genesis Surrogate — Part IV Validation Roadmap

This directory implements the **Enterprise and Grid Surrogate Architecture** described in Part IV of the *Connotative Governance and Zero Trust Architectures* whitepaper (C3-ICM/LRAI, Project Genesis).

It uses the frequency response simulation data from Sajadi et al. (2022), *Nature Communications* 13, 2490 ([doi:10.1038/s41467-022-30164-3](https://doi.org/10.1038/s41467-022-30164-3)) as the grid telemetry engine.

## Directory Structure

```
genesis_surrogate/
├── README.md                    # This file
├── telemetry_emitter.py         # Phase 1: Reads freq_response_data, emits structured telemetry JSON
├── hard_detectors.py            # Phase 2: Evaluates H_DEEP from live or replayed telemetry
├── weight_calibration.ipynb     # Phase 3: Calibrates I_GEN weights (w1-w10) from heatmap_data
├── iam_role_layer.py            # Phase 5: IAM/role hierarchy + tool permission map
└── adversarial_injection_test.py # Phase 4: Simulates prompt injection against grid controls
```

## Setup

```bash
pip install numpy pandas scipy scikit-learn jupyter matplotlib
```

Unzip the repo archives into `data/` before running:
```bash
unzip freq_response_data.zip -d data/freq_response_data/
unzip heatmap_data.zip       -d data/heatmap_data/
```

## Surrogate Layers (Part IV Table)

| Surrogate Layer | Implementation |
|---|---|
| IAM / Role Hierarchy | `iam_role_layer.py` — mock identities, roles, approval powers |
| Verified Policy Repositories | `iam_role_layer.py` — versioned SOPs as ground truth |
| Ticket Metadata | `adversarial_injection_test.py` — source channel, trust zone, verification state |
| Tool/API Permission Maps | `iam_role_layer.py` — permission levels per role/action |
| Grid Telemetry Surrogate | `telemetry_emitter.py` + `hard_detectors.py` |
| Human Review Capacity (H_t) | `hard_detectors.py` — fatigue-aware queue depth tracking |

## Genesis Routing Logic

```
if H_DEEP == True:       → DEEP_PATH  (Sovereign Build Protocol)
elif Z(x) >= θ_MEDIUM:  → MEDIUM_PATH (Inertia Tax Triggered)
else:                   → FAST_PATH  (Public Grid Baseline Load)
```

Where `Z(x) = B_LRAI(x) + λ * I_GEN(x)`
