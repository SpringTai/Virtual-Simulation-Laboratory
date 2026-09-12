"""Axial experiments with explicitly declared section/model assumptions.

Circular specimens use the existing two-dimensional axisymmetric solid.
Rectangular specimens use finite-deformation, two-node axial bar elements.
The latter is a uniaxial-stress reduction with actual rectangular area b*h;
it is not an equivalent-radius or two-dimensional solid approximation.
"""
from __future__ import annotations

import math
import time
from typing import Callable

import numpy as np
from numba import njit

from .models import SimulationConfig, SimulationResult
from .solver import (SimulationCancelled, SimulationNumericalError,
                     axial_metadata, validate_config, _smooth_load,
                     _load_time_fraction)


def simulate_axial(config: SimulationConfig, progress_callback: Callable | None = None,
                   cancel_event=None) -> SimulationResult:
    """Dispatch tension/compression by real section shape."""
    experiment = getattr(config, "experiment", "tension")
    if experiment not in ("tension", "compression"):
        raise ValueError("轴向模块仅支持拉伸与压缩实验。")
    shape = getattr(config, "section_shape", "circle")
    if shape == "circle":
        from .solver import simulate
        return simulate(config, progress_callback, cancel_event)
    if shape != "rectangle":
        raise ValueError("轴向模块支持圆截面或矩形截面。")
    return _simulate_rectangular(config, progress_callback, cancel_event)


@njit(cache=True)
def _uniaxial_update(log_stretch, plastic_axial_old, ep_old, damage_old,
                     young, sy, hard_q, hard_b, onset, fracture_energy,
                     reference_length, damage_enabled):
    """Condensed traction-free uniaxial Hencky plasticity.

tau=E*(log(lambda)-hp); lateral logarithmic strain=-hp/2-nu*tau/E.
The signed plastic axial logarithmic strain hp and equivalent plastic strain
p are separate variables so elastic unloading and compression are retained.
"""
    trial = young*(log_stretch-plastic_axial_old)
    flow = sy+hard_q*(1-math.exp(-hard_b*ep_old))
    dp = 0.
    direction = 1. if trial >= 0 else -1.
    if abs(trial) > flow:
        dp = (abs(trial)-flow)/(young+hard_q*hard_b*math.exp(-hard_b*ep_old))
        for _ in range(6):
            expterm = math.exp(-hard_b*(ep_old+dp))
            residual = abs(trial)-young*dp-sy-hard_q*(1-expterm)
            dp += residual/(young+hard_q*hard_b*expterm)
        dp = max(0., dp)
    plastic_axial = plastic_axial_old+direction*dp
    ep = ep_old+dp
    elastic_log = log_stretch-plastic_axial
    tau = young*elastic_log
    damage = damage_old
    if damage_enabled and ep > onset and tau > 0:
        y0 = sy+hard_q*(1-math.exp(-hard_b*onset))
        yn = sy+hard_q*(1-math.exp(-hard_b*ep))
        plastic_displacement = reference_length*(ep-onset)
        final_displacement = 2*fracture_energy/y0
        damage = min(1., max(damage_old, 1-y0/yn*max(0., 1-plastic_displacement/final_displacement)))
    return plastic_axial, ep, damage, elastic_log, tau


