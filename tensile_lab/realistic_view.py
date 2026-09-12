"""Deterministic shared teaching animations, separate from numerical fields."""
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QLinearGradient
from .presets import make_config


def specimen_layout(kind, width, height):
    """One standard geometry per experiment, with isotropic screen scaling.

    Manual dimensions and material do not create new teaching animations.
    Length/diameter ratio comes from each experiment's own standard specimen.
    """
    reference = make_config(kind, 'circle', 'Fe')
    length_mm, diameter_mm = reference.gauge_length_mm, reference.diameter_mm
    displacement_mm = {'bending': .05*length_mm, 'buckling': .065*length_mm,
                       'shear': .32*diameter_mm}.get(kind, 0.)
    max_stretch = 1.14 if kind == 'tension' else 1.
    max_depth = diameter_mm*(1.23 if kind == 'compression' else 1.)
    usable_width = max(80., width-112.)
    usable_height = max(32., height-166.)
    scale = min(usable_width/(length_mm*max_stretch),
                usable_height/(max_depth+2*displacement_mm))
    length = length_mm*scale
    return dict(length_mm=length_mm, diameter_mm=diameter_mm,
                length=length, radius=diameter_mm*scale/2,
                left=48.+(usable_width-length*max_stretch)/2,
                cy=66.+usable_height/2, displacement=displacement_mm*scale)


