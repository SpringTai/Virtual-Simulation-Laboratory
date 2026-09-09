"""Independent closed-form and 2D Prandtl-Poisson review of structural models."""
from pathlib import Path
from dataclasses import replace
import json
import math
import numpy as np
from scipy.sparse import diags, kronsum
from scipy.sparse.linalg import spsolve
from tensile_lab.presets import make_config
from tensile_lab.structural_solver import simulate, rectangle_torsion


def poisson_torsion_reference(width,height):
    nx,ny=120,120
    hx,hy=width/nx,height/ny
    tx=diags([-np.ones(nx-2),2*np.ones(nx-1),-np.ones(nx-2)],[-1,0,1])/hx**2
    ty=diags([-np.ones(ny-2),2*np.ones(ny-1),-np.ones(ny-2)],[-1,0,1])/hy**2
    phi=np.zeros((ny+1,nx+1))
    phi[1:-1,1:-1]=spsolve(kronsum(tx,ty).tocsc(),2*np.ones((nx-1)*(ny-1))).reshape(ny-1,nx-1)
    torsion_constant=2*hx*hy*phi.sum()
    dx=(4*phi[1:-1,1]-phi[1:-1,2])/(2*hx)
    dy=(4*phi[1,1:-1]-phi[2,1:-1])/(2*hy)
    coefficient=max(np.max(np.abs(dx)),np.max(np.abs(dy)))
    return float(torsion_constant),float(coefficient)


def main():
    report={"rectangular_torsion_poisson_checks":[],"experiment_checks":[]}
    for width,height in [(10.,10.),(12.,8.),(8.,12.)]:
        j,c=rectangle_torsion(width,height)
        jfd,cfd=poisson_torsion_reference(width,height)
        ej,ec=abs(jfd/j-1),abs(cfd/c-1)
        assert ej<.001 and ec<.001
        report["rectangular_torsion_poisson_checks"].append(dict(
            width_mm=width,height_mm=height,series_J_mm4=j,independent_fd_J_mm4=jfd,
            series_tau_coefficient_mm=c,independent_fd_tau_coefficient_mm=cfd,
            J_relative_difference=ej,tau_coefficient_relative_difference=ec))
    for material in ["Fe","Al"]:
        for shape in ["circle","rectangle"]:
            for kind in ["torsion","bending","shear","buckling"]:
                c=make_config(kind,shape,material)
                r=simulate(c);f=r.frames[-1]
                area=math.pi*c.diameter_mm**2/4 if shape=="circle" else c.width_mm*c.height_mm
                if shape=="circle":
                    inertia=math.pi*c.diameter_mm**4/64;half=c.diameter_mm/2
                elif kind=="buckling":
                    inertia=max(c.width_mm,c.height_mm)*min(c.width_mm,c.height_mm)**3/12
                    half=min(c.width_mm,c.height_mm)/2
                else:
                    inertia=c.width_mm*c.height_mm**3/12;half=c.height_mm/2
                entry=dict(experiment=kind,shape=shape,material=material,passed=True)
                assert r.summary["status"]=="completed" and not r.summary["fractured"]
                if kind=="torsion":
                    j=math.pi*c.diameter_mm**4/32 if shape=="circle" else poisson_torsion_reference(c.width_mm,c.height_mm)[0]
                    g=c.young_mpa/(2*(1+c.poisson))
                    expected=f["torque_n_mm"]*c.gauge_length_mm/(g*j)
                    error=abs(f["twist_rad"]/expected-1)
                    assert error<.001
                    assert abs(f["reaction_torque_n_mm"]/f["torque_n_mm"]-1)<1e-10
                    entry.update(twist_relative_error=error)
                elif kind=="bending":
                    force=f["force_n"];length=c.gauge_length_mm
                    expected=force*length**3/(48*c.young_mpa*inertia)
                    error=abs(f["deflection_mm"]/expected-1)
                    assert error<1e-8
                    assert abs(f["bending_moment_n_mm"]/(force*length/4)-1)<1e-8
                    assert abs(f["reaction_left_n"]/(force/2)-1)<1e-8
                    assert abs(f["reaction_right_n"]/(force/2)-1)<1e-8
                    entry.update(deflection_relative_error=error)
                elif kind=="shear":
                    g=c.young_mpa/(2*(1+c.poisson))
                    assert abs(f["shear_stress_mpa"]/(g*f["shear_strain"])-1)<1e-10
                    assert abs(f["shear_force_n"]/(f["shear_stress_mpa"]*area)-1)<1e-10
                    assert abs(f["reaction_shear_force_n"]/f["shear_force_n"]-1)<1e-10
                    entry.update(tau_Ggamma_agree=True)
                else:
                    euler=math.pi**2*c.young_mpa*inertia/c.gauge_length_mm**2
                    pc=f["critical_force_n"];force=f["force_n"]
                    error=abs(pc/euler-1)
                    assert error<1e-5
                    expected=c.imperfection*c.gauge_length_mm/(1-force/pc)
                    assert abs(f["lateral_deflection_mm"]/expected-1)<1e-8
                    expected_moment=force*f["lateral_deflection_mm"]
                    assert abs(f["bending_moment_n_mm"]/expected_moment-1)<.003
                    expected_stress=force/area+expected_moment*half/inertia
                    assert abs(f["max_stress_mpa"]/expected_stress-1)<.003
                    assert 0<force/pc<1
                    assert f["engineering_strain"]<0 and f["engineering_stress_mpa"]<0
                    entry.update(Euler_critical_relative_error=error,critical_load_ratio=force/pc)
                report["experiment_checks"].append(entry)
    perfect=simulate(replace(make_config("buckling","circle","Fe"),imperfection=0.))
    assert all(f["lateral_deflection_mm"]==0 for f in perfect.frames)
    report["perfect_column_not_given_fake_buckled_shape"]=True
    report["passed"]=True
    path=Path(__file__).resolve().parents[1]/"verification-output"/"structural_independent_review.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=="__main__":
    main()
