"""六类实验：数据、场结果、图片与可回放记录导出。"""
from pathlib import Path
from datetime import datetime
import csv
import json
import math
import numpy as np
from .storage import plain, save_result
from .plotting import CURVE_NAMES, curve_data, plot_range
from .presets import EXPERIMENTS


def _number(value):
    value = float(value)
    return format(value, '.10g') if math.isfinite(value) else ''


def export_result(result, folder):
    if not result.frames:
        raise ValueError('尚无可导出的实验数据')
    from .engine import decorate
    decorate(result)
    c, d = result.config, result.diagnostics
    name = EXPERIMENTS[c.experiment]
    parent = Path(folder)
    stem = name + '实验_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    destination = parent / stem
    suffix = 1
    while destination.exists():
        destination = parent / (stem + f'_{suffix}')
        suffix += 1
    destination.mkdir(parents=True)
    curve = destination / (CURVE_NAMES[c.experiment] + '数据.csv')
    # CSV stores base units; display scales never modify recorded values.
    candidates = [
        ('displacement_mm', 'displacement_mm'), ('force_n', 'force_N'),
        ('engineering_strain', 'engineering_strain'), ('engineering_stress_mpa', 'engineering_stress_MPa'),
        ('torque_n_mm', 'torque_N_mm'), ('twist_rad', 'twist_rad'),
        ('bending_moment_n_mm', 'bending_moment_N_mm'), ('deflection_mm', 'deflection_mm'),
        ('shear_force_n', 'shear_force_N'), ('shear_strain', 'shear_strain'),
        ('shear_stress_mpa', 'shear_stress_MPa'), ('critical_force_n', 'critical_force_N'),
        ('lateral_deflection_mm', 'lateral_deflection_mm'),
        ('max_stress_mpa', 'max_stress_MPa'), ('torsion_constant_mm4', 'torsion_constant_mm4'),
        ('critical_load_ratio', 'critical_load_ratio'), ('current_min_area_mm2', 'minimum_area_mm2'),
        ('current_min_width_mm', 'minimum_width_mm'), ('current_min_height_mm', 'minimum_height_mm'),
    ]
    relevant = {
        'torsion': {'torque_n_mm', 'twist_rad', 'shear_stress_mpa', 'torsion_constant_mm4'},
        'bending': {'force_n', 'deflection_mm', 'bending_moment_n_mm', 'max_stress_mpa'},
        'shear': {'shear_force_n', 'displacement_mm', 'shear_strain', 'shear_stress_mpa'},
        'buckling': {'force_n', 'displacement_mm', 'engineering_strain', 'engineering_stress_mpa',
                     'lateral_deflection_mm', 'critical_force_n', 'critical_load_ratio', 'max_stress_mpa'},
    }
    allowed = relevant.get(c.experiment, {key for key, _ in candidates})
    columns = [(key, label) for key, label in candidates if key in allowed and any(key in f for f in result.frames)]
    axial_circle = c.experiment in ('tension', 'compression') and c.section_shape == 'circle'
    with curve.open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(['step'] + [label for _, label in columns] +
                        (['minimum_diameter_mm'] if axial_circle else []) +
                        ['max_eq_plastic_strain', 'max_damage', 'active_elements', 'stage'])
        for frame in result.frames:
            row = [frame.get('step', 0)] + [_number(frame[key]) if key in frame else '' for key, _ in columns]
            if axial_circle:
                row.append(_number(2*frame['min_radius_mm']))
            row.extend([_number(np.max(frame['cell_eq_plastic_strain'])),
                        _number(np.max(frame['cell_damage'])),
                        int(np.count_nonzero(frame['cell_active'])), frame['stage']])
            writer.writerow(row)
    field_path = destination / '最后加载步_场结果.csv'
    frame = result.frames[-1]
    centers = np.asarray(frame['points_mm'])[np.asarray(result.cells)].mean(axis=1)
    fields = [('cell_stress_axial_mpa', 'axial_stress_MPa'), ('cell_shear_stress_mpa', 'shear_stress_MPa'),
              ('cell_eq_plastic_strain', 'eq_plastic_strain'), ('cell_damage', 'damage')]
    fields = [(key, label) for key, label in fields if key in frame]
    with field_path.open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(['cell_id', 'x_mm', 'y_or_radius_mm'] + [label for _, label in fields] + ['active'])
        for i, center in enumerate(centers):
            writer.writerow([i, _number(center[0]), _number(center[1])] +
                            [_number(frame[key][i]) for key, _ in fields] + [int(frame['cell_active'][i])])
    metadata = {
        'description': name + '教学仿真实验', 'exported_at': datetime.now().isoformat(timespec='seconds'),
        'config': c.to_dict(), 'summary': plain(result.summary), 'diagnostics': plain(d),
        'units': {'length': 'mm', 'force': 'N', 'stress': 'MPa', 'moment': 'N·mm', 'angle': 'rad',
                  'energy': 'N·mm', 'strain': '无量纲'},
        'config_units': {'young_mpa': 'MPa', 'yield_mpa': 'MPa', 'hardening_q_mpa': 'MPa',
                         'gauge_length_mm': 'mm', 'diameter_mm': 'mm', 'width_mm': 'mm', 'height_mm': 'mm',
                         'fracture_energy_n_mm': 'N/mm（单位裂面面积的断裂能）',
                         'damage_onset': '累积等效塑性应变，无量纲'},
        'curve': {'x_key': d.get('plot_x_key'), 'y_key': d.get('plot_y_key'),
                  'x_label': d.get('plot_x_label'), 'y_label': d.get('plot_y_label'),
                  'x_display_scale': d.get('plot_x_scale', 1), 'y_display_scale': d.get('plot_y_scale', 1)},
        'field_definition': d.get('field_label', '轴向应力 / MPa'),
    }
    params = destination / '实验参数与诊断.json'
    params.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = destination / '完整实验记录.npz'
    save_result(result, archive)
    readme = destination / '数据说明.txt'
    sign_note = ('失稳实验 force_N 为轴压力的正幅值；engineering_stress_MPa=-force_N/A0，工程压应变为负。\n'
                 if c.experiment == 'buckling' else
                 '轴向实验拉伸正、压缩负；工程应力=带符号端部反力/初始名义截面积，工程应变=长度变化/初始长度。\n')
    readme.write_text(
        '虚拟仿真实验室 · ' + name + '实验数据\n\n' +
        '模型：' + d.get('model_name', '') + '\n' + d.get('model_note', '') + '\n\n' +
        '这是由材料参数、试样尺寸和加载条件计算的教学仿真数据，并非实测数据。\n'
        'Fe、Al 为教学代表参数，不对应已标定的具体牌号。CSV 为带 BOM 的 UTF-8，可用 Excel 打开。\n'
        'strain 字段为无量纲小数，0.01=1%；力为 N，长度为 mm，应力为 MPa，扭矩/弯矩为 N·mm，角度为 rad。\n'
        '显示曲线可能使用 %、kN、N·m、°；对应换算系数保存在 JSON 的 curve 项。\n'
        + sign_note +
        '非轴向实验请使用其专用物理量列；兼容的 engineering_* 列不应替代对应实验定义。\n'
        '圆棒轴对称坐标为 (轴向x,半径r)，其他模型为 (x,y)；显示变形放大不影响导出坐标和数值。\n'
        '梁/杆模型场图为截面假设下恢复的应力，不是三维实体网格计算。扭转、剪切使用剪应力列。\n'
        'active=0 表示退出传力的单元。中止或取消的记录只包含已完成加载步；状态见 JSON。\n'
        '完整实验记录.npz 可在程序中回放，包含每一步的坐标、场量与计算状态。\n', encoding='utf-8')
    image_path = _curve_png(result, destination)
    return {'folder': str(destination), 'csv': str(curve), 'fields': str(field_path),
            'parameters': str(params), 'archive': str(archive), 'image': image_path}


