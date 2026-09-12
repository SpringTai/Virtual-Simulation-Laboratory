"""Recompute only migrated models; preserve a recoverable sample baseline."""
from pathlib import Path
import sys
import shutil
import json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tensile_lab.engine import simulate
from tensile_lab.presets import make_config,example_path
from tensile_lab.storage import save_result,load_result

backup=ROOT/'verification-output/v2.1/sample-backup';backup.mkdir(parents=True,exist_ok=True)
report=[]
for experiment in ('tension','compression','torsion','bending','buckling'):
    for shape in (('rectangle',) if experiment in ('tension','compression') else ('circle','rectangle')):
        for material in ('Fe','Al'):
            c=make_config(experiment,shape,material);path=example_path(c)
            if not (backup/path.name).exists():shutil.copy2(path,backup/path.name)
            r=simulate(c);assert r.diagnostics['status']=='completed'
            save_result(r,path)
            assert load_result(path).config.to_dict()==c.to_dict()
            report.append(path.name)
target=ROOT/'verification-output/v2.1/refreshed-examples.json';target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(report,indent=2),encoding='utf-8');print('Recomputed examples:',len(report))
