"""Versioned C ABI bridge. Set MECHANICS_BACKEND=python for regression checks."""
import ctypes as ct
import os
from pathlib import Path
import numpy as np

_library = None
_reason = ''

def library():
    global _library, _reason
    mode = os.environ.get('MECHANICS_BACKEND', 'auto')
    if mode not in ('auto', 'cpp', 'python'):
        raise ValueError('MECHANICS_BACKEND must be auto, cpp or python')
    if mode == 'python':
        return None
    if _library is None:
        path = Path(__file__).parent / '_native' / 'mechanics_core.dll'
        try:
            lib = ct.CDLL(str(path))
            lib.mechanics_abi_version.restype = ct.c_int
            if lib.mechanics_abi_version() != 1:
                raise RuntimeError('Unsupported mechanics native ABI')
            ptr = ct.POINTER(ct.c_double)
            lib.assemble.argtypes = [ct.c_int, ct.c_double, ct.c_double, ct.c_int, ptr, ptr]
            lib.assemble.restype = ct.c_int
            lib.rod_advance.argtypes = [ct.c_int, ct.c_int, ct.c_int, ptr, ct.POINTER(ptr), ptr]
            lib.rod_advance.restype = ct.c_int
            _library = lib
        except (OSError, RuntimeError) as exc:
            _reason = str(exc)
            if mode == 'cpp':
                raise RuntimeError('C++ core unavailable: ' + _reason) from exc
            return None
    return _library

def pointer(array):
    if array.dtype != np.float64 or not array.flags.c_contiguous or not array.flags.writeable:
        raise ValueError('Native buffers must be writable contiguous float64 arrays')
    return array.ctypes.data_as(ct.POINTER(ct.c_double))

def matrices(n, length, rigidity, beam):
    lib = library()
    if lib is None:
        return None
    if not 1 <= n <= 160 or not np.isfinite([length, rigidity]).all() or min(length, rigidity) <= 0:
        raise ValueError('Invalid native element parameters')
    size = (2 if beam else 1)*(n+1)
    k = np.zeros((size, size)); g = np.zeros_like(k)
    if lib.assemble(n, length, rigidity, beam, pointer(k), pointer(g)):
        raise RuntimeError('C++ matrix assembly failed')
    return k, g

def rod_advance(*args):
    count, start, dt, duration, maximum, hold = args[:6]
    arrays = list(args[6:22])
    damping, young, poisson, sy, q, b, onset, energy, damage_enabled, last = args[22:]
    n = len(arrays[5])
    if any(a.ndim != 1 or len(a) != (n+1 if i < 5 else n) for i,a in enumerate(arrays)):
        raise ValueError('Inconsistent native rod buffer sizes')
    internal = np.zeros(n+1); arrays.append(internal)
    params = np.array([dt,duration,maximum,hold,damping,young,poisson,sy,q,b,onset,energy,damage_enabled,last], dtype=float)
    buffers = (ct.POINTER(ct.c_double)*len(arrays))(*(pointer(a) for a in arrays))
    out = np.zeros(4)
    if library().rod_advance(n,count,start,pointer(params),buffers,pointer(out)):
        raise RuntimeError('C++ rod integration failed')
    return internal, int(out[0]), int(out[1]), out[2], out[3]