def paint_realistic(view, p):
    w, h = view.width(), view.height()
    kind = getattr(view.config, 'experiment', 'tension')
    t = max(0., min(1., view.animation_progress)) if view.frame is not None else 0.
    p.fillRect(view.rect(), QColor('#edf2f6'))
    view._text(p, QRectF(14,4,w-28,23), '写实教学示意 · 同类实验共用动画', '#28445a', 9, True)
    view._text(p, QRectF(14,28,w-28,25), '裂纹、褶皱为视觉示意，非计算预测', '#7b8794', 8)
    geometry = specimen_layout(kind, w, h)
    left, length, cy, radius = (geometry[k] for k in ('left','length','cy','radius'))
    displacement = geometry['displacement']
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(31,49,64,22))
    p.drawEllipse(QRectF(left-8,cy+radius+24,length+18,15))
    stretch = 1+.14*t if kind=='tension' else 1-.12*t if kind=='compression' else 1.
    span=length*stretch
    def center(s):
        if kind=='bending': return cy+displacement*t*math.sin(math.pi*s)
        if kind=='buckling': return cy-displacement*t*t*math.sin(math.pi*s)
        if kind=='shear': return cy-displacement*t*(.5+.5*math.tanh((s-.5)*10))
        return cy
    def half(s):
        if kind=='tension': return radius*(1-.46*t*t*math.exp(-((s-.5)/.115)**2))
        if kind=='compression': return radius*(1+.23*t*math.sin(math.pi*s))
        if kind=='torsion': return radius*(.88+.12*math.cos(4*t*s))
        return radius
    def point(s, q):return QPointF(left+span*s,center(s)+half(s)*q)
    def skin(a,b):
        path=QPainterPath(point(a,-1))
        for i in range(1,81):path.lineTo(point(a+(b-a)*i/80,-1))
        for i in range(80,-1,-1):path.lineTo(point(a+(b-a)*i/80,1))
        path.closeSubpath();return path
    broken=kind=='tension' and t>.89
    gap=max(0.,(t-.89)*.24)
    regions=[(0,.5-gap),(.5+gap,1)] if broken else [(0,1)]
    metallic=QLinearGradient(0,cy-radius,0,cy+radius)
    for pos,color in [(0,'#526371'),(.28,'#b6c1ca'),(.43,'#f2f5f7'),(.56,'#a1aeb9'),(.8,'#637584'),(1,'#334858')]:metallic.setColorAt(pos,QColor(color))
    for a,b in regions:
        path=skin(a,b)
        p.setBrush(metallic);p.setPen(QPen(QColor('#4f6474'),1.2));p.drawPath(path)
        p.save();p.setClipPath(path)
        # Fixed surface coordinates prevent random texture flicker during replay.
        for i in range(180):
            s=((i*67)%181)/181
            q=((i*37)%173)/86.5-1
            start=point(s,q)
            p.setPen(QPen(QColor(28,43,53,20 if i%3 else 35),.6))
            p.drawLine(start,QPointF(start.x()+3+(i%9),start.y()+.35))
        for q in [-.72,-.38,.18,.58]:
            line=QPainterPath(point(0,q))
            for i in range(1,101):
                s=i/100
                qq=q if kind!='torsion' else .83*math.sin(math.asin(q)+t*4*s)
                line.lineTo(point(s,qq))
            p.setPen(QPen(QColor(240,247,250,85),1.));p.drawPath(line)
        if kind in ('compression','buckling'):
            amplitude=t*t*(2.6 if kind=='compression' else 1.3)
            for j in range(7):
                s=.32+j*.06
                fold=QPainterPath(point(s,-1))
                for i in range(1,31):
                    q=-1+2*i/30;pt=point(s,q)
                    fold.lineTo(QPointF(pt.x()+amplitude*math.sin(q*math.pi*2+j),pt.y()))
                p.setPen(QPen(QColor(29,43,51,round(100*t)),1.2));p.drawPath(fold)
                p.translate(1,0);p.setPen(QPen(QColor(247,249,251,round(125*t)),.8));p.drawPath(fold);p.translate(-1,0)
        if kind=='tension' and t>.57:
            severity=min(1.,(t-.57)/.32)
            for side in [-1,1]:
                crack=QPainterPath(point(.493,side))
                for i in range(1,9):
                    q=side*(1-severity*i/8)
                    crack.lineTo(point(.493+.008*math.sin(i*2.1),q))
                p.setPen(QPen(QColor('#2b3035'),.7+severity*1.5));p.drawPath(crack)
        p.restore()
    # Apparatus is also shared across specimen dimensions and materials.
    p.setPen(QPen(QColor('#708493'),1));p.setBrush(QColor('#afbdc8'))
    if kind in ('tension','compression','torsion','shear'):
        for s in (0,1):
            pt=point(s,0);p.drawRoundedRect(QRectF(pt.x()-8,pt.y()-radius-9,16,2*radius+18),3,3)
    if kind in ('bending','buckling'):
        view._pin(p,left,center(0)+radius);view._pin(p,left+span,center(1)+radius,True)
    if kind=='bending':view._arrow(p,QPointF(left+span/2,center(.5)-radius-30),point(.5,-1))
    elif kind=='torsion':
        p.setPen(QPen(QColor('#ce7948'),2));p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(left+span-14,cy-radius-20,30,2*radius+40),40*16,280*16)
    else:
        end=point(1,0)
        if kind=='shear':view._arrow(p,QPointF(end.x()+22,end.y()+22),QPointF(end.x()+22,end.y()-20))
        elif kind=='tension':view._arrow(p,QPointF(end.x()+12,end.y()),QPointF(end.x()+35,end.y()))
        else:view._arrow(p,QPointF(end.x()+35,end.y()),QPointF(end.x()+12,end.y()))
    captions={'tension':'拉伸 · 局部变细与表面开裂','compression':'压缩 · 鼓胀与表面褶皱','torsion':'扭转 · 表面纹理随截面转动','bending':'弯曲 · 梁体连续挠曲','shear':'剪切 · 截面相对错动','buckling':'压杆失稳 · 侧向弯曲'}
    view._text(p,QRectF(12,h-80,w-24,23),captions[kind],'#405d72',9,False,Qt.AlignmentFlag.AlignCenter)
    reference_label=f"动画参考试样：L {geometry['length_mm']:g} mm / D {geometry['diameter_mm']:g} mm · 等比例外形"
    view._text(p,QRectF(12,h-55,w-24,23),reference_label,'#60798b',8,False,Qt.AlignmentFlag.AlignCenter)
    view._text(p,QRectF(12,h-30,w-24,23),f'演示进度 {t:.0%} · 右侧曲线和读数来自实际计算','#7b8794',8,False,Qt.AlignmentFlag.AlignCenter)
