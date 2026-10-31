"""Full-matrix import/link smoke app; does not exercise every module's features."""
import importlib
import json
from pathlib import Path
import sys
import traceback

documents = Path.home() / "Documents"
documents.mkdir(exist_ok=True)
sys.stdout = (documents / "matrix-smoke.log").open("w", buffering=1)
sys.stderr = sys.stdout

try:
    # Explicit imports let pyside6-ios-deploy discover static binding registrations.
    from PySide6 import (QtCore, QtGui, QtWidgets, QtPrintSupport, QtSql, QtNetwork,
                         QtTest, QtConcurrent, QtXml, QtHelp, QtMultimedia,
                         QtMultimediaWidgets, QtOpenGL, QtOpenGLWidgets, QtPdf,
                         QtPdfWidgets, QtPositioning, QtLocation, QtNetworkAuth,
                         QtNfc, QtQml, QtQuick, QtQuick3D, QtQuickControls2,
                         QtCanvasPainter, QtQuickTest, QtQuickWidgets, QtLabsStyleKit,
                         QtRemoteObjects, QtScxml, QtSensors, QtStateMachine,
                         QtTextToSpeech, QtCharts, QtSpatialAudio, QtSvg, QtSvgWidgets,
                         QtDataVisualization, QtGraphs, QtGraphsWidgets, QtBluetooth,
                         QtUiTools, QtWebChannel, QtWebSockets, QtHttpServer, QtWebView,
                         Qt3DCore, Qt3DRender, Qt3DInput, Qt3DLogic, Qt3DAnimation, Qt3DExtras,
                         QtQmlFeatures)
    import PySide6
    from PySide6._config import built_modules

    imported = []
    for name in built_modules:
        importlib.import_module("PySide6.Qt" + name)
        imported.append(name)
    importlib.import_module("PySide6.QtAsyncio")
    app = QtWidgets.QApplication(sys.argv)
    window = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(window)
    label = QtWidgets.QLabel(f"Qt {QtCore.qVersion()} / Python {sys.version.split()[0]}\n"
                            f"{len(imported)} binding modules imported")
    label.setWordWrap(True)
    layout.addWidget(label)
    button = QtWidgets.QPushButton("Tap to test")
    layout.addWidget(button)
    count = 0

    def report():
        result = {"python": sys.version, "pyside": PySide6.__version__, "qt": QtCore.qVersion(),
                  "os_type": QtCore.QSysInfo.productType(), "os_version": QtCore.QSysInfo.productVersion(),
                  "cpu": QtCore.QSysInfo.currentCpuArchitecture(),
                  "binding_count": len(imported), "imported": imported, "taps": count,
                  "pyside_helpers_imported": ["QtQmlFeatures", "QtAsyncio"],
                  "window_visible": window.isVisible(), "all_imports_succeeded": True,
                  "module_features_exercised": False}
        (documents / "matrix-smoke.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)

    def tapped():
        global count
        count += 1
        button.setText(f"Tapped {count} times")
        report()

    button.clicked.connect(tapped)
    window.resize(360, 600)
    window.show()
    QtCore.QTimer.singleShot(2000, report)
    sys.exit(app.exec())
except BaseException:
    traceback.print_exc()
    raise
