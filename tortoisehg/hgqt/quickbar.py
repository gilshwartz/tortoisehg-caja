# Copyright (c) 2009-2010 LOGILAB S.A. (Paris, FRANCE).
# http://www.logilab.fr/ -- mailto:contact@logilab.fr
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""
Qt4 QToolBar-based class for quick bars XXX
"""

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt.qtlib import geticon

class GotoQuickBar(QToolBar):
    gotoSignal = pyqtSignal(QString)

    def __init__(self, parent):
        QToolBar.__init__(self, _('Goto'), parent)
        self.setIconSize(QSize(16,16))
        self.setFloatable(False)
        self.setMovable(False)
        self.setAllowedAreas(Qt.BottomToolBarArea)
        self.setVisible(False)
        self.goAction = QAction(geticon('go-jump'), _('Go'), self)
        self.goAction.triggered.connect(self.goto)
        self.entry = QLineEdit(self)
        self.entry.returnPressed.connect(self.goAction.trigger)
        self.addWidget(self.entry)
        self.addAction(self.goAction)

    def goto(self):
        self.gotoSignal.emit(self.entry.text())

    def setVisible(self, visible=True):
        super(GotoQuickBar, self).setVisible(visible)
        if visible:
            self.entry.setFocus()
            self.entry.selectAll()

    def setCompletionKeys(self, keys):
        self.entry.setCompleter(QCompleter(keys, self))
