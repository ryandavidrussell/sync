"""
hard_detectors.py — Phase 2: Genesis Hard Detectors + H_t Human Oversight

Implements H_DEEP from the ZetaScript control law (whitepaper Section 11)
and the I_GEN composite risk index (Section 10).

Also implements H_t (human oversight capacity) as a formally defined
variable — addressing the open weakness noted in the whitepaper.

Genesis routing:
    if H_DEEP:          → DEEP_PATH  (Sovereign Build Protocol)
    elif Z(x) >= θ_MED: → MEDIUM_PATH (Inertia Tax Triggered)
    else:               → FAST_PATH  (Public Grid Baseline Load)
"""

from __future__ import annotations
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Deque, Dict
from telemetry_emitter import TelemetryRecord

# ---------------------------------------------------------------------------
# Calibrated I_GEN weights and threshold (logistic regression, group holdout
# by source_file; see calibrated_igen_weights_final.json).
# ---------------------------------------------------------------------------
WEIGHTS = {
    "rocof_risk": 0.1336,
    "frequency_deviation": 0.0588,
    "voltage_instability": 0.0014,
    "thermal_violation": 0.0044,
    "reserve_depletion": 0.6242,
    "inertia_deficit": 0.0038,
    "ramp_rate_excess": 0.0525,
    "power_quality": 0.0014,
    "interconnection_stress": 0.0082,
    "isolation_failure": 0.0000,
    "damping_failure": 0.1117,
}

I_GEN_THRESHOLD = 0.190566


def compute_igen_score(detector_values: dict) -> float:
    """Sum weight * value across the calibrated detector set.

    Missing or None values are treated as 0.0. Values are coerced to float.
    """
    score = 0.0
    for name, weight in WEIGHTS.items():
        raw = detector_values.get(name)
        if raw is None:
            continue
        score += weight * float(raw)
    return score


def classify_igen_risk(detector_values: dict) -> dict:
    """Classify against the calibrated I_GEN threshold."""
    score = compute_igen_score(detector_values)
    return {
        "igen_score": score,
        "igen_threshold": I_GEN_THRESHOLD,
        "igen_violated": score >= I_GEN_THRESHOLD,
        "margin": score - I_GEN_THRESHOLD,
    }


def explain_igen_score(detector_values: dict) -> dict:
    """Return per-detector contributions sorted by descending contribution."""
    contributions = []
    for name, weight in WEIGHTS.items():
        raw = detector_values.get(name)
        value = 0.0 if raw is None else float(raw)
        contributions.append({
            "detector": name,
            "value": value,
            "weight": weight,
            "contribution": weight * value,
        })
    contributions.sort(key=lambda c: c["contribution"], reverse=True)
    score = sum(c["contribution"] for c in contributions)
    return {
        "contributions": contributions,
        "igen_score": score,
        "igen_threshold": I_GEN_THRESHOLD,
        "igen_violated": score >= I_GEN_THRESHOLD,
        "margin": score - I_GEN_THRESHOLD,
    }

# ---------------------------------------------------------------------------
# Threshold defaults (treat as calibration baselines, not production values)
# Calibrate using weight_calibration.ipynb against heatmap_data corpus.
# ---------------------------------------------------------------------------
ROCOF_THRESHOLD_HZ_PER_S   = 0.5    # IEEE 2800-2022 / NERC BAL-003 informed
FREQ_DEVIATION_BAND_HZ      = 0.5    # ±0.5 Hz from nominal
INERTIA_FLOOR               = 0.10   # Minimum acceptable M_i
DAMPING_RESERVE_FLOOR_PCT   = 5.0    # Headroom below which GFM damping fails
THERMAL_MARGIN_FLOOR_PCT    = 10.0   # Thermal overload threshold
RESERVE_MARGIN_FLOOR_PCT    = 5.0    # Spinning reserve collapse
VOLTAGE_FLOOR_PU            = 0.90   # Voltage stability floor
RAMP_RATE_MAX_HZ_PER_S2     = 0.10   # Ramp rate violation threshold

# H_t thresholds
DEEP_QUEUE_SAFE_FLOOR       = 20     # Max open DEEP events before H_t degrades
ANALYST_REVIEW_SLA_S        = 300    # Target review time per DEEP event [s]
FATIGUE_SHIFT_HOURS         = 8.0    # Analyst shift length before fatigue penalty


