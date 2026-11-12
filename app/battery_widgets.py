# SPDX-License-Identifier: GPL-2.0-or-later
"""Code-native connector, cell and history graphics for the battery workspace."""
from datetime import datetime
from math import ceil, floor
from PySide6.QtCore import Qt, QRectF, Signal, QSortFilterProxyModel, QModelIndex, QEvent
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCompleter, QSizePolicy, QSpinBox
from .battery_catalog import ROLE_COLORS, connection_for, catalog, normalized


class ConnectionSpinBox(QSpinBox):
    """Scrolling the settings page must not silently change bus wiring/address."""
    def wheelEvent(self, event):
        event.ignore()


class BatteryFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.terms = []

    def set_query(self, text):
        terms = [normalized(term) for term in text.split() if normalized(term)]
        if hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.terms = terms
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.terms = terms
            self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        index = self.sourceModel().index(row, 0, parent)
        keywords = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        return all(term in keywords for term in self.terms)


class BatterySelector(QComboBox):
    """An editable catalog combo: aliases filter its completion popup too."""
    entry_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_entry = None
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(9)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Search battery model or part number")
        self.source = QStandardItemModel(self)
        self.entries = catalog()
        for entry in self.entries:
            count = len(entry["pins"])
            display = f"{entry['model']} · {entry['manufacturer']} · {count} positions"
            item = QStandardItem(display)
            item.setData(entry, Qt.ItemDataRole.UserRole)
            item.setData(normalized(" ".join([entry["manufacturer"], entry["model"], *entry.get("aliases", [])])), Qt.ItemDataRole.UserRole + 1)
            item.setToolTip(", ".join(entry.get("aliases", [])))
            self.source.appendRow(item)
        self.setModel(self.source)
        self.setCurrentIndex(-1)
        self.lineEdit().setPlaceholderText("Search battery model or part number…")
        self.lineEdit().setClearButtonEnabled(False)
        self.filtered = BatteryFilter(self)
        self.filtered.setSourceModel(self.source)
        completion = QCompleter(self.filtered, self)
        self.setCompleter(completion)
        completion.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completion.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completion.popup().setMinimumWidth(360)
        completion.activated[QModelIndex].connect(self._completion_selected)
        self.activated.connect(self._combo_selected)
        self.lineEdit().textEdited.connect(self._edited)
        self.lineEdit().installEventFilter(self)
        completion.popup().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            popup = self.completer().popup()
            if popup.isVisible() and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                model = self.completer().completionModel()
                current = popup.currentIndex().row()
                row = max(0, min(model.rowCount()-1, current + (1 if event.key() == Qt.Key.Key_Down else -1)))
                popup.setCurrentIndex(model.index(row, 0))
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.selected_entry is None:
                if not self.lineEdit().text().strip():
                    popup.hide()
                    return True
                index = popup.currentIndex()
                entry = index.data(Qt.ItemDataRole.UserRole) if index.isValid() else (
                    self.filtered.index(0, 0).data(Qt.ItemDataRole.UserRole) if self.filtered.rowCount() else None)
                if entry:
                    popup.hide()
                    self._commit(entry)
                    return True
        return super().eventFilter(watched, event)

    def _edited(self, text):
        if self.selected_entry is not None:
            self.selected_entry = None
            self.entry_selected.emit(None)
        self.filtered.set_query(text)
        if text.strip() and self.filtered.rowCount():
            self.completer().setCompletionPrefix("")
            self.completer().complete()
        else:
            self.completer().popup().hide()

    def _completion_selected(self, index):
        self._commit(index.data(Qt.ItemDataRole.UserRole))

    def _combo_selected(self, index):
        self._commit(self.itemData(index))

    def _commit(self, entry):
        if not entry:
            return
        index = next(i for i, value in enumerate(self.entries) if value["id"] == entry["id"])
        self.blockSignals(True)
        self.setCurrentIndex(index)
        self.setEditText(self.itemText(index))
        self.blockSignals(False)
        self.selected_entry = entry
        self.entry_selected.emit(entry)

    def select_id(self, entry_id):
        for entry in self.entries:
            if entry["id"] == entry_id:
                self._commit(entry)
                return True
        return False


