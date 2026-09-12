"""Verify the company identity, neutral icon, and representative header layouts."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from tensile_lab.gui import MainWindow
from tensile_lab.presets import make_config, example_path
from tensile_lab.storage import load_result

app = QApplication([])
for name in ('msyh.ttc', 'msyhbd.ttc', 'arial.ttf'):
    QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name))
app.setFont(QFont('Microsoft YaHei', 10))
assert not QIcon(str(ROOT / 'assets/lab.png')).isNull()
assert not (ROOT / 'assets/logo.jpeg').exists()
assert not (ROOT / 'assets/lab.ico').exists()
window = MainWindow()
window.show()
out = ROOT / 'verification-output/v2.1/branding'
out.mkdir(parents=True, exist_ok=True)
for width, height in ((1160, 680), (1280, 720), (1920, 1080)):
    window.resize(width, height)
    app.processEvents()
    label = window.company_label
    assert label.text() == '云南数美汇云软件有限公司'
    assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
    assert label.height() >= label.fontMetrics().height()
for experiment in ('buckling', 'compression'):
    result = load_result(example_path(make_config(experiment)))
    window._apply_config(result.config)
    window._on_complete(result)
    window.resize(1280, 720)
    window.style_combo.setCurrentIndex(window.style_combo.findData('realistic'))
    window.timeline.setValue(len(result.frames) - 1)
    app.processEvents()
    assert window.grab().save(str(out / f'preview-{experiment}.png'))
window.close()
(out / 'report.json').write_text(json.dumps({'passed': True, 'company': '云南数美汇云软件有限公司', 'header_sizes': 3}, ensure_ascii=False, indent=2), encoding='utf-8')
print('Branding verification passed')
