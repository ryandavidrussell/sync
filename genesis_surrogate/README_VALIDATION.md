# I-GEN Detector — Calibration & Validation Notes

This document records how the I-GEN detector weights and threshold in
[`hard_detectors.py`](hard_detectors.py) and
[`calibrated_igen_weights_final.json`](calibrated_igen_weights_final.json)
were calibrated, what leakage/duplicate diagnostics were run, and why the
fixed-weight logistic-regression rule was chosen as the production scoring
function over a higher-AUC gradient-boosting model.

## Calibration method

- **Model class:** logistic regression (L2-regularized) over the eleven
  detector signals emitted by `hard_detectors.py`
  (`rocof_risk`, `frequency_deviation`, `voltage_instability`,
  `thermal_violation`, `reserve_depletion`, `inertia_deficit`,
  `ramp_rate_excess`, `power_quality`, `interconnection_stress`,
  `isolation_failure`, `damping_failure`).
- **Fixed weights:** the trained logistic-regression coefficients are
  exported as a **fixed linear scoring rule** — `I_GEN(x) = w · x`. There is
  no per-deployment retraining; production reads the same weights from
  `calibrated_igen_weights_final.json`.
- **Split:** grouped holdout with `group = source_file`, `test_size = 0.2`,
  `random_state = 42`. Grouping by source simulation trace prevents
  near-neighbor rows from the same trace appearing in both train and test.
- **Threshold:** the raw threshold `I_GEN_THRESHOLD = 0.190566` was derived
  from a normalized cutpoint of `0.2` mapped through the training-score
  min/max range
  (`train_score_min = 0.01051`, `train_score_max = 0.91078`).

## Why fixed-weight logistic regression, not gradient boosting

A `GradientBoostingClassifier` baseline produced **AUC = 1.000 ± 0.000** on
both stratified and grouped cross-validation. We deliberately did **not**
ship it. The reasons:

1. **Interpretability.** A linear `w · x` score lets reviewers and
   operators read off the contribution of each detector signal. The
   detector layer feeds the Genesis routing rule (`H_DEEP`, `Z(x)`), where
   per-signal accountability matters more than headline AUC.
2. **Deployment simplicity.** Eleven floats plus a threshold ship as JSON.
   No model binary, no version-skew risk between training and serving
   environments, no `scikit-learn` version pinning in inference.
3. **Overfit / synthetic-rule artifacts.** The heatmap dataset is
   simulation-derived, and an AUC of exactly 1.000 across folds is a
   strong indicator that the booster recovered the synthetic generator's
   threshold rule rather than the underlying physical risk surface. The
   fixed-weight rule's lower-but-honest AUC degrades more gracefully under
   distribution shift in real telemetry.

## Leakage and duplicate diagnostics

Run prior to calibration on the merged heatmap dataset:

- **Exact duplicates:** none. `df.duplicated().sum() == 0`.
- **Near-identical rows:** none detected within numerical tolerance after
  rounding feature columns to 6 decimals.
- **Target-copy features:** no single feature was equal (or
  bijectively mappable) to the label.
- **Single-feature AUC ceiling:** no individual feature achieved
  `AUC ≥ 0.98` against the label, so no one signal trivially dominates the
  score.
- **Grouped vs. stratified CV:** grouped CV (by `source_file`) produced
  AUC values consistent with stratified CV, indicating the model is not
  relying on trace-level shortcuts.

## Grouped-holdout results

| Metric | Value |
|---|---|
| Logistic regression ROC AUC | **0.9355** |
| Fixed-weight ROC AUC | **0.8997** |
| Fixed-weight PR AUC | **0.9116** |
| Fixed-weight accuracy | **0.8050** |
| Precision | **0.7799** |
| Recall | **0.8407** |
| F1 | **0.8091** |

The ~3.6-point AUC gap between the trained logistic model and the
fixed-weight rule reflects the loss from freezing coefficients across all
deployment contexts; it is the price paid for the interpretability and
simplicity gains above.

## Exported weights and threshold

The values below mirror `calibrated_igen_weights_final.json` and are the
ones loaded into `hard_detectors.py`:

```python
WEIGHTS = {
    "rocof_risk":            0.1336,
    "frequency_deviation":   0.0588,
    "voltage_instability":   0.0014,
    "thermal_violation":     0.0044,
    "reserve_depletion":     0.6242,
    "inertia_deficit":       0.0038,
    "ramp_rate_excess":      0.0525,
    "power_quality":         0.0014,
    "interconnection_stress":0.0082,
    "isolation_failure":     0.0000,
    "damping_failure":       0.1117,
}

I_GEN_THRESHOLD = 0.190566   # raw threshold; normalized cutpoint = 0.20
```

## Production interpretation

The fixed-weight score `I_GEN(x) = w · x` should be read as an
**interpretable risk score** in `[train_score_min, train_score_max]`
≈ `[0.011, 0.911]`, not a calibrated probability. The cutpoint at
`I_GEN_THRESHOLD = 0.190566` is intentionally **recall-favoring**:

- Recall **0.8407** — most genuinely risky telemetry windows are flagged.
- Precision **0.7799** — false-positive rate is held to a level
  compatible with the downstream Genesis routing
  (`MEDIUM_PATH` / `DEEP_PATH`), where flagged events incur additional
  review rather than hard blocks.
- The dominant weights (`reserve_depletion` 0.6242,
  `rocof_risk` 0.1336, `damping_failure` 0.1117) align with the physical
  failure modes the white paper identifies as inertia-driven precursors,
  giving the score a defensible mechanistic reading.

Operators tuning for a higher-precision regime should raise the threshold
above 0.19; tuning for higher recall should lower it. Re-deriving the
weights themselves requires re-running
[`weight_calibration.ipynb`](weight_calibration.ipynb) against an updated
heatmap dataset with the same grouped-holdout protocol.
