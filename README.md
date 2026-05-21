# sync — Genesis / I-GEN Surrogate Detector & Validation Workspace

This repository hosts the **Genesis Surrogate** validation workspace for the C3-ICM / LRAI **Project Genesis** research program. It implements and calibrates the **I-GEN** (Inertia-Generation) hard-detector stack used to score grid-telemetry risk in the *Connotative Governance and Zero Trust Architectures* white paper (Part IV).

The repository pairs a surrogate enterprise/grid environment (IAM, telemetry, ticket metadata, adversarial injection harness) with a calibrated detector layer driven by the Sajadi et al. (2022) frequency-response dataset.

## Latest update — Calibrated I-GEN detector

The I-GEN detector weights have been **recalibrated** against the frequency-response heatmap dataset using a grouped-holdout protocol (group = `source_file`) to prevent leakage across simulation traces. The fixed-weight scoring rule is now the production interpretation; the gradient-boosted variant was set aside despite a near-perfect cross-validation AUC because it tracked synthetic-rule artifacts and is harder to audit in deployment.

Key artifacts:

- [`genesis_surrogate/hard_detectors.py`](genesis_surrogate/hard_detectors.py) — `H_DEEP` evaluation and `I_GEN` scoring (uses the calibrated weights and threshold).
- [`genesis_surrogate/calibrated_igen_weights_final.json`](genesis_surrogate/calibrated_igen_weights_final.json) — exported weights, threshold, and holdout metrics.
- [`genesis_surrogate/README_VALIDATION.md`](genesis_surrogate/README_VALIDATION.md) — calibration methodology and leakage diagnostics.

## Validation summary

Grouped holdout (held-out simulation traces, 20% of groups, `random_state=42`):

| Metric | Value |
|---|---|
| Logistic regression (grouped-holdout) ROC AUC | **0.9355** |
| Fixed-weight (grouped-holdout) ROC AUC | **0.8997** |
| Fixed-weight PR AUC | **0.9116** |
| Fixed-weight accuracy | **0.8050** |
| Precision | **0.7799** |
| Recall | **0.8407** |
| F1 | **0.8091** |
| `I_GEN_THRESHOLD` (raw) | **0.190566** |

See [`genesis_surrogate/README_VALIDATION.md`](genesis_surrogate/README_VALIDATION.md) for the full calibration write-up, leakage/duplicate diagnostics, and the production interpretation of the threshold.

## Repository layout

```
.
├── genesis_surrogate/             # I-GEN detector, calibration, IAM + injection harness
│   ├── hard_detectors.py
│   ├── calibrated_igen_weights_final.json
│   ├── weight_calibration.ipynb
│   ├── telemetry_emitter.py
│   ├── iam_role_layer.py
│   ├── adversarial_injection_test.py
│   ├── README.md
│   └── README_VALIDATION.md
├── freq_response_data.zip         # Sajadi et al. (2022) frequency response data
├── freq_response_code.zip
├── heatmap_data.zip               # Calibration dataset for I-GEN weights
├── heatmap_code.zip
└── mech_system_code_data.zip
```

## White paper

The accompanying *Connotative Governance and Zero Trust Architectures* white paper (C3-ICM / LRAI, Project Genesis) is **intentionally frozen** as a citable reference document. White-paper files are not part of this documentation cleanup and should not be edited as part of repository maintenance.

## Citation

Frequency-response simulation data: Sajadi, A. et al. (2022). *Nature Communications* **13**, 2490. [doi:10.1038/s41467-022-30164-3](https://doi.org/10.1038/s41467-022-30164-3).
