"""Axisymmetric tensile finite elements for the teaching laboratory.

Units: mm, N, MPa.  The explicit integration uses a numerical density of one;
its time coordinate is a pseudo-time, not a prediction of strain-rate effects.

Four-node quadrilaterals, 2x2 Gauss integration and an element-averaged
volumetric logarithmic strain are used.  The constitutive update is a
multiplicative elastic predictor / logarithmic principal-strain J2 return with
Voce hardening.  Damage acts on the complete Kirchhoff stress.  Its post-onset
plastic displacement uses the initial axial element length, appropriate to the
predominantly transverse failure band in this particular tensile experiment.

This is an educational implementation, not a calibrated fracture predictor.
"""

from __future__ import annotations

import math
import time
from typing import Callable

import numpy as np
from numba import njit

from .models import SimulationConfig, SimulationResult


class SimulationCancelled(RuntimeError):
    """Cancellation preserving the last successfully assembled output frames."""


class SimulationNumericalError(RuntimeError):
    """Numerical termination with a ``partial_result`` attached by simulate."""


def validate_config(c: SimulationConfig) -> None:
    vals = c.to_dict()
    for key, value in vals.items():
        if isinstance(value, (float, int)) and not math.isfinite(value):
            raise ValueError(f"参数 {key} 必须是有限数值。")
    if c.young_mpa <= 0 or c.yield_mpa <= 0 or c.yield_mpa >= c.young_mpa * .1:
        raise ValueError("弹性模量和屈服强度须为正，且屈服强度应小于弹性模量的 10%。")
    if not -.5 < c.poisson < .49:
        raise ValueError("泊松比须处于 −0.5 与 0.49 之间。")
    if c.hardening_q_mpa < 0 or c.hardening_b <= 0:
        raise ValueError("强化幅值不能为负，强化速率须为正。")
    if c.damage_onset <= 0 or c.fracture_energy_n_mm <= 0:
        raise ValueError("损伤起始塑性应变和断裂能须为正。")
    if c.gauge_length_mm <= 0 or c.diameter_mm <= 0:
        raise ValueError("标距和直径须为正。")
    if not 0 < c.max_strain <= 2.0:
        raise ValueError("首版最大工程应变须处于 0 与 2 之间。")
    if getattr(c, "experiment", "tension") == "compression" and c.max_strain >= .8:
        raise ValueError("压缩缩短比例须小于 80%，防止试样长度趋近于零。")
    if not 0 <= c.imperfection <= .10:
        raise ValueError("中部初始半径缺陷须处于 0 与 10% 之间。")
    if not 4 <= c.mesh_axial <= 160 or not 2 <= c.mesh_radial <= 24:
        raise ValueError("轴向网格数须为 4～160，径向网格数须为 2～24。")
    if not 10 <= c.output_steps <= 1000:
        raise ValueError("输出步数须为 10～1000。")


def axial_metadata(c, view_kind="axisymmetric", model_name=None, model_note=None):
    compression = getattr(c, "experiment", "tension") == "compression"
    return {
        "model_name": model_name or "圆棒轴对称大变形弹塑性有限元",
        "model_note": model_note or ("端面轴向位移一致、径向自由；忽略夹具摩擦和整体屈曲；压缩不启用拉伸损伤。" if compression else "四节点轴对称单元，J2 塑性、Voce 强化与渐进拉伸损伤。"),
        "view_kind": view_kind,
        "field_key": "cell_stress_axial_mpa",
        "field_label": "轴向应力 / MPa",
        "plot_x_key": "engineering_strain",
        "plot_y_key": "engineering_stress_mpa",
        "plot_x_label": "工程应变 / %",
        "plot_y_label": "工程应力 / MPa",
        "plot_x_scale": 100., "plot_y_scale": 1.,
        "experiment": "compression" if compression else "tension",
        "section_shape": getattr(c, "section_shape", "circle"),
        "metric_specs": [
            {"label": "端部压力" if compression else "端部拉力", "key": "force_n", "scale": .001, "unit": "kN", "decimals": 2},
            {"label": "工程应力", "key": "engineering_stress_mpa", "scale": 1., "unit": "MPa", "decimals": 1},
            {"label": "工程应变", "key": "engineering_strain", "scale": 100., "unit": "%", "decimals": 2},
            {"label": "标距变化", "key": "displacement_mm", "scale": 1., "unit": "mm", "decimals": 2},
        ],
    }


