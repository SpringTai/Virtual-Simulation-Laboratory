"""绘图与导出共用物理量描述，缩放仅用于显示。"""
import numpy as np

CURVE_NAMES = {
    "tension": "应力应变", "compression": "应力应变", "torsion": "扭矩转角",
    "bending": "载荷挠度", "shear": "剪应力剪应变", "buckling": "轴压力侧向挠度",
}


def curve_data(result):
    d = result.diagnostics
    xkey, ykey = d.get("plot_x_key", "engineering_strain"), d.get("plot_y_key", "engineering_stress_mpa")
    xs = np.asarray([f.get(xkey, 0.) for f in result.frames], dtype=float) * d.get("plot_x_scale", 100.)
    ys = np.asarray([f.get(ykey, 0.) for f in result.frames], dtype=float) * d.get("plot_y_scale", 1.)
    return xs, ys, d.get("plot_x_label", "工程应变 / %"), d.get("plot_y_label", "工程应力 / MPa")


def plot_range(values):
    lo, hi = min(0., float(np.min(values))), max(0., float(np.max(values)))
    span = hi - lo
    if span < 1e-12:
        return 0., 1.
    return (lo - .05*span if lo < 0 else 0.), (hi + .05*span if hi > 0 else 0.)
