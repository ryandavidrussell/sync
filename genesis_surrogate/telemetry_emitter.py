"""
telemetry_emitter.py — Phase 1: Grid Telemetry Surrogate

Reads pre-computed frequency response data from Sajadi et al. (2022)
(freq_response_data.zip) and emits structured telemetry records that
feed the Genesis hard detectors.

Each record maps to the `telemetry_state` field in the Part IV
surrogate architecture table of the whitepaper.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Generator

NOMINAL_FREQ_HZ = 60.0  # North America (use 50.0 for Europe)
DATA_DIR = Path("data/freq_response_data")


@dataclass
class TelemetryRecord:
    """Single timestep telemetry snapshot fed to Genesis hard detectors."""
    t: float                          # Simulation time [s]
    frequency_hz: float               # System frequency [Hz]
    rocof_hz_per_s: float             # Rate of Change of Frequency [Hz/s]
    frequency_nadir_hz: float         # Lowest frequency reached so far [Hz]
    hertz_sec_score: float            # Proxy for kinetic energy induced by disturbance
    inertia_coeffs: List[float]       # M_i per generator
    damping_coeffs: List[float]       # D_i per generator
    generator_technologies: List[str] # "SG", "GFM-droop", "GFM-VSM", "GFL"
    headroom_reserve_pct: float       # Available headroom power reserve [%]
    voltage_pu: float                 # Per-unit voltage (1.0 = nominal)
    thermal_margin_pct: float         # Remaining thermal margin on hottest line [%]
    reserve_margin_pct: float         # Spinning reserve margin [%]
    scenario_id: str                  # Benchmark network + random seed identifier
    network_bus_count: int            # 9, 14, 30, 57, 118, or 300

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


class TelemetryEmitter:
    """
    Replays pre-computed frequency response data as a structured telemetry stream.

    In Phase 1 this reads from CSV/MAT files exported from the Sajadi et al.
    MATLAB simulations. In a live deployment this would connect to a PMU
    (Phasor Measurement Unit) data feed with cryptographic signature verification.
    """

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self._scenarios: List[pd.DataFrame] = []
        self._load_scenarios()

    def _load_scenarios(self):
        """Load all CSV scenario files from the data directory."""
        csv_files = list(self.data_dir.glob("*.csv"))
        if not csv_files:
            print(f"[TelemetryEmitter] No CSV files found in {self.data_dir}.")
            print("  → Falling back to synthetic demonstration data.")
            self._scenarios = [self._generate_synthetic_scenario(bus_count=9)]
            return
        for f in csv_files:
            try:
                self._scenarios.append(pd.read_csv(f))
            except Exception as e:
                print(f"[TelemetryEmitter] Warning: could not load {f}: {e}")

    def _generate_synthetic_scenario(
        self,
        bus_count: int = 9,
        n_generators: int = 3,
        duration_s: float = 5.0,
        dt: float = 0.01,
        disturbance_at: float = 0.5,
        seed: int = 42,
    ) -> pd.DataFrame:
        """
        Generates a synthetic frequency response trace using the second-order
        swing equation model from Sajadi et al. (2022) Eq. (2):

            d2δ/dt2 = M^-1 * (p* - pe - D * dδ/dt)

        Parameters match the 3-generator, 9-bus benchmark (Table 1, base case):
            Mi = [1.59, 0.80, 0.32], Di = [1.53, 1.53, 0.92]
        """
        rng = np.random.default_rng(seed)

        Mi = np.array([1.59, 0.80, 0.32][:n_generators])
        Di = np.array([1.53, 1.53, 0.92][:n_generators])
        tech = ["SG", "GFM-droop", "GFL"][:n_generators]

        timesteps = np.arange(0, duration_s, dt)
        freq = np.full(len(timesteps), NOMINAL_FREQ_HZ)
        rocof = np.zeros(len(timesteps))

        # Simple single-machine equivalent swing equation
        M_eq = float(np.mean(Mi))
        D_eq = float(np.mean(Di))
        omega = 0.0  # frequency deviation [Hz]
        delta = 0.0  # angle deviation [rad]

        records = []
        freq_nadir = NOMINAL_FREQ_HZ

        for i, t in enumerate(timesteps):
            # Apply step disturbance at t = disturbance_at
            p_disturbance = -0.10 if t >= disturbance_at else 0.0

            # Swing equation: d(omega)/dt = (1/M) * (disturbance - D*omega)
            d_omega = (1.0 / M_eq) * (p_disturbance - D_eq * omega)
            omega += d_omega * dt
            delta += omega * dt

            f = NOMINAL_FREQ_HZ + omega
            rocof_val = d_omega
            freq_nadir = min(freq_nadir, f)

            # Synthetic ancillary signals
            headroom = max(0.0, 20.0 - abs(omega) * 50)
            voltage = 1.0 - abs(omega) * 0.02
            thermal = max(0.0, 85.0 - abs(omega) * 200)
            reserve = max(0.0, 15.0 - abs(omega) * 100)
            hz_sec = abs(omega) * M_eq

            records.append({
                "t": round(t, 4),
                "frequency_hz": round(f, 6),
                "rocof_hz_per_s": round(rocof_val, 6),
                "frequency_nadir_hz": round(freq_nadir, 6),
                "hertz_sec_score": round(hz_sec, 6),
                "inertia_coeffs": Mi.tolist(),
                "damping_coeffs": Di.tolist(),
                "generator_technologies": tech,
                "headroom_reserve_pct": round(headroom, 2),
                "voltage_pu": round(voltage, 4),
                "thermal_margin_pct": round(thermal, 2),
                "reserve_margin_pct": round(reserve, 2),
                "scenario_id": f"synthetic_9bus_seed{seed}",
                "network_bus_count": bus_count,
            })

        return pd.DataFrame(records)

    def stream(self, scenario_index: int = 0) -> Generator[TelemetryRecord, None, None]:
        """Yield TelemetryRecord objects one timestep at a time."""
        if scenario_index >= len(self._scenarios):
            raise IndexError(f"scenario_index {scenario_index} out of range")
        df = self._scenarios[scenario_index]
        for _, row in df.iterrows():
            yield TelemetryRecord(
                t=row["t"],
                frequency_hz=row["frequency_hz"],
                rocof_hz_per_s=row["rocof_hz_per_s"],
                frequency_nadir_hz=row["frequency_nadir_hz"],
                hertz_sec_score=row["hertz_sec_score"],
                inertia_coeffs=row["inertia_coeffs"] if isinstance(row["inertia_coeffs"], list)
                               else json.loads(row["inertia_coeffs"]),
                damping_coeffs=row["damping_coeffs"] if isinstance(row["damping_coeffs"], list)
                               else json.loads(row["damping_coeffs"]),
                generator_technologies=row["generator_technologies"] if isinstance(row["generator_technologies"], list)
                                       else json.loads(row["generator_technologies"]),
                headroom_reserve_pct=row["headroom_reserve_pct"],
                voltage_pu=row["voltage_pu"],
                thermal_margin_pct=row["thermal_margin_pct"],
                reserve_margin_pct=row["reserve_margin_pct"],
                scenario_id=row["scenario_id"],
                network_bus_count=int(row["network_bus_count"]),
            )

    def export_scenario_csv(self, scenario_index: int = 0, path: Optional[Path] = None) -> Path:
        """Export a scenario DataFrame to CSV for offline replay."""
        df = self._scenarios[scenario_index]
        out = path or Path(f"data/surrogate_scenario_{scenario_index}.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(f"[TelemetryEmitter] Exported {len(df)} rows to {out}")
        return out


if __name__ == "__main__":
    emitter = TelemetryEmitter()
    out = emitter.export_scenario_csv(0)
    print(f"Sample telemetry record:")
    for i, record in enumerate(emitter.stream(0)):
        if i == 50:
            print(record.to_json())
            break
