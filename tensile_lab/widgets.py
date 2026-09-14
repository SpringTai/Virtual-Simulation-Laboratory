"""Classroom views driven by solver coordinates and recovered fields."""
from __future__ import annotations
import math
import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, QUrl
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QFont, QLinearGradient
from PySide6.QtWidgets import QWidget, QFrame, QLabel, QVBoxLayout
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

COLORS = [QColor(c) for c in ("#234b88", "#287ab1", "#3fb6ba", "#b9d968", "#f2c35c", "#de654b")]
def field_color(value, low, high):
    position=float(np.clip((value-low)/max(high-low,1e-12),0,1))*(len(COLORS)-1)
    index=min(int(position),len(COLORS)-2)
    a,b,f=COLORS[index],COLORS[index+1],position-index
    return QColor(round(a.red()*(1-f)+b.red()*f),round(a.green()*(1-f)+b.green()*f),round(a.blue()*(1-f)+b.blue()*f))

class VideoAnimation(QWidget):
    """Packaged MP4 view with its original audio track enabled."""
    FRACTURE_MS = 8300
    def __init__(self, video_path, parent=None):
        super().__init__(parent)
        self.setMinimumSize(285,208)
        self._pending_position=0
        self.video=QVideoWidget(self);self.video.setStyleSheet("background: #050505;")
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.addWidget(self.video)
        self.audio=QAudioOutput(self);self.audio.setMuted(False);self.audio.setVolume(1.)
        self.player=QMediaPlayer(self);self.player.setAudioOutput(self.audio);self.player.setVideoOutput(self.video)
        self.player.durationChanged.connect(lambda _duration:self.seek_ms(self._pending_position))
        self.player.setSource(QUrl.fromLocalFile(str(video_path)))
    def is_playing(self):return self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState
    def seek_ms(self, position):
        self._pending_position=max(0,round(float(position)))
        if self.player.duration()>0:self.player.setPosition(round(float(np.clip(self._pending_position,0,self.player.duration()))))
    def play(self):self.player.play()
    def pause(self):self.player.pause()
    def set_playback_rate(self, rate):self.player.setPlaybackRate(float(rate))

class MetricCard(QFrame):
    def __init__(self,title,unit,parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.unit=unit
        layout=QVBoxLayout(self);layout.setContentsMargins(13,8,13,8);layout.setSpacing(3)
        self.caption,self.value=QLabel(title),QLabel("—")
        self.caption.setObjectName("metricCaption");self.value.setObjectName("metricValue")
        self.value.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.caption);layout.addWidget(self.value)
    def set_value(self,number=None,decimals=2):
        value=None if number is None else float(number)
        if value is not None and round(value,decimals)==0:value=0.
        self.value.setText("—" if value is None else f"{value:,.{decimals}f} {self.unit}")

