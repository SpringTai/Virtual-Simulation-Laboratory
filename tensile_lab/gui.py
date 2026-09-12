"""Chinese desktop UI. Create MainWindow only after a QApplication exists."""
from __future__ import annotations

import threading
import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QStandardPaths
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QPushButton,
    QComboBox, QDoubleSpinBox, QSpinBox, QScrollArea, QToolButton,
    QCheckBox, QSlider, QProgressBar, QFileDialog, QMessageBox, QSplitter, QAbstractSpinBox,
)

from .models import SimulationConfig, SimulationResult
from .widgets import MetricCard, SpecimenView


STYLE = """
QMainWindow, QWidget#central { background: #f2f5f7; color: #253c51; }
QWidget { font-family: 'Microsoft YaHei UI', 'Microsoft YaHei'; font-size: 13px; color: #253c51; }
QFrame#header { background: #ffffff; border-bottom: 1px solid #e1e7ed; }
QLabel#title { font-size: 23px; font-weight: 650; color: #183d5b; }
QLabel#subtitle, QLabel#hint { color: #748496; font-size: 12px; }
QLabel#badge { background: #e8f1f7; color: #396b8f; border-radius: 11px; padding: 5px 10px; }
QFrame#panel, QFrame#metricCard, QFrame#controls { background: white; border: 1px solid #e1e7ed; border-radius: 10px; }
QLabel#sectionTitle { color: #294b66; font-size: 15px; font-weight: 650; }
QLabel#metricCaption { color: #738396; font-size: 12px; }
QLabel#metricValue { color: #163e5e; font-size: 20px; font-weight: 650; }
QPushButton { min-height: 32px; background: #edf3f7; color: #345c7a; border: 1px solid #d6e2eb; border-radius: 6px; padding: 2px 13px; }
QPushButton:hover { background: #e1edf6; border-color: #b4cce0; }
QPushButton:pressed { background: #d3e4f1; }
QPushButton#primary { background: #246c9f; color: white; border: 1px solid #246c9f; font-weight: 600; }
QPushButton#primary:hover { background: #1b5a88; }
QPushButton#cancel { color: #a45e38; background: #fff5ee; border-color: #efd7c5; }
QPushButton:disabled { background: #f1f3f5; color: #a8b0b8; border-color: #e4e8ec; }
QDoubleSpinBox, QSpinBox, QComboBox { min-height: 28px; background: #fbfcfd; border: 1px solid #d9e2e9; border-radius: 5px; padding: 2px 7px; selection-background-color: #3a81b0; }
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border-color: #71a6cc; }
QComboBox::drop-down { border: 0; width: 22px; }
QScrollArea { background: transparent; border: 0; }
QScrollArea > QWidget > QWidget { background: white; }
QScrollBar:vertical { background: #f1f5f8; width: 6px; margin: 0; border: 0; }
QScrollBar::handle:vertical { background: #c9d9e4; min-height: 26px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QToolButton { text-align: left; background: #edf3f7; border: 0; border-radius: 5px; padding: 8px 6px; color: #42667f; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; }
QSlider::groove:horizontal { height: 5px; background: #dbe5ed; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #3984b6; border-radius: 2px; }
QSlider::handle:horizontal { background: #246c9f; border: 2px solid white; width: 13px; height: 13px; margin: -5px 0; border-radius: 7px; }
QProgressBar { border: 0; background: #e6edf2; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background: #57a0c6; border-radius: 3px; }
QStatusBar { background: #eef3f6; color: #6c8090; font-size: 12px; }
QToolTip { color: #243d51; background: #ffffff; border: 1px solid #b8cbd9; padding: 7px; }
"""


