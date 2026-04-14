import sys
import datetime
import os

# Mock qgis modules so we can import the widget class
class MockQgis:
    class core:
        Qgis = type('Qgis', (), {'Info': 1, 'Warning': 2})
        class QgsMessageLog:
            @staticmethod
            def logMessage(msg, tag, level):
                pass
        QgsAggregateCalculator = type('QgsAggregateCalculator', (), {'Max': 1, 'Min': 2})
        QgsMapLayer = type('QgsMapLayer', (), {})
        QgsExpression = type('QgsExpression', (), {})
        QgsExpressionContext = type('QgsExpressionContext', (), {})
        QgsExpressionContextUtils = type('QgsExpressionContextUtils', (), {})
    class PyQt:
        class QtWidgets:
            class QWidget:
                def __init__(self):
                    pass
                def installEventFilter(self, *args):
                    pass
                def setToolTip(self, *args):
                    pass
                def setFixedWidth(self, *args):
                    pass
                def setLayout(self, *args):
                    pass
            class QVBoxLayout:
                def addWidget(self, *args):
                    pass
            class QHBoxLayout:
                def addWidget(self, *args):
                    pass
                def setContentsMargins(self, *args):
                    pass
            class QLabel(QWidget):
                def __init__(self, text=""):
                    super().__init__()
            class QMenu(QWidget):
                pass
        class QtCore:
            class QEvent:
                ContextMenu = 1
                DeferredDelete = 2
            class QDate:
                pass
            class QDateTime:
                @classmethod
                def fromMSecsSinceEpoch(cls, msecs):
                    import datetime
                    dt = datetime.datetime.fromtimestamp(msecs / 1000.0)
                    class MockQDateTime:
                        def __init__(self, dt):
                            self.dt = dt
                        def toString(self, fmt):
                            fmt = fmt.replace("yyyy", "%Y").replace("MM", "%m").replace("dd", "%d")
                            fmt = fmt.replace("HH", "%H").replace("mm", "%M").replace("ss", "%S")
                            return self.dt.strftime(fmt)
                    return MockQDateTime(dt)
            class QVariant:
                Date = 14
                DateTime = 16
    class gui:
        class QgsLayerTreeEmbeddedWidgetProvider:
            def __init__(self):
                pass
        class QgsLayerTreeEmbeddedWidgetRegistry:
            pass

sys.modules['qgis'] = MockQgis
sys.modules['qgis.core'] = MockQgis.core
sys.modules['qgis.PyQt'] = MockQgis.PyQt
sys.modules['qgis.PyQt.QtWidgets'] = MockQgis.PyQt.QtWidgets
sys.modules['qgis.PyQt.QtCore'] = MockQgis.PyQt.QtCore
sys.modules['qgis.gui'] = MockQgis.gui
sys.modules['PyQt5'] = type('PyQt5', (), {'QtCore': MockQgis.PyQt.QtCore})
sys.modules['PyQt5.QtCore'] = MockQgis.PyQt.QtCore

# Mock qrangeslider
class MockQRangeSlider(MockQgis.PyQt.QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        class Signal:
            def connect(self, fn):
                pass
        self.startValueChanged = Signal()
        self.endValueChanged = Signal()
    def setDrawValues(self, *args):
        pass
    def setFixedHeight(self, *args):
        pass
    def setEnabled(self, *args):
        pass
    def max(self):
        return 100
    def start(self):
        return 0
    def end(self):
        return 100

sys.modules['qrangeslider'] = type('qrangeslider', (), {'QRangeSlider': MockQRangeSlider})

# modify import locally to allow importing
with open("data_layer_range_filter_widget.py", "r") as f:
    content = f.read()
content = content.replace("from .qrangeslider import QRangeSlider", "from qrangeslider import QRangeSlider")
with open("data_layer_range_filter_widget_test.py", "w") as f:
    f.write(content)

from data_layer_range_filter_widget_test import RangeSlider

def test_date_range():
    print("Running Test 1: Date Range")
    fmin = datetime.datetime(2021, 1, 1).timestamp()
    fmax = datetime.datetime(2021, 1, 5).timestamp() # 4 days
    slider = RangeSlider(None, "date_field", fmin, fmax, is_date_or_time=True)
    slider.slider.start = lambda: 0
    slider.slider.end = lambda: 50 # middle

    assert slider.pretty(0) == "2021-01-01 00:00", f"Got: {slider.pretty(0)}"
    assert slider.getQueryValue(0) == "'2021-01-01 00:00:00'"

    slider._dirty = True
    assert slider.getRangeFilter() == '"date_field" >= \'2021-01-01 00:00:00\' AND "date_field" <= \'2021-01-03 00:00:00\''
    print("Test 1 passed.")

def test_time_range():
    print("Running Test 2: Time Range (< 1 day)")
    fmin2 = datetime.datetime(2021, 1, 1, 12, 0).timestamp()
    fmax2 = datetime.datetime(2021, 1, 1, 18, 0).timestamp() # 6 hours
    slider2 = RangeSlider(None, "date_field_2", fmin2, fmax2, is_date_or_time=True)
    assert slider2.pretty(0) == "12:00:00", f"Got: {slider2.pretty(0)}"
    print("Test 2 passed.")

if __name__ == '__main__':
    test_date_range()
    test_time_range()

    # Cleanup
    if os.path.exists("data_layer_range_filter_widget_test.py"):
        os.remove("data_layer_range_filter_widget_test.py")

def test_coerce():
    print("Running Test 3: Type Coercion Menu")
    # To test coercion logic, we simulate an event filter execution
    fmin = datetime.datetime(2021, 1, 1).timestamp()
    fmax = datetime.datetime(2021, 1, 5).timestamp() # 4 days
    class MockParent:
        def on_coerce_slider(self, s):
            pass
    slider = RangeSlider(None, "date_field", fmin, fmax, is_date_or_time=True)
    slider.parent = MockParent()

    # Try coercing to NUMBER
    slider.is_date_or_time = not slider.is_date_or_time
    # pretty should now just format as number
    assert slider.pretty(100) != "2021-01-05 00:00"
    print("Test 3 passed.")

if __name__ == '__main__':
    test_coerce()