@dataclass
class HumanOversightState:
    """
    H_t — Human oversight capacity variable.

    Formally defined to address the open weakness in whitepaper v0.2:
    'H_t appears in G_t but no formula, measurement method, or threshold
    is provided.'

    H_t ∈ [0.0, 1.0] where 1.0 = full capacity, 0.0 = saturated/unsafe.
    When H_t falls below H_FLOOR, the system escalates all actions to
    DEEP_PATH by default (fail-safe posture).
    """
    H_FLOOR: float = 0.25             # Safe floor; below this → auto-deny all DEEP
    analyst_count: int = 2            # Number of available analysts
    shift_start_epoch: float = field(default_factory=time.time)
    deep_queue: Deque[float] = field(default_factory=deque)  # timestamps of open events
    resolved_count: int = 0
    total_review_time_s: float = 0.0

    def open_deep_event(self):
        self.deep_queue.append(time.time())

    def resolve_deep_event(self):
        if self.deep_queue:
            opened_at = self.deep_queue.popleft()
            review_time = time.time() - opened_at
            self.total_review_time_s += review_time
            self.resolved_count += 1

    @property
    def queue_depth(self) -> int:
        return len(self.deep_queue)

    @property
    def mean_review_time_s(self) -> float:
        return self.total_review_time_s / max(1, self.resolved_count)

    @property
    def shift_hours_elapsed(self) -> float:
        return (time.time() - self.shift_start_epoch) / 3600.0

    @property
    def fatigue_factor(self) -> float:
        """Degrades linearly after FATIGUE_SHIFT_HOURS, flooring at 0.5."""
        excess = max(0.0, self.shift_hours_elapsed - FATIGUE_SHIFT_HOURS)
        return max(0.5, 1.0 - (excess / FATIGUE_SHIFT_HOURS))

    def compute(self) -> float:
        """
        H_t = fatigue_factor * (1 - queue_pressure) * sla_compliance

        queue_pressure  = min(1.0, queue_depth / (analyst_count * DEEP_QUEUE_SAFE_FLOOR))
        sla_compliance  = 1.0 if mean_review_time <= SLA, else SLA/mean_review_time
        """
        queue_pressure = min(1.0, self.queue_depth /
                            max(1, self.analyst_count * DEEP_QUEUE_SAFE_FLOOR))
        sla_compliance = min(1.0, ANALYST_REVIEW_SLA_S /
                            max(1.0, self.mean_review_time_s))
        return self.fatigue_factor * (1.0 - queue_pressure) * sla_compliance

    @property
    def is_degraded(self) -> bool:
        return self.compute() < self.H_FLOOR


@dataclass
class GenesisDetectorResult:
    """Output of a single telemetry evaluation pass."""
    timestamp: float
    H_DEEP: bool
    fired_detectors: List[str]
    I_GEN: float             # Composite grid risk index [0, 1]
    Z_score: float           # Full ZetaScript score Z(x) = B_LRAI + λ*I_GEN
    route: str               # FAST_PATH, MEDIUM_PATH, or DEEP_PATH
    H_t: float               # Human oversight capacity at time of evaluation
    H_t_degraded: bool       # True if H_t < H_FLOOR (auto-deny active)


