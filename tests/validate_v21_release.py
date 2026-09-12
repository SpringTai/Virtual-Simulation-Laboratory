"""Verify delivered archive contents against the tested release directory."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'verification-output/v2.1'
archive=ROOT/'MechanicsVirtualLab-v2.1-Windows-x64-offline.zip'
release=ROOT/'release-v2.1'
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
    names=set(bundle.namelist())
    assert 'TensileLab/_internal/tensile_lab/_native/mechanics_core.dll' in names
    assert 'install.ps1' in names and 'uninstall.ps1' in names
    checked=0
    for name in names:
        if name.endswith('/'):continue
        original=release/name
        assert original.is_file(),name
        assert hashlib.sha256(bundle.read(name)).digest()==hashlib.sha256(original.read_bytes()).digest(),name
        checked+=1
    assert len([n for n in names if n.startswith('TensileLab/_internal/examples/') and n.endswith('.npz')])==24
    assert not any(n.endswith('/验收记录.md') or n.endswith('/default_result.npz') for n in names)
native=json.loads((out/'native-parity.json').read_text())
frozen=json.loads((out/'frozen/report.json').read_text())
visual=json.loads((out/'visual/report.json').read_text())
installed=[json.loads((out/'installed/installation-report.json').read_text(encoding='utf-8-sig'))]
axial=json.loads((out/'axial/axial_validation.json').read_text(encoding='utf-8'))
assert native['passed'] and frozen['ok'] and visual['passed'] and axial['passed']
assert any(p['passed'] for p in installed)
report=dict(passed=True,version='2.1.0',archive=str(archive),bytes=archive.stat().st_size,
            sha256=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest(),verified_archive_files=checked,
            native_parity_combinations=len(native['calculations']),visual_states=visual['states'],
            frozen_calculations=len(frozen['calculations']),frozen_examples=len(frozen['examples']),
            native_abi=frozen['native_abi'],custom_install_upgrade_uninstall=True,
            historical_circle_force_error_over_peak=axial['legacy_circular_tension_regression']['max_force_difference_over_peak'])
(out/'release-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2))