class MetricCard(QFrame):
    def __init__(self, title, unit="", parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        layout=QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(2)
        caption=QLabel(title);caption.setObjectName("muted")
        self.value=QLabel("—");self.value.setObjectName("metricValue")
        self.detail=QLabel(unit);self.detail.setObjectName("metricUnit")
        value_row=QHBoxLayout();value_row.setSpacing(4)
        value_row.addWidget(self.value,0,Qt.AlignmentFlag.AlignBaseline)
        value_row.addWidget(self.detail,0,Qt.AlignmentFlag.AlignBaseline);value_row.addStretch()
        layout.addWidget(caption);layout.addLayout(value_row)

    def set_value(self, value, detail=None):
        self.value.setText(str(value))
        if detail is not None:self.detail.setText(detail)


class ConnectorDiagram(QWidget):
    pin_selected=Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entry=None;self.selected=None;self.mirrored=False;self.sda=7;self.scl=9
        self.rects=[]
        self.setFixedHeight(78)
        self.setMinimumWidth(220)
        self.setMaximumWidth(420)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setAccessibleName("Battery connector contact diagram")

    def set_entry(self, entry, sda=7, scl=9):
        self.entry,self.sda,self.scl=entry,sda,scl
        self.selected=None
        count=len(entry["pins"]) if entry else 8
        self.setMinimumWidth(max(220,count*31+16))
        self.setMaximumWidth(max(300,count*40+16))
        self.update()

    def paintEvent(self, event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.entry:
            painter.setPen(QColor("#9da7b5"))
            painter.setFont(QFont("Segoe UI",9))
            painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"Select a battery to see its connector")
            return
        pins=list(self.entry["pins"])
        if self.mirrored:pins.reverse()
        width=min(40,(self.width()-16)/max(1,len(pins)))
        left=(self.width()-width*len(pins))/2
        painter.setPen(QPen(QColor("#354252"),1))
        painter.setBrush(QColor("#1e2834"))
        painter.drawRoundedRect(QRectF(left-6,16,width*len(pins)+12,32),6,6)
        self.rects=[]
        for i,pin in enumerate(pins):
            x=left+i*width
            color=QColor(ROLE_COLORS[pin["role"]])
            painter.setFont(QFont("Segoe UI",7))
            painter.setPen(QColor("#aab6c5"))
            painter.drawText(QRectF(x,0,width,14),Qt.AlignmentFlag.AlignCenter,str(pin["number"]))
            rect=QRectF(x+3,21,width-6,22)
            painter.setPen(QPen(color,2 if self.selected==pin["number"] else 1))
            painter.setBrush(QColor(color.red(),color.green(),color.blue(),48))
            painter.drawRoundedRect(rect,3,3)
            painter.setPen(color);painter.setFont(QFont("Segoe UI",8,QFont.Weight.DemiBold))
            short={"data":"D","clock":"C","ground":"−","positive":"+","temperature":"T","present":"SP","gap":"·","unused":"NC","unknown":"?"}[pin["role"]]
            if pin.get("uncertain"):short+="?"
            painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,short)
            painter.setFont(QFont("Segoe UI",7))
            if (pin["role"] in ("data","clock","ground") or (pin["role"]=="present" and self.entry.get("present_to_ground"))) and not pin.get("uncertain"):
                target={"data":f"GP{self.sda}","clock":f"GP{self.scl}","ground":"GND","present":"B−"}[pin["role"]]
                painter.drawLine(int(x+width/2),49,int(x+width/2),54)
                painter.drawText(QRectF(x,56,width,18),Qt.AlignmentFlag.AlignCenter,target)
            else:
                painter.setPen(QColor("#687687"))
                painter.drawText(QRectF(x,56,width,18),Qt.AlignmentFlag.AlignCenter,"—")
            self.rects.append((rect,pin))

    def mouseMoveEvent(self,event):
        for rect,pin in self.rects:
            if rect.contains(event.position()):
                target,note=connection_for(pin,self.entry,self.sda,self.scl)
                self.setToolTip(f"Contact {pin['number']} · {pin['label']}\n{target}\n{note}")
                return
        self.setToolTip("")

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        for rect,pin in self.rects:
            if rect.contains(event.position()):
                self.selected=pin["number"];self.update();self.pin_selected.emit(pin["number"])
                return


