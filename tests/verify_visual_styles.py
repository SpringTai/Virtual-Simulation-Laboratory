"""Exercise both views at two classroom sizes, including switching mid-playback."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase,QFont
from tensile_lab.gui import MainWindow
from tensile_lab.presets import make_config,example_path,EXPERIMENTS
from tensile_lab.storage import load_result
from tensile_lab.realistic_view import specimen_layout

# Geometry regression: each animation preserves its standard length/diameter
# ratio at every viewport size; slender buckling and squat compression differ.
for viewport in [(285,208),(486,289),(900,640)]:
    for kind in EXPERIMENTS:
        layout=specimen_layout(kind,*viewport);reference=make_config(kind)
        ratio=layout['length']/(2*layout['radius'])
        assert abs(ratio-reference.gauge_length_mm/reference.diameter_mm)<1e-10
    assert specimen_layout('buckling',*viewport)['radius'] < specimen_layout('compression',*viewport)['radius']/5

app=QApplication([])
for name in ('msyh.ttc','msyhbd.ttc','arial.ttf'):
    QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name))
app.setFont(QFont('Microsoft YaHei',10))
window=MainWindow();window.show();app.processEvents()
out=ROOT/'verification-output/v2.1/visual';out.mkdir(parents=True,exist_ok=True)
count=0
for size in [(1280,720),(1920,1080)]:
    window.resize(*size)
    for experiment in EXPERIMENTS:
        result=load_result(example_path(make_config(experiment)))
        window._apply_config(result.config);window._on_complete(result)
        for style in ('realistic','mesh'):
            window.style_combo.setCurrentIndex(window.style_combo.findData(style))
            for progress in (0,.75,1):
                index=round(progress*(len(result.frames)-1));window.timeline.setValue(index);app.processEvents()
                assert window._current_index==index
                assert window.visual_stack.currentWidget() is (window.specimen_view if style=='mesh' else window.video_view)
                assert window.specimen_view.visual_style=='mesh'
                assert window.field_combo.isVisible()==(style=='mesh')
                if progress in (0,.75,1):
                    assert window.grab().save(str(out/f'{experiment}_{style}_{size[0]}_{progress}.png'))
                count+=1
window.close();(out/'report.json').write_text(json.dumps({'passed':True,'states':count}),encoding='utf-8')
print('Visual states passed:',count)
