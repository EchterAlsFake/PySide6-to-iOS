import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    width: 390
    height: 640
    visible: true
    title: "Hello PySide6 on iOS"
    property int taps: 0
    ColumnLayout {
        anchors.centerIn: parent
        spacing: 20
        Label { text: "Hello Python + Qt!"; font.pixelSize: 24 }
        Button {
            text: "Tapped " + taps + " times"
            onClicked: taps += 1
        }
    }
}
