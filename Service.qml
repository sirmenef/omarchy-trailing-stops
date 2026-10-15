import QtQuick
import Quickshell
import Quickshell.Io

// Single instance: the only thing that fetches prices and sends alerts.
// Bar widgets (one per monitor) just read the state file this keeps current.
Item {
  id: root
  property var shell: null
  property real intervalMin: 5

  // The refresh period is set from the panel (tracker.py interval); pick it up as soon as it's saved.
  FileView {
    path: Quickshell.env("HOME") + "/.config/omarchy/trailing-stops.json"
    watchChanges: true
    printErrors: false
    // text() is stale inside the change signal, so re-read and parse in onLoaded.
    onFileChanged: reload()
    onLoaded: {
      try { root.intervalMin = JSON.parse(text()).interval_min || 5 } catch (e) {}
    }
  }

  Process {
    id: checkProcess
    command: ["python3", Qt.resolvedUrl("tracker.py").toString().replace("file://", ""), "check"]
  }

  Timer {
    interval: root.intervalMin * 60000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: if (!checkProcess.running) checkProcess.running = true
  }
}
