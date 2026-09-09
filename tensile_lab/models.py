from dataclasses import dataclass, asdict, field
from typing import Any

@dataclass
class SimulationConfig:
    material_name: str = "Fe"
    young_mpa: float = 200000.0
    poisson: float = 0.3
    yield_mpa: float = 250.0
    hardening_q_mpa: float = 450.0
    hardening_b: float = 8.0
    damage_onset: float = 0.45
    fracture_energy_n_mm: float = 80.0  # Gf: N/mm (energy per fracture area)
    gauge_length_mm: float = 40.0
    diameter_mm: float = 10.0
    max_strain: float = 0.65
    imperfection: float = 0.01
    mesh_axial: int = 40
    mesh_radial: int = 6
    output_steps: int = 100
    experiment: str = "tension"
    section_shape: str = "circle"
    width_mm: float = 10.0
    height_mm: float = 10.0
    load_factor: float = 1.0
    geometry_preset: str = "standard"
    def to_dict(self):
        return asdict(self)

@dataclass
class SimulationResult:
    config: SimulationConfig
    initial_points: Any
    cells: Any
    frames: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)

# Frame is a dict with these keys:
# step, displacement_mm, force_n, engineering_strain, engineering_stress_mpa,
# stage (Chinese), points_mm (N,2; columns z,r), cell_stress_axial_mpa (M,),
# cell_eq_plastic_strain (M,), cell_damage (M,), cell_active (M,), min_radius_mm.
# cells is (M,4) with nodes in perimeter order; coordinates in mm.
# All results must be computed, never synthesized from a target curve.
# simulate(config, progress_callback=None, cancel_event=None) -> SimulationResult
# progress_callback(frame, progress_fraction, message); progress_fraction in [0,1].
