try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
except ImportError:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

from labelimg.i18n import language_changed, tr


class ZoomWidget(QSpinBox):

    def __init__(self, value=100):
        super(ZoomWidget, self).__init__()
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setRange(1, 500)
        self.setSuffix(' %')
        self.setValue(value)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        self.setAlignment(Qt.AlignCenter)

    def retranslate_ui(self, _language=None):
        self.setToolTip(tr("zoom.level"))
        self.setStatusTip(self.toolTip())

    def minimumSizeHint(self):
        height = super(ZoomWidget, self).minimumSizeHint().height()
        fm = QFontMetrics(self.font())
        width = fm.width(str(self.maximum()))
        return QSize(width, height)
