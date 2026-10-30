"""Minimal Qt Quick/Material smoke app: no providers, accounts or external network."""
from pathlib import Path
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow  # Include/register Quick bindings in the static launcher.
from PySide6.QtQuickControls2 import QQuickStyle

app = QGuiApplication(sys.argv)
QQuickStyle.setStyle("Material")
engine = QQmlApplicationEngine()
engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("Main.qml"))))
if not engine.rootObjects():
    raise SystemExit("QML window creation failed")
raise SystemExit(app.exec())
