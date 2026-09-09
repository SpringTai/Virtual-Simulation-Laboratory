"""Verify cached wheel bytes against the hashes published by PyPI itself."""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request
from pip._vendor.packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'offline_packages'

def verify(path: Path) -> dict:
    distribution, version, _, _ = parse_wheel_filename(path.name)
    url = f'https://pypi.org/pypi/{urllib.parse.quote(str(distribution))}/{version}/json'
    error = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=25) as response:
                published = json.load(response)
            break
        except Exception as exc:
            error = exc
    else:
        raise RuntimeError(f'{path.name}: could not retrieve PyPI metadata: {error}')
    entry = next((item for item in published['urls'] if item['filename'] == path.name), None)
    if entry is None:
        raise RuntimeError(f'{path.name}: filename is absent from PyPI metadata')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    expected = entry['digests']['sha256']
    if actual != expected:
        raise RuntimeError(f'{path.name}: SHA256 mismatch')
    return {'filename': path.name, 'sha256': actual, 'verified_against': url, 'match': True}

if __name__ == '__main__':
    files = sorted(CACHE.glob('*.whl'))
    if not files:
        raise SystemExit('No cached wheels found.')
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(verify, files))
    (CACHE / 'pypi-verification.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'All {len(results)} cached wheels match the SHA256 digests published by PyPI.')
