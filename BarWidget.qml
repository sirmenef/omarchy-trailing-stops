import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.sirmenef.trailing-stops"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property string tracker: Qt.resolvedUrl("tracker.py").toString().replace("file://", "")
  property var stocks: ({})
  property var settings: ({})
  property var rules: ({})
  property string lastError: ""
  readonly property bool busy: proc.running
  readonly property var symbols: Object.keys(stocks)
  // The icon says what needs doing: red = a sell stop fired, green = a buy dip or buy bounce fired
  // (sell wins if both), theme colour = nothing to do. Bounce/stop stay lit until reset; a dip until
  // the next trading day. Fixed colours: themes don't reliably have a green (aetheria's color2 is red).
  readonly property var sells: symbols.filter(function(s) { return fired(stocks[s], ["down"]) })
  readonly property var buys: symbols.filter(function(s) { return fired(stocks[s], ["dip", "up"]) })
  function fired(it, dirs) {
    return dirs.some(function(d) { return it[d] !== undefined && it[d].status === "triggered" })
  }
  readonly property color sellColor: "#e5484d"
  readonly property color buyColor: "#30a46c"
  // The panel colours each ticker and alert line the same way as the icon.
  function alertColor(direction) { return direction === "down" ? sellColor : buyColor }
  function tickerColor(it, neutral) {
    return fired(it, ["down"]) ? sellColor : fired(it, ["dip", "up"]) ? buyColor : neutral
  }

  // Panel actions (set/remove/reset/check) are queued so a click never gets dropped
  // because the previous command is still fetching prices.
  property var queue: []
  function run(args) {
    queue = queue.concat([args])
    next()
  }
  function next() {
    if (proc.running || queue.length === 0) return
    proc.command = ["python3", tracker].concat(queue[0])
    queue = queue.slice(1)
    proc.running = true
  }

  Process {
    id: proc
    stdout: StdioCollector {
      onStreamFinished: {
        if (!text.trim()) return
        try {
          var d = JSON.parse(text)
          root.stocks = d.stocks
          root.settings = d.settings
          root.rules = d.rules
        } catch (e) { console.log("trailing-stops: " + e) }
      }
    }
    stderr: StdioCollector {
      onStreamFinished: root.lastError = text.trim()
    }
    onExited: root.next()
  }

  // The service does the fetching; this only re-reads its state file.
  Timer {
    interval: 30000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: if (!proc.running) root.run(["show"])
  }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  // Bar framework panel contract — required for proper open/close coordination
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }

  onBarChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰄨"
    active: root.sells.length > 0 || root.buys.length > 0
    activeColor: root.sells.length > 0 ? root.sellColor : root.buyColor
    tooltipText: [root.sells.length ? "Sell stop: " + root.sells.join(", ") : "",
                  root.buys.length ? "Buy signal: " + root.buys.join(", ") : ""]
                 .filter(function(t) { return t }).join("\n") || "Trailing stops: nothing to do"
    hasVisualContent: true
    horizontalMargin: 8.75
    verticalPadding: 8.75

    onPressed: function(b) {
      if (b === Qt.LeftButton && panelLoader.item) panelLoader.item.toggle()
      else if (b === Qt.MiddleButton) root.run(["check"])
    }
  }
}