@njit(cache=True)
def _rod_advance(count, drive_step, dt, duration, maximum, hold,
                 x0, x, v, acc, mass, area0, reference_length,
                 plastic_axial, ep, damage, elastic_log, cell_stress,
                 lateral_log, last_element_force, previous_length,
                 work, damping, young, poisson, sy, hard_q, hard_b,
                 onset, energy, damage_enabled, last_reaction):
    internal = np.zeros_like(x)
    extwork, dampwork = 0., 0.
    bad = -1
    for k in range(count):
        index = drive_step+k+1
        previous_u = _smooth_load((index-1)*dt, duration, maximum)
        u = _smooth_load(index*dt, duration, maximum)
        if hold < 1e20:
            previous_u, u = hold, hold
        v += .5*dt*acc
        x += dt*v
        x[0], x[-1] = x0[0], x0[-1]+u
        v[0], v[-1] = 0., (u-previous_u)/dt
        internal[:] = 0.
        for e in range(len(area0)):
            current_length = x[e+1]-x[e]
            stretch = current_length/reference_length[e]
            if stretch <= .02:
                bad = e
                return internal, index, bad, extwork, dampwork
            force = 0.
            if damage[e] < 1.:
                hp, pn, dn, he, tau = _uniaxial_update(
                    math.log(stretch), plastic_axial[e], ep[e], damage[e],
                    young, sy, hard_q, hard_b, onset, energy,
                    reference_length[e], damage_enabled)
                plastic_axial[e], ep[e], damage[e] = hp, pn, dn
                elastic_log[e] = he
                lateral_log[e] = -.5*hp-poisson*he
                jac = math.exp((1-2*poisson)*he)
                cell_stress[e] = tau*(1-dn)/jac
                # Area=A0*exp(2*lateral_log); sigma=effective tau/J.
                # Therefore force=A0*effective tau/stretch exactly.
                force = area0[e]*tau*(1-dn)/stretch
            else:
                cell_stress[e] = 0.
            work[e] += .5*(last_element_force[e]+force)*(current_length-previous_length[e])
            previous_length[e] = current_length
            last_element_force[e] = force
            internal[e] -= force
            internal[e+1] += force
        reaction = internal[-1]
        extwork += .5*(last_reaction+reaction)*(u-previous_u)
        last_reaction = reaction
        for n in range(1, len(x)-1):
            dampwork += damping*mass[n]*v[n]*v[n]*dt
            acc[n] = -internal[n]/mass[n]-damping*v[n]
        acc[0], acc[-1] = 0., 0.
        v += .5*dt*acc
    return internal, drive_step+count, bad, extwork, dampwork


