"""Checks for axial section/experiment expansion, independent of the GUI."""
from pathlib import Path
from dataclasses import replace
import json
import math
import threading
import numpy as np

from tensile_lab.models import SimulationConfig
from tensile_lab.axial_solver import simulate_axial
from tensile_lab.solver import SimulationCancelled
from tensile_lab.storage import load_result, save_result


def uniaxial_reference(c, signed_strain):
    stretch=1+signed_strain
    signed_h=math.log(stretch)
    direction=1 if signed_h>=0 else -1
    h=abs(signed_h)
    if c.young_mpa*h<=c.yield_mpa:
        p,tau=0.,direction*c.young_mpa*h
    else:
        lo,hi=0.,h
        for _ in range(80):
            p=.5*(lo+hi)
            flow=c.yield_mpa+c.hardening_q_mpa*(1-math.exp(-c.hardening_b*p))
            if p+flow/c.young_mpa<h:
                lo=p
            else:
                hi=p
        tau=direction*flow
    lateral=-.5*direction*p-c.poisson*tau/c.young_mpa
    return tau/stretch,math.exp(lateral)


def main():
    output=Path(__file__).resolve().parents[1]/"verification-output"/"v2.1"/"axial"
    output.mkdir(parents=True,exist_ok=True)
    report={}
    for experiment in ["tension","compression"]:
        c=SimulationConfig(experiment=experiment,section_shape="rectangle",
                           width_mm=12.,height_mm=8.,mesh_axial=12,
                           output_steps=20,max_strain=.0001,imperfection=0.)
        r=simulate_axial(c)
        f=r.frames[-1]
        expected,lateral=uniaxial_reference(c,f["engineering_strain"])
        assert abs(f["engineering_stress_mpa"]/expected-1)<.001
        assert abs(f["current_min_width_mm"]/(c.width_mm*lateral)-1)<1e-6
        assert abs(f["current_min_height_mm"]/(c.height_mm*lateral)-1)<1e-6
        report[experiment+"_rectangle_elastic"]={
            "expected_stress_mpa":expected,"computed_stress_mpa":f["engineering_stress_mpa"],
            "expected_width_mm":c.width_mm*lateral,"computed_width_mm":f["current_min_width_mm"],
            "expected_height_mm":c.height_mm*lateral,"computed_height_mm":f["current_min_height_mm"]}
    # Same area, different b/h: force agrees in the explicitly uniaxial model
    # but the actual displayed geometry keeps its different dimensions.
    c1=SimulationConfig(section_shape="rectangle",width_mm=12.,height_mm=8.,
                        mesh_axial=12,output_steps=20,max_strain=.01,imperfection=0.)
    c2=replace(c1,width_mm=6.,height_mm=16.)
    r1,r2=simulate_axial(c1),simulate_axial(c2)
    assert np.allclose([f["force_n"] for f in r1.frames],
                       [f["force_n"] for f in r2.frames],rtol=1e-11,atol=1e-7)
    assert np.allclose(r2.initial_points[:,1],2*r1.initial_points[:,1])
    assert abs(r2.frames[-1]["current_min_width_mm"]/
               r1.frames[-1]["current_min_width_mm"]-.5)<1e-12
    c3=replace(c1,width_mm=24.)
    r3=simulate_axial(c3)
    assert np.allclose([f["force_n"] for f in r3.frames],
                       2*np.array([f["force_n"] for f in r1.frames]),rtol=1e-10,atol=1e-6)
    report["real_rectangle_geometry_and_area"]={"passed":True,
        "equal_area_sections":[[12,8],[6,16]],"double_width_force_ratio":r3.frames[-1]["force_n"]/r1.frames[-1]["force_n"]}
    for shape in ["rectangle","circle"]:
        path=output/("compression_"+shape+".npz")
        if path.exists():
            r=load_result(path)
        else:
            c=SimulationConfig(experiment="compression",section_shape=shape,
                               width_mm=12.,height_mm=8.,max_strain=.25,imperfection=0.)
            r=simulate_axial(c);save_result(r,path)
        f=r.frames[-1];c=r.config
        expected,lateral=uniaxial_reference(c,-.25)
        relative_error=abs(f["engineering_stress_mpa"]/expected-1)
        assert relative_error<.005
        assert abs(f["engineering_strain"]+.25)<1e-10
        assert all(np.all(q["cell_damage"]==0) and np.all(q["cell_active"]) for q in r.frames)
        assert not r.summary["fractured"]
        assert np.all(np.array([q["force_n"] for q in r.frames])<=1e-6)
        if shape=="rectangle":
            dimensional_error=abs(f["current_min_height_mm"]/(c.height_mm*lateral)-1)
        else:
            dimensional_error=abs(f["min_radius_mm"]/(.5*c.diameter_mm*lateral)-1)
        assert dimensional_error<.001
        e=r.diagnostics["energy_history"][-1]
        energy_error=abs(e["external_work_n_mm"]-e["internal_work_n_mm"]-
                         e["kinetic_energy_n_mm"]-e["damping_energy_n_mm"])/e["external_work_n_mm"]
        assert energy_error<.005
        report["compression_"+shape]={"passed":True,"expected_stress_mpa":expected,
            "computed_stress_mpa":f["engineering_stress_mpa"],"relative_error":relative_error,
            "lateral_size_relative_error":dimensional_error,"energy_balance_error":energy_error,
            "summary":r.summary}
        print("Compression",shape,report["compression_"+shape],flush=True)
    path=output/"tension_rectangle.npz"
    if path.exists():
        r=load_result(path)
    else:
        r=simulate_axial(SimulationConfig(section_shape="rectangle",width_mm=12.,height_mm=8.))
        save_result(r,path)
    f=r.frames[-1]
    assert r.summary["fractured"]
    assert all(.3*r.config.gauge_length_mm<z<.7*r.config.gauge_length_mm
               for z in r.summary["fracture_band_initial_z_mm"])
    assert f["cell_active"][0] and f["cell_active"][-1]
    assert abs(f["force_n"])<.001*r.summary["peak_force_magnitude_n"]
    assert any(q["current_min_area_mm2"]<.8*r.summary["initial_area_mm2"] for q in r.frames)
    e=r.diagnostics["energy_history"][-1]
    energy_error=abs(e["external_work_n_mm"]-e["internal_work_n_mm"]-
                     e["kinetic_energy_n_mm"]-e["damping_energy_n_mm"])/e["external_work_n_mm"]
    assert energy_error<.005
    report["tension_rectangle_fracture"]={"passed":True,"summary":r.summary,
        "energy_balance_error":energy_error,"model_note":r.diagnostics["model_note"]}
    cancelled=threading.Event();cancelled.set()
    try:
        simulate_axial(SimulationConfig(section_shape="rectangle"),cancel_event=cancelled)
        raise AssertionError("Cancellation was ignored")
    except SimulationCancelled as exc:
        assert exc.partial_result.summary["status"]=="cancelled"
        assert len(exc.partial_result.frames)==1
        report["rectangle_cancel_preserves_result"]={"passed":True}
    baseline=load_result(Path(__file__).resolve().parents[1]/'examples'/'tension_circle_Fe.npz')
    new=simulate_axial(baseline.config)
    save_result(new,output/"tension_circle_regression.npz")
    old_curve=np.array([[f["engineering_strain"],f["force_n"]] for f in baseline.frames])
    new_curve=np.array([[f["engineering_strain"],f["force_n"]] for f in new.frames])
    assert old_curve.shape==new_curve.shape
    np.testing.assert_allclose(old_curve[:,0],new_curve[:,0],rtol=1e-10,atol=1e-12)
    # Across Windows CPU/libm builds, near-zero fracture residuals differ by
    # micro-newtons. Scale the absolute force tolerance to the peak load.
    force_scale=max(1.,float(np.max(np.abs(old_curve[:,1]))))
    np.testing.assert_allclose(old_curve[:,1],new_curve[:,1],rtol=1e-10,atol=1e-10*force_scale)
    assert all(np.array_equal(before['cell_active'],after['cell_active']) for before,after in zip(baseline.frames,new.frames))
    for before,after in zip(baseline.frames,new.frames):
        assert np.allclose(before["points_mm"],after["points_mm"],rtol=1e-11,atol=1e-10)
    report["legacy_circular_tension_regression"]={"passed":True,
        "max_force_difference_n":float(np.max(np.abs(old_curve[:,1]-new_curve[:,1]))),
        "max_force_difference_over_peak":float(np.max(np.abs(old_curve[:,1]-new_curve[:,1]))/force_scale),
        "summary":new.summary}
    report["passed"]=True
    (output/"axial_validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("All axial expansion checks passed",flush=True)


if __name__=="__main__":
    main()
