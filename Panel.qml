import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.sirmenef.trailing-stops"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property var stocks: hostWidget ? hostWidget.stocks : ({})
  readonly property var symbols: Object.keys(stocks)
  readonly property var settings: hostWidget ? hostWidget.settings : ({})
  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property var rules: hostWidget ? hostWidget.rules : ({})

  // PanelKeyCatcher eats keys (Esc closes, etc.) unless a text field is being edited.
  property bool editing: false

  // "Buy dip [2.5] %" — a blank field means that alert is off.
  // `value` is the saved %. The field is only rewritten when that changes (a save), so the 30 s
  // refresh can't wipe a half-typed number: an unchanged string property doesn't signal.
  component PctField: Row {
    id: pctField
    property string label
    property alias text: field.text
    property string value
    property color foreground
    property string fontFamily
    readonly property bool editing: field.activeFocus
    signal accepted()
    onValueChanged: field.text = value
    Component.onCompleted: field.text = value
    spacing: Style.space(3)

    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: pctField.label
      font.family: pctField.fontFamily
      font.pixelSize: Style.font.caption
      color: pctField.foreground
    }
    TextField {
      id: field
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(46)
      verticalPadding: Style.space(3)
      horizontalAlignment: TextInput.AlignRight
      placeholderText: "off"
      foreground: pctField.foreground
      font.family: pctField.fontFamily
      font.pixelSize: Style.font.caption
      onAccepted: pctField.accepted()
    }
    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: "%"
      font.family: pctField.fontFamily
      font.pixelSize: Style.font.caption
      color: pctField.foreground
    }
  }

  function open() {
    if (hostWidget) hostWidget.run(["show"])
    root.controller.show()
  }
  function close() { root.controller.hide() }
  function toggle() { root.opened ? root.close() : root.open() }

  function run(args) { if (hostWidget) hostWidget.run(args) }
  function money(n) { return n === undefined ? "–" : n.toFixed(2) }
  function signed(n) { return (n >= 0 ? "▲ " : "▼ ") + Math.abs(n).toFixed(2) + "%" }

  function pctText(rule, dir) { return rule[dir] !== undefined ? String(rule[dir]) : "" }

  readonly property var alerts: ["dip", "up", "down"]  // display order
  readonly property var names: ({ dip: "Buy dip", up: "Buy bounce", down: "Sell stop" })

  function detail(dir, t, price) {
    var up = dir === "up"
    var away = (up ? t.level - price : price - t.level) / price * 100
    var from = dir === "dip" ? "  close " : (up ? "  low " : "  high ")
    return names[dir] + from + money(t.anchor) + "  →  alert " + (up ? "≥ " : "≤ ") + money(t.level) +
      (t.status === "triggered" ? "  ·  TRIGGERED " + new Date(t.triggered_at).toLocaleTimeString(Qt.locale(), "HH:mm") +
                                  (dir === "dip" ? ", re-arms next session" : "")
                                : "  ·  " + away.toFixed(2) + "% away")
  }

  readonly property string lastChecked: {
    var t = symbols.map(function(s) { return stocks[s].checked_at || "" }).sort().pop()
    return t ? "checked " + new Date(t).toLocaleTimeString(Qt.locale(), "HH:mm") : ""
  }

  // Clear the add field once the ticker shows up in the list.
  Connections {
    target: root.hostWidget
    function onStocksChanged() {
      if (root.stocks[tickerField.text.trim().toUpperCase()]) tickerField.text = ""
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(470))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: root.editing
      onCloseRequested: root.close()

      Column {
        id: content
        width: parent.width
        spacing: Style.space(10)

        // Header
        Item {
          width: parent.width
          height: refreshButton.height

          Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "Trailing Stops"
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            color: root.fg
          }

          Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(6)

            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: root.lastChecked
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              color: root.fg
              opacity: 0.6
            }

            Button {
              id: refreshButton
              iconText: "󰑓"
              iconSpinning: root.hostWidget ? root.hostWidget.busy : false
              tooltipText: "Fetch prices now"
              foreground: root.fg
              fontFamily: root.fontFamily
              onClicked: root.run(["check"])
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.fg }

        // One block per tracked share
        Repeater {
          model: root.symbols

          delegate: Column {
            id: row
            required property string modelData
            readonly property var it: root.stocks[modelData] || ({})
            readonly property var rule: root.rules[modelData] || ({})
            function save() {
              root.run(["set", modelData, upField.text, downField.text, dipField.text])
              keyCatcher.forceActiveFocus()
            }
            width: content.width
            spacing: Style.space(4)

            Item {
              width: parent.width
              height: controls.height

              Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(10)

                Text {
                  text: row.modelData
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                  color: root.hostWidget ? root.hostWidget.tickerColor(row.it, root.fg) : root.fg
                }
                Text {
                  text: root.money(row.it.price)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  color: root.fg
                }
                Text {
                  visible: row.it.price !== undefined && row.it.prev_close !== undefined
                  text: visible ? root.signed((row.it.price - row.it.prev_close) / row.it.prev_close * 100) : ""
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  color: root.fg
                  opacity: 0.7
                }
              }

              Row {
                id: controls
                anchors.right: parent.right
                spacing: Style.space(8)

                PanelActionButton {
                  anchors.verticalCenter: parent.verticalCenter
                  iconText: "󰦛"
                  tooltipText: "Reset: restart buy bounce and sell stop from yesterday's close"
                  foreground: root.fg
                  fontFamily: root.fontFamily
                  onClicked: root.run(["reset", row.modelData])
                }

                PanelActionButton {
                  anchors.verticalCenter: parent.verticalCenter
                  iconText: "󰆴"
                  tooltipText: "Stop tracking " + row.modelData
                  foreground: root.fg
                  hoverColor: root.urgent
                  fontFamily: root.fontFamily
                  onClicked: root.run(["remove", row.modelData])
                }
              }
            }

            Row {
              spacing: Style.space(14)

              PctField {
                id: dipField
                label: root.names.dip
                value: root.pctText(row.rule, "dip")
                foreground: root.fg
                fontFamily: root.fontFamily
                onEditingChanged: root.editing = editing
                onAccepted: row.save()
              }

              PctField {
                id: upField
                label: root.names.up
                value: root.pctText(row.rule, "up")
                foreground: root.fg
                fontFamily: root.fontFamily
                onEditingChanged: root.editing = editing
                onAccepted: row.save()
              }

              PctField {
                id: downField
                label: root.names.down
                value: root.pctText(row.rule, "down")
                foreground: root.fg
                fontFamily: root.fontFamily
                onEditingChanged: root.editing = editing
                onAccepted: row.save()
              }
            }

            // One line per active alert.
            Repeater {
              model: root.alerts.filter(function(d) { return row.it[d] !== undefined })

              delegate: Text {
                required property string modelData
                readonly property bool hit: row.it[modelData].status === "triggered"
                width: row.width
                text: root.detail(modelData, row.it[modelData], row.it.price)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                color: hit && root.hostWidget ? root.hostWidget.alertColor(modelData) : root.fg
                opacity: hit ? 1 : 0.7
                elide: Text.ElideRight
              }
            }

            Text {
              visible: row.it.error !== undefined || row.it.price === undefined
              width: parent.width
              text: row.it.error === undefined ? "waiting for first price"
                  : (row.it.price === undefined ? "no price: " : "last fetch failed: ") + row.it.error
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              color: root.urgent
              elide: Text.ElideRight
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.fg }

        // Add a share
        Row {
          spacing: Style.space(8)

          TextField {
            id: tickerField
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(150)
            verticalPadding: Style.space(3)
            placeholderText: "Ticker (WDC, BP:LON)"
            foreground: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            onActiveFocusChanged: root.editing = activeFocus
            onAccepted: addButton.clicked()
          }

          Button {
            id: addButton
            anchors.verticalCenter: parent.verticalCenter
            text: "Add"
            bordered: true
            foreground: root.fg
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            enabled: tickerField.text.trim() !== ""
            onClicked: {
              if (!enabled) return
              root.run(["set", tickerField.text.trim(), newUpField.text, newDownField.text, newDipField.text])
              keyCatcher.forceActiveFocus()
            }
          }
        }

        Row {
          spacing: Style.space(14)

          PctField {
            id: newDipField
            label: root.names.dip
            foreground: root.fg
            fontFamily: root.fontFamily
            onEditingChanged: root.editing = editing
            onAccepted: addButton.clicked()
          }

          PctField {
            id: newUpField
            label: root.names.up
            value: "2.5"
            foreground: root.fg
            fontFamily: root.fontFamily
            onEditingChanged: root.editing = editing
            onAccepted: addButton.clicked()
          }

          PctField {
            id: newDownField
            label: root.names.down
            foreground: root.fg
            fontFamily: root.fontFamily
            onEditingChanged: root.editing = editing
            onAccepted: addButton.clicked()
          }
        }

        PanelSeparator { width: parent.width; foreground: root.fg }

        // Settings
        Row {
          spacing: Style.space(6)

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "Refresh every"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: root.fg
          }

          TextField {
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(46)
            verticalPadding: Style.space(3)
            horizontalAlignment: TextInput.AlignRight
            readonly property string saved: root.settings.interval_min !== undefined ? String(root.settings.interval_min) : ""
            onSavedChanged: text = saved
            foreground: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            onActiveFocusChanged: root.editing = activeFocus
            onAccepted: {
              root.run(["interval", text])
              keyCatcher.forceActiveFocus()
            }
          }

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "min"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: root.fg
          }
        }

        Item {
          width: parent.width
          height: pushField.height

          Text {
            id: phoneLabel
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "Phone"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: root.fg
          }

          TextField {
            id: pushField
            anchors.left: phoneLabel.right
            anchors.leftMargin: Style.space(6)
            anchors.right: testButton.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            verticalPadding: Style.space(3)
            placeholderText: "https://ntfy.sh/your-secret-topic"
            readonly property string saved: root.settings.push_url || ""
            onSavedChanged: text = saved
            foreground: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            onActiveFocusChanged: root.editing = activeFocus
            onAccepted: {
              root.run(["push", text.trim()])
              keyCatcher.forceActiveFocus()
            }
          }

          Button {
            id: testButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: "Test"
            bordered: true
            foreground: root.fg
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            tooltipText: "Save the URL and send a test push"
            enabled: pushField.text.trim() !== ""
            onClicked: {
              if (!enabled) return
              root.run(["push", pushField.text.trim()])
              root.run(["test"])
            }
          }
        }

        Text {
          visible: root.hostWidget && root.hostWidget.lastError !== ""
          width: parent.width
          text: root.hostWidget ? root.hostWidget.lastError : ""
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          color: root.urgent
          wrapMode: Text.Wrap
        }

        Text {
          width: parent.width
          text: "Buy dip alerts when the price is the set % below yesterday's close (once a day). Buy bounce alerts when it rises the set % off its lowest point; sell stop when it falls the set % from its highest — both start at yesterday's close and stay triggered until reset. Leave a field blank to turn it off; press Enter to save. Phone: subscribe to the same URL in the ntfy app."
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          color: root.fg
          opacity: 0.5
          wrapMode: Text.Wrap
        }
      }
    }
  }
}