class SimulationWorker(QThread):
    new_frame = Signal(object, float, str)
    succeeded = Signal(object)
    failed = Signal(str)
    interrupted = Signal(object, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.cancel_event = threading.Event()

    def run(self):
        try:
            from .engine import simulate
            result = simulate(self.config, progress_callback=self._progress,
                              cancel_event=self.cancel_event)
            self.succeeded.emit(result)
        except Exception as exc:
            partial = getattr(exc, "partial_result", None)
            if partial is not None and partial.frames:
                self.interrupted.emit(partial, str(exc))
                return
            if self.cancel_event.is_set():
                self.failed.emit("计算已取消。您可以调整参数后重新开始。")
            else:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

    def _progress(self, frame, fraction, message):
        self.new_frame.emit(frame, float(fraction), str(message))

    def cancel(self):
        self.cancel_event.set()


from dataclasses import replace
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QButtonGroup
from .presets import EXPERIMENTS, MATERIALS, GEOMETRY_PRESETS, make_config, material_key, example_path

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("虚拟仿真实验室")
        self.resize(1510,890);self.setMinimumSize(1160,680)
        self.setStyleSheet(STYLE+"""
        QPushButton#nav { background: transparent; border: 0; border-bottom: 3px solid transparent; border-radius: 0; font-size: 15px; padding: 4px 18px; }
        QPushButton#nav:checked { color: #1b6699; background: #eaf3f9; border-bottom: 3px solid #287caf; font-weight: 600; }
        QLabel#materialBrief { color: #637c91; background: #f2f7fa; padding: 8px; border-radius: 6px; font-size: 12px; }
        """)
        self.result=None;self._frames=[];self._worker=None;self._current_index=0
        self._calculating=False;self._active_config=None;self._changing_preset=True
        self._close_after_cancel=False;self._inputs={};self._input_groups={}
        self.experiment="tension";self._metadata={};self._metric_specs=[]
        self._play_timer=QTimer(self);self._play_timer.timeout.connect(self._advance)
        self._build_ui();self._bind_shortcuts()
        self._changing_preset=False
        self._apply_config(make_config());self._clear_results()
        if self._example_path().is_file():QTimer.singleShot(0,self.load_classroom_example)

    def _build_ui(self):
        central=QWidget();central.setObjectName("central");self.setCentralWidget(central)
        root=QVBoxLayout(central);root.setContentsMargins(0,0,0,0);root.setSpacing(0)
        header=QFrame();header.setObjectName("header")
        head=QHBoxLayout(header);head.setContentsMargins(20,5,20,5);head.setSpacing(8)
        self.logo_label=QLabel();self.logo_label.setFixedSize(62,62)
        logo=QPixmap(str(self._resource_root()/"assets"/"lab.png"))
        if not logo.isNull():self.logo_label.setPixmap(logo.scaled(62,62,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        head.addWidget(self.logo_label)
        branding=QVBoxLayout();branding.setSpacing(2)
        title=QLabel("虚拟仿真实验室");title.setObjectName("title");branding.addWidget(title)
        self.company_label=QLabel("云南数美汇云软件有限公司")
        self.company_label.setObjectName("subtitle");branding.addWidget(self.company_label)
        head.addLayout(branding);head.addStretch()
        root.addWidget(header)
        nav=QHBoxLayout();nav.setContentsMargins(18,3,18,3);nav.setSpacing(3)
        self.nav_buttons={};self.nav_group=QButtonGroup(self);self.nav_group.setExclusive(True)
        for key,name in EXPERIMENTS.items():
            button=QPushButton(name);button.setObjectName("nav");button.setCheckable(True)
            button.clicked.connect(lambda checked=False,k=key:self._select_experiment(k))
            self.nav_group.addButton(button);self.nav_buttons[key]=button;nav.addWidget(button)
        nav.addStretch()
        self.example_button=QPushButton("课堂示例");self.example_button.clicked.connect(self.load_classroom_example);nav.addWidget(self.example_button)
        self.info_button=QPushButton("实验说明");self.info_button.clicked.connect(self.show_experiment_info);nav.addWidget(self.info_button)
        self.fullscreen_button=QPushButton("全屏 F11");self.fullscreen_button.clicked.connect(self.toggle_fullscreen);nav.addWidget(self.fullscreen_button)
        root.addLayout(nav)
        body=QHBoxLayout();body.setContentsMargins(17,9,17,10);body.setSpacing(12)
        body.addWidget(self._build_parameters())
        right=QVBoxLayout();right.setSpacing(9)
        context=QHBoxLayout()
        self.stage_label=QLabel("准备实验");self.stage_label.setObjectName("sectionTitle");context.addWidget(self.stage_label)
        self.result_state_label=QLabel("待计算");self.result_state_label.setObjectName("badge");context.addWidget(self.result_state_label)
        context.addStretch()
        self.frame_label=QLabel("选择实验与试样");self.frame_label.setObjectName("hint");context.addWidget(self.frame_label)
        right.addLayout(context)
        split=QSplitter(Qt.Orientation.Horizontal);split.setChildrenCollapsible(False);split.setHandleWidth(9)
        view_panel=QFrame();view_panel.setObjectName("panel")
        view=QVBoxLayout(view_panel);view.setContentsMargins(12,9,12,7);view.setSpacing(5)
        view_top=QHBoxLayout();label=QLabel("试样与受力");label.setObjectName("sectionTitle");view_top.addWidget(label);view_top.addStretch()
        self.field_combo=QComboBox();self.field_combo.setMinimumWidth(112);self.field_combo.setMaximumWidth(200);view_top.addWidget(self.field_combo);view.addLayout(view_top)
        self.specimen_view=SpecimenView();self.field_combo.currentTextChanged.connect(self.specimen_view.set_field);view.addWidget(self.specimen_view,1)
        opts=QHBoxLayout()
        self.style_combo=QComboBox();self.style_combo.addItem("写实示意","realistic");self.style_combo.addItem("网格云图","mesh")
        self.style_combo.currentIndexChanged.connect(self._visual_style_changed);opts.addWidget(self.style_combo)
        self.mesh_check=QCheckBox("显示网格");self.mesh_check.setChecked(True);self.mesh_check.toggled.connect(self.specimen_view.set_mesh_visible);opts.addWidget(self.mesh_check);self.mesh_check.hide();opts.addStretch()
        self.magnify_label=QLabel("变形显示");self.magnify_label.setObjectName("hint");opts.addWidget(self.magnify_label)
        self.magnify_combo=QComboBox()
        for value in [1,5,20,50,100]:self.magnify_combo.addItem(f"{value}×",value)
        self.magnify_combo.setFixedWidth(76);self.magnify_combo.currentIndexChanged.connect(lambda:self.specimen_view.set_magnification(self.magnify_combo.currentData() or 1));opts.addWidget(self.magnify_combo)
        view.addLayout(opts);split.addWidget(view_panel)
        chart_panel=QFrame();chart_panel.setObjectName("panel")
        chart=QVBoxLayout(chart_panel);chart.setContentsMargins(12,9,12,7);chart.setSpacing(5)
        self.curve_title=QLabel("工程应力—应变曲线");self.curve_title.setObjectName("sectionTitle");chart.addWidget(self.curve_title)
        self.curve_hint=QLabel();self.curve_hint.setObjectName("hint");chart.addWidget(self.curve_hint)
        pg.setConfigOptions(antialias=True)
        self.plot=pg.PlotWidget(background="w");self.plot.setMinimumSize(250,222);self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True,y=True,alpha=.15);self.plot.setMouseEnabled(x=False,y=False);self.plot.getPlotItem().hideButtons()
        for name in ("left","bottom"):
            axis=self.plot.getAxis(name);axis.setPen("#c7d5df");axis.setTextPen("#667d90");axis.setTickFont(QFont("Microsoft YaHei UI",10))
        self.future_curve=self.plot.plot([],[],pen=pg.mkPen("#ccdce7",width=2))
        self.curve=self.plot.plot([],[],pen=pg.mkPen("#237db2",width=3))
        self.marker=self.plot.plot([],[],pen=None,symbol="o",symbolSize=10,symbolBrush="#e79c52",symbolPen=pg.mkPen("w",width=2))
        chart.addWidget(self.plot,1)
        note=QLabel("蓝线：当前记录   灰线：完整记录   橙点：当前状态");note.setObjectName("hint");note.setWordWrap(True);chart.addWidget(note)
        split.addWidget(chart_panel);split.setSizes([520,460]);right.addWidget(split,1)
        cards=QHBoxLayout();cards.setSpacing(8)
        self.cards=[MetricCard("", "") for _ in range(4)]
        self.force_card,self.stress_card,self.strain_card,self.extension_card=self.cards
        for card in self.cards:cards.addWidget(card,1)
        right.addLayout(cards);right.addWidget(self._build_controls())
        body.addLayout(right,1);root.addLayout(body,1)
        self.statusBar().showMessage("选择课堂示例可直接回放；手动尺寸可重新计算。")

    def _build_parameters(self):
        panel=QFrame();panel.setObjectName("panel");panel.setFixedWidth(260)
        outer=QVBoxLayout(panel);outer.setContentsMargins(13,12,13,10);outer.setSpacing(8)
        label=QLabel("试样设置");label.setObjectName("sectionTitle");outer.addWidget(label)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.parameter_content=QWidget();layout=QVBoxLayout(self.parameter_content);layout.setContentsMargins(0,0,3,3);layout.setSpacing(8)
        row=QHBoxLayout();material=QVBoxLayout();shape=QVBoxLayout()
        material.addWidget(self._label("材料"));self.material_combo=QComboBox();self.material_combo.addItems(["Fe","Al"]);material.addWidget(self.material_combo)
        shape.addWidget(self._label("截面"));self.shape_combo=QComboBox();self.shape_combo.addItem("圆形","circle");self.shape_combo.addItem("矩形","rectangle");shape.addWidget(self.shape_combo)
        row.addLayout(material,1);row.addLayout(shape,1);layout.addLayout(row)
        self.material_brief=QLabel();self.material_brief.setObjectName("materialBrief");self.material_brief.setWordWrap(True);layout.addWidget(self.material_brief)
        layout.addWidget(self._label("尺寸方案"))
        self.geometry_combo=QComboBox()
        for key,title in GEOMETRY_PRESETS.items():self.geometry_combo.addItem(title,key)
        layout.addWidget(self.geometry_combo)
        self._add_input(layout,"gauge_length_mm","初始长度 L / mm",40,.1,10000,2,10)
        self._add_input(layout,"diameter_mm","直径 d / mm",10,.1,1000,2,1)
        row=QHBoxLayout();left,right=QVBoxLayout(),QVBoxLayout()
        self._add_input(left,"width_mm","宽度 b / mm",10,.1,1000,2,1);self._add_input(right,"height_mm","高度 h / mm",10,.1,1000,2,1)
        row.addLayout(left);row.addLayout(right);layout.addLayout(row)
        self.area_label=QLabel();self.area_label.setObjectName("hint");layout.addWidget(self.area_label)
        self._add_input(layout,"max_strain_percent","最大工程应变 / %",65,.001,150,3,5)
        self.advanced_button=QToolButton();self.advanced_button.setText("加载与计算设置");self.advanced_button.setCheckable(True);self.advanced_button.setArrowType(Qt.ArrowType.RightArrow);self.advanced_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon);layout.addWidget(self.advanced_button)
        self.advanced_area=QWidget();advanced=QVBoxLayout(self.advanced_area);advanced.setContentsMargins(0,0,0,0);advanced.setSpacing(8)
        self._add_input(advanced,"load_factor","加载范围比例",1,.01,2,2,.1)
        self._add_input(advanced,"imperfection_percent","初始缺陷 / %",1,0,5,3,.1)
        self._add_input(advanced,"mesh_axial","轴向网格数",40,4,160,integer=True)
        self._add_input(advanced,"mesh_radial","截面网格数",6,2,24,integer=True)
        self._add_input(advanced,"output_steps","记录步数",100,10,400,integer=True)
        self.advanced_area.hide();layout.addWidget(self.advanced_area)
        self.advanced_button.toggled.connect(self.advanced_area.setVisible)
        self.advanced_button.toggled.connect(lambda checked:self.advanced_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow))
        layout.addStretch();scroll.setWidget(self.parameter_content);outer.addWidget(scroll,1)
        self.defaults_button=QPushButton("恢复本实验标准参数");self.defaults_button.clicked.connect(self._restore_defaults);outer.addWidget(self.defaults_button)
        self.material_combo.currentIndexChanged.connect(self._selection_changed)
        self.shape_combo.currentIndexChanged.connect(self._selection_changed)
        self.geometry_combo.currentIndexChanged.connect(self._selection_changed)
        return panel

    def _label(self,text):
        label=QLabel(text);label.setObjectName("hint");return label

    def _add_input(self,layout,key,caption,default,minimum,maximum,decimals=2,step=1,integer=False):
        group=QWidget();box=QVBoxLayout(group);box.setContentsMargins(0,0,0,0);box.setSpacing(3)
        label=self._label(caption);box.addWidget(label)
        control=QSpinBox() if integer else QDoubleSpinBox()
        if not integer:control.setDecimals(decimals)
        control.setRange(minimum,maximum);control.setSingleStep(step);control.setValue(default)
        control.setKeyboardTracking(False);control.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons);control.setAccessibleName(caption)
        control.valueChanged.connect(self._parameter_changed);self._inputs[key]=control;self._input_groups[key]=group
        box.addWidget(control);layout.addWidget(group)

    def _build_controls(self):
        panel=QFrame();panel.setObjectName("controls");layout=QVBoxLayout(panel);layout.setContentsMargins(12,9,12,9);layout.setSpacing(5)
        row=QHBoxLayout();row.setSpacing(6)
        self.start_button=QPushButton("开始计算");self.start_button.setObjectName("primary");self.start_button.clicked.connect(self.start_simulation);row.addWidget(self.start_button)
        self.cancel_button=QPushButton("取消计算");self.cancel_button.setObjectName("cancel");self.cancel_button.clicked.connect(self.cancel_simulation);self.cancel_button.hide();row.addWidget(self.cancel_button)
        self.play_button=QPushButton("播放");self.play_button.clicked.connect(self.toggle_playback);row.addWidget(self.play_button)
        self.step_button=QPushButton("单步");self.step_button.clicked.connect(self._step_once);row.addWidget(self.step_button)
        self.reset_button=QPushButton("重置");self.reset_button.clicked.connect(self.reset_experiment);row.addWidget(self.reset_button);row.addStretch()
        self.speed_combo=QComboBox();self.speed_combo.addItems(["慢放 0.5×","播放 1×","快放 2×"]);self.speed_combo.setCurrentIndex(1);self.speed_combo.currentIndexChanged.connect(self._update_play_speed);row.addWidget(self.speed_combo)
        self.open_button=QPushButton("打开记录");self.open_button.clicked.connect(self.open_record);row.addWidget(self.open_button)
        self.export_button=QPushButton("导出数据");self.export_button.clicked.connect(self.export_data);row.addWidget(self.export_button)
        layout.addLayout(row)
        progress=QHBoxLayout();progress.addWidget(self._label("实验回放"))
        self.timeline=QSlider(Qt.Orientation.Horizontal);self.timeline.setRange(0,0);self.timeline.valueChanged.connect(self._seek);progress.addWidget(self.timeline,1)
        self.step_label=self._label("0 / 0");self.step_label.setMinimumWidth(60);self.step_label.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter);progress.addWidget(self.step_label);layout.addLayout(progress)
        self.progress_bar=QProgressBar();self.progress_bar.setRange(0,1000);self.progress_bar.setTextVisible(False);self.progress_bar.hide();layout.addWidget(self.progress_bar)
        return panel

    def _bind_shortcuts(self):
        for key,callback in [("F11",self.toggle_fullscreen),("Escape",lambda:self.toggle_fullscreen() if self.isFullScreen() else None),("Space",self.toggle_playback)]:
            action=QAction(self);action.setShortcut(QKeySequence(key));action.triggered.connect(callback);self.addAction(action)
    def toggle_fullscreen(self):
        if self.isFullScreen():self.showNormal();self.fullscreen_button.setText("全屏 F11")
        else:self.showFullScreen();self.fullscreen_button.setText("退出全屏")

    @staticmethod
    def _resource_root():return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[1]))

    def _select_experiment(self,key):
        if self._calculating:return
        if key==self.experiment:return
        self.experiment=key
        self._apply_config(make_config(key,self.shape_combo.currentData(),self.material_combo.currentText()))
        self._clear_results()
        if self._example_path().is_file():self.load_classroom_example()

    def _selection_changed(self,*args):
        if self._changing_preset or self._calculating:return
        cfg=make_config(self.experiment,self.shape_combo.currentData(),self.material_combo.currentText(),self.geometry_combo.currentData())
        if self.geometry_combo.currentData()=="manual":
            cfg=replace(cfg,**{key:self._inputs[key].value() for key in ("gauge_length_mm","diameter_mm","width_mm","height_mm")})
        self._apply_config(cfg);self._clear_results()
        if self.geometry_combo.currentData()=="standard" and self._example_path().is_file():self.load_classroom_example()

    def _parameter_changed(self,*args):
        if self._changing_preset:return
        self._preview_changed()
        if self.result is not None:
            self.frame_label.setText("参数已修改 · 当前显示上次记录")
            self.statusBar().showMessage("点击“开始计算”应用新参数；导出内容为当前显示的计算记录。")

    def _restore_defaults(self):
        if self._calculating:return
        self._apply_config(make_config(self.experiment,self.shape_combo.currentData(),self.material_combo.currentText()))
        self._clear_results()
        if self._example_path().is_file():self.load_classroom_example()

    def _get_config(self):
        c=make_config(self.experiment,self.shape_combo.currentData(),self.material_combo.currentText(),self.geometry_combo.currentData())
        values={key:self._inputs[key].value() for key in ("gauge_length_mm","diameter_mm","width_mm","height_mm","load_factor","mesh_axial","mesh_radial","output_steps")}
        values["max_strain"]=self._inputs["max_strain_percent"].value()/100
        values["imperfection"]=self._inputs["imperfection_percent"].value()/100
        c=replace(c,**values)
        from .engine import validate
        validate(c)
        return c

    def _apply_config(self,c):
        self._changing_preset=True;self.experiment=getattr(c,"experiment","tension")
        self.nav_buttons[self.experiment].setChecked(True)
        self.material_combo.setCurrentText(material_key(c.material_name))
        self.shape_combo.setCurrentIndex(0 if c.section_shape=="circle" else 1)
        self.geometry_combo.setCurrentIndex(0 if getattr(c,"geometry_preset","standard")=="standard" else 1)
        for key,control in self._inputs.items():
            if key=="max_strain_percent":control.setValue(c.max_strain*100)
            elif key=="imperfection_percent":control.setValue(c.imperfection*100)
            elif hasattr(c,key):control.setValue(getattr(c,key))
        self._changing_preset=False;self._preview_changed()

    def _preview_changed(self):
        if not hasattr(self,"specimen_view"):return
        shape=self.shape_combo.currentData();manual=self.geometry_combo.currentData()=="manual"
        self._input_groups["diameter_mm"].setVisible(shape=="circle")
        for key in ("width_mm","height_mm"):self._input_groups[key].setVisible(shape=="rectangle")
        for key in ("gauge_length_mm","diameter_mm","width_mm","height_mm"):self._inputs[key].setReadOnly(not manual)
        axial=self.experiment in ("tension","compression");self._input_groups["max_strain_percent"].setVisible(axial)
        self._input_groups["load_factor"].setVisible(not axial)
        self._inputs["max_strain_percent"].setMaximum(79.9 if self.experiment=="compression" else 150.)
        self._input_groups["imperfection_percent"].setVisible(axial or self.experiment=="buckling")
        self._inputs["imperfection_percent"].setMaximum(2. if self.experiment=="buckling" else 5.)
        material=MATERIALS[self.material_combo.currentText()]
        self.material_brief.setText(f"E = {material['young_mpa']/1000:g} GPa    ν = {material['poisson']:g}\n屈服强度 {material['yield_mpa']:g} MPa")
        area=np.pi*self._inputs["diameter_mm"].value()**2/4 if shape=="circle" else self._inputs["width_mm"].value()*self._inputs["height_mm"].value()
        self.area_label.setText(f"初始截面积 A0 = {area:.2f} mm²")
        if self.result is None and not self._calculating:
            try:
                c=self._get_config();self._active_config=c;self._configure_outputs(c)
                self._set_preview(c)
            except ValueError:pass
        self.example_button.setEnabled(not self._calculating and self._example_path().is_file())

    def _set_preview(self,c):
        height=c.diameter_mm if c.section_shape=="circle" else c.height_mm
        self.specimen_view.set_preview(c.gauge_length_mm,height)
        extent=c.gauge_length_mm*(1+c.max_strain) if c.experiment=="tension" else c.gauge_length_mm
        self.specimen_view.set_view_extent(extent,height/2)

    def _default_metadata(self,c):
        exp=c.experiment
        axes={
          "tension":("engineering_strain",100,"工程应变 / %","engineering_stress_mpa",1,"工程应力 / MPa","工程应力—应变曲线","σ = F / A0 · ε = ΔL / L0"),
          "compression":("engineering_strain",100,"工程应变 / %","engineering_stress_mpa",1,"工程应力 / MPa","压缩应力—应变曲线","压缩应变与应力采用负号"),
          "torsion":("twist_rad",180/np.pi,"转角 / °","torque_n_mm",.001,"扭矩 / N·m","扭矩—转角曲线","转角为两端截面的相对转动"),
          "bending":("deflection_mm",1,"跨中挠度 / mm","force_n",.001,"载荷 / kN","载荷—挠度曲线","两端简支 · 跨中集中载荷"),
          "shear":("shear_strain",100,"剪应变 / %","shear_stress_mpa",1,"剪应力 / MPa","剪应力—剪应变曲线","左端固定 · 右端竖向平移"),
          "buckling":("lateral_deflection_mm",1,"中点侧移 / mm","force_n",.001,"轴向压力 / kN","压力—侧移曲线","两端铰支 · 观察初始缺陷的放大")}
        x,xs,xl,y,ys,yl,title,hint=axes[exp]
        metrics={
          "torsion":[("扭矩","torque_n_mm",.001,"N·m",2),("相对转角","twist_rad",180/np.pi,"°",3),("最大剪应力","shear_stress_mpa",1,"MPa",1),("剪切模量","shear_modulus_mpa",.001,"GPa",1)],
          "bending":[("载荷","force_n",.001,"kN",3),("跨中挠度","deflection_mm",1,"mm",3),("最大弯矩","bending_moment_n_mm",.001,"N·m",2),("最大正应力","engineering_stress_mpa",1,"MPa",1)],
          "shear":[("剪力","shear_force_n",.001,"kN",2),("剪应力","shear_stress_mpa",1,"MPa",1),("剪应变","shear_strain",100,"%",3),("端部位移","displacement_mm",1,"mm",3)],
          "buckling":[("轴向压力","force_n",.001,"kN",2),("临界力","critical_force_n",.001,"kN",2),("中点侧移","lateral_deflection_mm",1,"mm",2),("端部压缩","displacement_mm",1,"mm",3)]}.get(exp,[("轴向力","force_n",.001,"kN",2),("工程应力","engineering_stress_mpa",1,"MPa",1),("工程应变","engineering_strain",100,"%",2),("标距变化","displacement_mm",1,"mm",2)])
        return dict(plot_x_key=x,plot_x_scale=xs,plot_x_label=xl,plot_y_key=y,plot_y_scale=ys,plot_y_label=yl,plot_title=title,plot_hint=hint,field_label="剪应力" if exp in ("torsion","shear") else "轴向应力",field_key="cell_shear_stress_mpa" if exp in ("torsion","shear") else "cell_stress_axial_mpa",metric_specs=[dict(label=a,key=b,scale=d,unit=e,decimals=f) for a,b,d,e,f in metrics],default_magnification={"torsion":20,"bending":5,"shear":20,"buckling":1}.get(exp,1))

    def _configure_outputs(self,c,diagnostics=None):
        meta=self._default_metadata(c);meta.update(diagnostics or {})
        if c.experiment=="buckling":meta["default_magnification"]=5
        meta["field_description"]=meta.get("field_label","轴向应力")
        meta["field_label"]="剪应力" if c.experiment in ("torsion","shear") else "弯曲正应力" if c.experiment=="bending" else "轴向应力"
        self._metadata=meta;self._metric_specs=meta.get("metric_specs",[])[:4]
        self.curve_title.setText(meta.get("plot_title",self._default_metadata(c)["plot_title"]))
        self.curve_hint.setText(meta.get("plot_hint",self._default_metadata(c)["plot_hint"]))
        self.plot.setLabel("bottom",meta["plot_x_label"],color="#496b85",**{"font-size":"11pt"})
        self.plot.setLabel("left",meta["plot_y_label"],color="#496b85",**{"font-size":"11pt"})
        self.specimen_view.configure(c,meta)
        current=self.field_combo.currentText();self.field_combo.blockSignals(True);self.field_combo.clear();self.field_combo.addItems(list(self.specimen_view.FIELDS))
        self.field_combo.setCurrentText(current if current in self.specimen_view.FIELDS else next(iter(self.specimen_view.FIELDS)));self.field_combo.blockSignals(False);self.specimen_view.set_field(self.field_combo.currentText())
        for card,spec in zip(self.cards,self._metric_specs):card.caption.setText(spec["label"]);card.unit=spec.get("unit","")
        self.magnify_label.setText("转角显示" if c.experiment=="torsion" else "变形显示")
        value=meta.get("default_magnification",1);idx=self.magnify_combo.findData(value)
        self.magnify_combo.setCurrentIndex(max(0,idx));self.magnify_combo.setEnabled(True)
        self._visual_style_changed()

    def _visual_style_changed(self):
        style=self.style_combo.currentData()
        self.specimen_view.set_visual_style(style)
        mesh=style=='mesh'
        self.mesh_check.setVisible(mesh);self.field_combo.setVisible(mesh)
        self.magnify_label.setVisible(mesh);self.magnify_combo.setVisible(mesh)

    def _clear_results(self):
        self._pause();self.result=None;self._frames=[];self._current_index=0
        for line in (self.curve,self.future_curve,self.marker):line.setData([],[])
        self.timeline.setRange(0,0);self.step_label.setText("0 / 0")
        self.stage_label.setText(EXPERIMENTS[self.experiment]+"实验");self._set_result_state("待计算","working")
        self.frame_label.setText("选择课堂示例或开始计算")
        self._clear_metrics();self._preview_changed();self._lock_for_calculation(False)
        self.plot.setXRange(-1 if self.experiment=="compression" else 0,1,padding=0)
        self.plot.setYRange(-1 if self.experiment=="compression" else 0,1,padding=0)

    def start_simulation(self):
        if self._calculating or (self._worker is not None and self._worker.isRunning()):return
        try:c=self._get_config()
        except ValueError as exc:QMessageBox.information(self,"检查实验参数",str(exc));return
        self._clear_results();self._active_config=c;self._calculating=True;self._configure_outputs(c);self._set_preview(c);self._lock_for_calculation(True)
        self.stage_label.setText("正在准备计算…");self._set_result_state("计算中","working")
        self.frame_label.setText("首次计算可能稍慢");self.progress_bar.setValue(0)
        self.statusBar().showMessage("正在后台计算；可取消，已完成的加载记录会保留。")
        try:
            from .storage import cache_path,load_result
            candidates=[example_path(c),cache_path(c)]
            for path in candidates:
                if path.is_file():
                    result=load_result(path)
                    if result.frames:
                        self._on_complete(result);self.timeline.setValue(0);self._display_frame(0)
                        self.frame_label.setText("已载入该参数的计算记录");return
        except Exception:pass
        self._worker=SimulationWorker(c,self);self._worker.new_frame.connect(self._on_frame);self._worker.succeeded.connect(self._on_complete)
        self._worker.failed.connect(self._on_failed);self._worker.interrupted.connect(self._on_interrupted);self._worker.finished.connect(self._worker_finished);self._worker.start()

    def cancel_simulation(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel();self.cancel_button.setEnabled(False);self.cancel_button.setText("正在取消…");self.statusBar().showMessage("正在安全停止当前计算步。")

    def _lock_for_calculation(self,locked):
        self.parameter_content.setEnabled(not locked);self.defaults_button.setEnabled(not locked);self.open_button.setEnabled(not locked)
        for button in self.nav_buttons.values():button.setEnabled(not locked)
        self.example_button.setEnabled(not locked and self._example_path().is_file())
        self.start_button.setEnabled(not locked);self.start_button.setText("正在计算…" if locked else "重新计算" if self._frames else "开始计算")
        self.cancel_button.setVisible(locked);self.cancel_button.setEnabled(True);self.cancel_button.setText("取消计算");self.progress_bar.setVisible(locked)
        has=bool(self._frames)
        self.play_button.setEnabled(not locked and has);self.step_button.setEnabled(not locked and has);self.reset_button.setEnabled(not locked);self.timeline.setEnabled(not locked and has)
        self.export_button.setEnabled(not locked and self.result is not None and has)

    def _on_frame(self,frame,fraction,message):
        if frame is not None:
            if not self._frames and frame.get("diagnostics"):self._configure_outputs(self._active_config,frame["diagnostics"])
            self._frames.append(frame);self._display_frame(len(self._frames)-1)
            self.specimen_view.animation_progress=float(np.clip(fraction,0,1));self.specimen_view.update()
        self.progress_bar.setValue(round(np.clip(fraction,0,1)*1000));self.frame_label.setText(f"计算进度 {fraction:.0%} · {len(self._frames)} 个记录")
        if message:self.statusBar().showMessage(message)

    def _on_complete(self,result):
        self.result=result;self._active_config=result.config;self._frames=list(result.frames);self._calculating=False
        self._configure_outputs(result.config,result.diagnostics)
        status=str(result.diagnostics.get("status",result.summary.get("status","completed")))
        self._set_result_state("数值中止 · 部分记录" if status=="numerical_stop" else "已取消 · 部分记录" if status=="cancelled" else "完整计算记录","warning" if status in ("cancelled","numerical_stop") else "complete")
        self.specimen_view.set_mesh(result.initial_points,result.cells)
        initial=np.asarray(result.initial_points);origin=float(initial[:,0].min())
        max_length=max([float(np.max(np.asarray(f["points_mm"])[:,0]))-origin for f in self._frames]+[float(np.ptp(initial[:,0]))])
        max_dy=max([float(np.max(np.abs(np.asarray(f["points_mm"])[:,1]-initial[:,1]))) for f in self._frames]+[0.])
        self.specimen_view.set_view_extent(max_length,float(np.max(np.abs(initial[:,1]))),max_dy)
        limits={}
        for label,(key,unit) in self.specimen_view.FIELDS.items():
            if not key:continue
            lo,hi=0.,1. if key=="cell_damage" else 1e-9
            for frame in self._frames:
                values=np.asarray(frame.get(key,[]),float);values=values[np.isfinite(values)]
                if len(values):lo=min(lo,float(values.min()));hi=max(hi,float(values.max()))
                if result.config.experiment=="torsion" and key=="cell_shear_stress_mpa":
                    surface=np.asarray(frame.get("torsion_surface_shear_mpa",[]),float)
                    surface=surface[np.isfinite(surface)]
                    if len(surface):lo=min(lo,float(surface.min()));hi=max(hi,float(surface.max()))
            limits[label]=(lo,hi)
        self.specimen_view.set_field_limits(limits);self.timeline.setRange(0,max(0,len(self._frames)-1));self._lock_for_calculation(False)
        if self._frames:self.timeline.setValue(len(self._frames)-1);self._display_frame(len(self._frames)-1)
        self.frame_label.setText(f"计算完成 · {len(self._frames)} 个加载记录")
        reason=result.diagnostics.get("termination_reason","可回放并导出完整记录")
        self.statusBar().showMessage(f"{EXPERIMENTS[result.config.experiment]}实验：{reason}")
        if status=="completed" and self._frames:
            try:
                from .storage import cache_path,save_result
                save_result(result,cache_path(result.config))
            except Exception:pass

    def _on_interrupted(self,result,message):
        cancelled=bool(self._worker and self._worker.cancel_event.is_set())
        result.diagnostics["status"]="cancelled" if cancelled else "numerical_stop";self._on_complete(result)
        self.frame_label.setText(("已取消" if cancelled else "计算中止")+f" · {len(self._frames)} 个有效记录")
        self.statusBar().showMessage(("已保留有效记录。" if cancelled else "数值中止不代表试样发生失效。")+message)

    def _on_failed(self,message):
        self._calculating=False;self._lock_for_calculation(False)
        cancelled=bool(self._worker and self._worker.cancel_event.is_set())
        self._set_result_state("已取消" if cancelled else "计算中止","warning");self.frame_label.setText("计算已停止");self.statusBar().showMessage(message)
        if not cancelled:QMessageBox.warning(self,"本次计算未完成",message+"\n\n可恢复本实验标准参数后重试。")

    def _worker_finished(self):
        if self._close_after_cancel:QTimer.singleShot(0,self.close)

    def _display_frame(self,index):
        if not self._frames:return
        index=int(np.clip(index,0,len(self._frames)-1));self._current_index=index;frame=self._frames[index]
        c=self._active_config
        if c and c.experiment in ("tension","compression"):
            values=np.asarray(frame.get("cell_eq_plastic_strain",[0]),float);allowed=not len(values) or float(values.max())<.02
            if not allowed:self.magnify_combo.setCurrentIndex(0)
            self.magnify_combo.setEnabled(allowed)
        self.specimen_view.animation_progress=index/max(1,len(self._frames)-1)
        self.specimen_view.set_frame(frame)
        stage=str(frame.get("stage",EXPERIMENTS[self.experiment]+"加载"))
        caption="达到屈服 · 加载结束" if "首屈服" in stage else "临界前变形 · 加载结束" if "临界前" in stage and "停止" in stage else stage
        self.stage_label.setText(caption if len(caption)<=22 else caption[:21]+"…");self.stage_label.setToolTip(stage)
        for card,spec in zip(self.cards,self._metric_specs):
            value=frame.get(spec["key"])
            card.set_value(None if value is None else float(value)*float(spec.get("scale",1)),int(spec.get("decimals",2)))
        m=self._metadata
        x=np.asarray([f.get(m["plot_x_key"],0)*m.get("plot_x_scale",1) for f in self._frames],float)
        y=np.asarray([f.get(m["plot_y_key"],0)*m.get("plot_y_scale",1) for f in self._frames],float)
        self.future_curve.setData(x[index:] if not self._calculating else [],y[index:] if not self._calculating else [])
        self.curve.setData(x[:index+1],y[:index+1]);self.marker.setData([x[index]],[y[index]])
        xmin,xmax=min(0,float(x.min())*1.05),max(0,float(x.max())*1.05)
        ymin,ymax=min(0,float(y.min())*1.1),max(0,float(y.max())*1.1)
        if xmax-xmin<1e-9:xmax=xmin+1.
        if ymax-ymin<1e-9:ymax=ymin+1.
        self.plot.setXRange(xmin,xmax,padding=0);self.plot.setYRange(ymin,ymax,padding=0)
        self.step_label.setText(f"{index+1} / {len(self._frames)}")
        if not self._calculating:self.frame_label.setText(f"第 {index+1} 个加载记录 · 共 {len(self._frames)} 个")

    def _seek(self,index):
        if not self._calculating:self._display_frame(index)
    def toggle_playback(self):
        if self._calculating or not self._frames:return
        if self._play_timer.isActive():self._pause()
        else:
            if self._current_index>=len(self._frames)-1:self.timeline.setValue(0);self._display_frame(0)
            self._update_play_speed();self._play_timer.start();self.play_button.setText("暂停")
    def _update_play_speed(self):self._play_timer.setInterval([180,90,45][self.speed_combo.currentIndex()])
    def _pause(self):
        self._play_timer.stop()
        if hasattr(self,"play_button"):self.play_button.setText("播放")
    def _advance(self):
        if self._current_index>=len(self._frames)-1:self._pause()
        else:self.timeline.setValue(self._current_index+1)
    def _step_once(self):
        self._pause()
        if self._frames:
            index=0 if self._current_index>=len(self._frames)-1 else self._current_index+1
            self.timeline.setValue(index);self._display_frame(index)
    def reset_experiment(self):
        if self._calculating:return
        self._pause()
        if self._frames:self.timeline.setValue(0);self._display_frame(0)
        else:self._clear_results()
    def _clear_metrics(self):
        for card in self.cards:card.set_value()
    def _set_idle(self):self._clear_results()
    def _set_result_state(self,text,kind):
        self.result_state_label.setText(text)
        background,color={"warning":("#fff0e2","#ad642f"),"working":("#e8f1f7","#39739c"),"complete":("#e6f2ee","#3b7c68")}.get(kind,("#e8f1f7","#396b8f"))
        self.result_state_label.setStyleSheet(f"background:{background};color:{color};border-radius:9px;padding:4px 8px;font-size:11px;")
    def _example_path(self):
        try:return example_path(self._get_config())
        except Exception:return self._resource_root()/"examples"/"not-available.npz"
    def load_classroom_example(self):
        if self._calculating:return
        path=self._example_path()
        if not path.is_file():self.statusBar().showMessage("当前参数暂无预计算记录，可点击“开始计算”。");return
        self._pause()
        try:
            from .storage import load_result
            result=load_result(path)
            if not result.frames:raise ValueError("记录中没有加载数据")
            self._apply_config(result.config);self._on_complete(result);self.timeline.setValue(0);self._display_frame(0)
            self.frame_label.setText("课堂示例已载入 · 点击播放")
            self.statusBar().showMessage(f"{EXPERIMENTS[result.config.experiment]} · {material_key(result.config.material_name)} · 课堂示例已就绪。")
        except Exception as exc:self.statusBar().showMessage(f"示例未打开：{exc}")
    def open_record(self):
        if self._calculating:return
        self._pause();filename,_=QFileDialog.getOpenFileName(self,"打开实验记录","","实验记录 (*.npz)")
        if not filename:return
        try:
            from .storage import load_result
            result=load_result(filename)
            if not result.frames:raise ValueError("这份记录没有加载数据")
            self._apply_config(result.config);self._on_complete(result);self.timeline.setValue(0);self._display_frame(0)
            self.statusBar().showMessage(f"已打开：{Path(filename).name}")
        except Exception as exc:QMessageBox.warning(self,"记录未打开",str(exc))
    def export_data(self):
        if self.result is None or not self._frames:return
        self._pause()
        folder=QFileDialog.getExistingDirectory(self,"选择实验结果保存文件夹",QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
        if not folder:return
        try:
            from .export import export_result
            paths=export_result(self.result,folder);destination=paths.get("folder",folder)
            self.statusBar().showMessage(f"已保存：{destination}")
            QMessageBox.information(self,"导出完成",f"已保存完整记录、CSV 数据和曲线图片。\n\n{destination}")
        except Exception as exc:QMessageBox.warning(self,"导出未完成",str(exc))
    def show_experiment_info(self):
        meta=self._metadata
        default_notes={
          "tension":"轴向位移加载，观察弹性、屈服、颈缩与损伤失效。圆形与矩形试样采用各自的计算模型。",
          "compression":"端面向内位移加载，观察轴向压缩与截面扩张。应力和应变采用带符号数据。",
          "torsion":"左端固定、右端施加扭矩。外观按有限元计算转角投影，不额外描绘未计算的翘曲。",
          "bending":"两端简支、跨中集中力。变形来自梁单元位移；应力由梁截面关系恢复。",
          "shear":"左端固定、右端竖向平移，按均匀剪切模型观察平行四边形变形。",
          "buckling":"两端铰支压杆，观察侧向初始缺陷随压力增加而放大，比较临界载荷。"}
        name=meta.get("model_name",EXPERIMENTS[self.experiment]+"实验")
        note=meta.get("model_note",default_notes[self.experiment])
        material_note=meta.get("material_note","Fe、Al 使用教学代表参数，不对应经标定的具体牌号。")
        QMessageBox.information(self,EXPERIMENTS[self.experiment]+" · 实验说明",f"{name}\n\n{note}\n\n{material_note}\n\n动画、曲线与导出使用同一份计算数据。放大仅改变显示，数值读数及导出保持实际值。")
    def closeEvent(self,event):
        self._pause()
        if self._worker is not None and self._worker.isRunning():
            self._close_after_cancel=True;self.cancel_simulation();event.ignore();self.statusBar().showMessage("正在停止计算，结束后自动关闭。");return
        super().closeEvent(event)