class SpecimenView(QWidget):
    FIELDS={"轴向应力":("cell_stress_axial_mpa","MPa"),"等效塑性应变":("cell_eq_plastic_strain",""),"损伤":("cell_damage",""),"变形":(None,"")}
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumSize(285,208);self.setMouseTracking(True)
        self.initial_points=self.cells=self.frame=None
        self.preview_length,self.preview_diameter=40.,10.
        self.view_length,self.view_radius,self.max_displacement_y=66.,5.,0.
        self.field_limits,self.meta={},{}
        self.config=None
        self.field,self.show_mesh,self.magnification="轴向应力",True,1.
        self._hit_cells=[]
        self.visual_style = 'realistic'
        self.animation_progress = 0.
    def set_visual_style(self, style):
        self.visual_style = style
        self.update()
    def configure(self,config,metadata=None):
        self.config=config
        experiment=getattr(config,"experiment","tension");shape=getattr(config,"section_shape","circle")
        kind=("axisymmetric" if shape=="circle" else "solid2d") if experiment in ("tension","compression") else {"bending":"beam","buckling":"buckling","torsion":"torsion","shear":"shear"}[experiment]
        self.meta={"view_kind":kind,"field_label":"轴向应力","field_key":"cell_stress_axial_mpa"}
        self.meta.update(metadata or {})
        label=self.meta.get("field_label","轴向应力")
        self.FIELDS={label:(self.meta.get("field_key","cell_stress_axial_mpa"),"MPa")}
        if experiment in ("tension","compression"):self.FIELDS.update({"等效塑性应变":("cell_eq_plastic_strain",""),"损伤":("cell_damage","")})
        self.FIELDS["变形"]=(None,"")
        if self.field not in self.FIELDS:self.field=label
        self.update()
    def set_preview(self,length,diameter):
        self.preview_length,self.preview_diameter=float(length),float(diameter)
        self.view_length,self.view_radius=length,diameter/2
        self.max_displacement_y=0.;self.initial_points=self.cells=self.frame=None;self.field_limits={};self.update()
    def set_mesh(self,initial_points,cells):
        self.initial_points,self.cells=np.asarray(initial_points,float),np.asarray(cells,int);self.update()
    def set_view_extent(self,maximum_length,radius,displacement_y=0.):
        self.view_length=max(float(maximum_length),1e-6);self.view_radius=max(float(radius),1e-6)
        self.max_displacement_y=max(float(displacement_y),0.);self.update()
    def set_field_limits(self,limits):self.field_limits=dict(limits);self.update()
    def set_frame(self,frame):
        self.frame=frame
        if frame is not None and frame.get("initial_points") is not None and frame.get("cells") is not None:
            self.initial_points=np.asarray(frame["initial_points"],float);self.cells=np.asarray(frame["cells"],int)
        self.update()
    def set_field(self,field):self.field=field;self.update()
    def set_mesh_visible(self,value):self.show_mesh=bool(value);self.update()
    def set_magnification(self,factor):self.magnification=float(factor);self.update()
    def _text(self,p,rect,text,color="#60768a",size=9,bold=False,alignment=Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter):
        font=QFont("Microsoft YaHei UI",size);font.setBold(bold);p.setFont(font);p.setPen(QColor(color));p.drawText(rect,alignment,str(text))
    def _arrow(self,p,start,end,color="#ce7948",width=2.3):
        p.setPen(QPen(QColor(color),width));p.drawLine(start,end)
        angle=math.atan2(end.y()-start.y(),end.x()-start.x())
        for delta in (-.48,.48):p.drawLine(QPointF(end.x()-7*math.cos(angle+delta),end.y()-7*math.sin(angle+delta)),end)
    def _fixed(self,p,x,y,halfheight):
        p.setPen(QPen(QColor("#8da4b5"),2));p.drawLine(QPointF(x,y-halfheight),QPointF(x,y+halfheight))
        p.setPen(QPen(QColor("#b4c4d0"),1))
        for yy in np.arange(y-halfheight,y+halfheight,8):p.drawLine(QPointF(x,yy),QPointF(x-8,yy+7))
    def _pin(self,p,x,y,roller=False):
        p.setPen(QPen(QColor("#90a7b9"),1.5));p.setBrush(QColor("#e6eef4"))
        p.drawPolygon(QPolygonF([QPointF(x,y),QPointF(x-9,y+14),QPointF(x+9,y+14)]))
        if roller:
            for xx in (x-5,x+5):p.drawEllipse(QPointF(xx,y+17),2.5,2.5)
        p.drawLine(QPointF(x-14,y+22),QPointF(x+14,y+22))
    def _legend(self,p,low,high):
        key,unit=self.FIELDS.get(self.field,(None,""));w,h=self.width(),self.height()
        if not key or self.frame is None:
            self._text(p,QRectF(12,h-35,w-24,24),"试样预览 · 选择课堂示例或开始计算" if self.frame is None else "显示位移计算结果",alignment=Qt.AlignmentFlag.AlignCenter);return
        length=min(w-90,260);left=(w-length)/2
        gradient=QLinearGradient(left,0,left+length,0)
        for i,color in enumerate(COLORS):gradient.setColorAt(i/(len(COLORS)-1),color)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(gradient);p.drawRoundedRect(QRectF(left,h-36,length,8),4,4)
        self._text(p,QRectF(12,h-62,w-24,23),self.field+(f" / {unit}" if unit else ""),alignment=Qt.AlignmentFlag.AlignCenter)
        formatter=".1f" if unit else ".3f"
        if round(low,1 if unit else 3)==0:low=0.
        if round(high,1 if unit else 3)==0:high=0.
        self._text(p,QRectF(left,h-27,length,24),f"{low:{formatter}}",size=8)
        self._text(p,QRectF(left,h-27,length,24),f"{high:{formatter}} {unit}",size=8,alignment=Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.fillRect(self.rect(),QColor("#fbfcfd"));self._hit_cells=[]
        if self.visual_style == 'realistic':
            from .realistic_view import paint_realistic
            paint_realistic(self, p)
            p.end()
            return
        w,h=self.width(),self.height();experiment=getattr(self.config,"experiment","tension");kind=self.meta.get("view_kind","axisymmetric")
        descriptions={"axisymmetric":"圆形截面 · 轴对称剖面","solid2d":"矩形截面 · 纵向剖面","rod":"矩形截面 · 纵向剖面","beam":"梁的侧面","buckling":"压杆的侧面","torsion":"扭转外观 · 按计算转角投影","shear":"剪切变形示意"}
        self._text(p,QRectF(14,3,w-28,22),descriptions.get(kind,"变形与受力"))
        name="转角显示" if kind=="torsion" else "变形显示"
        self._text(p,QRectF(14,25,w-28,22),f"{name} ×{self.magnification:g}"+(" · 真实比例" if self.magnification==1 else " · 读数与导出保持实际数值"),color="#627b8f" if self.magnification==1 else "#ac733e",size=8)
        box=QRectF(51,67,max(80,w-111),max(28,h-173))
        radius=self.view_radius+self.magnification*self.max_displacement_y
        scale=min(box.width()/self.view_length,box.height()/max(2*radius,1e-6))
        cy=box.center().y();origin=float(self.initial_points[:,0].min()) if self.initial_points is not None else 0.;x0=box.left()
        transform=lambda x,y:QPointF(x0+(x-origin)*scale,cy-y*scale)
        initial=self.initial_points;points=None
        if self.frame is not None and initial is not None:points=initial+self.magnification*(np.asarray(self.frame["points_mm"],float)-initial)
        length=float(getattr(self.config,"gauge_length_mm",self.preview_length));xend=x0+length*scale
        key,unit=self.FIELDS.get(self.field,(None,""));low,high=0.,1.
        values=np.zeros(len(self.cells)) if self.cells is not None else np.zeros(1)
        if self.frame is not None and key:
            values=np.asarray(self.frame.get(key,values),float);good=values[np.isfinite(values)]
            if kind=="torsion":
                surface_values=np.asarray(self.frame.get("torsion_surface_shear_mpa",[]),float)
                good=np.concatenate([good,surface_values[np.isfinite(surface_values)]])
            low=min(0.,float(good.min())) if len(good) else 0.;high=max(1e-9,float(good.max())) if len(good) else 1.
            low,high=self.field_limits.get(self.field,(low,high))
        p.setPen(QPen(QColor("#c2d0da"),1,Qt.PenStyle.DashLine));p.drawLine(QPointF(x0-20,cy),QPointF(x0+self.view_length*scale+20,cy))
        if kind=="torsion":xend=self._torsion(p,transform,cy,scale,length,low,high,values,key)
        elif points is None:
            halfheight=self.preview_diameter/2;rect=QRectF(x0,cy-halfheight*scale,length*scale,2*halfheight*scale)
            p.setPen(QPen(QColor("#8daec5"),1.1));p.setBrush(QColor("#deebf4"));p.drawRect(rect)
            if self.show_mesh:
                p.setPen(QPen(QColor("#b2c9d9"),.6))
                for xx in np.linspace(rect.left(),rect.right(),18):p.drawLine(QPointF(xx,rect.top()),QPointF(xx,rect.bottom()))
                for yy in np.linspace(rect.top(),rect.bottom(),5):p.drawLine(QPointF(rect.left(),yy),QPointF(rect.right(),yy))
        else:
            active=np.asarray(self.frame.get("cell_active",np.ones(len(self.cells))),bool);sides=(-1,1) if kind=="axisymmetric" else (1,)
            for i,cell in enumerate(self.cells):
                if not active[i]:continue
                value=float(values[i]) if i<len(values) else 0.;color=field_color(value,low,high) if key else QColor("#78accb")
                p.setBrush(color);p.setPen(QPen(QColor(28,62,90,90),.5) if self.show_mesh else QPen(color,.5))
                for side in sides:
                    poly=QPolygonF([transform(points[node,0],side*points[node,1]) for node in cell]);p.drawPolygon(poly);self._hit_cells.append((poly,i,value))
            xend=transform(float(points[:,0].max()),0).x()
        halfheight=max(5,self.view_radius*scale)
        if experiment in ("tension","compression"):
            self._fixed(p,x0,cy,halfheight+10);p.setBrush(QColor("#e1e9ef"));p.setPen(QPen(QColor("#a8bdcc"),1))
            endhalf=halfheight
            if points is not None:
                end_nodes=np.isclose(initial[:,0],initial[:,0].max())
                endhalf=max(4,float(np.max(np.abs(points[end_nodes,1])))*scale)
            p.drawRoundedRect(QRectF(xend,cy-endhalf-7,12,2*endhalf+14),2,2)
            start,end=(QPointF(xend+16,cy),QPointF(xend+42,cy)) if experiment=="tension" else (QPointF(xend+43,cy),QPointF(xend+15,cy))
            self._arrow(p,start,end);self._text(p,QRectF(xend+5,cy-30,47,24),"拉力" if experiment=="tension" else "压力",color="#b66d3f",size=8)
        elif experiment=="bending":
            boundary=self.meta.get("boundary_kind","simply_supported_center_load")
            if boundary=="cantilever_end_load":self._fixed(p,x0,cy,halfheight+16);loadx=xend
            else:self._pin(p,x0,cy+halfheight);self._pin(p,xend,cy+halfheight,True);loadx=(x0+xend)/2
            loady=cy-halfheight
            if points is not None:
                target=initial[:,0].max() if boundary=="cantilever_end_load" else (initial[:,0].min()+initial[:,0].max())/2
                near=np.abs(initial[:,0]-target)
                cross=points[near<=near.min()+1e-8]
                location=transform(float(cross[:,0].mean()),float(cross[:,1].max()))
                loadx,loady=location.x(),location.y()
            self._arrow(p,QPointF(loadx,loady-34),QPointF(loadx,loady-2));self._text(p,QRectF(loadx+8,loady-39,40,24),"F",color="#b66d3f")
        elif experiment=="buckling":
            self._pin(p,x0,cy+halfheight);self._pin(p,xend,cy+halfheight,True);self._arrow(p,QPointF(xend+40,cy),QPointF(xend+10,cy));self._text(p,QRectF(xend+10,cy-29,42,24),"P",color="#b66d3f")
        elif experiment=="shear":
            self._fixed(p,x0,cy,halfheight+12)
            end_y=float(np.mean(points[np.isclose(initial[:,0],initial[:,0].max()),1])) if points is not None else 0.
            end_screen=transform(length,end_y)
            self._arrow(p,QPointF(xend+23,end_screen.y()+27),QPointF(xend+23,end_screen.y()-4))
            self._text(p,QRectF(xend+27,end_screen.y()-12,28,24),"V",color="#b66d3f")
        if experiment not in ("shear","torsion"):
            actual=float(np.ptp(np.asarray(self.frame["points_mm"])[:,0])) if self.frame is not None else length
            self._text(p,QRectF(14,h-91,w-28,23),f"初始长度 {length:g} mm"+(f" · 当前轴向跨度 {actual:.2f} mm" if experiment in ("tension","compression") else ""),size=8,alignment=Qt.AlignmentFlag.AlignCenter)
        self._legend(p,low,high);p.end()
    def _torsion(self,p,transform,cy,scale,length,low,high,values,key):
        xs=np.asarray(self.frame.get("section_x_mm",[]),float) if self.frame is not None else np.array([])
        theta=np.asarray(self.frame.get("section_twist_rad",[]),float) if self.frame is not None else np.array([])
        if len(xs)<2 or len(theta)!=len(xs):xs=np.linspace(0,length,25);theta=np.zeros(25)
        theta=theta*self.magnification;shape=getattr(self.config,"section_shape","circle")
        angles=np.linspace(0,2*np.pi,13) if shape=="circle" else np.array([math.atan2(sy*getattr(self.config,"height_mm",10),sx*getattr(self.config,"width_mm",10)) for sx,sy in [(1,1),(-1,1),(-1,-1),(1,-1),(1,1)]])
        corner_radius=self.view_radius if shape=="circle" else math.hypot(getattr(self.config,"width_mm",10)/2,getattr(self.config,"height_mm",10)/2)
        surface=[]
        for angle in angles:
            section=[]
            for x,t in zip(xs,theta):
                base=transform(x,0);section.append(QPointF(base.x()+.27*corner_radius*math.cos(angle+t)*scale,base.y()-corner_radius*math.sin(angle+t)*scale))
            surface.append(section)
        recovered=np.asarray(self.frame.get("torsion_surface_shear_mpa",[]),float) if self.frame is not None else np.array([])
        for face_index in range(len(surface)-1):
            for axial_index in range(len(xs)-1):
                has_surface=recovered.ndim==2 and axial_index<recovered.shape[0] and face_index<recovered.shape[1]
                scalar=float(recovered[axial_index,face_index]) if has_surface else 0.
                color=field_color(scalar,low,high) if key and has_surface else QColor("#91b8cf")
                p.setBrush(color);p.setPen(QPen(QColor(36,70,95,100),.55) if self.show_mesh else QPen(color,.4))
                p.drawPolygon(QPolygonF([surface[face_index][axial_index],surface[face_index][axial_index+1],surface[face_index+1][axial_index+1],surface[face_index+1][axial_index]]))
        end=transform(length,0).x();self._fixed(p,transform(0,0).x()-3,cy,max(10,corner_radius*scale+8))
        p.setPen(QPen(QColor("#d07d48"),2.2));p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(end-12,cy-corner_radius*scale-15,30,2*corner_radius*scale+30),35*16,270*16)
        self._arrow(p,QPointF(end+15,cy+corner_radius*scale+2),QPointF(end+21,cy+corner_radius*scale-8))
        self._text(p,QRectF(end+17,cy-20,38,22),"T",color="#b66d3f")
        if self.frame is not None:
            actual=float(self.frame.get("twist_rad",theta[-1]/self.magnification))
            self._text(p,QRectF(12,self.height()-91,self.width()-24,23),f"实际转角 {math.degrees(actual):.3f}° · 长度 {length:g} mm",size=8,alignment=Qt.AlignmentFlag.AlignCenter)
        return end
    def mouseMoveEvent(self,event):
        if self.visual_style == 'realistic':
            self.setToolTip('同类实验共用写实教学动画；切换“网格云图”查看计算变形和场值。')
            return super().mouseMoveEvent(event)
        for polygon,index,value in reversed(self._hit_cells):
            if polygon.containsPoint(event.position(),Qt.FillRule.OddEvenFill):
                unit=self.FIELDS.get(self.field,(None,""))[1];self.setToolTip(f"单元 {index+1}\n{self.field}：{value:.5g} {unit}\n计算与模型说明可在“实验说明”查看。");break
        else:self.setToolTip("变形、局部场与曲线来自同一份计算记录。")
        super().mouseMoveEvent(event)

