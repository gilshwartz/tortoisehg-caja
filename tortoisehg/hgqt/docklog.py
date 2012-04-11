# docklog.py - Log dock widget for the TortoiseHg Workbench
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import cmdui

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class LogDockWidget(QDockWidget):
    visibilityChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super(LogDockWidget, self).__init__(parent)

        self.setFeatures(QDockWidget.DockWidgetClosable |
                         QDockWidget.DockWidgetMovable  |
                         QDockWidget.DockWidgetFloatable)
        self.setWindowTitle(_('Output Log'))
        # Not enabled until we have a way to make it configurable
        #self.setWindowFlags(Qt.Drawer)

        self.logte = cmdui.ConsoleWidget()
        self.logte.closeRequested.connect(self.close)
        self.setWidget(self.logte)
        for name in ('setRepository', 'progressReceived'):
            setattr(self, name, getattr(self.logte, name))

        self.visibilityChanged.connect(
            lambda visible: visible and self.logte.setFocus())

    @pyqtSlot()
    def clear(self):
        self.logte.clear()

    @pyqtSlot(QString, QString)
    def output(self, msg, label):
        self.logte.appendLog(msg, label)

    @pyqtSlot()
    def beginSuppressPrompt(self):
        self.logte.suppressPrompt = True

    @pyqtSlot()
    def endSuppressPrompt(self):
        self.logte.suppressPrompt = False
        self.logte.openPrompt()

    def showEvent(self, event):
        self.visibilityChanged.emit(True)

    def hideEvent(self, event):
        self.visibilityChanged.emit(False)
