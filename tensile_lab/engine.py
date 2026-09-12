"""统一实验入口；各实验明确采用对应的力学模型。"""
import math
from .models import SimulationConfig
from .presets import EXPERIMENTS, MATERIALS, material_key


def validate(config):
    if config.experiment not in EXPERIMENTS:
        raise ValueError("请选择支持的实验")
    if config.section_shape not in ("circle", "rectangle"):
        raise ValueError("请选择圆形或矩形截面")
    if config.material_name not in (*MATERIALS, "教学钢材", "教学铝合金"):
        raise ValueError("材料仅支持 Fe 与 Al")
    for name, value in config.to_dict().items():
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError(f"参数 {name} 必须为有限数")
    for name in ("gauge_length_mm", "diameter_mm", "width_mm", "height_mm", "young_mpa", "yield_mpa"):
        if getattr(config, name) <= 0:
            raise ValueError("材料模量、强度与试样尺寸须为正数")
    if not -.5 < config.poisson < .49:
        raise ValueError("泊松比须处于 −0.5 与 0.49 之间")
    if not .01 <= config.load_factor <= 2:
        raise ValueError("加载比例须处于 0.01 与 2 之间")
    if not 4 <= config.mesh_axial <= 160 or not 2 <= config.mesh_radial <= 24:
        raise ValueError("轴向网格数须为 4～160，截面网格数须为 2～24")
    if not 10 <= config.output_steps <= 1000:
        raise ValueError("输出步数须为 10～1000")


def decorate(result):
    """为旧版拉伸记录提供统一绘图描述，保持其数值不变。"""
    c, d = result.config, result.diagnostics
    if c.experiment in ("tension", "compression"):
        d.setdefault("plot_x_key", "engineering_strain")
        d.setdefault("plot_y_key", "engineering_stress_mpa")
        d.setdefault("plot_x_label", "工程应变 / %")
        d.setdefault("plot_y_label", "工程应力 / MPa")
        d.setdefault("plot_x_scale", 100.)
        d.setdefault("plot_y_scale", 1.)
        d.setdefault("field_label", "轴向应力 / MPa")
        d.setdefault("view_kind", "axisymmetric" if c.section_shape == "circle" else "solid2d")
        d.setdefault("model_name", "轴对称大变形弹塑性有限元")
        d.setdefault("model_note", "圆棒标距段，端面轴向位移加载且径向自由；J2 塑性、Voce 强化与渐进损伤。颈缩由微小中部初始缺陷定位。")
        d.setdefault("metric_specs", [
            dict(label="轴向力", key="force_n", scale=.001, unit="kN", decimals=2),
            dict(label="工程应力", key="engineering_stress_mpa", scale=1, unit="MPa", decimals=1),
            dict(label="工程应变", key="engineering_strain", scale=100, unit="%", decimals=2),
            dict(label="伸长" if c.experiment == "tension" else "端部位移", key="displacement_mm", scale=1, unit="mm", decimals=2)])
    d.setdefault("experiment_name", EXPERIMENTS[c.experiment])
    d.setdefault("material_note", "Fe、Al 为教学用代表参数，不对应经标定的具体牌号或纯元素试验数据。")
    return result


def simulate(config: SimulationConfig, progress_callback=None, cancel_event=None):
    validate(config)
    if config.experiment in ("tension", "compression"):
        from .axial_solver import simulate_axial
        implementation = simulate_axial
    else:
        from .structural_solver import simulate
        implementation = simulate
    try:
        result = decorate(implementation(config, progress_callback, cancel_event))
        from .native_backend import library
        if config.experiment in ('torsion', 'bending', 'buckling'):
            result.diagnostics['compute_backend'] = 'C++ assembly + SciPy solve' if library() is not None else 'Python/NumPy + SciPy'
        elif config.experiment == 'shear':
            result.diagnostics['compute_backend'] = 'Python/NumPy uniform shear'
        elif config.section_shape == 'circle':
            result.diagnostics['compute_backend'] = 'Python/Numba axisymmetric'
        return result
    except Exception as exc:
        partial = getattr(exc, "partial_result", None)
        if partial is not None:
            decorate(partial)
        raise