class GenesisHardDetectors:
    """
    Evaluates the Genesis hard detector set H_DEEP from whitepaper Section 11
    and computes the ZetaScript composite score Z(x).

    Weights w1-w10 default to equal weighting; run weight_calibration.ipynb
    to replace with physics-grounded values from the heatmap_data corpus.
    """

    # I_GEN signal weights — calibrated via logistic regression group holdout
    # (see calibrated_igen_weights_final.json / module-level WEIGHTS).
    WEIGHTS = dict(WEIGHTS)

    def __init__(
        self,
        lambda_coupling: float = 0.5,  # λ in Z(x) = B_LRAI + λ*I_GEN
        theta_medium: float = 0.30,
        theta_deep: float = 0.40,      # Calibration baseline from V10 run
        h_state: HumanOversightState = None,
    ):
        self.lambda_coupling = lambda_coupling
        self.theta_medium = theta_medium
        self.theta_deep = theta_deep
        self.h_state = h_state or HumanOversightState()

    def evaluate(self, t: TelemetryRecord, b_lrai: float = 0.0) -> GenesisDetectorResult:
        """
        Full evaluation pass:
        1. Check hard detectors → H_DEEP
        2. Compute I_GEN signal scores
        3. Compute Z(x) = B_LRAI + λ * I_GEN
        4. Determine route
        """
        fired, H_DEEP = self._check_hard_detectors(t)
        i_gen_signals = self._compute_igen_signals(t)
        I_GEN = sum(self.WEIGHTS.get(k, 0) * v for k, v in i_gen_signals.items())
        Z = b_lrai + self.lambda_coupling * I_GEN
        H_t = self.h_state.compute()
        H_t_degraded = self.h_state.is_degraded

        if H_DEEP or H_t_degraded:
            route = "DEEP_PATH"
            if H_t_degraded and not H_DEEP:
                fired.append("H_t_saturation")
        elif Z >= self.theta_deep:
            route = "DEEP_PATH"
        elif Z >= self.theta_medium:
            route = "MEDIUM_PATH"
        else:
            route = "FAST_PATH"

        if route == "DEEP_PATH":
            self.h_state.open_deep_event()

        return GenesisDetectorResult(
            timestamp=t.t,
            H_DEEP=H_DEEP or H_t_degraded,
            fired_detectors=fired,
            I_GEN=round(I_GEN, 4),
            Z_score=round(Z, 4),
            route=route,
            H_t=round(H_t, 4),
            H_t_degraded=H_t_degraded,
        )

    def _check_hard_detectors(self, t: TelemetryRecord):
        fired = []
        if abs(t.rocof_hz_per_s) > ROCOF_THRESHOLD_HZ_PER_S:
            fired.append("ROCOF_limit_breach")
        if abs(t.frequency_hz - 60.0) > FREQ_DEVIATION_BAND_HZ:
            fired.append("frequency_deviation_breach")
        if any(m < INERTIA_FLOOR for m in t.inertia_coeffs):
            fired.append("inertia_deficit")
        if t.headroom_reserve_pct < DAMPING_RESERVE_FLOOR_PCT:
            fired.append("synthetic_damping_failure")  # New: Sajadi-grounded
        if t.thermal_margin_pct < THERMAL_MARGIN_FLOOR_PCT:
            fired.append("thermal_line_overload")
        if t.reserve_margin_pct < RESERVE_MARGIN_FLOOR_PCT:
            fired.append("reserve_margin_collapse")
        if t.voltage_pu < VOLTAGE_FLOOR_PU:
            fired.append("voltage_stability_violation")
        if all(g == "GFL" for g in t.generator_technologies):
            fired.append("isolation_failure")  # GFL-only = no synchronization source
        return fired, len(fired) > 0

    def _compute_igen_signals(self, t: TelemetryRecord) -> dict:
        """Normalize each I_GEN signal to [0, 1]."""
        return {
            "rocof_risk":               min(1.0, abs(t.rocof_hz_per_s) / ROCOF_THRESHOLD_HZ_PER_S),
            "frequency_deviation":      min(1.0, abs(t.frequency_hz - 60.0) / FREQ_DEVIATION_BAND_HZ),
            "voltage_instability":      min(1.0, max(0.0, (1.0 - t.voltage_pu) / 0.10)),
            "thermal_violation":        min(1.0, max(0.0, 1.0 - t.thermal_margin_pct / 100.0)),
            "reserve_depletion":        min(1.0, max(0.0, 1.0 - t.reserve_margin_pct / RESERVE_MARGIN_FLOOR_PCT)),
            "inertia_deficit":          min(1.0, max(0.0, 1.0 - min(t.inertia_coeffs) / 1.0)),
            "ramp_rate_excess":         min(1.0, abs(t.rocof_hz_per_s) / RAMP_RATE_MAX_HZ_PER_S2),
            "power_quality":            min(1.0, abs(1.0 - t.voltage_pu) * 5),
            "interconnection_stress":   min(1.0, max(0.0, 1.0 - t.thermal_margin_pct / 50.0)),
            "isolation_failure":        1.0 if all(g == "GFL" for g in t.generator_technologies) else 0.0,
            "damping_failure":          min(1.0, max(0.0, 1.0 - t.headroom_reserve_pct / 20.0)),
        }
