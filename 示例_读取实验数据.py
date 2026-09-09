"""Python课堂示例：读取实验CSV，并选择对应的实验量。仅使用标准库。"""
import csv
import sys
from pathlib import Path


def read_curve(filename):
    with Path(filename).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def fit_elastic_modulus(rows, max_strain=.0008):
    pairs = [(float(r['engineering_strain']), float(r['engineering_stress_MPa']))
             for r in rows if 0 < abs(float(r['engineering_strain'])) <= max_strain]
    if len(pairs) < 2:
        raise ValueError('弹性段记录不足；可缩小最大加载应变后重新计算。')
    return sum(e*s for e,s in pairs)/sum(e*e for e,_ in pairs)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('请在程序文件名后指定导出的CSV文件。')
        raise SystemExit(1)
    rows = read_curve(sys.argv[1])
    print(f'共 {len(rows)} 条加载记录')
    for key in ('force_N', 'engineering_stress_MPa', 'torque_N_mm', 'twist_rad',
                'deflection_mm', 'shear_stress_MPa', 'shear_strain', 'critical_force_N', 'lateral_deflection_mm'):
        if key in rows[0]:
            print(f'{key} 的最大绝对值：{max(abs(float(r[key])) for r in rows):.6g}')
    if 'critical_force_N' in rows[0] or all(abs(float(r.get('engineering_strain',0))) == 0 for r in rows):
        raise SystemExit(0)
    try:
        print(f'轴向初始弹性段拟合模量：{fit_elastic_modulus(rows)/1000:.2f} GPa')
    except ValueError as error:
        print(error)