def make_mesh(c: SimulationConfig):
    """Return points (Z,R), counterclockwise cells, and reference quadrature."""
    nz, nr = int(c.mesh_axial), int(c.mesh_radial)
    length, radius = c.gauge_length_mm, c.diameter_mm / 2
    z = np.linspace(0., length, nz + 1)
    # A small, disclosed geometric imperfection selects the neck location.
    outer = radius * (1 - c.imperfection * np.exp(-((z - length/2)/(.12*length))**2))
    points = np.array([(zz, rr) for zz, rout in zip(z, outer)
                       for rr in np.linspace(0., rout, nr+1)], dtype=np.float64)
    cells = np.array([[i*(nr+1)+j, (i+1)*(nr+1)+j,
                       (i+1)*(nr+1)+j+1, i*(nr+1)+j+1]
                      for i in range(nz) for j in range(nr)], dtype=np.int64)
    gp = [-1/math.sqrt(3), 1/math.sqrt(3)]
    shapes, natural = [], []
    for eta in gp:
        for xi in gp:
            shapes.append([.25*(1-xi)*(1-eta), .25*(1+xi)*(1-eta),
                           .25*(1+xi)*(1+eta), .25*(1-xi)*(1+eta)])
            natural.append([[-.25*(1-eta), -.25*(1-xi)],
                            [.25*(1-eta), -.25*(1+xi)],
                            [.25*(1+eta), .25*(1+xi)],
                            [-.25*(1+eta), .25*(1-xi)]])
    shapes = np.asarray(shapes)
    natural = np.asarray(natural)
    grad = np.empty((len(cells), 4, 4, 2))
    hoop = np.empty((len(cells), 4, 4))
    volume = np.empty((len(cells), 4))
    mass = np.zeros(len(points))
    for e, conn in enumerate(cells):
        xy = points[conn]
        for q in range(4):
            jac = xy.T @ natural[q]
            grad[e, q] = natural[q] @ np.linalg.inv(jac)
            rq = shapes[q] @ xy[:, 1]
            hoop[e, q] = shapes[q] / rq
            # Full solid-of-revolution volume: no omitted 2*pi factor.
            volume[e, q] = 2*math.pi*rq*np.linalg.det(jac)
            mass[conn] += shapes[q]*volume[e, q]
    return points, cells, shapes, grad, hoop, volume, mass


