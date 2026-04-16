# NOTE that this code evolved from this post:
# http://www.qgis.nl/2019/02/14/about-layer-tree-embedded-widgets-and-have-your-wmts-always-crispy-sharp/?lang=en
# Thank you to the author, Richard Duivenvoorde (Zuidt)
# which evolved from this code:
#   code from https://github.com/qgis/QGIS/pull/3170
#
# This is a work in progress. There are many things still to improve.
# TODO: save settings
# vlayer.setCustomProperty("mytext", "hello world")
# read the value again (returning "default text" if not found)
# mytext = vlayer.customProperty("mytext", "default text")


WIDGET_SETTING_PREFIX = "legend_data_filter_%s"

from qgis.PyQt.QtWidgets import *
from qgis.PyQt.QtWidgets import QListWidget, QListWidgetItem, QDialog, QComboBox, QTableWidget, QTableWidgetItem, QDialogButtonBox, QMessageBox
from qgis.PyQt import QtCore
from qgis.core import QgsMessageLog, QgsAggregateCalculator, Qgis
from qgis.core import QgsMapLayer, QgsExpression, QgsExpressionContext, QgsExpressionContextUtils
from qgis.PyQt.QtCore import QDate, QDateTime
from qgis.gui import QgsLayerTreeEmbeddedWidgetProvider, QgsLayerTreeEmbeddedWidgetRegistry
from .qrangeslider import QRangeSlider

import numbers
import math


