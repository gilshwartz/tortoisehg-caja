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

from mercurial import error

from tortoisehg.util import hglib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import htmldelegate
from tortoisehg.hgqt.logcolumns import ColumnSelectDialog

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class HgRepoViewHeader(QHeaderView):
    menuRequested = pyqtSignal(QPoint)
    def contextMenuEvent(self, event):
        self.menuRequested.emit(event.globalPos())

class HgRepoView(QTableView):

    revisionClicked = pyqtSignal(object)
    revisionAltClicked = pyqtSignal(object)
    revisionSelected = pyqtSignal(object)
    revisionActivated = pyqtSignal(object)
    menuRequested = pyqtSignal(QPoint, object)
    showMessage = pyqtSignal(unicode)

    def __init__(self, repo, cfgname, colselect, parent=None):
        QTableView.__init__(self, parent)
        self.repo = repo
        self.current_rev = -1
        self.resized = False
        self.cfgname = cfgname
        self.colselect = colselect
        self.setShowGrid(False)

        vh = self.verticalHeader()
        vh.hide()
        vh.setDefaultSectionSize(20)

        header = HgRepoViewHeader(Qt.Horizontal, self)
        header.setHighlightSections(False)
        header.menuRequested.connect(self.headerMenuRequest)
        self.setHorizontalHeader(header)

        self.createActions()

        self.standardDelegate = self.itemDelegate()
        self.htmlDelegate = htmldelegate.HTMLDelegate(self)

        self.setAcceptDrops(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)

        self.setStyle(HgRepoViewStyle(self.style()))

        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)

        self.doubleClicked.connect(self.revActivated)
        self.clicked.connect(self.revClicked)

    def setRepo(self, repo):
        self.repo = repo

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
        if event.button() == Qt.MidButton:
            self.gotoAncestor(index)
            return
        QTableView.mousePressEvent(self, event)

    def contextMenuEvent(self, event):
        self.menuRequested.emit(event.globalPos(), self.selectedRevisions())

    def createActions(self):
        menu = QMenu(self)
        act = QAction(_('Choose log columns...'), self)
        act.triggered.connect(self.setHistoryColumns)
        menu.addAction(act)
        self.headermenu = menu

    def headerMenuRequest(self, point):
        self.headermenu.exec_(point)

    def setHistoryColumns(self):
        dlg = ColumnSelectDialog(self.colselect[0], self.colselect[1],
                                 self.model())
        if dlg.exec_() == QDialog.Accepted:
            self.model().updateColumns()
            self.resizeColumns()

    def setModel(self, model):
        QTableView.setModel(self, model)
        #Check if the font contains the glyph needed by the model
        if not QFontMetrics(self.font()).inFont(QString(u'\u2605').at(0)):
            model.unicodestar = False
        if not QFontMetrics(self.font()).inFont(QString(u'\u2327').at(0)):
            model.unicodexinabox = False
        self.selectionModel().currentRowChanged.connect(self.onRowChange)
        self.resetDelegate()
        self._rev_history = []
        self._rev_pos = -1
        self._in_history = False
        model.layoutChanged.connect(self.resetDelegate)

    def resetBrowseHistory(self, revs, reselrev=None):
        graph = self.model().graph
        self._rev_history = [r for r in revs if r in graph.nodesdict]
        if reselrev is not None and reselrev in self._rev_history:
            self._rev_pos = self._rev_history.index(reselrev)
        else:
            self._rev_pos = -1
        self.forward()

    def resetDelegate(self):
        # Model column layout has changed so we need to move
        # our column delegate to correct location
        if not self.model():
            return
        model = self.model()

        for c in range(model.columnCount(QModelIndex())):
            if model._columns[c] in ['Description', 'Changes']:
                self.setItemDelegateForColumn(c, self.htmlDelegate)
            else:
                self.setItemDelegateForColumn(c, self.standardDelegate)

    def resizeColumns(self, *args):
        if not self.model():
            return
        hh = self.horizontalHeader()
        hh.setStretchLastSection(False)
        self._resizeColumns()
        hh.setStretchLastSection(True)
        self.resized = True

    def _resizeColumns(self):
        # _resizeColumns misbehaves if called with last section streched
        for c, w in enumerate(self._columnWidthHints()):
            self.setColumnWidth(c, w)

    def _columnWidthHints(self):
        """Return list of recommended widths of all columns"""
        model = self.model()
        fontm = QFontMetrics(self.font())
        widths = [-1 for _i in xrange(model.columnCount(QModelIndex()))]

        key = '%s/column_widths/%s' % (self.cfgname, str(self.repo[0]))
        col_widths = [int(w) for w in QSettings().value(key).toStringList()]

        if len(model._columns) <> len(col_widths):
            # If the columns and widths don't match, use the calculated
            # widths as they will probably be a better fit (likely because
            # columns were changed without updating the widths)
            col_widths = []

        for c in range(model.columnCount(QModelIndex())):
            if c < len(col_widths) and col_widths[c] > 0:
                w = col_widths[c]
            else:
                w = model.maxWidthValueForColumn(c)

            if isinstance(w, int):
                widths[c] = w
            elif w is not None:
                w = fontm.width(hglib.tounicode(str(w)) + 'w')
                widths[c] = w
            else:
                w = super(HgRepoView, self).sizeHintForColumn(c)
                widths[c] = w

        return widths

    def revFromindex(self, index):
        if not index.isValid():
            return
        model = self.model()
        if model and model.graph:
            row = index.row()
            gnode = model.graph[row]
            return gnode.rev

    def context(self, rev):
        return self.repo.changectx(rev)

    def revClicked(self, index):
        rev = self.revFromindex(index)
        if QApplication.keyboardModifiers() & Qt.AltModifier:
            self.revisionAltClicked.emit(rev)
        else:
            self.revisionClicked.emit(rev)

    def revActivated(self, index):
        rev = self.revFromindex(index)
        if rev is not None:
            self.revisionActivated.emit(rev)

    def onRowChange(self, index, index_from):
        rev = self.revFromindex(index)
        if self.current_rev != rev and not self._in_history:
            del self._rev_history[self._rev_pos+1:]
            self._rev_history.append(rev)
            self._rev_pos = len(self._rev_history)-1
        self._in_history = False
        self.current_rev = rev
        self.revisionSelected.emit(rev)

    def selectedRevisions(self):
        """Return the list of selected revisions"""
        selmodel = self.selectionModel()
        return [self.revFromindex(i) for i in selmodel.selectedRows()]

    def gotoAncestor(self, index):
        rev = self.revFromindex(index)
        if rev is None or self.current_rev is None:
            return
        ctx = self.context(self.current_rev)
        ctx2 = self.context(rev)
        if ctx.thgmqunappliedpatch() or ctx2.thgmqunappliedpatch():
            return
        ancestor = ctx.ancestor(ctx2)
        self.showMessage.emit(_("Goto ancestor of %s and %s") % (
                                ctx.rev(), ctx2.rev()))
        self.goto(ancestor.rev())

    def canGoBack(self):
        return bool(self._rev_history and self._rev_pos > 0)

    def canGoForward(self):
        return bool(self._rev_history
                    and self._rev_pos < len(self._rev_history) - 1)

    def back(self):
        if self.canGoBack():
            self._rev_pos -= 1
            idx = self.model().indexFromRev(self._rev_history[self._rev_pos])
            if idx is not None:
                self._in_history = True
                self.setCurrentIndex(idx)

    def forward(self):
        if self.canGoForward():
            self._rev_pos += 1
            idx = self.model().indexFromRev(self._rev_history[self._rev_pos])
            if idx is not None:
                self._in_history = True
                self.setCurrentIndex(idx)

    def goto(self, rev):
        """
        Select revision 'rev' (can be anything understood by repo.changectx())
        """
        if isinstance(rev, (unicode, QString)):
            rev = hglib.fromunicode(rev)
        try:
            rev = self.repo.changectx(rev).rev()
        except error.RepoError:
            self.showMessage.emit(_("Can't find revision '%s'") % rev)
        except LookupError, e:
            self.showMessage.emit(hglib.fromunicode(str(e)))
        else:
            idx = self.model().indexFromRev(rev)
            if idx is not None:
                # avoid unwanted selection change (#1019)
                if self.currentIndex().row() != idx.row():
                    self.setCurrentIndex(idx)
                self.scrollTo(idx)

    def saveSettings(self, s = None):
        if not s:
            s = QSettings()

        col_widths = []
        for c in range(self.model().columnCount(QModelIndex())):
            col_widths.append(self.columnWidth(c))

        key = '%s/column_widths/%s' % (self.cfgname, str(self.repo[0]))
        s.setValue(key, col_widths)

    def resizeEvent(self, e):
        # re-size columns the smart way: the column holding Description
        # is re-sized according to the total widget size.
        if self.resized and e.oldSize().width() != e.size().width():
            model = self.model()
            total_width = stretch_col = 0

            for c in range(model.columnCount(QModelIndex())):
                if model._columns[c] in model._stretchs:
                    #save the description column
                    stretch_col = c
                else:
                    #total the other widths
                    total_width += self.columnWidth(c)

            width = max(self.viewport().width() - total_width, 100)
            self.setColumnWidth(stretch_col, width)

        super(HgRepoView, self).resizeEvent(e)

