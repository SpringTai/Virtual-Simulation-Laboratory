"""Build with the isolated Zig C++ compiler: python native/build.py."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
output = root / 'tensile_lab' / '_native' / 'mechanics_core.dll'
output.parent.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, '-m', 'ziglang', 'c++', '-std=c++17', '-O3',
                '-ffp-contract=off', '-shared', '-static', str(root/'native/core.cpp'),
                '-o', str(output)], check=True)
print(output)