class CategoryFilterWidget(QWidget):
    def __init__(self, parent, field_name, unique_values, is_spacious=False):
        QWidget.__init__(self)
        self.parent = parent
        self.field_name = field_name
        self._dirty = False
        self.is_spacious = is_spacious

        layout = QVBoxLayout() if is_spacious else QHBoxLayout()
        self.setLayout(layout)

        label = QLabel(field_name)
        label.setToolTip(field_name)
        label.setFixedWidth(120 if is_spacious else 60)

        self.list_widget = QListWidget()
        if not is_spacious:
            self.list_widget.setFixedHeight(40)
        else:
            self.list_widget.setFixedHeight(80)

        for val in unique_values:
            val_str = str(val) if val is not None else "NULL"
            item = QListWidgetItem(val_str)
            item.setData(QtCore.Qt.UserRole, val)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.list_widget.addItem(item)

        self.list_widget.itemChanged.connect(self.on_value_changed)

        layout.addWidget(label)
        layout.addWidget(self.list_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.installEventFilter(self)

    def eventFilter(self, source, event):
        if event.type() == QtCore.QEvent.ContextMenu and source is self:
            menu = QMenu()
            action_hide = menu.addAction('Hide')
            action_number = menu.addAction('Treat as Number')
            action_date = menu.addAction('Treat as Date')
            action_category = menu.addAction('Treat as Category')
            menu.addSeparator()
            action_options = menu.addAction('Options...')
            selected_action = menu.exec_(event.globalPos())
            if selected_action == action_hide:
                if hasattr(self.parent, 'on_coerce_slider_hide'):
                    self.parent.on_coerce_slider_hide(self)
            elif selected_action == action_number:
                if hasattr(self.parent, 'on_coerce_slider_number'):
                    self.parent.on_coerce_slider_number(self)
            elif selected_action == action_date:
                if hasattr(self.parent, 'on_coerce_slider_date'):
                    self.parent.on_coerce_slider_date(self)
            elif selected_action == action_category:
                if hasattr(self.parent, 'on_coerce_slider_category'):
                    self.parent.on_coerce_slider_category(self)
            elif selected_action == action_options:
                if hasattr(self.parent, 'on_options_menu'):
                    self.parent.on_options_menu()
            return True
        return False

    def getRangeFilter(self):
        if not self._dirty:
            return ""

        checked_values = []
        all_checked = True
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                checked_values.append(item.data(QtCore.Qt.UserRole))
            else:
                all_checked = False

        if all_checked:
            return ""
        if not checked_values:
            return "1 = 0"

        formatted_values = []
        has_null = False
        for v in checked_values:
            if v is None:
                has_null = True
            elif isinstance(v, (int, float)):
                formatted_values.append(str(v))
            else:
                formatted_values.append("'" + str(v).replace("'", "''") + "'")

        conditions = []
        if formatted_values:
            in_clause = ", ".join(formatted_values)
            conditions.append(f'"{self.field_name}" IN ({in_clause})')
        if has_null:
            conditions.append(f'"{self.field_name}" IS NULL')

        if not conditions:
            return "1 = 0"
        return " OR ".join(conditions)

    def on_value_changed(self, item=None):
        if not self._dirty:
            QgsMessageLog.logMessage("Switching category field %s to dirty" % self.field_name, 'Range Filter Plugin', level=Qgis.Info)
            self._dirty = True
        self.parent.on_slider_changed(self)



class OptionsDialog(QDialog):
    def __init__(self, layer, parent=None, default_hidden=False):
        super(OptionsDialog, self).__init__(parent)
        self.layer = layer
        self.setWindowTitle("Options...")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)

        self.layout = QVBoxLayout(self)

        # UI Mode toggle
        self.mode_layout = QHBoxLayout()
        self.mode_label = QLabel("UI Mode:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Classic", "Spacious"])
        current_mode = self.layer.customProperty(WIDGET_SETTING_PREFIX % "UI_MODE", "Classic")
        self.mode_combo.setCurrentText(current_mode)
        self.mode_layout.addWidget(self.mode_label)
        self.mode_layout.addWidget(self.mode_combo)
        self.layout.addLayout(self.mode_layout)

        # Fields Table
        self.table = QTableWidget()
        db = self.layer.dataProvider()
        fields = db.fields()
        self.table.setColumnCount(2)
        self.table.setRowCount(len(fields))
        self.table.setHorizontalHeaderLabels(["Field", "Data Type"])
        self.table.horizontalHeader().setStretchLastSection(True)

        self.field_combos = {}

        slider_names = self.layer.customProperty(WIDGET_SETTING_PREFIX % SLIDER_LIST_CONFIG_NAME, None)
        active_sliders = set(slider_names.split("###")) if slider_names is not None else None

        for i, field in enumerate(fields):
            field_name = field.name()
            item = QTableWidgetItem(field_name)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(i, 0, item)

            combo = QComboBox()
            combo.addItems(["Hidden/Ignore", "Number", "Date", "Category"])

            # Read existing coercion property or determine default
            coerced_setting = self.layer.customProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + field_name), None)

            if coerced_setting:
                if coerced_setting == "HIDDEN":
                    combo.setCurrentText("Hidden/Ignore")
                elif coerced_setting == "NUMBER":
                    combo.setCurrentText("Number")
                elif coerced_setting == "DATE":
                    combo.setCurrentText("Date")
                elif coerced_setting == "CATEGORY":
                    combo.setCurrentText("Category")
            else:
                if active_sliders is not None and field_name not in active_sliders:
                    combo.setCurrentText("Hidden/Ignore")
                elif default_hidden:
                    combo.setCurrentText("Hidden/Ignore")
                else:
                    # Default Logic
                    if field.isNumeric():
                        combo.setCurrentText("Number")
                    elif (hasattr(field, 'isDateOrTime') and field.isDateOrTime()) or field.type() in [QtCore.QVariant.Date, QtCore.QVariant.DateTime]:
                        combo.setCurrentText("Date")
                    else:
                        # Default string etc to Category, we will show warning later if too many
                        combo.setCurrentText("Category")

            # Connect combo change event to check category size
            combo.currentTextChanged.connect(lambda text, fname=field_name, c=combo: self.check_category_size(text, fname, c))

            self.table.setCellWidget(i, 1, combo)
            self.field_combos[field_name] = combo

        self.layout.addWidget(self.table)

        # Dialog Buttons
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.layout.addWidget(self.buttonBox)

    def check_category_size(self, text, field_name, combo):
        if text == "Category":
            try:
                # Try to get unique values count
                # Note: For large layers this could be slow, but it's requested functionality
                idx = self.layer.dataProvider().fieldNameIndex(field_name)
                unique_values = self.layer.uniqueValues(idx)
                if len(unique_values) > 10:
                    reply = QMessageBox.warning(self, "Warning", f"Are you sure? There are {len(unique_values)} distinct items!",
                                                QMessageBox.Yes | QMessageBox.No)
                    if reply == QMessageBox.No:
                        # Reset to previous or Hidden
                        combo.blockSignals(True)
                        combo.setCurrentText("Hidden/Ignore")
                        combo.blockSignals(False)
            except Exception as e:
                pass

    def accept(self):
        # Save mode
        self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % "UI_MODE", self.mode_combo.currentText())

        # Save fields
        sliders = []
        for field_name, combo in self.field_combos.items():
            val = combo.currentText()
            if val == "Hidden/Ignore":
                self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + field_name), "HIDDEN")
            elif val == "Number":
                self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + field_name), "NUMBER")
                sliders.append(field_name)
            elif val == "Date":
                self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + field_name), "DATE")
                sliders.append(field_name)
            elif val == "Category":
                self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + field_name), "CATEGORY")
                sliders.append(field_name)

        self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % SLIDER_LIST_CONFIG_NAME, "###".join(sliders))
        super(OptionsDialog, self).accept()
        if hasattr(self.parent(), 'on_options_closed'):
            self.parent().on_options_closed()


