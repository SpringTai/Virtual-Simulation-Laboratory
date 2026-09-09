"""课堂材料、试样尺寸与随程序分发的预计算记录。"""
from dataclasses import replace
from pathlib import Path
import sys

from .models import SimulationConfig

EXPERIMENTS = {"tension": "拉伸", "compression": "压缩", "torsion": "扭转",
               "bending": "弯曲", "shear": "剪切", "buckling": "压杆失稳"}
MATERIALS = {
    "Fe": dict(young_mpa=200000., poisson=.3, yield_mpa=250., hardening_q_mpa=450.,
               hardening_b=8., damage_onset=.45, fracture_energy_n_mm=80.),
    "Al": dict(young_mpa=70000., poisson=.33, yield_mpa=120., hardening_q_mpa=180.,
               hardening_b=8., damage_onset=.35, fracture_energy_n_mm=40.),
}
GEOMETRY_PRESETS = {"standard": "标准试样（预计算）", "manual": "手动尺寸"}


def material_key(name):
    return "Al" if name in ("Al", "教学铝合金") else "Fe"


def make_config(experiment="tension", shape="circle", material="Fe", preset="standard"):
    if experiment not in EXPERIMENTS or shape not in ("circle", "rectangle"):
        raise ValueError("实验或截面类型不受支持")
    if material not in MATERIALS:
        raise ValueError("材料请选择 Fe 或 Al")
    c = SimulationConfig(experiment=experiment, section_shape=shape,
                         material_name=material, geometry_preset=preset,
                         **MATERIALS[material])
    if experiment == "compression":
        return replace(c, gauge_length_mm=20., max_strain=.25, imperfection=0.)
    if experiment == "torsion":
        return replace(c, gauge_length_mm=120., width_mm=12., height_mm=8., imperfection=0.)
    if experiment == "bending":
        return replace(c, gauge_length_mm=240., width_mm=12., height_mm=8., imperfection=0.)
    if experiment == "shear":
        return replace(c, gauge_length_mm=20., width_mm=12., height_mm=8., imperfection=0.)
    if experiment == "buckling":
        return replace(c, gauge_length_mm=600., width_mm=12., height_mm=8., imperfection=.001)
    return c


def is_standard_config(config):
    expected = make_config(config.experiment, config.section_shape, material_key(config.material_name))
    actual = replace(config, material_name=material_key(config.material_name), geometry_preset="standard")
    return actual.to_dict() == expected.to_dict()


def example_path(config):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    if not is_standard_config(config):
        return root / "examples" / "manual-no-precomputed-record.npz"
    filename = f"{config.experiment}_{config.section_shape}_{material_key(config.material_name)}.npz"
    return root / "examples" / filename