def _curve_png(result, destination):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter, QPen, QColor, QFont, QPainterPath
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        return None
    xs, ys, xlabel, ylabel = curve_data(result)
    xmin, xmax = plot_range(xs)
    ymin, ymax = plot_range(ys)
    image = QImage(1400, 950, QImage.Format.Format_ARGB32)
    image.fill(QColor('#ffffff'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(QFont('Microsoft YaHei', 15))
    left, top, width, height = 165., 130., 1130., 640.
    def position(x, y):
        return QPointF(left+width*(x-xmin)/(xmax-xmin), top+height*(ymax-y)/(ymax-ymin))
    painter.setPen(QColor('#1b2e45'))
    painter.setFont(QFont('Microsoft YaHei', 23))
    painter.drawText(QRectF(70, 35, 1260, 60), Qt.AlignmentFlag.AlignCenter,
                     EXPERIMENTS[result.config.experiment] + '实验 · ' + CURVE_NAMES[result.config.experiment] + '曲线')
    painter.setFont(QFont('Microsoft YaHei', 15))
    for i in range(6):
        x, y = xmin+(xmax-xmin)*i/5, ymin+(ymax-ymin)*i/5
        px, py = position(x, 0).x(), position(0, y).y()
        painter.setPen(QPen(QColor('#e1e7ee'), 1))
        painter.drawLine(QPointF(px, top), QPointF(px, top+height))
        painter.drawLine(QPointF(left, py), QPointF(left+width, py))
        painter.setPen(QColor('#263a50'))
        painter.drawText(QRectF(px-65, top+height+12, 130, 35), Qt.AlignmentFlag.AlignCenter, f'{x:.4g}')
        painter.drawText(QRectF(10, py-17, 135, 35), Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,
                         f'{0. if abs(y)<1e-12 else y:.4g}')
    painter.setPen(QPen(QColor('#8a99a9'), 1.5))
    painter.drawRect(QRectF(left, top, width, height))
    path = QPainterPath(position(xs[0], ys[0]))
    for x, y in zip(xs[1:], ys[1:]):
        path.lineTo(position(x,y))
    painter.setPen(QPen(QColor('#176abb'), 3))
    painter.drawPath(path)
    painter.setPen(QColor('#1b2e45'))
    painter.drawText(QRectF(550, 820, 750, 40), Qt.AlignmentFlag.AlignRight, xlabel)
    painter.drawText(QRectF(left, 90, 750, 40), ylabel)
    painter.setFont(QFont('Microsoft YaHei', 12))
    shape = '圆形' if result.config.section_shape == 'circle' else '矩形'
    painter.drawText(QRectF(left, 890, 1150, 30),
                     '教学仿真数据 · ' + result.config.material_name + ' · ' + shape + ' · ' + str(result.frames[-1].get('stage', '')))
    painter.end()
    filename = destination / (CURVE_NAMES[result.config.experiment] + '曲线.png')
    if not image.save(str(filename)):
        raise OSError('曲线图片保存失败')
    return str(filename)