class RangeSlider(QWidget):
    def __init__(self, parent, field_name, fmin, fmax, is_date_or_time=False, is_numeric=False, is_spacious=False):
        if not isinstance(fmin, numbers.Number) or not isinstance(fmax, numbers.Number):
          raise ValueError("Min or Max is not a number")
        self.is_date_or_time = is_date_or_time
        self.is_numeric = is_numeric
        QWidget.__init__(self)
        self.parent = parent
        self.field_name = field_name
        self.fmin = fmin
        self.fmax = fmax
        self._dirty = False
        self.slider = QRangeSlider()
        self.slider.setDrawValues(True, self)
        self.slider.setFixedHeight(24 if is_spacious else 16)
        self.slider.startValueChanged.connect(self.on_value_changed)
        self.slider.endValueChanged.connect(self.on_value_changed)

        QgsMessageLog.logMessage("Creating Range Slider for field %s" % self.field_name, 'Range Filter Plugin', level=Qgis.Info)


        #self.on_value_changed()

        layout = QVBoxLayout() if is_spacious else QHBoxLayout()
        label = QLabel(field_name)
        label.setToolTip(field_name)
        label.setFixedWidth(120 if is_spacious else 60)
        layout.addWidget(label)
        layout.addWidget(self.slider)

        if is_spacious:
            layout.setContentsMargins(0, 5, 0, 10)
        else:
            layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.installEventFilter(self)

    def pretty(self, slider_num):
        num = (float(slider_num)/self.slider.max()) * (self.fmax - self.fmin) + self.fmin
        # handle edge case where the max and the min are the same
        if self.fmax == self.fmin:
          # disable slider movement if there's no range
          self.slider.setEnabled(False)
          if self.is_date_or_time:
             msecs = int(self.fmax) if abs(self.fmax) > 30000000000 else int(self.fmax * 1000)
             return QDateTime.fromMSecsSinceEpoch(msecs).toString("yyyy-MM-dd HH:mm:ss")
          if self.fmax > 10:
            return str(int(self.fmax))
          else:
            return '{0:.2f}'.format(self.fmax)

        pretty_out = ""

        # handle corner case where we're looking at the maximum number, and need to make sure the filter value is above that
        if num == self.fmax:
          if self.is_date_or_time:
            pass # exact max
          elif self.fmax - self.fmin > 10:
            pretty_out = str(math.ceil(num))
          else:
            num += 0.01
            pretty_out = '{0:.2f}'.format(num)
        elif self.is_date_or_time:
            pass # handle below
        elif self.fmax - self.fmin > 10:
            pretty_out = str(int(num))
        else:
            pretty_out = '{0:.2f}'.format(num)

        if self.is_date_or_time:
            msecs = int(num) if abs(num) > 30000000000 else int(num * 1000)
            dt = QDateTime.fromMSecsSinceEpoch(msecs)
            diff = self.fmax - self.fmin
            if abs(self.fmax) > 30000000000 or abs(self.fmin) > 30000000000:
                diff /= 1000
            if diff < 86400:
                pretty_out = dt.toString("HH:mm:ss")
            elif diff < 2592000:
                pretty_out = dt.toString("yyyy-MM-dd HH:mm")
            else:
                pretty_out = dt.toString("yyyy-MM-dd")

        #QgsMessageLog.logMessage("Slider Value: %f, Converted num: %s" % (slider_num, pretty_out), 'Range Filter Plugin', level=Qgis.Info)

        return pretty_out

    def getQueryValue(self, slider_num):
        num = (float(slider_num)/self.slider.max()) * (self.fmax - self.fmin) + self.fmin

        if self.is_date_or_time and not self.is_numeric:
            msecs = int(num) if abs(num) > 30000000000 else int(num * 1000)
            dt = QDateTime.fromMSecsSinceEpoch(msecs)
            return "'" + dt.toString("yyyy-MM-dd HH:mm:ss") + "'"

        if self.fmax == self.fmin:
            return str(self.fmax)

        if num == self.fmax:
          if self.fmax - self.fmin > 10:
            return str(math.ceil(num))
          else:
            num += 0.01
            return str(num)
        elif self.fmax - self.fmin > 10:
            return str(int(num))
        else:
            return str(num)


    def eventFilter(self, source, event):
        # handle right click removal of features to filter
        if (event.type() == QtCore.QEvent.ContextMenu and
            source is self):
            menu = QMenu()
            action_hide = menu.addAction('Hide')
            action_number = menu.addAction('Treat as Number')
            action_date = menu.addAction('Treat as Date')
            action_category = menu.addAction('Treat as Category')
            menu.addSeparator()
            action_options = menu.addAction('Options...')

            selected_action = menu.exec_(event.globalPos())
            if selected_action == action_hide:
                if hasattr(self.parent, 'on_coerce_slider_hide'):
                    self.parent.on_coerce_slider_hide(self)
            elif selected_action == action_number:
                if hasattr(self.parent, 'on_coerce_slider_number'):
                    self.parent.on_coerce_slider_number(self)
            elif selected_action == action_date:
                if hasattr(self.parent, 'on_coerce_slider_date'):
                    self.parent.on_coerce_slider_date(self)
            elif selected_action == action_category:
                if hasattr(self.parent, 'on_coerce_slider_category'):
                    self.parent.on_coerce_slider_category(self)
            elif selected_action == action_options:
                if hasattr(self.parent, 'on_options_menu'):
                    self.parent.on_options_menu()

            return True
        return False #super(DataRangeSliders, self).eventFilter(source, event)

    def _getStartEndValuesStr(self):
        return (self.getQueryValue(self.slider.start()), self.getQueryValue(self.slider.end()))

    def getRangeFilter(self):
        if self._dirty == False:
          return ""

        (start_actual_val, end_actual_val) = self._getStartEndValuesStr()
        filter_clause1 = '"%s" >= %s' % (self.field_name, start_actual_val)
        filter_clause2 = '"%s" <= %s' % (self.field_name, end_actual_val)
        filter_clause = filter_clause1 + ' AND ' + filter_clause2
        return filter_clause

    def on_value_changed(self):
        if self._dirty == False:
          QgsMessageLog.logMessage("Switching field %s to dirty" % self.field_name, 'Range Filter Plugin', level=Qgis.Info)
          self._dirty = True
        self.parent.on_slider_changed(self)