@njit(cache=True)
def _material_update(f, fold, be, pold, dold, mu, bulk, sy, qh, bh,
                     onset, energy, char_length, mean_logj):
    """Return new be, p, damage, Kirchhoff stress; matrices exploit symmetry."""
    old_det = fold[0]*fold[3]-fold[1]*fold[2]
    a = (f[0]*fold[3]-f[1]*fold[2])/old_det
    b = (-f[0]*fold[1]+f[1]*fold[0])/old_det
    cc = (f[2]*fold[3]-f[3]*fold[2])/old_det
    dd = (-f[2]*fold[1]+f[3]*fold[0])/old_det
    hh = f[4]/fold[4]
    bzz = a*a*be[0] + 2*a*b*be[1] + b*b*be[2]
    bzr = a*cc*be[0] + (a*dd+b*cc)*be[1] + b*dd*be[2]
    brr = cc*cc*be[0] + 2*cc*dd*be[1] + dd*dd*be[2]
    btt = hh*hh*be[3]
    center = .5*(bzz+brr)
    delta = .5*(bzz-brr)
    radius = math.sqrt(delta*delta+bzr*bzr)
    eig1, eig2 = max(center+radius, 1e-14), max(center-radius, 1e-14)
    h1, h2, h3 = .5*math.log(eig1), .5*math.log(eig2), .5*math.log(max(btt, 1e-14))
    hm = (h1+h2+h3)/3
    d1, d2, d3 = h1-hm, h2-hm, h3-hm
    equivalent = 2*mu*math.sqrt(1.5*(d1*d1+d2*d2+d3*d3))
    flow_old = sy+qh*(1-math.exp(-bh*pold))
    dp = 0.
    if equivalent > flow_old:
        dp = (equivalent-flow_old)/(3*mu+qh*bh*math.exp(-bh*pold))
        for _ in range(6):
            ex = math.exp(-bh*(pold+dp))
            residual = equivalent-3*mu*dp-sy-qh*(1-ex)
            dp += residual/(3*mu+qh*bh*ex)
        dp = max(dp, 0.)
    p = pold+dp
    factor = max(0., 1-3*mu*dp/max(equivalent, 1e-30))
    d1, d2, d3 = d1*factor, d2*factor, d3*factor
    l1, l2, l3 = math.exp(2*(hm+d1)), math.exp(2*(hm+d2)), math.exp(2*(hm+d3))
    newbe = np.empty(4)
    if radius > 1e-14:
        slope = (l1-l2)/(2*radius)
        newbe[0] = .5*(l1+l2)+slope*delta
        newbe[1] = slope*bzr
        newbe[2] = .5*(l1+l2)-slope*delta
    else:
        newbe[0], newbe[1], newbe[2] = l1, 0., l2
    newbe[3] = l3
    damage = dold
    if p > onset:
        flow_at_onset = sy+qh*(1-math.exp(-bh*onset))
        flow_now = sy+qh*(1-math.exp(-bh*p))
        u = char_length*(p-onset)
        uf = 2*energy/flow_at_onset
        # Linear effective traction versus accumulated plastic displacement.
        damage = max(dold, 1-(flow_at_onset/flow_now)*max(0., 1-u/uf))
        damage = min(1., damage)
    tau = np.empty(4)
    pressure = bulk*mean_logj
    t1, t2, t3 = 2*mu*d1, 2*mu*d2, 2*mu*d3
    if radius > 1e-14:
        slope = (t1-t2)/(2*radius)
        tau[0] = .5*(t1+t2)+slope*delta+pressure
        tau[1] = slope*bzr
        tau[2] = .5*(t1+t2)-slope*delta+pressure
    else:
        tau[0], tau[1], tau[2] = t1+pressure, 0., t2+pressure
    tau[3] = t3+pressure
    tau *= 1-damage
    return newbe, p, damage, tau


