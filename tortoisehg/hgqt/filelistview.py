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

import os

from tortoisehg.util import hglib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, visdiff

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class HgFileListView(QTableView):
    """
    A QTableView for displaying a HgFileListModel
    """

    fileSelected = pyqtSignal(QString, QString)
    linkActivated = pyqtSignal(QString)
    clearDisplay = pyqtSignal()

    def __init__(self, repo, parent, multiselectable):
        QTableView.__init__(self, parent)
        self.repo = repo
        self.multiselectable = multiselectable
        self.setShowGrid(False)
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(20)
        if multiselectable:
            self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        else:
            self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setTextElideMode(Qt.ElideLeft)

    def setModel(self, model):
        QTableView.setModel(self, model)
        model.layoutChanged.connect(self.layoutChanged)
        self.selectionModel().currentRowChanged.connect(self.onRowChange)
        self.horizontalHeader().setResizeMode(1, QHeaderView.Stretch)

    def setRepo(self, repo):
        self.repo = repo

    def setContext(self, ctx):
        self.ctx = ctx
        self.model().setContext(ctx)

    def currentFile(self):
        index = self.currentIndex()
        return self.model().fileFromIndex(index)

    def getSelectedFiles(self):
        model = self.model()
        sf = [model.fileFromIndex(eachIndex)
                for eachIndex in self.selectedRows()]
        return sf

    def layoutChanged(self):
        'file model has new contents'
        index = self.currentIndex()
        count = len(self.model())
        if index.row() == -1:
            # index is changing, onRowChange() called for us
            self.selectRow(0)
        elif index.row() >= count:
            if count:
                # index is changing, onRowChange() called for us
                self.selectRow(count-1)
            else:
                self.clearDisplay.emit()
        else:
            # redisplay previous row
            self.onRowChange(index)

    def onRowChange(self, index, *args):
        if index is None:
            index = self.currentIndex()
        data = self.model().dataFromIndex(index)
        if data:
            self.fileSelected.emit(hglib.tounicode(data['path']), data['status'])
        else:
            self.clearDisplay.emit()

    def resizeEvent(self, event):
        if self.model() is not None:
            vp_width = self.viewport().width()
            col_widths = [self.columnWidth(i) \
                        for i in range(1, self.model().columnCount())]
            col_width = vp_width - sum(col_widths)
            col_width = max(col_width, 50)
            self.setColumnWidth(0, col_width)
        QTableView.resizeEvent(self, event)

    #
    ## Mouse drag
    #

    def selectedRows(self):
        return self.selectionModel().selectedRows()

    def dragObject(self):
        if type(self.ctx.rev()) == str:
            return
        paths = []
        for index in self.selectedRows():
            paths.append(self.model().fileFromIndex(index))
        if not paths:
            return
        if self.ctx.rev() is None:
            base = self.repo.root
        else:
            base, _ = visdiff.snapshot(self.repo, paths, self.ctx)
        urls = []
        for path in paths:
            urls.append(QUrl.fromLocalFile(os.path.join(base, path)))
        if urls:
            d = QDrag(self)
            m = QMimeData()
            m.setUrls(urls)
            d.setMimeData(m)
            d.start(Qt.CopyAction)

    def mousePressEvent(self, event):
        self.pressPos = event.pos()
        self.pressTime = QTime.currentTime()
        return QTableView.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        d = event.pos() - self.pressPos
        if d.manhattanLength() < QApplication.startDragDistance():
            return QTableView.mouseMoveEvent(self, event)
        elapsed = self.pressTime.msecsTo(QTime.currentTime())
        if elapsed < QApplication.startDragTime():
            return QTableView.mouseMoveEvent(self, event)
        self.dragObject()
        return QTableView.mouseMoveEvent(self, event)