SLIDER_LIST_CONFIG_NAME = "!!SLIDERS!!"
class DataLayerRangeFilterWidget(QWidget):

    def __init__(self, layer):
        QWidget.__init__(self)
        #QgsMessageLog.logMessage("Widget Loaded", 'Range Filter Plugin', level=Qgis.Info)

        layout = QVBoxLayout()
        layout.setSpacing(2)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self.layer = layer
        self.sliders = []
        self.layout = layout

        db = self.layer.dataProvider()
        # TURN OFF ALL FILTERING prior to analyzing the data
        # TODO: take whatever filter already exists on the data now and make sure those are
        # honoured.
        db.setSubsetString("")

        slider_names = self.layer.customProperty(WIDGET_SETTING_PREFIX % SLIDER_LIST_CONFIG_NAME, None)
        schema_version = self.layer.customProperty(WIDGET_SETTING_PREFIX % "SCHEMA_VERSION", None)

        if slider_names is not None:
            if schema_version is None:
                # Old version: force classic UI to prevent layout breakage
                self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % "UI_MODE", "Classic")
                self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % "SCHEMA_VERSION", "2")

            slider_names = slider_names.split("###")
            for name in slider_names:
                self._add_filter(name)
        else:
            # First time user is setting up this layer
            msg_box = QMessageBox()
            msg_box.setWindowTitle("Setup Range Filters")
            msg_box.setText("Do you want to select which fields to filter manually, or let the plugin auto-pick the best fields?")
            btn_select = msg_box.addButton("Select Fields", QMessageBox.ActionRole)
            btn_auto = msg_box.addButton("Auto-Pick", QMessageBox.ActionRole)
            msg_box.exec_()

            self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % "SCHEMA_VERSION", "2")

            if msg_box.clickedButton() == btn_select:
                # Let user configure manually
                dialog = OptionsDialog(self.layer, self, default_hidden=True)
                dialog.exec_()
                # If they hit cancel, the config is unpopulated, which is fine

                # Check what was saved (if accepted)
                saved_sliders = self.layer.customProperty(WIDGET_SETTING_PREFIX % SLIDER_LIST_CONFIG_NAME, None)
                if saved_sliders:
                    for name in saved_sliders.split("###"):
                        self._add_filter(name)
            else:
                # Auto pick
                for field in db.fields():
                    QgsMessageLog.logMessage("Adding slider for field %s" % field.name(), 'Range Filter Plugin', level=Qgis.Warning)
                    self._add_filter(field.name())

        QgsMessageLog.logMessage("DONE adding sliders", 'Range Filter Plugin', level=Qgis.Warning)
        self._save_sliders()

        # cleanup handling
        self.layer.willBeDeleted.connect(self.onLayerRemoved)
        self.installEventFilter(self)

    def onLayerRemoved(self):
      self.layer = None

    def on_options_menu(self):
        dialog = OptionsDialog(self.layer, self)
        dialog.exec_()

    def on_options_closed(self):
        # Clear existing layout and sliders
        for slider in self.sliders:
            self.layout.removeWidget(slider)
            slider.deleteLater()
        self.sliders = []

        # Reload
        slider_names = self.layer.customProperty(WIDGET_SETTING_PREFIX % SLIDER_LIST_CONFIG_NAME, None)
        if slider_names is not None:
            slider_names = slider_names.split("###")
            for name in slider_names:
                self._add_filter(name)
        else:
            db = self.layer.dataProvider()
            for field in db.fields():
                self._add_filter(field.name())
        self._save_sliders()
        self.on_slider_changed(None)

        current_width = self.width()
        self.adjustSize()
        self.resize(current_width, self.height())
        self.updateGeometry()

    def eventFilter(self, source, event):
      # TODO: This event is emitted when the legend widget is removed. I am not sure if this is the right way to handle widget removeal
      # with QGIS. Requires asking around and looking at some examples and docs, which weren't easy to find alas.
      if self.layer and event.type() == QtCore.QEvent.DeferredDelete:
        #QgsMessageLog.logMessage("Event %d" % event.type(), 'Range Filter Plugin', level=Qgis.Warning)
        db = self.layer.dataProvider()
        db.setSubsetString("")
      return False

    def _save_sliders(self):
        slider_names = [slider.field_name for slider in self.sliders]
        self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % SLIDER_LIST_CONFIG_NAME, "###".join(slider_names))

    def _add_filter(self, field_name):
        db = self.layer.dataProvider()
        i = db.fieldNameIndex(field_name)
        if i != -1:
          field = db.fields()[i]

          # retrieve coercion setting if exists
          coerced_setting = self.layer.customProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + field_name), None)

          if coerced_setting == "HIDDEN":
              return

          ui_mode = self.layer.customProperty(WIDGET_SETTING_PREFIX % "UI_MODE", "Classic")
          is_spacious = (ui_mode == "Spacious")

          is_date_or_time = False
          is_numeric = False
          is_category = False

          if coerced_setting == "DATE":
              is_date_or_time = True
          elif coerced_setting == "NUMBER":
              is_numeric = True
          elif coerced_setting == "CATEGORY":
              is_category = True
          else:
              # Auto-detection
              if field.isNumeric():
                  is_numeric = True
              elif (hasattr(field, 'isDateOrTime') and field.isDateOrTime()) or field.type() in [QtCore.QVariant.Date, QtCore.QVariant.DateTime]:
                  is_date_or_time = True
              else:
                  # Check unique values count for auto-category
                  unique_values = self.layer.uniqueValues(i)
                  if 1 < len(unique_values) < 10:
                      is_category = True
                  else:
                      # If >= 10 or <= 1, don't show it by default
                      return

          if is_category:
              unique_values = self.layer.uniqueValues(i)
              try:
                  widget = CategoryFilterWidget(self, field_name, unique_values, is_spacious=is_spacious)
                  self.layout.addWidget(widget)
                  widget.show()
                  self.sliders.append(widget) # re-use sliders array for generic widgets
              except Exception as e:
                  QgsMessageLog.logMessage("Error for category fieldname %s: %s" % (field_name, str(e)), 'Range Filter Plugin', level=Qgis.Warning)
          else:
              field_max = self.layer.aggregate(QgsAggregateCalculator.Max, field.name())[0]
              field_min = self.layer.aggregate(QgsAggregateCalculator.Min, field.name())[0]

              if is_date_or_time:
                  # convert to timestamp (epoch seconds) for slider
                  import datetime
                  def _to_timestamp(val):
                      if hasattr(val, 'toMSecsSinceEpoch'):
                          return val.toMSecsSinceEpoch() / 1000.0
                      elif type(val) is QtCore.QDate:
                          return QtCore.QDateTime(val).toMSecsSinceEpoch() / 1000.0
                      elif hasattr(val, 'toPython'):
                          return val.toPython().timestamp()
                      elif type(val) is datetime.date:
                          return datetime.datetime(val.year, val.month, val.day).timestamp()
                      elif type(val) is datetime.datetime:
                          return val.timestamp()
                      return val

                  field_max = _to_timestamp(field_max)
                  field_min = _to_timestamp(field_min)
              elif coerced_setting is not None:
                  # ensure field max/min are numbers in case they were natively dates but forced to numbers
                  if hasattr(field_max, 'toMSecsSinceEpoch') or type(field_max) in [QtCore.QDate, QtCore.QDateTime] or hasattr(field_max, 'toPython'):
                      import datetime
                      def _to_timestamp(val):
                          if hasattr(val, 'toMSecsSinceEpoch'):
                              return val.toMSecsSinceEpoch() / 1000.0
                          elif type(val) is QtCore.QDate:
                              return QtCore.QDateTime(val).toMSecsSinceEpoch() / 1000.0
                          elif hasattr(val, 'toPython'):
                              return val.toPython().timestamp()
                          elif type(val) is datetime.date:
                              return datetime.datetime(val.year, val.month, val.day).timestamp()
                          elif type(val) is datetime.datetime:
                              return val.timestamp()
                          return val
                      field_max = _to_timestamp(field_max)
                      field_min = _to_timestamp(field_min)

              try:
                # Add spacing option to RangeSlider if needed? Will do in next step.
                slider = RangeSlider(self, field_name, field_min, field_max, is_date_or_time, field.isNumeric(), is_spacious=is_spacious)
                self.layout.addWidget(slider)
                slider.show()
                self.sliders.append(slider)
              except ValueError as v:
                QgsMessageLog.logMessage("Error for fieldname %s: %s" % (field_name, str(v)), 'Range Filter Plugin', level=Qgis.Warning)

    def on_slider_changed(self, the_slider):
        text = " AND ".join([w.getRangeFilter() for w in self.sliders if w.getRangeFilter() != ""])
        db = self.layer.dataProvider()
        db.setSubsetString(text)

    def on_coerce_slider(self, slider):
        val = "DATE" if slider.is_date_or_time else "NUMBER"
        self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + slider.field_name), val)

    def on_coerce_slider_hide(self, slider):
        self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + slider.field_name), "HIDDEN")
        self.on_options_closed()

    def on_coerce_slider_number(self, slider):
        self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + slider.field_name), "NUMBER")
        self.on_options_closed()

    def on_coerce_slider_date(self, slider):
        self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + slider.field_name), "DATE")
        self.on_options_closed()

    def on_coerce_slider_category(self, slider):
        self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % ("COERCE_" + slider.field_name), "CATEGORY")
        self.on_options_closed()

    def on_remove_slider(self, slider):
        self.sliders.remove(slider)
        self.layout.removeWidget(slider)
        self._save_sliders()
        slider.deleteLater()
        self.on_slider_changed(None)

        current_width = self.width()
        self.adjustSize()
        self.resize(current_width, self.height())
        self.updateGeometry()


class RangeFilterWidgetProvider(QgsLayerTreeEmbeddedWidgetProvider):

    def __init__(self):
        QgsLayerTreeEmbeddedWidgetProvider.__init__(self)

    def id(self):
        return "data_range_filter"

    def name(self):
        return "Data Range Filter"

    def createWidget(self, layer, widgetIndex):
        return DataLayerRangeFilterWidget(layer)

    def supportsLayer(self, layer):
        # TODO: this is necc. but is it sufficient?
        return hasattr(layer.dataProvider(), "fields")