@njit(cache=True)
def _assemble(x, cells, grad, hoop, volume, fold, be, ep, damage,
              old_pstress, axial, work, material, char_length):
    ne = len(cells)
    internal = np.zeros_like(x)
    mu, bulk, sy, qh, bh, onset, energy = material
    bad = -1
    for e in range(ne):
        fs = np.zeros((4, 5))
        meanlogj, vtotal = 0., 0.
        active = False
        for q in range(4):
            if damage[e, q] < 1.:
                active = True
            for a in range(4):
                n = cells[e, a]
                fs[q, 0] += x[n, 0]*grad[e, q, a, 0]
                fs[q, 1] += x[n, 0]*grad[e, q, a, 1]
                fs[q, 2] += x[n, 1]*grad[e, q, a, 0]
                fs[q, 3] += x[n, 1]*grad[e, q, a, 1]
                fs[q, 4] += x[n, 1]*hoop[e, q, a]
            det = (fs[q, 0]*fs[q, 3]-fs[q, 1]*fs[q, 2])*fs[q, 4]
            if det <= .02 and damage[e, q] < 1.:
                bad = e
            # The volumetric projection must lose the failed quadrature
            # points too; otherwise a crack still couples pressure through
            # nominally stress-free integration points.
            weight = volume[e, q]*(1-damage[e, q])
            meanlogj += math.log(max(det, 1e-12))*weight
            vtotal += weight
        if not active:
            axial[e, :] = 0.
            continue
        meanlogj /= max(vtotal, 1e-20)
        for q in range(4):
            f = fs[q]
            det2 = f[0]*f[3]-f[1]*f[2]
            jac = det2*f[4]
            pstress = np.zeros(5)
            if damage[e, q] < 1. and jac > .02:
                benew, pn, dn, tau = _material_update(
                    f, fold[e, q], be[e, q], ep[e, q], damage[e, q],
                    mu, bulk, sy, qh, bh, onset, energy, char_length, meanlogj)
                be[e, q] = benew
                ep[e, q], damage[e, q] = pn, dn
                pstress[0] = (tau[0]*f[3]-tau[1]*f[1])/det2
                pstress[1] = (-tau[0]*f[2]+tau[1]*f[0])/det2
                pstress[2] = (tau[1]*f[3]-tau[2]*f[1])/det2
                pstress[3] = (-tau[1]*f[2]+tau[2]*f[0])/det2
                pstress[4] = tau[3]/f[4]
                axial[e, q] = tau[0]/jac
            else:
                axial[e, q] = 0.
            dw = 0.
            for j in range(5):
                dw += .5*(pstress[j]+old_pstress[e, q, j])*(f[j]-fold[e, q, j])
            work[e, q] += dw*volume[e, q]
            old_pstress[e, q] = pstress
            fold[e, q] = f
            for a in range(4):
                n = cells[e, a]
                internal[n, 0] += volume[e, q]*(pstress[0]*grad[e, q, a, 0]+pstress[1]*grad[e, q, a, 1])
                internal[n, 1] += volume[e, q]*(pstress[2]*grad[e, q, a, 0]+pstress[3]*grad[e, q, a, 1]+pstress[4]*hoop[e, q, a])
    return internal, bad


@njit(cache=True)
def _smooth_load(t, duration, maximum):
    s = min(max(t/duration, 0.), 1.)
    return maximum*s*s*s*(10-15*s+6*s*s)


@njit(cache=True)
def _advance(nsteps, start_step, dt, duration, maximum, reference, x, velocity,
             acceleration, mass, fixed_z, moving_z, axis_nodes, cells, grad,
             hoop, volume, fold, be, ep, damage, old_pstress, axial, work,
             material, char_length, damping, hold_disp=-1., last_reaction=0.):
    internal = np.zeros_like(x)
    dissipated = 0.
    external = 0.
    for it in range(nsteps):
        index = start_step+it+1
        ti = index*dt
        previous_disp = _smooth_load(ti-dt, duration, maximum)
        disp = _smooth_load(ti, duration, maximum)
        if hold_disp >= 0.:
            previous_disp, disp = hold_disp, hold_disp
        velocity += .5*dt*acceleration
        x += dt*velocity
        for n in fixed_z:
            x[n, 0] = reference[n, 0]
            velocity[n, 0] = 0.
        for n in moving_z:
            x[n, 0] = reference[n, 0]+disp
            velocity[n, 0] = (disp-previous_disp)/dt
        for n in axis_nodes:
            x[n, 1] = 0.
            velocity[n, 1] = 0.
        internal, bad = _assemble(x, cells, grad, hoop, volume, fold, be, ep,
                                 damage, old_pstress, axial, work, material, char_length)
        right_reaction = 0.
        for n in moving_z:
            right_reaction += internal[n, 0]
        external += .5*(last_reaction+right_reaction)*(disp-previous_disp)
        last_reaction = right_reaction
        if bad >= 0:
            return internal, dissipated, bad, index, external
        for n in range(len(x)):
            for j in range(2):
                dissipated += damping*mass[n]*velocity[n, j]**2*dt
                acceleration[n, j] = -internal[n, j]/mass[n]-damping*velocity[n, j]
        for n in fixed_z:
            acceleration[n, 0] = 0.
            dissipated -= damping*mass[n]*velocity[n, 0]**2*dt
        for n in moving_z:
            acceleration[n, 0] = 0.
            dissipated -= damping*mass[n]*velocity[n, 0]**2*dt
        for n in axis_nodes:
            acceleration[n, 1] = 0.
            dissipated -= damping*mass[n]*velocity[n, 1]**2*dt
        velocity += .5*dt*acceleration
    return internal, dissipated, -1, start_step+nsteps, external


