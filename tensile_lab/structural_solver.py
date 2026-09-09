"""Small, explicit teaching models for torsion, bending, shear and buckling.

All units are mm, N and MPa. Beam/torsion FE degrees of freedom are genuine
one-dimensional unknowns. The quadrilateral mesh is a visualization of a
longitudinal section: it is NOT a solid finite-element stress solution.
"""
from __future__ import annotations

import math
import time
import numpy as np
from scipy.linalg import eigh, solve

from .models import SimulationConfig, SimulationResult
from .solver import SimulationCancelled, SimulationNumericalError


EXPERIMENTS = {'torsion', 'bending', 'shear', 'buckling'}
BEAM_REFERENCE = 'https://interactivetextbooks.citg.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html'
TORSION_REFERENCE = 'https://www.iieta.org/journals/ama_a/paper/10.18280/ama_a.560103'
BUCKLING_REFERENCE = 'https://comet-fenics.readthedocs.io/en/latest/demo/beam_buckling/beam_buckling.html'


def rectangle_torsion(width: float, height: float, terms: int = 120):
    """Exact convergent Saint-Venant series, full side lengths a >= b.

    Returns J [mm^4] and c_tau [mm], where tau_max = G * twist_rate * c_tau.
    In particular J(square) = 0.140577... side^4, not its polar moment.
    """
    a, b = sorted((float(width), float(height)), reverse=True)
    if b <= 0:
        raise ValueError('矩形边长必须大于零。')
    odd = np.arange(1, 2 * terms, 2, dtype=float)
    q = odd * math.pi * a / (2 * b)
    j = a * b**3 * (1/3 - 64*b/(math.pi**5*a) * np.sum(np.tanh(q)/odd**5))
    sech = 2 * np.exp(-q) / (1 + np.exp(-2*q))
    coefficient = b * (1 - 8 / math.pi**2 * np.sum(sech / odd**2))
    return float(j), float(coefficient)


def _rectangle_shear(y, z, width, height, terms=120):
    """Shear magnitude divided by G*twist_rate on the rectangular section.

    Derivatives of Prandtl's Fourier stress function; stable hyperbolic ratios
    avoid overflow for a thin rectangle. y is the displayed height direction.
    """
    a, b = max(width, height), min(width, height)
    y, z = np.broadcast_arrays(np.atleast_1d(np.asarray(y, dtype=float)), np.atleast_1d(np.asarray(z, dtype=float)))
    u, v = (z, y) if width >= height else (y, z)
    n = np.arange(1, 2*terms, 2, dtype=float)[:, None]
    signs = (-1.)**np.arange(terms)[:, None]
    q = n * math.pi * a / (2*b)
    s = n * math.pi * u[None, :] / b
    denominator = 1 + np.exp(-2*q)
    cosh_ratio = (np.exp(s-q) + np.exp(-s-q)) / denominator
    sinh_ratio = (np.exp(s-q) - np.exp(-s-q)) / denominator
    angle = n * math.pi * v[None, :] / b
    dv = -2*v + 8*b/math.pi**2 * np.sum(signs*cosh_ratio*np.sin(angle)/n**2, axis=0)
    du = -8*b/math.pi**2 * np.sum(signs*sinh_ratio*np.cos(angle)/n**2, axis=0)
    return np.hypot(du, dv)


def _rectangle_midplane_shear(y, width, height, terms=120):
    return _rectangle_shear(y, np.zeros_like(y), width, height, terms)


def section_properties(c: SimulationConfig, weak_axis=False):
    if c.section_shape == 'circle':
        radius = c.diameter_mm / 2
        area = math.pi * radius**2
        inertia = math.pi * radius**4 / 4
        return dict(area=area, inertia=inertia, torsion=2*inertia,
                    half_depth=radius, width=2*radius, height=2*radius,
                    tau_coefficient=radius, section_orientation='圆形截面')
    width, height = float(c.width_mm), float(c.height_mm)
    orientation = '绕平行于宽度方向的轴弯曲'
    if weak_axis:
        width, height = max(width, height), min(width, height)
        orientation = '按矩形弱轴屈曲；显示剖面高度取较短边'
    j, tau_coefficient = rectangle_torsion(width, height)
    return dict(area=width*height, inertia=width*height**3/12, torsion=j,
                half_depth=height/2, width=width, height=height,
                tau_coefficient=tau_coefficient, section_orientation=orientation)


