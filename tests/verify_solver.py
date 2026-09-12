"""Independent physical checks, run with: python -m tests.verify_solver."""
from pathlib import Path
import json
import math
import threading
import numpy as np

from tensile_lab.models import SimulationConfig
from tensile_lab.solver import simulate, make_mesh, SimulationCancelled, _material_update
from tensile_lab.storage import save_result, load_result


def main():
    output = Path(__file__).resolve().parents[1] / "verification-output"
    output.mkdir(exist_ok=True)
    checks = {}
    c = SimulationConfig(mesh_axial=8, mesh_radial=2, output_steps=20,
                         max_strain=.0001, imperfection=0)
    points, cells, shapes, grad, hoop, volume, mass = make_mesh(c)
    exact_volume = math.pi*(c.diameter_mm/2)**2*c.gauge_length_mm
    assert abs(volume.sum()/exact_volume-1) < 1e-12
    assert abs(mass.sum()/exact_volume-1) < 1e-12
    checks["axisymmetric_volume_and_mass"] = {"relative_error": abs(volume.sum()/exact_volume-1)}
    r = simulate(c)
    save_result(r, output/"elastic_result.npz")
    computed_e = r.frames[-1]["engineering_stress_mpa"]/c.max_strain
    radial_strain = np.mean(r.frames[-1]["points_mm"][2::3, 1])/(c.diameter_mm/2)-1
    computed_nu = -radial_strain/c.max_strain
    assert abs(computed_e/c.young_mpa-1) < .01
    assert abs(computed_nu-c.poisson) < .01
    checks["elastic_modulus_and_poisson"] = dict(
        expected_E_mpa=c.young_mpa, computed_E_mpa=computed_e,
        expected_poisson=c.poisson, computed_poisson=computed_nu)
    print("Elastic check", checks["elastic_modulus_and_poisson"], flush=True)

    # For spatially uniform uniaxial Hencky J2 flow, log(lambda)=p+tau/E,
    # and the nominal stress is tau/lambda.  This scalar relation is
    # independent of the quadrilateral equilibrium implementation.
    c = SimulationConfig(mesh_axial=8, mesh_radial=2, output_steps=30,
                         max_strain=.15, imperfection=0, damage_onset=100.)
    lo, hi = 0., math.log(1+c.max_strain)
    for _ in range(80):
        p = .5*(lo+hi)
        tau = c.yield_mpa+c.hardening_q_mpa*(1-math.exp(-c.hardening_b*p))
        if p+tau/c.young_mpa < math.log(1+c.max_strain):
            lo = p
        else:
            hi = p
    expected = tau/(1+c.max_strain)
    r = simulate(c)
    save_result(r, output/"uniform_plastic_result.npz")
    actual = r.frames[-1]["engineering_stress_mpa"]
    assert abs(actual/expected-1) < .015
    checks["uniform_finite_strain_plasticity"] = dict(
        expected_nominal_stress_mpa=expected, computed_nominal_stress_mpa=actual,
        relative_error=abs(actual/expected-1))
    print("Uniform plastic check", checks["uniform_finite_strain_plasticity"], flush=True)

    # Objectivity of an already stressed elastic state under a superposed
    # rigid rotation, tested at one integration point.
    mu = 200000/(2*1.3); bulk = 200000/(3*.4)
    angle = .37
    rr = np.array([[math.cos(angle), -math.sin(angle)],
                   [math.sin(angle), math.cos(angle)]])
    oldf = np.array([1., 0., 0., 1., 1.])
    be0 = np.array([math.exp(.002), 0., math.exp(-.001), math.exp(-.001)])
    rotated = np.r_[rr.reshape(-1), 1.]
    args = (mu, bulk, 1e9, 0., 1., 100., 80., 1., 0.)
    _, _, _, t0 = _material_update(oldf, oldf, be0, 0., 0., *args)
    _, _, _, t1 = _material_update(rotated, oldf, be0, 0., 0., *args)
    expected_tensor = rr @ np.array([[t0[0], t0[1]], [t0[1], t0[2]]]) @ rr.T
    actual_tensor = np.array([[t1[0], t1[1]], [t1[1], t1[2]]])
    err = float(np.max(np.abs(expected_tensor-actual_tensor)))
    assert err < 1e-6
    checks["rigid_rotation_objectivity"] = {"max_stress_error_mpa": err}

    cancelled = threading.Event(); cancelled.set()
    try:
        simulate(SimulationConfig(mesh_axial=8, mesh_radial=2), cancel_event=cancelled)
        raise AssertionError("Cancellation was not honored")
    except SimulationCancelled as exc:
        assert exc.partial_result.summary["status"] == "cancelled"
        assert len(exc.partial_result.frames) == 1
        checks["cancellation_preserves_result"] = True

    c = SimulationConfig(mesh_axial=20, mesh_radial=3)
    coarse = simulate(c)
    save_result(coarse, output/"coarse_result.npz")
    candidate = output/"default_result.npz"
    if candidate.exists():
        default = load_result(candidate)
    else:
        default = simulate(SimulationConfig())
        save_result(default, candidate)
    for name, r in [("coarse", coarse), ("default", default)]:
        final = r.frames[-1]
        assert r.summary["fractured"], f"{name}: no complete fracture"
        assert abs(final["force_n"])/r.summary["peak_force_n"] < .002
        dead = np.flatnonzero(~final["cell_active"])
        dead_z = r.initial_points[r.cells[dead], 0].mean(1)
        assert np.all((dead_z > .3*r.config.gauge_length_mm) &
                      (dead_z < .7*r.config.gauge_length_mm)), f"{name}: grip fracture"
        nr = r.config.mesh_radial
        outer = final["points_mm"][nr::nr+1, 1]
        assert outer.min() < .85*.5*(outer[0]+outer[-1]), f"{name}: no neck"
        assert max(np.max(f["cell_eq_plastic_strain"])
                   for f in r.frames if np.max(f["cell_damage"]) == 0) > .1
        energy = r.diagnostics["energy_history"][-1]
        mismatch = abs(energy["external_work_n_mm"] - energy["internal_work_n_mm"]
                       -energy["kinetic_energy_n_mm"]-energy["damping_energy_n_mm"])
        mismatch /= energy["external_work_n_mm"]
        assert mismatch < .02, f"{name}: poor energy balance"
        checks[name+"_necking_and_fracture"] = dict(
            peak_stress_mpa=r.summary["peak_engineering_stress_mpa"],
            strain_at_fracture=r.summary["fracture_engineering_strain"],
            fracture_band_initial_z_mm=[float(dead_z.min()), float(dead_z.max())],
            final_force_n=final["force_n"], final_min_radius_mm=final["min_radius_mm"],
            energy_balance_relative_error=mismatch,
            compute_seconds=r.summary["elapsed_seconds"])
        print(name, checks[name+"_necking_and_fracture"], flush=True)
    checks["mesh_comparison"] = dict(
        peak_stress_relative_difference=abs(coarse.summary["peak_engineering_stress_mpa"]/
                                           default.summary["peak_engineering_stress_mpa"]-1),
        fracture_strain_difference=abs(coarse.summary["fracture_engineering_strain"]-
                                       default.summary["fracture_engineering_strain"]),
        note="两种网格用于发现明显问题，不构成网格收敛证明。")
    (output/"solver_verification.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    print("All checks passed", flush=True)


if __name__ == "__main__":
    main()