class HgRepoViewStyle(QStyle):
    "Override a style's drawPrimitive method to customize the drop indicator"
    def __init__(self, style):
        style.__class__.__init__(self)
        self._style = style
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_IndicatorItemViewItemDrop:
            # Drop indicators should be painted using the full viewport width
            vp = widget.viewport().rect()
            painter.drawRect(vp.x(), option.rect.y(),
                             vp.width() - 1, option.rect.height())
        else:
            self._style.drawPrimitive(element, option, painter, widget)
    # Delegate all other methods overridden by QProxyStyle to the base class
    def drawComplexControl(self, *args):
        return self._style.drawComplexControl(*args)
    def drawControl(self, *args):
        return self._style.drawControl(*args)
    def drawItemPixmap(self, *args):
        return self._style.drawItemPixmap(*args)
    def drawItemText(self, *args):
        return self._style.drawItemText(*args)
    def generatedIconPixmap(self, *args):
        return self._style.generatedIconPixmap(*args)
    def hitTestComplexControl(self, *args):
        return self._style.hitTestComplexControl(*args)
    def itemPixmapRect(self, *args):
        return self._style.itemPixmapRect(*args)
    def itemTextRect(self, *args):
        return self._style.itemTextRect(*args)
    def pixelMetric(self, *args):
        return self._style.pixelMetric(*args)
    def polish(self, *args):
        return self._style.polish(*args)
    def sizeFromContents(self, *args):
        return self._style.sizeFromContents(*args)
    def standardPalette(self):
        return self._style.standardPalette()
    def standardPixmap(self, *args):
        return self._style.standardPixmap(*args)
    def styleHint(self, *args):
        return self._style.styleHint(*args)
    def subControlRect(self, *args):
        return self._style.subControlRect(*args)
    def subElementRect(self, *args):
        return self._style.subElementRect(*args)
    def unpolish(self, *args):
        return self._style.unpolish(*args)
    def event(self, *args):
        return self._style.event(*args)
    def layoutSpacingImplementation(self, *args):
        return self._style.layoutSpacingImplementation(*args)
    def standardIconImplementation(self, *args):
        return self._style.standardIconImplementation(*args)

