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


from qgis.PyQt.QtWidgets import *
from qgis.PyQt import QtCore
from qgis.core import QgsMessageLog, QgsAggregateCalculator
from qgis.core import QgsMapLayer, QgsExpression, QgsExpressionContext, QgsExpressionContextUtils
from qgis.gui import QgsLayerTreeEmbeddedWidgetProvider, QgsLayerTreeEmbeddedWidgetRegistry
from .qrangeslider import QRangeSlider

class RangeSlider(QWidget):
    def __init__(self, parent, field_name, fmin, fmax):
        QWidget.__init__(self)
        self.parent = parent
        self.field_name = field_name
        self.fmin = fmin
        self.fmax = fmax
        self.slider = QRangeSlider()
        self.slider.setRange(0, 100)
        self.slider.setDrawValues(True, self)
        self.slider.setFixedHeight(16)
        self.slider.startValueChanged.connect(self.on_value_changed)
        self.slider.endValueChanged.connect(self.on_value_changed)
        self.on_value_changed()
        
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
        num = (slider_num/100.0) * (self.fmax - self.fmin) + self.fmin
        if type(self.fmin) is int:
            return str(int)
        
        assert type(self.fmin) is float
        
        if self.fmax - self.fmin > 10:
            return str(int(num))
        else:
            return '{0:.2f}'.format(num)
    
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

    def _getStartEndValues(self):
        start_slider_val = self.slider.start()
        start_actual_val = (start_slider_val/100.0) * (self.fmax - self.fmin) + self.fmin
        
        end_slider_val = self.slider.end()
        end_actual_val = (end_slider_val/100.0) * (self.fmax - self.fmin) + self.fmin
        
        return (start_actual_val, end_actual_val)
    
    def getRangeFilter(self):
        (start_actual_val, end_actual_val) = self._getStartEndValues()
        
        return '"%s" > %f AND "%s" < %f' % (self.field_name, start_actual_val, self.field_name, end_actual_val)

    def on_value_changed(self):
        (start_actual_val, end_actual_val) = self._getStartEndValues()
        self.parent.on_slider_changed(self)
        

class DataLayerRangeFilterWidget(QWidget):

    def __init__(self, layer):
        QWidget.__init__(self)
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.layer = layer
        self.sliders = []
        
        db = self.layer.dataProvider()
        # TURN OFF ALL FILTERING prior to analyzing the data
        # TODO: take whatever filter already exists on the data now and make sure those are
        # honoured. 
        db.setSubsetString("")
        for field in db.fields():
            if field.isNumeric():
                field_name = field.name()
                field_max = self.layer.aggregate(QgsAggregateCalculator.Max, field.name())[0]
                field_min = self.layer.aggregate(QgsAggregateCalculator.Min, field.name())[0]
                
                slider = RangeSlider(self, field_name, field_min, field_max)
                layout.addWidget(slider)
                self.sliders.append(slider)        
        
        self.layout = layout
        
        
    def on_slider_changed(self, the_slider):
        text = " AND ".join(map(RangeSlider.getRangeFilter,  self.sliders))
        db = self.layer.dataProvider()
        db.setSubsetString(text)
    
    def on_remove_slider(self, slider):
        self.sliders.remove(slider)
        self.layout.removeWidget(slider)
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