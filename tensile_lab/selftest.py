"""离线包自检：十二类几何/实验计算、24份样本、Qt和数据回放。"""
from pathlib import Path
from dataclasses import replace
import json
import time
import traceback
import csv
import math
import numpy as np


def run_selftest(report_filename):
    destination = Path(report_filename).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'calculations': [], 'examples': []}
    start = time.perf_counter()
    try:
        from .presets import make_config, example_path, EXPERIMENTS
        from .engine import simulate
        from .storage import save_result, load_result
        from .export import export_result
        from .gui import MainWindow
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        window = MainWindow()
        window.resize(1280, 800)
        window.show()
        app.processEvents()
        report['bundled_classroom_example'] = window.result is not None
        report['classroom_initial_frame'] = window._current_index
        window.grab().save(str(destination.parent / 'desktop-selftest.png'))
        for experiment in EXPERIMENTS:
            for shape in ('circle', 'rectangle'):
                for material in ('Fe', 'Al'):
                    config = make_config(experiment, shape, material)
                    path = example_path(config)
                    if not path.is_file():
                        raise AssertionError(f'缺少课堂样本：{path.name}')
                    result = load_result(path)
                    assert result.config.to_dict() == config.to_dict(), path.name
                    assert len(result.frames) >= 10
                    assert result.diagnostics.get('status', 'completed') == 'completed', path.name
                    assert all(np.isfinite(f['points_mm']).all() for f in result.frames)
                    window._apply_config(result.config)
                    window._on_complete(result)
                    window.timeline.setValue(len(result.frames)-1)
                    app.processEvents()
                    assert window._current_index == len(result.frames)-1
                    assert window.play_button.isEnabled() and window.export_button.isEnabled()
                    assert window.result.config.experiment == experiment
                    report['examples'].append(path.name)
                # Independent small compute proves no dependence on bundled data.
                config = replace(make_config(experiment, shape, 'Fe'),
                                 mesh_axial=8, mesh_radial=2, output_steps=12,
                                 geometry_preset='manual', load_factor=.25)
                if experiment in ('tension', 'compression'):
                    config = replace(config, max_strain=.0005, imperfection=0.)
                result = simulate(config)
                last = result.frames[-1]
                check = {'experiment': experiment, 'shape': shape, 'frames': len(result.frames)}
                assert len(result.frames) >= 10
                if experiment in ('tension', 'compression'):
                    expected = config.young_mpa*last['engineering_strain']
                    error = abs(last['engineering_stress_mpa']/expected-1)
                    assert error < .02, (experiment, shape, error)
                    check['elastic_relative_error'] = error
                    assert last['engineering_strain'] * (1 if experiment=='tension' else -1) > 0
                    if experiment == 'compression':
                        assert np.max(last['cell_damage']) == 0
                if experiment == 'bending':
                    inertia = math.pi*config.diameter_mm**4/64 if shape=='circle' else config.width_mm*config.height_mm**3/12
                    expected = abs(last['force_n'])*config.gauge_length_mm**3/(48*config.young_mpa*inertia)
                    error = abs(abs(last['deflection_mm'])/expected-1)
                    assert error < .02, error
                    check['deflection_relative_error'] = error
                if experiment == 'shear':
                    expected = config.young_mpa/(2*(1+config.poisson))*last['shear_strain']
                    error = abs(last['shear_stress_mpa']/expected-1)
                    assert error < 1e-9
                    check['shear_relative_error'] = error
                if experiment == 'buckling':
                    inertia = math.pi*config.diameter_mm**4/64 if shape=='circle' else min(config.width_mm*config.height_mm**3,config.height_mm*config.width_mm**3)/12
                    expected = math.pi**2*config.young_mpa*inertia/config.gauge_length_mm**2
                    error = abs(last['critical_force_n']/expected-1)
                    assert error < .02, error
                    check['critical_force_relative_error'] = error
                target = destination.parent / 'roundtrip' / f'{experiment}_{shape}.npz'
                save_result(result, target)
                restored = load_result(target)
                for key, value in last.items():
                    if isinstance(value, np.ndarray):
                        assert np.array_equal(value, restored.frames[-1][key]), key
                exports = export_result(restored, destination.parent / 'exports')
                with open(exports['csv'], encoding='utf-8-sig', newline='') as stream:
                    rows = list(csv.DictReader(stream))
                assert len(rows) == len(result.frames)
                if experiment in ('torsion','shear'):
                    assert 'shear_stress_MPa' in Path(exports['fields']).read_text(encoding='utf-8-sig').splitlines()[0]
                assert exports['image'] and Path(exports['image']).is_file()
                check['roundtrip_exact'] = True
                check['export_rows'] = len(rows)
                report['calculations'].append(check)
        window.close()
        report.update(ok=True, elapsed_seconds=time.perf_counter()-start)
    except Exception:
        report['error'] = traceback.format_exc()
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['ok'] else 1
