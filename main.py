"""桌面启动入口；可直接运行，也可打包为独立 Windows 程序。"""
import os
import sys
from pathlib import Path

def main():
    data = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MechanicsVirtualLab"
    data.mkdir(parents=True, exist_ok=True)
    # Numba 的编译缓存必须在用户可写目录，打包安装后也可使用。
    os.environ.setdefault("NUMBA_CACHE_DIR", str(data / "numba_cache"))
    if "--self-test" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QFont, QFontDatabase, QIcon
    app = QApplication(sys.argv)
    app.setApplicationName("虚拟仿真实验室")
    if not QFontDatabase.families():
        font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc", "arial.ttf"):
            font_file = font_directory / name
            if font_file.is_file():
                QFontDatabase.addApplicationFont(str(font_file))
    app.setFont(QFont("Microsoft YaHei", 10))
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    icon_path = resource_root / "assets" / "lab.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    try:
        if "--self-test" in sys.argv:
            from tensile_lab.selftest import run_selftest
            index = sys.argv.index("--self-test")
            report = sys.argv[index+1] if len(sys.argv)>index+1 else str(data / "selftest.json")
            return run_selftest(report)
        from tensile_lab.gui import MainWindow
        window = MainWindow()
        window.show()
        return app.exec()
    except Exception as error:
        import traceback
        detail = traceback.format_exc()
        (data / "startup-error.log").write_text(detail, encoding="utf-8")
        QMessageBox.critical(None, "启动未完成", f"{error}\n\n详细信息已保存：{data / 'startup-error.log'}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
