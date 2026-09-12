"""Record the exact installed dependencies and cached Windows wheels."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
license_root = ROOT / 'third_party_licenses'
license_root.mkdir(exist_ok=True)
packages = sorted(
    (dist.metadata['Name'], dist.version)
    for dist in importlib.metadata.distributions()
    if dist.metadata['Name'].lower() not in ('pip', 'ziglang')
)
(ROOT / 'requirements-lock.txt').write_text(
    '# CPython 3.12 / Windows x64; all dependencies are cached in offline_packages.\n'
    + ''.join(f'{name}=={version}\n' for name, version in packages),
    encoding='utf-8',
)
wheels = []
for wheel in sorted((ROOT / 'offline_packages').glob('*.whl')):
    wheels.append({
        'filename': wheel.name,
        'bytes': wheel.stat().st_size,
        'sha256': hashlib.file_digest(wheel.open('rb'), 'sha256').hexdigest(),
    })
manifest = {
    'python': sys.version.split()[0],
    'platform': platform.platform(),
    'architecture': platform.machine(),
    'packages': dict(packages),
    'wheels': wheels,
}
(ROOT / 'offline_packages' / 'manifest.json').write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
)
(ROOT / 'offline_packages' / 'SHA256SUMS.txt').write_text(
    ''.join(f"{item['sha256']}  {item['filename']}\n" for item in wheels), encoding='utf-8'
)
for dist in importlib.metadata.distributions():
    name = dist.metadata['Name']
    for item in dist.files or ():
        lowered = str(item).lower()
        if ('license' in lowered or 'copying' in lowered or 'notice' in lowered) and not lowered.endswith(('.py', '.pyc')):
            source = Path(dist.locate_file(item))
            if source.is_file():
                target = license_root / name / str(item).replace('..', '_parent_')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.is_file():
    (license_root / 'CPython').mkdir(exist_ok=True)
    shutil.copy2(python_license, license_root / 'CPython' / 'LICENSE.txt')
(license_root / 'README.txt').write_text(
    'This distribution includes third-party Python packages and dynamically linked Qt libraries.\n'
    'The package versions are listed in requirements-lock.txt. Their supplied license notices\n'
    'are retained in the subdirectories. Qt/PySide6 library files remain separate in the\n'
    'application _internal directory.\n', encoding='utf-8'
)
print(f'Recorded {len(packages)} locked packages and {len(wheels)} cached wheels.')
