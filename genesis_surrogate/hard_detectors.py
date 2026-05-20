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
from typing import List, Deque
from telemetry_emitter import TelemetryRecord

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

    # I_GEN signal weights (w1-w10) — replace after calibration
    WEIGHTS = {
        "rocof_risk":               0.20,  # w1 — highest per Sajadi et al.
        "frequency_deviation":      0.18,  # w2
        "voltage_instability":      0.13,  # w3
        "thermal_margin_violation": 0.10,  # w4
        "reserve_margin_depletion": 0.10,  # w5
        "inertia_deficit":          0.08,  # w6 — lower per Sajadi finding
        "ramp_rate_excess":         0.08,  # w7
        "power_quality_distortion": 0.05,  # w8
        "interconnection_stress":   0.05,  # w9
        "isolation_failure":        0.03,  # w10
        # New detector grounded in Sajadi et al. damping finding:
        "synthetic_damping_failure": 0.10, # w11 (headroom reserve depletion)
    }

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
            "thermal_margin_violation": min(1.0, max(0.0, 1.0 - t.thermal_margin_pct / 100.0)),
            "reserve_margin_depletion": min(1.0, max(0.0, 1.0 - t.reserve_margin_pct / RESERVE_MARGIN_FLOOR_PCT)),
            "inertia_deficit":          min(1.0, max(0.0, 1.0 - min(t.inertia_coeffs) / 1.0)),
            "ramp_rate_excess":         min(1.0, abs(t.rocof_hz_per_s) / RAMP_RATE_MAX_HZ_PER_S2),
            "power_quality_distortion": min(1.0, abs(1.0 - t.voltage_pu) * 5),
            "interconnection_stress":   min(1.0, max(0.0, 1.0 - t.thermal_margin_pct / 50.0)),
            "isolation_failure":        1.0 if all(g == "GFL" for g in t.generator_technologies) else 0.0,
            "synthetic_damping_failure": min(1.0, max(0.0, 1.0 - t.headroom_reserve_pct / 20.0)),
        }
