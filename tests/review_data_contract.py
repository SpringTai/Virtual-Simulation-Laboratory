"""Independent configuration, CSV units/signs, arrays and legacy NPZ audit."""
from pathlib import Path
import csv
import json
import math
import numpy as np

from tensile_lab.presets import EXPERIMENTS,make_config,is_standard_config,example_path
from tensile_lab.storage import load_result,save_result
from tensile_lab.export import export_result
from tensile_lab.plotting import curve_data


def main():
    root=Path(__file__).resolve().parents[1]
    out=root/"verification-output"/"independent-data-audit"
    out.mkdir(parents=True,exist_ok=True)
    records=[]
    for experiment in EXPERIMENTS:
        for shape in ("circle","rectangle"):
            for material in ("Fe","Al"):
                expected=make_config(experiment,shape,material)
                source=root/"examples"/f"{experiment}_{shape}_{material}.npz"
                r=load_result(source)
                assert r.config.to_dict()==expected.to_dict(),source.name
                assert is_standard_config(r.config)
                assert Path(example_path(r.config)).name==source.name
                for f in r.frames:
                    assert len(f["cell_active"])==len(r.cells)
                    assert np.asarray(f["points_mm"]).shape==r.initial_points.shape
                    assert np.all(np.isfinite(f["points_mm"]))
                final=r.frames[-1]
                if experiment=="torsion":
                    expected_shape=(r.diagnostics["actual_mesh_axial"],12 if shape=="circle" else 4)
                    assert final["torsion_surface_shear_mpa"].shape==expected_shape
                    assert np.max(final["torsion_surface_shear_mpa"])<=final["shear_stress_mpa"]*(1+1e-12)
                paths=export_result(r,out)
                with Path(paths["csv"]).open(encoding="utf-8-sig",newline="") as stream:
                    reader=csv.DictReader(stream);rows=list(reader);headers=reader.fieldnames
                assert len(rows)==len(r.frames)
                last=rows[-1]
                if experiment in ("tension","compression"):
                    assert math.isclose(float(last["engineering_strain"]),final["engineering_strain"],rel_tol=1e-9,abs_tol=1e-12)
                    assert math.isclose(float(last["engineering_stress_MPa"]),float(last["force_N"])/r.summary["initial_area_mm2"],rel_tol=1e-9,abs_tol=1e-9)
                    if experiment=="compression":
                        assert float(last["force_N"])<0 and float(last["engineering_strain"])<0
                    if shape=="rectangle":
                        assert "minimum_width_mm" in headers and "minimum_height_mm" in headers
                        assert "minimum_diameter_mm" not in headers
                    else:
                        assert math.isclose(float(last["minimum_diameter_mm"]),2*final["min_radius_mm"],rel_tol=1e-9)
                elif experiment=="torsion":
                    assert math.isclose(float(last["twist_rad"]),final["twist_rad"],rel_tol=1e-9)
                    assert math.isclose(float(last["torque_N_mm"]),final["torque_n_mm"],rel_tol=1e-9)
                    x,y,_,_=curve_data(r)
                    assert math.isclose(x[-1],final["twist_rad"]*180/math.pi,rel_tol=1e-12)
                    assert math.isclose(y[-1],final["torque_n_mm"]*.001,rel_tol=1e-12)
                elif experiment=="buckling":
                    assert float(last["force_N"])>0 and float(last["engineering_stress_MPa"])<0
                    assert math.isclose(float(last["engineering_stress_MPa"]),-float(last["force_N"])/r.summary["initial_area_mm2"],rel_tol=1e-9)
                restored=load_result(paths["archive"])
                assert restored.config.to_dict()==r.config.to_dict()
                for a,b in zip(r.frames,restored.frames):
                    for key,value in a.items():
                        if isinstance(value,np.ndarray):
                            assert np.array_equal(value,b[key]),(source.name,key)
                metadata=json.loads(Path(paths["parameters"]).read_text(encoding="utf-8"))
                assert metadata["units"]["moment"]=="N·mm"
                assert metadata["units"]["angle"]=="rad"
                assert metadata["config_units"]["fracture_energy_n_mm"].startswith("N/mm")
                records.append(dict(file=source.name,config_matches_standard=True,
                                    csv_signs_units_pass=True,array_roundtrip_pass=True,
                                    exported_to=paths["folder"]))
    legacy=root/"examples"/"tension_circle_Fe.npz"
    with np.load(legacy,allow_pickle=False) as data:
        legacy_version=json.loads(str(data["metadata_json"]))["format_version"]
    old=load_result(legacy)
    save_result(old,out/"legacy_roundtrip.npz")
    restored=load_result(out/"legacy_roundtrip.npz")
    assert old.config.experiment=="tension" and old.config.section_shape=="circle"
    assert np.array_equal(old.frames[-1]["points_mm"],restored.frames[-1]["points_mm"])
    assert old.frames[-1]["force_n"]==restored.frames[-1]["force_n"]
    report=dict(passed=True,checked_standard_combinations=len(records),records=records,
                legacy_source_format_version=legacy_version,legacy_roundtrip_pass=True,
                note="无GUI的数值导出检查；图片/界面由独立GUI验收覆盖。")
    (root/"verification-output"/"independent_data_audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Data audit passed:",len(records),"standard combinations; legacy format",legacy_version,flush=True)


if __name__=="__main__":
    main()