def _validate(c):
    if c.experiment not in EXPERIMENTS:
        raise ValueError('此计算模块仅支持扭转、弯曲、剪切与压杆失稳。')
    if c.section_shape not in {'circle', 'rectangle'}:
        raise ValueError('截面应为 circle 或 rectangle。')
    for name in ('young_mpa', 'yield_mpa', 'gauge_length_mm', 'diameter_mm',
                 'width_mm', 'height_mm', 'load_factor'):
        value = float(getattr(c, name))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f'参数 {name} 必须是正的有限数值。')
    if not math.isfinite(c.poisson) or not -.5 < c.poisson < .49:
        raise ValueError('泊松比须处于 −0.5 与 0.49 之间。')
    if c.yield_mpa >= .1*c.young_mpa:
        raise ValueError('教学弹性模型要求屈服强度小于弹性模量的 10%。')
    if not math.isfinite(c.imperfection) or not 0 <= c.imperfection <= .02:
        raise ValueError('初始缺陷系数须在 0～0.02 之间，表示初始侧偏与杆长之比。')
    for name, lower, upper in (('mesh_axial', 4, 160), ('mesh_radial', 1, 24), ('output_steps', 2, 1000)):
        value = getattr(c, name)
        if not isinstance(value, (int, np.integer)) or not lower <= value <= upper:
            raise ValueError(f'{name} 须为 {lower}～{upper} 范围内的整数。')


def _visual_mesh(length, depth, n, ny):
    x = np.linspace(0, length, n+1)
    y = np.linspace(-depth, depth, ny+1)
    points = np.column_stack((np.repeat(x, ny+1), np.tile(y, n+1)))
    cells = []
    for i in range(n):
        for j in range(ny):
            p = i*(ny+1)+j
            cells.append((p, p+ny+1, p+ny+2, p+1))
    return x, y, points, np.asarray(cells, dtype=np.int32)


def _line_stiffness(n, length, rigidity):
    k = np.zeros((n+1, n+1))
    element = rigidity/(length/n)*np.array([[1., -1.], [-1., 1.]])
    for i in range(n):
        k[i:i+2, i:i+2] += element
    unit_load = np.zeros(n+1)
    unit_load[-1] = 1.
    solution = np.zeros(n+1)
    solution[1:] = solve(k[1:, 1:], unit_load[1:], assume_a='pos')
    return k, solution


def _beam_matrices(n, length, ei):
    h = length/n
    kb = ei/h**3*np.array([
        [12, 6*h, -12, 6*h], [6*h, 4*h*h, -6*h, 2*h*h],
        [-12, -6*h, 12, -6*h], [6*h, 2*h*h, -6*h, 4*h*h]])
    kg = np.array([
        [36, 3*h, -36, 3*h], [3*h, 4*h*h, -3*h, -h*h],
        [-36, -3*h, 36, -3*h], [3*h, -h*h, -3*h, 4*h*h]])/(30*h)
    k = np.zeros((2*(n+1), 2*(n+1)))
    g = np.zeros_like(k)
    for i in range(n):
        indices = np.arange(2*i, 2*i+4)
        k[np.ix_(indices, indices)] += kb
        g[np.ix_(indices, indices)] += kg
    free = np.setdiff1d(np.arange(len(k)), [0, 2*n])
    return k, g, free


def _curvature(dofs, length, locations=(.5,)):
    n = len(dofs)//2-1
    h = length/n
    elements = np.column_stack((dofs[:-2:2], dofs[1:-1:2], dofs[2::2], dofs[3::2]))
    rows = []
    for s in locations:
        b = np.array([(-6+12*s)/h**2, (-4+6*s)/h, (6-12*s)/h**2, (-2+6*s)/h])
        rows.append(elements @ b)
    return np.asarray(rows)


