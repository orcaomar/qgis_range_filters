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
from qgis.PyQt import QtCore
from qgis.core import QgsMessageLog, QgsAggregateCalculator, Qgis
from qgis.core import QgsMapLayer, QgsExpression, QgsExpressionContext, QgsExpressionContextUtils
from qgis.gui import QgsLayerTreeEmbeddedWidgetProvider, QgsLayerTreeEmbeddedWidgetRegistry
from .qrangeslider import QRangeSlider

import numbers
import math

class RangeSlider(QWidget):
    def __init__(self, parent, field_name, fmin, fmax):
        if not isinstance(fmin, numbers.Number) or not isinstance(fmax, numbers.Number):
          raise ValueError("Min or Max is not a number") 
        QWidget.__init__(self)
        self.parent = parent
        self.field_name = field_name
        self.fmin = fmin
        self.fmax = fmax
        self._dirty = False
        self.slider = QRangeSlider()
        self.slider.setDrawValues(True, self)
        self.slider.setFixedHeight(16)
        self.slider.startValueChanged.connect(self.on_value_changed)
        self.slider.endValueChanged.connect(self.on_value_changed)
        
        QgsMessageLog.logMessage("Creating Range Slider for field %s" % self.field_name, 'Range Filter Plugin', level=Qgis.Info)        
        
        
        #self.on_value_changed()
        
        layout = QHBoxLayout()
        label = QLabel(field_name)
        label.setToolTip(field_name)
        label.setFixedWidth(60)
        layout.addWidget(label)
        layout.addWidget(self.slider)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        
        self.installEventFilter(self)
    
    def pretty(self, slider_num):
        num = (float(slider_num)/self.slider.max()) * (self.fmax - self.fmin) + self.fmin
        # handle edge case where the max and the min are the same
        if self.fmax == self.fmin:
          # disable slider movement if there's no range
          self.slider.setEnabled(False)
          if self.fmax > 10:
            return str(int(self.fmax))
          else:
            return '{0:.2f}'.format(self.fmax)
        
        pretty_out = ""
        
        # handle corner case where we're looking at the maximum number, and need to make sure the filter value is above that
        if num == self.fmax:
          if self.fmax - self.fmin > 10:
            pretty_out = str(math.ceil(num))
          else:
            num += 0.01
            pretty_out = '{0:.2f}'.format(num)          
        elif self.fmax - self.fmin > 10:
            pretty_out = str(int(num))
        else:
            pretty_out = '{0:.2f}'.format(num)
        
        #QgsMessageLog.logMessage("Slider Value: %f, Converted num: %s" % (slider_num, pretty_out), 'Range Filter Plugin', level=Qgis.Info)        
        
        return pretty_out
        
    
    def eventFilter(self, source, event):
        # handle right click removal of features to filter
        if (event.type() == QtCore.QEvent.ContextMenu and
            source is self):
            menu = QMenu()
            menu.addAction('Remove %s' % self.field_name)
            if menu.exec_(event.globalPos()):
                item = source.parent.on_remove_slider(self)
            return True
        return False #super(DataRangeSliders, self).eventFilter(source, event)

    def _getStartEndValuesStr(self):
        return (self.pretty(self.slider.start()), self.pretty(self.slider.end()))
        
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
        if slider_names is not None:
            slider_names = slider_names.split("###")
            for name in slider_names:
                self._add_slider(name)
        else:
            for field in db.fields():
                QgsMessageLog.logMessage("Adding slider for field %s" % field.name(), 'Range Filter Plugin', level=Qgis.Warning)        
                self._add_slider(field.name())
        QgsMessageLog.logMessage("DONE adding sliders", 'Range Filter Plugin', level=Qgis.Warning)        
        self._save_sliders()
        
        # cleanup handling
        self.layer.willBeDeleted.connect(self.onLayerRemoved)
        self.installEventFilter(self)
    
    def onLayerRemoved(self):
      self.layer = None
    
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
    
    def _add_slider(self, field_name):
        db = self.layer.dataProvider()
        i = db.fieldNameIndex(field_name)
        if i != -1:
          field = db.fields()[i]
          if field.isNumeric():
              field_max = self.layer.aggregate(QgsAggregateCalculator.Max, field.name())[0]
              field_min = self.layer.aggregate(QgsAggregateCalculator.Min, field.name())[0]
                
              try:
                slider = RangeSlider(self, field_name, field_min, field_max)
                self.layout.addWidget(slider)
                self.sliders.append(slider)        
              except ValueError as v:
                QgsMessageLog.logMessage("Error for fieldname %s: %s" % (field_name, str(v)), 'Range Filter Plugin', level=Qgis.Warning)        
                
              #self.layer.setCustomProperty(WIDGET_SETTING_PREFIX % field_name, "1")
        
    def on_slider_changed(self, the_slider):
        text = " AND ".join([x for x in map(RangeSlider.getRangeFilter,  self.sliders) if x != ""])
        db = self.layer.dataProvider()
        db.setSubsetString(text)
    
    def on_remove_slider(self, slider):
        self.sliders.remove(slider)
        self.layout.removeWidget(slider)
        self._save_sliders()
        slider.setParent(None)
        # TODO: this doesn't cause the container for the widget to resize, which is what I was hoping for
        #self.parent().resize(self.parent().width(), self.parent().height() - 50)
        self.on_slider_changed(None)
        

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
        

#provider = RangeFilterWidgetProvider()
#QgsGui.layerTreeEmbeddedWidgetRegistry().addProvider(provider)