# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import struct
from PyInstaller.utils.hooks import copy_metadata
from PyInstaller.config import CONF

root = Path(SPECPATH)
# Windows ICO can embed a 256px PNG directly; no image conversion dependency.
icon_png = (root / 'assets' / 'lab.png').read_bytes()
assert icon_png[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', icon_png[16:24]) == (256, 256)
icon_file = Path(CONF['workpath']) / 'lab-neutral.ico'
icon_file.parent.mkdir(parents=True, exist_ok=True)
icon_file.write_bytes(struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(icon_png), 22) + icon_png)
datas = []
for package in ('numpy', 'scipy', 'numba', 'llvmlite', 'felupe', 'PySide6-Essentials', 'PySide6-Addons', 'shiboken6', 'pyqtgraph'):
    datas += copy_metadata(package)
for folder in ('assets', 'third_party_licenses'):
    if (root / folder).is_dir():
        datas.append((str(root / folder), folder))
if (root / 'requirements-lock.txt').is_file():
    datas.append((str(root / 'requirements-lock.txt'), '.'))
for filename in ('使用说明.txt', '模型与数据说明.md', '示例_读取实验数据.py', 'README.md', '验收记录-v2.1.md', '改造说明-v2.1.md'):
    if (root / filename).is_file():
        datas.append((str(root / filename), '.'))
# Distribute only named, accepted classroom examples, never prototype records.
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
    binaries=[(str(root / 'tensile_lab' / '_native' / 'mechanics_core.dll'), 'tensile_lab/_native')],
    datas=datas,
    hiddenimports=['scipy.sparse.csgraph', 'scipy.sparse.linalg', 'llvmlite.binding',
                   'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets'],
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
    icon=str(icon_file),
    version=str(root / 'packaging' / 'version_info.txt'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='TensileLab')