def _slope_squared_integrals(dofs, length):
    n = len(dofs)//2-1
    h = length/n
    elements = np.column_stack((dofs[:-2:2], dofs[1:-1:2], dofs[2::2], dofs[3::2]))
    points, weights = np.polynomial.legendre.leggauss(3)
    values = np.zeros(n)
    for xi, weight in zip((points+1)/2, weights/2):
        derivative = np.array([(-6*xi+6*xi*xi)/h, 1-4*xi+3*xi*xi,
                               (6*xi-6*xi*xi)/h, -2*xi+3*xi*xi])
        values += h*weight*(elements @ derivative)**2
    return values


def _metric(label, key, unit, scale=1., decimals=2):
    return dict(label=label, key=key, unit=unit, scale=scale, decimals=decimals)


def simulate(config: SimulationConfig, progress_callback=None, cancel_event=None):
    _validate(config)
    started = time.perf_counter()
    kind = config.experiment
    p = section_properties(config, weak_axis=kind == 'buckling')
    length, e = float(config.gauge_length_mm), float(config.young_mpa)
    g = e/(2*(1+config.poisson))
    n = int(config.mesh_axial)
    if n % 2:
        n += 1  # The center load / first-mode antinode is an actual FE node.
    ny = max(2, min(int(config.mesh_radial), 12))
    x, y, reference, cells = _visual_mesh(length, p['half_depth'], n, ny)
    element_y = reference[cells, 1].mean(axis=1)
    result = SimulationResult(config, reference.copy(), cells)
    d = result.diagnostics
    d.update(experiment=kind, section_shape=config.section_shape,
             section_area_mm2=p['area'], bending_inertia_mm4=p['inertia'],
             torsion_constant_mm4=p['torsion'], shear_modulus_mpa=g,
             section_orientation=p['section_orientation'], actual_mesh_axial=n,
             visualization_cells=int(len(cells)), finite_element_count=n,
             visualization_thickness_cells=ny,
             visualization_note='四边形为纵向剖面恢复网格，不是四节点实体有限元。',
             field_key='cell_stress_axial_mpa', field_label='轴向应力（梁截面恢复，MPa）',
             plot_x_scale=1., plot_y_scale=1., requested_load_factor=float(config.load_factor),
             effective_load_factor=float(min(config.load_factor, 1.)),
             load_factor_rule='1 为当前模型教学加载上限；大于1仍在模型适用上限停止。',
             plasticity_enabled=False, damage_enabled=False, finite=True,
             limitations=['线弹性教学模型；达到首屈服或小变形适用上限即停止，不计算塑性与材料断裂。'])
    factor = min(float(config.load_factor), 1.)
    zero = np.zeros(len(cells))
    base = dict(torque_n_mm=0., twist_rad=0., bending_moment_n_mm=0.,
                deflection_mm=0., shear_force_n=0., shear_strain=0., shear_stress_mpa=0.,
                critical_force_n=0., lateral_deflection_mm=0.)
    limit_reason = ''
    maximum_equilibrium_residual = 0.

    if kind == 'torsion':
        k, unit = _line_stiffness(n, length, g*p['torsion'])
        yield_torque = config.yield_mpa/math.sqrt(3)*p['torsion']/p['tau_coefficient']
        rotation_torque = .35/unit[-1]
        limit, limit_reason = min((yield_torque, '达到截面首屈服，线弹性扭转模型停止。'),
                                 (rotation_torque, '达到0.35 rad教学转角上限，停止加载。'))
        field_coefficient = (np.abs(element_y) if config.section_shape == 'circle'
                             else _rectangle_midplane_shear(element_y, p['width'], p['height']))
        surface_coefficient = (np.full(12, p['half_depth']) if config.section_shape == 'circle'
                               else _rectangle_shear(np.array([p['height']/2, 0, -p['height']/2, 0]),
                                                     np.array([0, -p['width']/2, 0, p['width']/2]), p['width'], p['height']))
        d.update(model_name='一维 Saint-Venant 扭转有限元',
                 model_note='求解截面转角自由度；圆形用极惯性矩，矩形用Saint-Venant级数扭转常数。剪应力由截面解恢复。',
                 view_kind='torsion', boundary_kind='fixed_twist', default_magnification=20.,
                 field_key='cell_shear_stress_mpa', field_label='剪应力幅值（Saint-Venant截面恢复，MPa）',
                 cell_field_note='cell_shear_stress_mpa位于纵向中剖面；torsion_surface_shear_mpa为实际外表面各面中点恢复值。',
                 plot_x_key='twist_rad', plot_y_key='torque_n_mm', plot_x_scale=180/math.pi,
                 plot_y_scale=.001, plot_x_label='端部转角（°）', plot_y_label='扭矩（N·m）',
                 metric_specs=[_metric('扭矩','torque_n_mm','N·m',.001), _metric('端部转角','twist_rad','°',180/math.pi),
                               _metric('最大剪应力','shear_stress_mpa','MPa'), _metric('扭转常数 J','torsion_constant_mm4','mm⁴')],
                 maximum_torque_n_mm=limit*factor, maximum_torque_at_yield_n_mm=yield_torque,
                 shear_stress_coefficient_mm=p['tau_coefficient'], references=[TORSION_REFERENCE])
        d['limitations'].append('固定端仅约束转角，采用自由翘曲Saint-Venant理想化；矩形轴向翘曲不在动画中重建，未求夹持区约束翘曲应力。')
    elif kind == 'shear':
        k, unit = _line_stiffness(n, length, g*p['area'])
        yield_force = config.yield_mpa/math.sqrt(3)*p['area']
        strain_force = .05*g*p['area']
        limit, limit_reason = min((yield_force, '达到均匀剪切首屈服，线弹性剪切模型停止。'),
                                 (strain_force, '达到0.05教学剪应变上限，停止加载。'))
        d.update(model_name='一维均匀剪切单元',
                 model_note='由剪切能½∫GA(v′)²dx组装单元刚度，求横向位移。假设均匀直接剪切，匹配边界剪切牵引/运动约束。',
                 view_kind='shear', boundary_kind='simple_shear', default_magnification=20.,
                 field_key='cell_shear_stress_mpa', field_label='均匀剪应力（MPa）',
                 plot_x_key='shear_strain', plot_y_key='shear_stress_mpa', plot_x_scale=100.,
                 plot_x_label='剪应变 γ（%）', plot_y_label='剪应力 τ（MPa）',
                 metric_specs=[_metric('剪力','shear_force_n','N'), _metric('剪切位移','displacement_mm','mm',decimals=4),
                               _metric('剪应力','shear_stress_mpa','MPa'), _metric('剪应变','shear_strain','%',100.,3)],
                 maximum_shear_force_n=limit*factor, shear_correction_factor=1., references=[])
        d['limitations'].append('不包含梁弯曲、真实剪切夹具接触或断口；圆/矩形均采用均匀剪应力假设，不能用本模型比较剪应力集中。')
    else:
        k, kg, free = _beam_matrices(n, length, e*p['inertia'])
        if kind == 'bending':
            load = np.zeros(len(k))
            load[n] = -1.  # vertical DOF at the center node
            unit = np.zeros(len(k))
            unit[free] = solve(k[np.ix_(free, free)], load[free], assume_a='pos')
            unit_curvature = _curvature(unit, length, (0., 1.))
            max_unit_stress = e*p['half_depth']*np.max(np.abs(unit_curvature))
            yield_force = config.yield_mpa/max_unit_stress
            deformation_force = (length/20)/np.max(np.abs(unit[::2]))
            limit, limit_reason = min((yield_force, '达到最外纤维首屈服，线弹性梁模型停止。'),
                                     (deformation_force, '跨中挠度达到L/20，小挠度梁模型停止。'))
            d.update(model_name='Euler–Bernoulli简支梁有限元',
                     model_note='每节点挠度和转角两个自由度、三次Hermite插值；两端简支、跨中集中力。按σx=−E·y·κ恢复正应力。',
                     view_kind='beam', boundary_kind='simply_supported_center_load', default_magnification=5.,
                     plot_x_key='deflection_mm', plot_y_key='force_n',
                     plot_x_label='跨中挠度（mm）', plot_y_label='跨中载荷（N）',
                     metric_specs=[_metric('跨中载荷','force_n','N'), _metric('跨中挠度','deflection_mm','mm',decimals=3),
                                   _metric('最大弯矩','bending_moment_n_mm','N·m',.001), _metric('最大正应力','max_stress_mpa','MPa')],
                     maximum_center_force_n=limit*factor, references=[BEAM_REFERENCE])
            d['limitations'].append('Euler–Bernoulli小挠度细长梁，忽略剪切变形及加载点局部接触应力；变形显示可放大。')
            if length/p['height'] < 10:
                d['limitations'].append('当前跨高比小于10，剪切变形可能明显；数值仅用于该理想梁模型演示。')
        else:
            values, vectors = eigh(k[np.ix_(free, free)], kg[np.ix_(free, free)], subset_by_index=(0, 0))
            critical = float(values[0])
            mode = np.zeros(len(k))
            mode[free] = vectors[:, 0]
            mode /= max(np.max(np.abs(mode[::2])), 1e-30)
            if mode[n] < 0:
                mode *= -1
            initial_deflection = config.imperfection*length
            initial_dofs = initial_deflection*mode
            initial_curvature = _curvature(initial_dofs, length, (0., 1.))
            curvature_max = np.max(np.abs(initial_curvature))
            def stress_at(force):
                return force/p['area'] + e*p['half_depth']*curvature_max*force/(critical-force)
            high = .98*critical
            limiting = '达到0.98倍临界载荷；临界前模型停止，不计算后屈曲。'
            if initial_deflection > 0:
                deformation_limit = critical*(1-initial_deflection/(length/20))
                if deformation_limit < high:
                    high, limiting = deformation_limit, '侧向挠度达到L/20；小转角临界前模型停止。'
            if stress_at(high) > config.yield_mpa:
                low = 0.
                for _ in range(60):
                    middle = (low+high)/2
                    if stress_at(middle) > config.yield_mpa:
                        high = middle
                    else:
                        low = middle
                high = (low+high)/2
                limiting = '达到截面首屈服；弹性临界前模型停止，不计算塑性屈曲。'
            limit, limit_reason = high, limiting
            initial_points = reference.copy()
            initial_points[:, 0] -= np.tile(y, n+1)*np.repeat(initial_dofs[1::2], ny+1)
            initial_points[:, 1] += np.repeat(initial_dofs[::2], ny+1)
            result.initial_points = initial_points
            euler = math.pi**2*e*p['inertia']/length**2
            d.update(model_name='梁几何刚度特征值与一阶缺陷放大',
                     model_note='两端铰支，求Kφ=Pcr·Kgφ；初始缺陷取计算第一模态。解(K−P·Kg)u=P·Kg·u0的单模态精确约化，始终P<Pcr。',
                     view_kind='buckling', boundary_kind='pinned_pinned', default_magnification=5.,
                     plot_x_key='lateral_deflection_mm', plot_y_key='force_n',
                     plot_x_label='中部总侧向挠度（mm）', plot_y_label='轴向压力（N）',
                     metric_specs=[_metric('轴向压力','force_n','N'), _metric('中部侧向挠度','lateral_deflection_mm','mm'),
                                   _metric('弹性临界载荷','critical_force_n','N'), _metric('临界载荷比','critical_load_ratio','%',100.,1)],
                     critical_force_n=critical, analytical_euler_force_n=euler,
                     initial_imperfection_mm=initial_deflection, imperfection_definition='初始侧偏幅值=imperfection×初始杆长；形状来自FE第一特征模态。',
                     maximum_axial_force_n=limit*factor, maximum_critical_load_ratio=limit*factor/critical,
                     references=[BEAM_REFERENCE, BUCKLING_REFERENCE])
            d['limitations'].extend(['没有后屈曲承载计算，也没有自动生成屈曲后下降曲线。',
                                     '正应力由轴向压力与相对初始无应力形状的曲率变化恢复；采用弱轴弹性梁和一阶初始缺陷。'])
            if initial_deflection == 0:
                d['limitations'].append('初始缺陷为0：理想直杆在临界前保持直线，不把特征模态当作实际变形。')
            if critical > config.yield_mpa*p['area']:
                d['limitations'].append('该短粗杆的Euler临界载荷高于轴向首屈服载荷；只展示弹性压缩，不声称预测其实际屈曲极限。')

    endpoint_reason = limit_reason if factor == 1. else '达到设定教学加载比例。'
    if config.load_factor > 1:
        endpoint_reason += ' 输入加载系数大于1，已限制在模型适用上限。'
    d['termination_reason'] = endpoint_reason
    d['model_loading_limit'] = limit_reason

    def finish(status):
        frames = result.frames
        last = frames[-1]
        result.summary = dict(status=status, fractured=False, initial_area_mm2=p['area'],
                              peak_force_n=max(f['force_n'] for f in frames),
                              peak_engineering_stress_mpa=max((f['engineering_stress_mpa'] for f in frames), key=abs),
                              final_engineering_strain=last['engineering_strain'], final_min_radius_mm=p['half_depth'],
                              elapsed_seconds=time.perf_counter()-started, termination_reason=d['termination_reason'],
                              max_stress_mpa=max(f.get('max_stress_mpa', 0.) for f in frames),
                              peak_torque_n_mm=max(f['torque_n_mm'] for f in frames),
                              maximum_deflection_mm=max(f['deflection_mm'] for f in frames),
                              maximum_shear_stress_mpa=max(f['shear_stress_mpa'] for f in frames),
                              critical_force_n=float(d.get('critical_force_n', 0.)))
        d.update(status=status, max_relative_equilibrium_residual=maximum_equilibrium_residual)

    for step, fraction in enumerate(np.linspace(0, 1, int(config.output_steps)+1)):
        if step and cancel_event is not None and cancel_event.is_set():
            d['termination_reason'] = '计算已取消；保留已完成加载步。'
            finish('cancelled')
            error = SimulationCancelled(d['termination_reason'])
            error.partial_result = result
            raise error
        magnitude = limit*factor*fraction
        frame = dict(base, step=step, displacement_mm=0., force_n=0., engineering_strain=0.,
                     engineering_stress_mpa=0., points_mm=reference.copy(),
                     cell_stress_axial_mpa=zero.copy(), cell_shear_stress_mpa=zero.copy(),
                     cell_eq_plastic_strain=zero.copy(), cell_damage=zero.copy(),
                     cell_active=np.ones(len(cells), dtype=bool), min_radius_mm=p['half_depth'],
                     max_stress_mpa=0., torsion_constant_mm4=p['torsion'],
                     stage='初始状态' if step == 0 else '线弹性加载')
        if kind == 'torsion':
            theta = unit*magnitude
            rate = np.diff(theta)/(length/n)
            shear = g*np.repeat(rate, ny)*field_coefficient
            max_tau = g*np.max(np.abs(rate))*p['tau_coefficient']
            frame.update(torque_n_mm=float(magnitude), twist_rad=float(theta[-1]),
                         shear_stress_mpa=float(max_tau), max_stress_mpa=float(math.sqrt(3)*max_tau),
                         cell_shear_stress_mpa=shear, section_x_mm=x.copy(), section_twist_rad=theta,
                         torsion_surface_shear_mpa=g*rate[:, None]*surface_coefficient[None, :],
                         node_twist_rad=np.repeat(theta, ny+1), reaction_torque_n_mm=float(-(k@theta)[0]))
        elif kind == 'shear':
            transverse = unit*magnitude
            strain = np.diff(transverse)/(length/n)
            frame['points_mm'][:, 1] += np.repeat(transverse, ny+1)
            frame.update(force_n=float(magnitude), shear_force_n=float(magnitude),
                         displacement_mm=float(transverse[-1]), shear_strain=float(transverse[-1]/length),
                         shear_stress_mpa=float(magnitude/p['area']),
                         max_stress_mpa=float(math.sqrt(3)*magnitude/p['area']),
                         cell_shear_stress_mpa=np.repeat(g*strain, ny), reaction_shear_force_n=float(-(k@transverse)[0]))
        elif kind == 'bending':
            displacement = unit*magnitude
            curvature = _curvature(displacement, length)[0]
            edge_curvature = _curvature(displacement, length, (0., 1.))
            frame['points_mm'][:, 0] -= np.tile(y, n+1)*np.repeat(displacement[1::2], ny+1)
            frame['points_mm'][:, 1] += np.repeat(displacement[::2], ny+1)
            reactions = k@displacement
            frame.update(force_n=float(magnitude), displacement_mm=float(-displacement[n]),
                         deflection_mm=float(-displacement[n]),
                         bending_moment_n_mm=float(e*p['inertia']*np.max(np.abs(edge_curvature))),
                         cell_stress_axial_mpa=-e*element_y*np.repeat(curvature, ny),
                         max_stress_mpa=float(e*p['half_depth']*np.max(np.abs(edge_curvature))),
                         reaction_left_n=float(reactions[0]), reaction_right_n=float(reactions[2*n]))
        else:
            amplification = critical/(critical-magnitude)
            additional = (amplification-1)*initial_dofs
            total = initial_dofs+additional
            curvature = _curvature(additional, length)[0]
            edge_curvature = _curvature(additional, length, (0., 1.))
            slope_change = _slope_squared_integrals(total, length)-_slope_squared_integrals(initial_dofs, length)
            shortening_nodes = magnitude*x/(e*p['area']) + np.r_[0., .5*np.cumsum(slope_change)]
            frame['points_mm'][:, 0] -= np.repeat(shortening_nodes, ny+1)+np.tile(y, n+1)*np.repeat(total[1::2], ny+1)
            frame['points_mm'][:, 1] += np.repeat(total[::2], ny+1)
            equilibrium = (k-magnitude*kg)@additional-magnitude*kg@initial_dofs
            denominator = max(np.linalg.norm((magnitude*kg@initial_dofs)[free]), 1.)
            maximum_equilibrium_residual = max(maximum_equilibrium_residual, float(np.linalg.norm(equilibrium[free])/denominator))
            frame.update(force_n=float(magnitude), displacement_mm=float(-shortening_nodes[-1]),
                         engineering_strain=float(-shortening_nodes[-1]/length), engineering_stress_mpa=float(-magnitude/p['area']),
                         lateral_deflection_mm=float(np.max(np.abs(total[::2]))),
                         deflection_mm=float(np.max(np.abs(total[::2]))), critical_force_n=critical,
                         critical_load_ratio=float(magnitude/critical), imperfection_amplification=float(amplification),
                         bending_moment_n_mm=float(e*p['inertia']*np.max(np.abs(edge_curvature))),
                         cell_stress_axial_mpa=-magnitude/p['area']-e*element_y*np.repeat(curvature, ny),
                         max_stress_mpa=float(magnitude/p['area']+e*p['half_depth']*np.max(np.abs(edge_curvature))),
                         stage='初始无应力缺陷' if step == 0 else '临界前缺陷放大')
        if step == config.output_steps:
            frame['stage'] = endpoint_reason
        if not all(np.all(np.isfinite(value)) for value in (frame['points_mm'], frame['cell_stress_axial_mpa'], frame['cell_shear_stress_mpa'])):
            error = SimulationNumericalError('计算产生非有限数值。')
            error.partial_result = result
            raise error
        result.frames.append(frame)
        if progress_callback is not None:
            progress_callback(frame, float(fraction), frame['stage'])
    finish('completed')
    return result