def _load_time_fraction(strain_fraction):
    low, high = 0., 1.
    for _ in range(48):
        mid = .5*(low+high)
        if mid**3*(10-15*mid+6*mid**2) < strain_fraction:
            low = mid
        else:
            high = mid
    return .5*(low+high)


def simulate(config: SimulationConfig, progress_callback: Callable | None = None,
             cancel_event=None) -> SimulationResult:
    validate_config(config)
    compression = getattr(config, "experiment", "tension") == "compression"
    direction = -1. if compression else 1.
    view_meta = axial_metadata(config)
    start = time.perf_counter()
    reference, cells, shapes, grad, hoop, volume, mass = make_mesh(config)
    ne, nq = len(cells), 4
    x = reference.copy()
    velocity, acceleration = np.zeros_like(x), np.zeros_like(x)
    fold = np.zeros((ne, nq, 5)); fold[:, :, 0] = 1.; fold[:, :, 3:] = 1.
    be = np.zeros((ne, nq, 4)); be[:, :, 0] = 1.; be[:, :, 2:] = 1.
    ep, damage, axial, work = [np.zeros((ne, nq)) for _ in range(4)]
    old_pstress = np.zeros_like(fold)
    length, radius = config.gauge_length_mm, config.diameter_mm/2
    area = math.pi*radius**2
    fixed_z = np.flatnonzero(reference[:, 0] == 0).astype(np.int64)
    moving_z = np.flatnonzero(reference[:, 0] == length).astype(np.int64)
    axis_nodes = np.flatnonzero(reference[:, 1] == 0).astype(np.int64)
    mu = config.young_mpa/(2*(1+config.poisson))
    bulk = config.young_mpa/(3*(1-2*config.poisson))
    wave = math.sqrt(bulk+4*mu/3)
    min_edge = min(length/config.mesh_axial,
                   radius*(1-config.imperfection)/config.mesh_radial)
    # Duration is measured in axial elastic-wave transit times.  It has no
    # calibrated physical loading-rate interpretation.
    duration = 800*length/wave
    target_dt = .20*min_edge/wave
    total_steps = math.ceil(duration/target_dt)
    dt = duration/total_steps
    damping = .01*wave/length
    material = np.array([mu, bulk, config.yield_mpa, config.hardening_q_mpa,
                         config.hardening_b, math.inf if compression else config.damage_onset,
                         config.fracture_energy_n_mm])
    char_length = length/config.mesh_axial
    result = SimulationResult(config, reference, cells)
    result.diagnostics = dict(view_meta)
    max_force, fracture_strain = 0., None
    kinetic_ratios, imbalance, energy_records = [], [], []
    damping_work, external_work = 0., 0.
    internal = np.zeros_like(x)
    outer_ids = np.arange(config.mesh_radial, len(reference), config.mesh_radial+1)
    peak_step, executed_steps = 0, 0

    def terminate(message, status):
        final = result.frames[-1]
        result.summary = dict(status=status, peak_force_n=direction*max_force,
                              peak_engineering_stress_mpa=direction*max_force/area,
                              strain_at_peak=result.frames[peak_step]["engineering_strain"],
                              fracture_engineering_strain=fracture_strain,
                              final_engineering_strain=final["engineering_strain"],
                              initial_area_mm2=area,
                              final_min_radius_mm=final["min_radius_mm"],
                              fractured=fracture_strain is not None,
                              elapsed_seconds=time.perf_counter()-start)
        result.diagnostics.update(status=status, termination_reason=message,
                                  finite=True, energy_history=energy_records,
                                  solver="轴对称四节点显式有限元；2×2 积分；平均体积对数应变")
        error = SimulationCancelled(message) if status == "cancelled" else SimulationNumericalError(message)
        error.partial_result = result
        raise error

    def append_frame(index, fraction):
        nonlocal max_force, fracture_strain, peak_step
        disp = float(x[moving_z[0], 0]-length)
        right = float(internal[moving_z, 0].sum())
        left = float(-internal[fixed_z, 0].sum())
        force = right
        stress = force/area
        plastic = np.average(ep, axis=1, weights=volume)
        dc = np.average(damage, axis=1, weights=volume)
        active = np.any(damage < 1., axis=1)
        local_stress = np.average(axial, axis=1, weights=volume)
        comparison_force = abs(force) if compression else force
        if comparison_force > max_force:
            max_force, peak_step = comparison_force, len(result.frames)
        attached = np.zeros(len(reference), dtype=bool)
        attached[cells[active].ravel()] = True
        visible_outer = outer_ids[attached[outer_ids]]
        center_radius = float(np.min(x[visible_outer, 1])) if len(visible_outer) else 0.
        # A transverse band without active quadrilaterals truly disconnects
        # the two clamps; it is not a visual hiding operation.
        severed = np.any(~np.any(active.reshape(config.mesh_axial, config.mesh_radial), axis=1))
        if severed and fracture_strain is None:
            fracture_strain = disp/length
        if compression:
            stage = "塑性压缩" if np.max(plastic) > .002 else ("开始压缩屈服" if np.max(plastic) > 1e-7 else "弹性压缩")
        elif severed:
            stage = "断裂后卸载"
        elif np.max(dc) > .001:
            stage = "损伤扩展"
        elif max_force > 0 and force < .985*max_force and np.max(plastic) > .03:
            stage = "颈缩"
        elif np.max(plastic) > .002:
            stage = "塑性强化"
        elif np.max(plastic) > 1e-7:
            stage = "开始屈服"
        else:
            stage = "弹性阶段"
        free_velocity = velocity.copy()
        free_velocity[fixed_z, 0] = 0.
        free_velocity[moving_z, 0] = 0.
        free_velocity[axis_nodes, 1] = 0.
        kinetic = float(.5*np.sum(mass[:, None]*free_velocity**2))
        internal_energy = float(np.sum(work))
        ratio = kinetic/max(abs(internal_energy), 1e-12)
        balance = abs(right-left)/max(abs(force), .01*max_force, 1.)
        if abs(disp/length) > 2*config.yield_mpa/config.young_mpa and not severed:
            kinetic_ratios.append(ratio)
            imbalance.append(balance)
        energy_records.append({"engineering_strain": disp/length,
                               "kinetic_energy_n_mm": kinetic,
                               "internal_work_n_mm": internal_energy,
                               "external_work_n_mm": external_work,
                               "damping_energy_n_mm": damping_work,
                               "kinetic_internal_ratio": ratio,
                               "reaction_imbalance": balance})
        frame = dict(step=len(result.frames), displacement_mm=disp, force_n=force,
                     engineering_strain=disp/length, engineering_stress_mpa=stress,
                     stage=stage, points_mm=x.copy(), cell_stress_axial_mpa=local_stress,
                     cell_eq_plastic_strain=plastic, cell_damage=dc,
                     cell_active=active, min_radius_mm=center_radius,
                     cells=cells, initial_points=reference,
                     reaction_right_n=right, reaction_left_n=left,
                     mean_reaction_n=.5*(right+left),
                     kinetic_energy_n_mm=kinetic, internal_work_n_mm=internal_energy,
                     kinetic_internal_ratio=ratio,
                     shortening_mm=max(0., -disp),
                     view_kind=view_meta["view_kind"], diagnostics=view_meta,
                     pseudo_time=executed_steps*dt)
        result.frames.append(frame)
        if progress_callback:
            progress_callback(frame, fraction, f"{stage} · 工程应变 {disp/length:.1%}")

    append_frame(0, 0.)
    # Dense early samples preserve the elastic segment even in a long test.
    number = int(config.output_steps)
    early_number = max(3, min(20, number//4))
    early_end = min(config.max_strain*.1, 4*config.yield_mpa/config.young_mpa)
    targets = np.r_[np.linspace(0, early_end, early_number+1)[1:],
                    np.linspace(early_end, config.max_strain, number-early_number+1)[1:]]
    output_indices = [max(1, int(round(total_steps*_load_time_fraction(float(v/config.max_strain))))) for v in targets]
    current = 0
    severed_during_step = False
    fracture_transient = []

    def run_steps(count, drive_step, drive_duration, drive_maximum,
                  damping_value, hold=-1.):
        nonlocal internal, damping_work, external_work, executed_steps
        nonlocal severed_during_step
        end_step = drive_step+count
        while drive_step < end_step:
            if cancel_event is not None and cancel_event.is_set():
                terminate("计算已取消，已保留最后有效结果。", "cancelled")
            chunk = min(50 if np.max(damage) > .9 else 250, end_step-drive_step)
            prior_step = drive_step
            internal, ddiss, bad, drive_step, dwork = _advance(
                chunk, drive_step, dt, drive_duration, drive_maximum,
                reference, x, velocity, acceleration, mass, fixed_z,
                moving_z, axis_nodes, cells, grad, hoop, volume, fold, be,
                ep, damage, old_pstress, axial, work, material, char_length,
                damping_value, hold, float(internal[moving_z, 0].sum()))
            executed_steps += drive_step-prior_step
            damping_work += ddiss
            external_work += dwork
            if bad >= 0 or not np.all(np.isfinite(x)):
                terminate(f"单元 {bad} 发生过大畸变，已保留最后有效帧。请减小最大应变或调整网格及损伤参数。", "numerical_stop")
            active_cells = np.any(damage < 1., axis=1)
            severed_during_step = bool(np.any(~np.any(active_cells.reshape(config.mesh_axial, config.mesh_radial), axis=1)))
            if severed_during_step and hold < 0:
                break
        return drive_step

    for target in output_indices:
        target = min(max(target, current+1), total_steps)
        current = run_steps(target-current, current, duration,
                            direction*length*config.max_strain, damping)
        if severed_during_step:
            fracture_strain = float((x[moving_z[0],0]-length)/length)
            break
        append_frame(current, min(.9, abs(x[moving_z[0],0]-length)/(length*config.max_strain)))
    if severed_during_step:
        # Stop the imposed displacement after an actual disconnected band is
        # detected.  A short, more strongly damped hold resolves the released
        # elastic waves.  Every unloading force below is still assembled from
        # the surviving finite elements; no curve clipping or zeroing occurs.
        hold_disp = float(x[moving_z[0], 0]-length)
        relaxation_chunk = max(1, int(round(2.5*length/wave/dt)))
        post_damping = 6*wave/length
        for relaxation in range(16):
            fracture_transient.append(dict(
                pseudo_time=executed_steps*dt,
                engineering_strain=hold_disp/length,
                reaction_right_n=float(internal[moving_z, 0].sum()),
                reaction_left_n=float(-internal[fixed_z, 0].sum())))
            run_steps(relaxation_chunk, 0, duration, 0., post_damping, hold=hold_disp)
            free_ke = float(.5*np.sum(mass[:, None]*velocity**2))
            small_force = max(abs(internal[moving_z, 0].sum()), abs(internal[fixed_z, 0].sum())) < .0005*max_force
            if relaxation >= 3 and small_force and free_ke < 1e-6*max(float(work.sum()),1.):
                break
        append_frame(current, 1.)
    finite = bool(all(np.all(np.isfinite(f["points_mm"])) for f in result.frames))
    dead = np.flatnonzero(~result.frames[-1]["cell_active"])
    dead_z = reference[cells[dead], 0].mean(axis=1) if len(dead) else np.array([])
    result.summary = {
        "status": "completed",
        "peak_force_n": direction*max_force,
        "peak_force_magnitude_n": max_force,
        "peak_engineering_stress_mpa": direction*max_force/area,
        "strain_at_peak": result.frames[peak_step]["engineering_strain"],
        "fracture_engineering_strain": fracture_strain,
        "final_engineering_strain": result.frames[-1]["engineering_strain"],
        "initial_area_mm2": area,
        "final_min_radius_mm": result.frames[-1]["min_radius_mm"],
        "final_force_n": result.frames[-1]["force_n"],
        "failed_element_count": int(len(dead)),
        "fracture_band_initial_z_mm": [float(dead_z.min()), float(dead_z.max())] if len(dead_z) else None,
        "fractured": fracture_strain is not None,
        "elapsed_seconds": time.perf_counter()-start,
    }
    result.diagnostics = {
        **view_meta,
        "status": "completed", "termination_reason": "达到断裂卸载状态。" if fracture_strain is not None else "达到设定最大工程应变。",
        "solver": "轴对称四节点显式有限元；2×2 积分；平均体积对数应变",
        "constitutive_model": "乘法式弹性预测、对数主应变 J2 返回、Voce 强化、渐进损伤",
        "damage_model": "压缩不启用损伤" if compression else "塑性位移线性牵引软化；轴向初始单元长度；全部积分点失效后单元不再传力",
        "numerical_density": 1., "time_is_pseudo_time": True,
        "time_step": dt, "explicit_steps": total_steps,
        "actual_explicit_steps": executed_steps,
        "reference_volume_mm3": float(volume.sum()),
        "max_kinetic_internal_ratio_after_yield_before_fracture": max(kinetic_ratios, default=0.),
        "max_reaction_imbalance_before_fracture": max(imbalance, default=0.),
        "energy_history": energy_records,
        "fracture_transient": fracture_transient,
        "energy_convention": "外功按每个显式步积分加载端反力；动能及阻尼耗散仅计自由自由度。断裂最终点取定应变松弛结果，释放波反力另存 fracture_transient。",
        "min_radius_definition": "仍连接有效单元的外表面节点最小半径；排除完全失效后孤立的节点。",
        "finite": finite,
        "limitations": ["演示参数未经材料试验标定，断裂位置及数值不能用于工程设计。",
                        "标距段端部轴向位移一致、径向自由；未建立夹具接触与过渡圆角。",
                        "网格特征长度缓解软化的网格依赖，但不能保证颈缩及断裂的网格客观性。",
                        "失效积分点应力降至零，失效单元不再承载；显示的断口间隙受单元尺寸影响。",
                        "截面断开后停止加载，并用数值阻尼消除断裂释放的弹性波；卸载帧应变保持不变。",
                        "时间为数值加载时间，材料模型不含应变率效应。"],
        "references": [
            "https://solidmechanics.org/Text/Chapter2_5/Chapter2_5.php",
            "https://docs.software.vt.edu/abaqusv2025/English/SIMACAEMATRefMap/simamat-c-damageevolductile.htm",
            "https://help.autodesk.com/cloudhelp/2026/ENU/NINCAD-SelfTraining/files/GUID-A7A2B970-91D0-4E4B-BE81-F5D6E27DEFA0.htm",
        ],
    }
    return result
