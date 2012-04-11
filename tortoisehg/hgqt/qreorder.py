# qreorder.py - reorder unapplied MQ patches
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from hgext import mq

from tortoisehg.hgqt import qtlib, thgrepo, qrename
from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _

from PyQt4.QtCore import *
from PyQt4.QtGui import *

# TODO:
#  This approach will nuke any user configured guards
#  Explicit refresh

class QReorderDialog(QDialog):
    def __init__(self, repo, parent=None):
        QDialog.__init__(self, parent)

        self.setWindowTitle(_('Reorder Unapplied Patches'))
        self.setWindowFlags(Qt.Window)
        self.setWindowIcon(qtlib.geticon('hg-qreorder'))

        self.repo = repo
        self.cached = None
        repo.repositoryChanged.connect(self.refresh)

        layout = QVBoxLayout()
        layout.setMargin(4)
        self.setLayout(layout)

        hb = QHBoxLayout()
        hb.setMargin(2)
        lbl = QLabel(_('Repository:'))
        hb.addWidget(lbl)
        le = QLineEdit()
        hb.addWidget(le)
        le.setReadOnly(True)
        le.setFont(qtlib.getfont('fontlist').font())
        le.setText(repo.displayname)
        le.setFocusPolicy(Qt.NoFocus)
        layout.addLayout(hb)
        hl = qtlib.LabeledSeparator('')
        layout.addWidget(hl)

        class PatchListWidget(QListWidget):
            menuRequested = pyqtSignal(QPoint, object)
            def __init__(self, parent):
                QListWidget.__init__(self, parent)
                self.setCurrentRow(0)
            def contextMenuEvent(self, event):
                i = self.item(self.currentRow())
                if i:
                    self.menuRequested.emit(event.globalPos(), i.patchname)
            def focusInEvent(self, e):
                i = self.item(self.currentRow())
                if i:
                    self.parent().parent().showSummary(i)
                QListWidget.focusInEvent(self, e)

        ugb = QGroupBox(_('Unapplied Patches - drag to reorder'))
        ugb.setLayout(QVBoxLayout())
        ugb.layout().setContentsMargins(*(0,)*4)
        self.ulw = PatchListWidget(self)
        self.ulw.setDragDropMode(QListView.InternalMove)
        ugb.layout().addWidget(self.ulw)
        self.ulw.currentItemChanged.connect(lambda:
                self.showSummary(self.ulw.item(self.ulw.currentRow())))
        self.ulw.menuRequested.connect(self.patchlistMenuRequest)
        layout.addWidget(ugb)

        agb = QGroupBox(_('Applied Patches'))
        agb.setLayout(QVBoxLayout())
        agb.layout().setContentsMargins(*(0,)*4)
        self.alw = PatchListWidget(self)
        agb.layout().addWidget(self.alw)
        self.alw.currentItemChanged.connect(lambda:
                self.showSummary(self.alw.item(self.alw.currentRow())))
        self.alw.menuRequested.connect(self.patchlistMenuRequest)
        layout.addWidget(agb)

        slbl = QLabel(_('Summary:'))
        layout.addWidget(slbl)
        self.summ = QTextEdit()
        self.summ.setFont(qtlib.getfont('fontcomment').font())
        self.summ.setMinimumWidth(500)  # min 80 chars
        self.summ.setMaximumHeight(100)
        self.summ.setReadOnly(True)
        self.summ.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.summ)

        self._readsettings()

        self.refresh()

        # dialog buttons
        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel)
        self.apply_button = bb.button(BB.Apply)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(BB.Ok).setDefault(True)
        layout.addWidget(bb)

        self.alw.setCurrentRow(0)
        self.ulw.setCurrentRow(0)
        self.ulw.setFocus()

    def patchlistMenuRequest(self, point, selection):
        self.menuselection = selection
        menu = QMenu(self)
        act = QAction(_('Rename patch'), self)
        act.triggered.connect(self.qrenamePatch)
        menu.addAction(act)
        menu.exec_(point)

    def qrenamePatch(self):
        patchname = self.menuselection
        dlg = qrename.QRenameDialog(self.repo, patchname, self)
        dlg.finished.connect(dlg.deleteLater)
        if self.parent():
            dlg.output.connect(self.parent().output)
            dlg.makeLogVisible.connect(self.parent().makeLogVisible)
        dlg.exec_()

    def refresh(self):
        patchnames = self.repo.mq.series[:]
        applied = [p.name for p in self.repo.mq.applied]
        if (patchnames, applied) == self.cached:
            return

        alw, ulw = self.alw, self.ulw
        if self.cached:
            if applied != self.cached[1]:
                cw = alw
            else:
                cw = ulw
        else:
            cw = ulw
        ar = alw.currentRow()
        ur = ulw.currentRow()
        ulw.clear()
        alw.clear()
        for p in reversed(patchnames):
            ctx = self.repo.changectx(p)
            desc = ctx.longsummary()
            item = QListWidgetItem('[%s]\t%s' % (hglib.tounicode(p), desc))
            # Save the patchname with the item so that we can easily
            # retrieve it later
            item.patchname = p

            if p in applied:
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                item.setForeground(QColor(111,111,111)) # gray, like disabled
                alw.addItem(item)
            else:
                item.setFlags(Qt.ItemIsSelectable |
                              Qt.ItemIsEnabled |
                              Qt.ItemIsDragEnabled)
                ulw.addItem(item)
        self.cached = patchnames, applied
        if cw == ulw:
            alw.setCurrentRow(ar)
            ulw.setCurrentRow(ur)
            self.ulw.setFocus()
        else:
            ulw.setCurrentRow(ur)
            alw.setCurrentRow(ar)
            self.alw.setFocus()

    def showSummary(self, item):
        if item is None:
            self.summ.clear()
        else:
            ctx = self.repo.changectx(item.patchname)
            self.summ.setText(hglib.tounicode(ctx.description()))

    def accept(self):
        self._writesettings()
        applied = [self.alw.item(x).patchname
                   for x in xrange(self.alw.count())]
        unapplied = [self.ulw.item(x).patchname
                     for x in xrange(self.ulw.count())]
        writeSeries(self.repo, applied, unapplied)
        QDialog.accept(self)

    def reject(self):
        QDialog.reject(self)

    def closeEvent(self, event):
        self._writesettings()
        self.repo.repositoryChanged.disconnect(self.refresh)
        super(QReorderDialog, self).closeEvent(event)

    def _readsettings(self):
        s = QSettings()
        self.restoreGeometry(s.value('qreorder/geom').toByteArray())

    def _writesettings(self):
        s = QSettings()
        s.setValue('qreorder/geom', self.saveGeometry())

def writeSeries(repo, applied, unapplied):
    try:
        repo.incrementBusyCount()
        # The series file stores the oldest unapplied patch at the bottom, and
        # the first applied patch at the top
        lines = reversed(unapplied + applied)
        if lines:
            fp = repo.mq.opener('series', 'wb')
            fp.write('\n'.join(lines))
            fp.close()
    finally:
        repo.decrementBusyCount()

def run(ui, *pats, **opts):
    repo = thgrepo.repository(None, paths.find_root())
    if hasattr(repo, 'mq'):
        return QReorderDialog(repo)
    else:
        qtlib.ErrorMsgBox(_('TortoiseHg Error'),
            _('Please enable the MQ extension first.'))
