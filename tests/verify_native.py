"""Compare both engines on full nonlinear histories and assembled operators."""
import os
import sys
import json
import time
from pathlib import Path
from dataclasses import replace
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tensile_lab.engine import simulate
from tensile_lab.presets import make_config
from tensile_lab.structural_solver import _beam_matrices, _line_stiffness
from tensile_lab.native_backend import library

def main():
    report={'passed':False,'calculations':[]}
    os.environ['MECHANICS_BACKEND']='cpp';assert library() is not None
    for n in (4,20,160):
        for fn in (_beam_matrices,_line_stiffness):
            os.environ['MECHANICS_BACKEND']='python';a=fn(n,240.,8.3e7)
            os.environ['MECHANICS_BACKEND']='cpp';b=fn(n,240.,8.3e7)
            for x,y in zip(a,b):np.testing.assert_allclose(x,y,rtol=1e-10,atol=1e-8)
    configs=[make_config(e,'rectangle',m) for e in ('tension','compression') for m in ('Fe','Al')]
    configs += [replace(make_config(e,s,m),mesh_axial=12,output_steps=12) for e in ('torsion','bending','buckling') for s in ('circle','rectangle') for m in ('Fe','Al')]
    # Warm Numba once so timing comparisons exclude compilation.
    os.environ['MECHANICS_BACKEND']='python'
    simulate(replace(configs[0],mesh_axial=4,output_steps=10,max_strain=.0005))
    for c in configs:
        pair=[];timings={}
        for mode in ('python','cpp'):
            os.environ['MECHANICS_BACKEND']=mode;t=time.perf_counter();pair.append(simulate(c));timings[mode]=time.perf_counter()-t
        a,b=pair
        assert len(a.frames)==len(b.frames)
        maximum=0.
        for fa,fb in zip(a.frames,b.frames):
            for key,value in fa.items():
                if isinstance(value,np.ndarray) or isinstance(value,(float,int)):
                    x=np.asarray(value);y=np.asarray(fb[key])
                    if x.dtype.kind=='b':np.testing.assert_array_equal(x,y)
                    else:
                        scale=max(1.,float(np.max(np.abs(x)))) if x.size else 1.
                        # Residual forces after complete fracture are near zero;
                        # allow 1e-6 absolute units for cross-compiler roundoff.
                        np.testing.assert_allclose(x,y,rtol=2e-7,atol=max(1e-6,2e-8*scale),err_msg=key)
                        if x.size:maximum=max(maximum,float(np.max(np.abs(x-y)))/scale)
        assert a.summary['fractured']==b.summary['fractured']
        row=dict(experiment=c.experiment,shape=c.section_shape,material=c.material_name,max_scaled_error=maximum,seconds=timings)
        print(json.dumps(row),flush=True);report['calculations'].append(row)
    report['passed']=True
    target=ROOT/'verification-output/v2.1/native-parity.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')

if __name__=='__main__':main()