class CellVoltages(QWidget):
    """Cell positions are supplied by a controller; never inferred from pack V."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.voltages=None
        self.setMinimumHeight(82)
        self.setAccessibleName("Individual cell voltages")

    def set_voltages(self, values):
        self.voltages=list(values) if values else None
        self.setAccessibleDescription(
            "; ".join(f"Cell {i+1}: {v/1000:.3f} V" if v else f"Cell {i+1}: unused" for i,v in enumerate(values))
            if values else "Cell voltages not reported")
        self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.voltages:
            p.setPen(QColor("#8f9daf"));p.setFont(QFont("Segoe UI",10))
            p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"Cell voltages not reported")
            return
        n=len(self.voltages);gap=8;w=(self.width()-gap*(n-1))/n
        for i,value in enumerate(self.voltages):
            x=i*(w+gap);rect=QRectF(x,5,w,self.height()-10)
            p.setBrush(QColor("#182d2c" if value else "#171e27"))
            p.setPen(QPen(QColor("#33544d" if value else "#2b3541"),1));p.drawRoundedRect(rect,6,6)
            p.setFont(QFont("Segoe UI",8));p.setPen(QColor("#98aaac"))
            p.drawText(QRectF(x,12,w,18),Qt.AlignmentFlag.AlignCenter,f"CELL {i+1}")
            p.setFont(QFont("Segoe UI",13,QFont.Weight.DemiBold));p.setPen(QColor("#8adac6" if value else "#6e7d8e"))
            p.drawText(QRectF(x,34,w,27),Qt.AlignmentFlag.AlignCenter,f"{value/1000:.3f} V" if value else "Unused")


class TrendPlot(QWidget):
    LABELS={"voltage":("Voltage","V","#76b8ff"),"current":("Current","A","#5ed8bd"),
            "temperature":("Temperature","°C","#efc16f"),"soc":("Charge","%","#c2a4fa")}
    # Minimum headroom and rounding step for each measurement's vertical axis.
    SCALES = {"current": (1, .25), "temperature": (5, 1)}

    def __init__(self,parent=None):
        super().__init__(parent)
        self.history=[];self.metric_key="voltage"
        self._ranges = {}
        self.setMinimumHeight(185)
        self.setAccessibleName("Battery measurement history chart")

    def reset_ranges(self):
        self._ranges.clear()

    def vertical_range(self, minimum, maximum):
        """Follow visible voltage values; keep the other scales steady."""
        if self.metric_key == "voltage":
            return max(0, minimum - 2), maximum + 2
        if self.metric_key == "soc":
            return min(0, floor(minimum)), max(100, ceil(maximum))
        margin, step = self.SCALES[self.metric_key]
        lower = floor((minimum - margin) / step) * step
        upper = ceil((maximum + margin) / step) * step
        previous = self._ranges.get(self.metric_key)
        if previous is not None:
            # Do not recenter for every new sample or shrink as old samples age out.
            lower = min(previous[0], lower) if minimum < previous[0] + step else previous[0]
            upper = max(previous[1], upper) if maximum > previous[1] - step else previous[1]
        self._ranges[self.metric_key] = lower, upper
        return lower, upper

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor("#121922"))
        chart=QRectF(60,20,max(1,self.width()-80),max(1,self.height()-53))
        points=[]
        for item in self.history[-600:]:
            value=item["metrics"].get(self.metric_key)
            if value is not None:points.append((datetime.fromisoformat(item["timestamp"]).timestamp(),float(value)))
        if not points:
            p.setPen(QColor("#8f9daf"))
            p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"Read battery or turn on Live readings to record measurements")
            return
        name,unit,color=self.LABELS[self.metric_key]
        ymin,ymax=self.vertical_range(min(v for t,v in points),max(v for t,v in points))
        first,last=points[0][0],max(points[-1][0],points[0][0]+1)
        p.setFont(QFont("Segoe UI",8))
        for i in range(5):
            y=chart.top()+chart.height()*i/4
            p.setPen(QPen(QColor("#283342"),1));p.drawLine(int(chart.left()),int(y),int(chart.right()),int(y))
            p.setPen(QColor("#9aa9bb"))
            digits=2 if self.metric_key == "current" else 0 if self.metric_key == "soc" else 1
            p.drawText(QRectF(0,y-8,52,18),Qt.AlignmentFlag.AlignRight,f"{ymax-(ymax-ymin)*i/4:.{digits}f}")
        path=QPainterPath()
        for i,(t,value) in enumerate(points):
            x=chart.left()+(t-first)/(last-first)*chart.width()
            y=chart.bottom()-(value-ymin)/(ymax-ymin)*chart.height()
            if i:path.lineTo(x,y)
            else:path.moveTo(x,y)
        p.setPen(QPen(QColor(color),2.2));p.drawPath(path)
        p.setBrush(QColor(color))
        p.drawEllipse(path.currentPosition(),3,3)
        p.setPen(QColor("#aab6c5"))
        p.drawText(QRectF(chart.left(),chart.bottom()+10,chart.width(),20),Qt.AlignmentFlag.AlignLeft,f"{name} · {unit}  /  last {points[-1][0]-first:.0f} seconds")