def _simulate_rectangular(config, progress_callback, cancel_event):
    validate_config(config)
    from .native_backend import library, rod_advance
    use_native = library() is not None
    advance_kernel = rod_advance if use_native else _rod_advance
    width = float(getattr(config, "width_mm", 10.))
    height = float(getattr(config, "height_mm", 10.))
    if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
        raise ValueError("矩形宽度和高度须为正的有限数值。")
    compression = getattr(config, "experiment", "tension") == "compression"
    direction = -1. if compression else 1.
    t0 = time.perf_counter()
    ne = int(config.mesh_axial)
    length = config.gauge_length_mm
    nominal_area = width*height
    x0 = np.linspace(0., length, ne+1)
    dx = np.diff(x0)
    center = .5*(x0[:-1]+x0[1:])
    # Both real rectangular dimensions carry the disclosed geometric defect.
    cell_scale0 = 1-config.imperfection*np.exp(-((center-length/2)/(.12*length))**2)
    node_scale0 = 1-config.imperfection*np.exp(-((x0-length/2)/(.12*length))**2)
    width0, height0 = width*cell_scale0, height*cell_scale0
    area0 = width0*height0
    mass = np.zeros(ne+1)
    mass[:-1] += .5*area0*dx
    mass[1:] += .5*area0*dx
    x, v, acc = x0.copy(), np.zeros(ne+1), np.zeros(ne+1)
    hp, ep, damage, he, stress, lateral, force_e, work = [np.zeros(ne) for _ in range(8)]
    old_length = dx.copy()
    reference = np.empty((2*(ne+1), 2))
    reference[0::2, 0] = x0; reference[1::2, 0] = x0
    reference[0::2, 1] = -.5*height*node_scale0
    reference[1::2, 1] = .5*height*node_scale0
    cells = np.array([[2*i, 2*i+2, 2*i+3, 2*i+1] for i in range(ne)], dtype=np.int64)
    note = ("有限变形一维杆单元；矩形面积为宽×高，截面内轴向应力均匀；"
            "侧向尺寸由弹性泊松效应及塑性不可压缩条件计算。"
            "可展示局部变细，但不预测三维颈部应力或断口形貌。")
    if compression:
        note += " 压缩不启用损伤；端部无摩擦、忽略整体屈曲。"
    meta = axial_metadata(config, "solid2d", "矩形截面有限变形一维杆单元", note)
    meta.update(computation_dimension="1D", display_dimension="矩形侧视图",
                compute_backend="C++ ABI 1" if use_native else "Python/Numba",
                section_width_is_out_of_plane=True,
                actual_section_area_formula="width_mm * height_mm")
    result = SimulationResult(config, reference, cells, diagnostics=dict(meta))
    wave = math.sqrt(config.young_mpa)
    duration = 800*length/wave
    nsteps = int(math.ceil(duration/(.2*dx.min()/wave)))
    dt = duration/nsteps
    damping = .01*wave/length
    internal = np.zeros(ne+1)
    external_work, damping_work, executed = 0., 0., 0
    peak_magnitude, peak_frame = 0., 0
    fracture_strain = None
    energy_history, transients = [], []
    kinetic_ratios, balances = [], []

    def summarize(status):
        final = result.frames[-1]
        dead = np.flatnonzero(~final["cell_active"])
        return dict(status=status, peak_force_n=direction*peak_magnitude,
                    peak_force_magnitude_n=peak_magnitude,
                    peak_engineering_stress_mpa=direction*peak_magnitude/nominal_area,
                    strain_at_peak=result.frames[peak_frame]["engineering_strain"],
                    fracture_engineering_strain=fracture_strain,
                    final_engineering_strain=final["engineering_strain"],
                    initial_area_mm2=nominal_area,
                    final_force_n=final["force_n"],
                    current_min_width_mm=final["current_min_width_mm"],
                    current_min_height_mm=final["current_min_height_mm"],
                    final_min_radius_mm=final["min_radius_mm"],
                    failed_element_count=len(dead),
                    fracture_band_initial_z_mm=[float(center[dead].min()),float(center[dead].max())] if len(dead) else None,
                    fractured=fracture_strain is not None,
                    elapsed_seconds=time.perf_counter()-t0)

    def terminate(message, status):
        result.summary = summarize(status)
        result.diagnostics.update(status=status, termination_reason=message,
                                  energy_history=energy_history, finite=True)
        error = SimulationCancelled(message) if status == "cancelled" else SimulationNumericalError(message)
        error.partial_result = result
        raise error

    def append(progress):
        nonlocal peak_magnitude, peak_frame
        u = float(x[-1]-length)
        f = float(internal[-1])
        left = float(-internal[0])
        comparison = abs(f) if compression else f
        if comparison > peak_magnitude:
            peak_magnitude, peak_frame = comparison, len(result.frames)
        active = damage < 1.
        current_width = width0*np.exp(lateral)
        current_height = height0*np.exp(lateral)
        # Volume-weighted projection of material-derived lateral strains to
        # section nodes only constructs the display skin, not equilibrium.
        node_lateral = np.zeros(ne+1)
        node_weight = np.zeros(ne+1)
        w = area0*dx
        node_lateral[:-1] += w*lateral; node_lateral[1:] += w*lateral
        node_weight[:-1] += w; node_weight[1:] += w
        node_lateral /= node_weight
        points = reference.copy()
        points[0::2, 0] = x; points[1::2, 0] = x
        points[0::2, 1] *= np.exp(node_lateral)
        points[1::2, 1] *= np.exp(node_lateral)
        minwidth = float(current_width[active].min()) if np.any(active) else 0.
        minheight = float(current_height[active].min()) if np.any(active) else 0.
        if np.any(~active):
            stage = "断裂后卸载"
        elif compression:
            stage = "塑性压缩" if ep.max() > .002 else ("开始压缩屈服" if ep.max()>1e-7 else "弹性压缩")
        elif damage.max() > .001:
            stage = "损伤扩展"
        elif peak_magnitude > 0 and f < .985*peak_magnitude and ep.max() > .03:
            stage = "局部变细（一维近似）"
        elif ep.max() > .002:
            stage = "塑性强化"
        else:
            stage = "开始屈服" if ep.max()>1e-7 else "弹性阶段"
        kinetic = float(.5*np.sum(mass[1:-1]*v[1:-1]**2))
        ie = float(work.sum())
        ratio = kinetic/max(abs(ie),1e-12)
        balance = abs(f-left)/max(abs(f), .01*peak_magnitude,1.)
        if abs(u/length)>2*config.yield_mpa/config.young_mpa and np.all(active):
            kinetic_ratios.append(ratio); balances.append(balance)
        energy_history.append(dict(engineering_strain=u/length, kinetic_energy_n_mm=kinetic,
                                   internal_work_n_mm=ie, external_work_n_mm=external_work,
                                   damping_energy_n_mm=damping_work,
                                   kinetic_internal_ratio=ratio,reaction_imbalance=balance))
        frame=dict(step=len(result.frames), displacement_mm=u, force_n=f,
                   engineering_strain=u/length, engineering_stress_mpa=f/nominal_area,
                   stage=stage, points_mm=points, cell_stress_axial_mpa=stress.copy(),
                   cell_eq_plastic_strain=ep.copy(), cell_damage=damage.copy(),
                   cell_active=active.copy(), min_radius_mm=.5*minheight,
                   current_min_width_mm=minwidth, current_min_height_mm=minheight,
                   current_min_area_mm2=float((current_width*current_height)[active].min()) if np.any(active) else 0.,
                   reaction_right_n=f,reaction_left_n=left,mean_reaction_n=.5*(f+left),
                   shortening_mm=max(0.,-u),kinetic_energy_n_mm=kinetic,
                   internal_work_n_mm=ie,kinetic_internal_ratio=ratio,
                   pseudo_time=executed*dt,cells=cells,initial_points=reference,
                   diagnostics=meta,view_kind=meta["view_kind"])
        result.frames.append(frame)
        if progress_callback:
            progress_callback(frame,float(progress),f"{stage} · 工程应变 {u/length:.1%}")

    def advance(count,start,hold=math.inf,damp=None):
        nonlocal internal,external_work,damping_work,executed
        stop=start+count
        while start<stop:
            if cancel_event is not None and cancel_event.is_set():
                terminate("计算已取消，已保留最后有效帧。","cancelled")
            chunk=min(50 if damage.max()>.9 else 500,stop-start)
            old=start
            internal,start,bad,ew,dw=advance_kernel(
                chunk,start,dt,duration,direction*length*config.max_strain,hold,
                x0,x,v,acc,mass,area0,dx,hp,ep,damage,he,stress,lateral,
                force_e,old_length,work,damping if damp is None else damp,
                config.young_mpa,config.poisson,config.yield_mpa,
                config.hardening_q_mpa,config.hardening_b,config.damage_onset,
                config.fracture_energy_n_mm,not compression,float(internal[-1]))
            executed += start-old
            external_work += ew; damping_work += dw
            if bad>=0 or not np.all(np.isfinite(x)):
                terminate("杆单元过度压缩或畸变，已保留最后有效帧。","numerical_stop")
            if np.any(damage>=1.) and math.isinf(hold):
                break
        return start

    append(0.)
    early_count=max(3,min(20,config.output_steps//4))
    early_end=min(config.max_strain*.1,4*config.yield_mpa/config.young_mpa)
    targets=np.r_[np.linspace(0,early_end,early_count+1)[1:],
                  np.linspace(early_end,config.max_strain,config.output_steps-early_count+1)[1:]]
    current=0
    for target_strain in targets:
        target=max(current+1,round(nsteps*_load_time_fraction(float(target_strain/config.max_strain))))
        target=min(target,nsteps)
        current=advance(target-current,current)
        if np.any(damage>=1.):
            fracture_strain=float((x[-1]-length)/length)
            break
        append(min(.9,abs(x[-1]-length)/(length*config.max_strain)))
    if fracture_strain is not None:
        hold=float(x[-1]-length)
        chunk=max(1,round(2.5*length/wave/dt))
        for k in range(20):
            transients.append(dict(pseudo_time=executed*dt,engineering_strain=hold/length,
                                   reaction_right_n=float(internal[-1]),reaction_left_n=float(-internal[0])))
            advance(chunk,0,hold,6*wave/length)
            ke=float(.5*np.sum(mass[1:-1]*v[1:-1]**2))
            if k>=3 and max(abs(internal[-1]),abs(internal[0]))<.0005*peak_magnitude and ke<1e-6*max(work.sum(),1.):
                break
        append(1.)
    result.summary=summarize("completed")
    result.diagnostics.update(status="completed",finite=True,
        termination_reason="达到断裂卸载状态。" if fracture_strain is not None else "达到设定轴向变形。",
        solver="有限变形两节点轴向杆单元；真实矩形截面积；显式慢加载",
        constitutive_model="自由侧向应力条件下的对数弹性＋Voce 塑性；材料塑性体积不变",
        damage_model="压缩关闭损伤" if compression else "塑性位移线性牵引软化；一个完整杆单元失效后传力路径断开",
        time_is_pseudo_time=True,time_step=dt,actual_explicit_steps=executed,
        reference_volume_mm3=float(np.sum(area0*dx)),energy_history=energy_history,
        fracture_transient=transients,
        max_kinetic_internal_ratio_after_yield_before_fracture=max(kinetic_ratios,default=0.),
        max_reaction_imbalance_before_fracture=max(balances,default=0.),
        min_radius_definition="仅为旧显示接口兼容的半高；矩形结果应使用宽度与高度，不解释为圆半径。",
        limitations=[note,"截面显示由一维材料侧向应变投影；不是二维/三维实体应力计算。",
                     "局部失效使用单元尺度正则化，但未证明断裂结果网格收敛。",
                     "加载时间为数值伪时间；不含应变率效应。"],
        references=["https://mooseframework.inl.gov/blackbear/source/materials/RadialReturnStressUpdate.html",
                    "https://docs.software.vt.edu/abaqusv2025/English/SIMACAEMATRefMap/simamat-c-damageevolductile.htm"])
    return result
