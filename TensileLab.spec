# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH)
datas = []
for package in ('numpy', 'scipy', 'numba', 'llvmlite', 'felupe', 'PySide6-Essentials', 'shiboken6', 'pyqtgraph'):
    datas += copy_metadata(package)
for folder in ('assets', 'third_party_licenses'):
    if (root / folder).is_dir():
        datas.append((str(root / folder), folder))
if (root / 'requirements-lock.txt').is_file():
    datas.append((str(root / 'requirements-lock.txt'), '.'))
for filename in ('使用说明.txt', '模型与数据说明.md', '示例_读取实验数据.py', 'README.md', '验收记录.md'):
    if (root / filename).is_file():
        datas.append((str(root / filename), '.'))
# Distribute only named, accepted classroom examples, never prototype records.
if (root / 'examples' / 'default_result.npz').is_file():
    datas.append((str(root / 'examples' / 'default_result.npz'), 'examples'))
for experiment in ('tension', 'compression', 'torsion', 'bending', 'shear', 'buckling'):
    for shape in ('circle', 'rectangle'):
        for material in ('Fe', 'Al'):
            sample = root / 'examples' / f'{experiment}_{shape}_{material}.npz'
            if not sample.is_file():
                raise RuntimeError(f'Missing accepted classroom example: {sample.name}')
            datas.append((str(sample), 'examples'))
# Numba's preferred explicit cache locator needs an existing source file.
for source_name in ('solver.py', 'axial_solver.py'):
    if (root / 'tensile_lab' / source_name).is_file():
        datas.append((str(root / 'tensile_lab' / source_name), 'tensile_lab'))

a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=['scipy.sparse.csgraph', 'scipy.sparse.linalg', 'llvmlite.binding'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'tkinter', 'IPython', 'jupyter', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TensileLab',
    icon=str(root / 'assets' / 'lab.ico') if (root / 'assets' / 'lab.ico').is_file() else None,
    version=str(root / 'packaging' / 'version_info.txt'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='TensileLab')
