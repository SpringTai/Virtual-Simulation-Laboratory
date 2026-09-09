"""Independent analytical and model-boundary checks for the four new modules."""
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
from threading import Event

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tensile_lab.presets import make_config
from tensile_lab.structural_solver import simulate, rectangle_torsion, _rectangle_shear
from tensile_lab.solver import SimulationCancelled


def relative(actual, expected):
    return abs(actual-expected)/max(abs(expected), 1e-20)


def run():
    results = []
    for kind in ('torsion', 'bending', 'shear', 'buckling'):
        for shape in ('circle', 'rectangle'):
            for material in ('Fe', 'Al'):
                c = replace(make_config(kind, shape, material), mesh_axial=20, mesh_radial=4, output_steps=10)
                result = simulate(c)
                last, d = result.frames[-1], result.diagnostics
                area = math.pi*c.diameter_mm**2/4 if shape == 'circle' else c.width_mm*c.height_mm
                inertia = math.pi*c.diameter_mm**4/64 if shape == 'circle' else c.width_mm*c.height_mm**3/12
                shear_modulus = c.young_mpa/(2*(1+c.poisson))
                errors = {}
                assert len(result.frames) == 11
                assert np.array_equal(result.frames[0]['points_mm'], result.initial_points)
                assert last['max_stress_mpa'] <= c.yield_mpa*(1+1e-9)
                assert not result.summary['fractured']
                for frame in result.frames:
                    assert np.isfinite(frame[d['plot_x_key']]) and np.isfinite(frame[d['plot_y_key']])
                    for key in ('points_mm','cell_stress_axial_mpa','cell_shear_stress_mpa','cell_damage'):
                        assert np.isfinite(frame[key]).all()
                    assert not np.any(frame['cell_eq_plastic_strain']) and not np.any(frame['cell_damage'])
                if kind == 'torsion':
                    expected = last['torque_n_mm']*c.gauge_length_mm/(shear_modulus*d['torsion_constant_mm4'])
                    errors['twist_vs_TL_over_GJ'] = relative(last['twist_rad'], expected)
                    errors['torque_reaction_balance'] = relative(last['reaction_torque_n_mm'], last['torque_n_mm'])
                    assert np.allclose(last['section_twist_rad'], last['twist_rad']*last['section_x_mm']/c.gauge_length_mm)
                    assert np.allclose(last['torsion_surface_shear_mpa'].max(), last['shear_stress_mpa'], rtol=1e-9)
                    assert not np.any(last['cell_stress_axial_mpa'])
                elif kind == 'bending':
                    expected = last['force_n']*c.gauge_length_mm**3/(48*c.young_mpa*inertia)
                    errors['deflection_vs_PL3_over_48EI'] = relative(last['deflection_mm'], expected)
                    errors['moment_vs_PL_over_4'] = relative(last['bending_moment_n_mm'], last['force_n']*c.gauge_length_mm/4)
                    errors['left_reaction_vs_P_over_2'] = relative(last['reaction_left_n'], last['force_n']/2)
                    errors['right_reaction_vs_P_over_2'] = relative(last['reaction_right_n'], last['force_n']/2)
                    assert last['cell_stress_axial_mpa'].min() < 0 < last['cell_stress_axial_mpa'].max()
                elif kind == 'shear':
                    expected = last['shear_force_n']*c.gauge_length_mm/(shear_modulus*area)
                    errors['displacement_vs_VL_over_GA'] = relative(last['displacement_mm'], expected)
                    errors['shear_law_tau_Ggamma'] = relative(last['shear_stress_mpa'], shear_modulus*last['shear_strain'])
                    errors['shear_reaction_balance'] = relative(last['reaction_shear_force_n'], last['shear_force_n'])
                    assert not np.any(last['cell_stress_axial_mpa'])
                else:
                    weak_i = inertia if shape == 'circle' else max(c.width_mm,c.height_mm)*min(c.width_mm,c.height_mm)**3/12
                    expected = math.pi**2*c.young_mpa*weak_i/c.gauge_length_mm**2
                    errors['critical_load_vs_Euler'] = relative(last['critical_force_n'], expected)
                    errors['imperfection_amplification'] = relative(last['lateral_deflection_mm'], c.imperfection*c.gauge_length_mm/(1-last['force_n']/last['critical_force_n']))
                    errors['FE_equilibrium_residual'] = d['max_relative_equilibrium_residual']
                    assert last['force_n'] <= .98*last['critical_force_n']*(1+1e-12)
                    assert last['lateral_deflection_mm'] <= c.gauge_length_mm/20*(1+1e-12)
                    assert last['engineering_stress_mpa'] < 0 and last['displacement_mm'] < 0
                assert max(errors.values()) < 2e-6, (kind, shape, material, errors)
                results.append(dict(experiment=kind, section=shape, material=material,
                                    errors=errors, final_plot_x=last[d['plot_x_key']], final_plot_y=last[d['plot_y_key']],
                                    final_max_stress_mpa=last['max_stress_mpa'], termination=d['termination_reason']))

    square_j, square_tau = rectangle_torsion(10, 10)
    assert relative(square_j/10**4, .140577014955) < 1e-9
    assert square_j < 10**4/6  # rectangle polar moment must not be used
    a, b = rectangle_torsion(12, 8), rectangle_torsion(8, 12)
    assert a == b
    assert np.allclose(_rectangle_shear([5], [0], 10, 10), square_tau, rtol=1e-10)
    thin_j, _ = rectangle_torsion(1000, 1)
    assert relative(thin_j, 1000/3) < .001

    boundary_checks = []
    for kind in ('torsion','bending','shear','buckling'):
        c = replace(make_config(kind), output_steps=10, mesh_axial=12)
        full = simulate(c)
        clipped = simulate(replace(c, load_factor=2.))
        assert full.frames[-1][full.diagnostics['plot_y_key']] == clipped.frames[-1][clipped.diagnostics['plot_y_key']]
        assert '大于1' in clipped.frames[-1]['stage']
        event = Event()
        def progress(frame, fraction, message):
            if fraction >= .2:
                event.set()
        try:
            simulate(c, progress, event)
            raise AssertionError('Cancellation was ignored')
        except SimulationCancelled as error:
            assert error.partial_result.summary['status'] == 'cancelled'
            assert len(error.partial_result.frames) == 3
        boundary_checks.append(kind)

    perfect = simulate(replace(make_config('buckling'), imperfection=0., output_steps=10))
    assert all(f['lateral_deflection_mm'] == 0 for f in perfect.frames)
    assert perfect.frames[-1]['force_n'] < perfect.frames[-1]['critical_force_n']
    short = simulate(replace(make_config('buckling'), gauge_length_mm=30., output_steps=10))
    assert short.frames[-1]['max_stress_mpa'] <= short.config.yield_mpa*(1+1e-8)
    rotated = simulate(replace(make_config('buckling','rectangle'), width_mm=8., height_mm=12., output_steps=10))
    original = simulate(replace(make_config('buckling','rectangle'), output_steps=10))
    assert math.isclose(rotated.frames[-1]['critical_force_n'], original.frames[-1]['critical_force_n'], rel_tol=1e-12)
    invalid = []
    for changes in ({'young_mpa':float('nan')}, {'width_mm':0.}, {'poisson':.5}, {'load_factor':0.}, {'imperfection':.1}):
        try:
            simulate(replace(make_config('bending'), **changes))
            raise AssertionError(f'Invalid input accepted: {changes}')
        except ValueError:
            invalid.extend(changes)
    report = dict(passed=True, combinations=results, rectangle_square_J_mm4=square_j,
                  clipping_and_cancellation=boundary_checks, perfect_column_stays_straight=True,
                  rectangle_weak_axis_rotation_invariant=True, invalid_inputs_rejected=invalid)
    target = ROOT/'verification-output'/'structural_verification.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=True, combinations=len(results), max_relative_error=max(max(v['errors'].values()) for v in results), report=str(target)),ensure_ascii=True))


if __name__ == '__main__':
    run()
