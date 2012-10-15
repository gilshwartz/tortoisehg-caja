# rejects.py - TortoiseHg patch reject editor
#
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.

import cStringIO
import os

from mercurial import hg, util, patch, commands
from hgext import record

from tortoisehg.util import hglib
from tortoisehg.util.patchctx import patchctx
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, qscilib, lexers

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4 import Qsci

qsci = Qsci.QsciScintilla

class RejectsDialog(QDialog):
    def __init__(self, path, parent):
        super(RejectsDialog, self).__init__(parent)
        self.setWindowTitle(_('Merge rejected patch chunks into %s') %
                            hglib.tounicode(path))
        self.setWindowFlags(Qt.Window)
        self.path = path

        self.setLayout(QVBoxLayout())
        editor = qscilib.Scintilla()
        editor.setBraceMatching(qsci.SloppyBraceMatch)
        editor.setFolding(qsci.BoxedTreeFoldStyle)
        editor.installEventFilter(qscilib.KeyPressInterceptor(self))
        editor.setContextMenuPolicy(Qt.CustomContextMenu)
        editor.customContextMenuRequested.connect(self.menuRequested)
        self.baseLineColor = editor.markerDefine(qsci.Background, -1)
        editor.setMarkerBackgroundColor(QColor('lightblue'), self.baseLineColor)
        self.layout().addWidget(editor, 3)

        searchbar = qscilib.SearchToolBar(self, hidable=True)
        searchbar.searchRequested.connect(editor.find)
        searchbar.conditionChanged.connect(editor.highlightText)
        searchbar.hide()
        def showsearchbar():
            searchbar.show()
            searchbar.setFocus(Qt.OtherFocusReason)
        qtlib.newshortcutsforstdkey(QKeySequence.Find, self, showsearchbar)
        self.layout().addWidget(searchbar)

        hbox = QHBoxLayout()
        hbox.setContentsMargins(2, 2, 2, 2)
        self.layout().addLayout(hbox, 1)
        self.chunklist = QListWidget(self)
        self.updating = True
        self.chunklist.currentRowChanged.connect(self.showChunk)
        hbox.addWidget(self.chunklist, 1)

        bvbox = QVBoxLayout()
        bvbox.setContentsMargins(2, 2, 2, 2)
        self.resolved = tb = QToolButton()
        tb.setIcon(qtlib.geticon('thg-success'))
        tb.setToolTip(_('Mark this chunk as resolved, goto next unresolved'))
        tb.pressed.connect(self.resolveCurrentChunk)
        self.unresolved = tb = QToolButton()
        tb.setIcon(qtlib.geticon('thg-warning'))
        tb.setToolTip(_('Mark this chunk as unresolved'))
        tb.pressed.connect(self.unresolveCurrentChunk)
        bvbox.addStretch(1)
        bvbox.addWidget(self.resolved, 0)
        bvbox.addWidget(self.unresolved, 0)
        bvbox.addStretch(1)
        hbox.addLayout(bvbox, 0)

        self.editor = editor
        self.rejectbrowser = RejectBrowser(self)
        hbox.addWidget(self.rejectbrowser, 5)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Save|BB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.layout().addWidget(bb)
        self.saveButton = bb.button(BB.Save)

        s = QSettings()
        self.restoreGeometry(s.value('rejects/geometry').toByteArray())
        self.editor.loadSettings(s, 'rejects/editor')
        self.rejectbrowser.loadSettings(s, 'rejects/rejbrowse')

        f = QFile(path)
        if not f.open(QIODevice.ReadOnly):
            qtlib.ErrorMsgBox(_('Unable to merge rejects'),
                              _("Can't read this file (maybe deleted)"))
            self.hide()
            QTimer.singleShot(0, self.reject)
            return
        earlybytes = f.readData(4096)
        if '\0' in earlybytes:
            qtlib.ErrorMsgBox(_('Unable to merge rejects'),
                              _('This appears to be a binary file'))
            self.hide()
            QTimer.singleShot(0, self.reject)
            return

        f.seek(0)
        editor.read(f)
        editor.setModified(False)
        lexer = lexers.get_lexer(path, earlybytes, self)
        editor.setLexer(lexer)
        editor.setMarginLineNumbers(1, True)
        editor.setMarginWidth(1, str(editor.lines())+'X')

        buf = cStringIO.StringIO()
        try:
            buf.write('diff -r aaaaaaaaaaaa -r bbbbbbbbbbb %s\n' % path)
            buf.write(open(path + '.rej', 'rb').read())
            buf.seek(0)
        except IOError, e:
            pass
        try:
            header = record.parsepatch(buf)[0]
            self.chunks = header.hunks
        except (patch.PatchError, IndexError), e:
            self.chunks = []

        for chunk in self.chunks:
            chunk.resolved = False
        self.updateChunkList()
        self.saveButton.setDisabled(len(self.chunks))
        self.resolved.setDisabled(True)
        self.unresolved.setDisabled(True)
        QTimer.singleShot(0, lambda: self.chunklist.setCurrentRow(0))

    def menuRequested(self, point):
        point = self.editor.viewport().mapToGlobal(point)
        return self.editor.createStandardContextMenu().exec_(point)

    def updateChunkList(self):
        self.updating = True
        self.chunklist.clear()
        for chunk in self.chunks:
            self.chunklist.addItem('@@ %d %s' % (chunk.fromline,
                            chunk.resolved and '(resolved)' or '(unresolved)'))
        self.updating = False

    @pyqtSlot()
    def resolveCurrentChunk(self):
        row = self.chunklist.currentRow()
        chunk = self.chunks[row]
        chunk.resolved = True
        self.updateChunkList()
        for i, chunk in enumerate(self.chunks):
            if not chunk.resolved:
                self.chunklist.setCurrentRow(i)
                return
        else:
            self.chunklist.setCurrentRow(row)
            self.saveButton.setEnabled(True)

    @pyqtSlot()
    def unresolveCurrentChunk(self):
        row = self.chunklist.currentRow()
        chunk = self.chunks[row]
        chunk.resolved = False
        self.updateChunkList()
        self.chunklist.setCurrentRow(row)
        self.saveButton.setEnabled(False)

    @pyqtSlot(int)
    def showChunk(self, row):
        if row == -1 or self.updating:
            return
        buf = cStringIO.StringIO()
        chunk = self.chunks[row]
        chunk.write(buf)
        startline = max(chunk.fromline-1, 0)
        self.rejectbrowser.showChunk(buf.getvalue().splitlines(True)[1:])
        self.editor.setCursorPosition(startline, 0)
        self.editor.ensureLineVisible(startline)
        self.editor.markerDeleteAll(-1)
        self.editor.markerAdd(startline, self.baseLineColor)
        self.resolved.setEnabled(not chunk.resolved)
        self.unresolved.setEnabled(chunk.resolved)

    def saveSettings(self):
        s = QSettings()
        s.setValue('rejects/geometry', self.saveGeometry())
        self.editor.saveSettings(s, 'rejects/editor')
        self.rejectbrowser.saveSettings(s, 'rejects/rejbrowse')

    def accept(self):
        # If the editor has been modified, we implicitly accept the changes
        acceptresolution = self.editor.isModified()
        if not acceptresolution:
            action = QMessageBox.warning(self,
                _("Warning"),
                _("You have marked all rejected patch chunks as resolved yet you " \
                "have not modified the file on the edit panel.\n\n" \
                "This probably means that no code from any of the rejected patch " \
                "chunks made it into the file.\n\n"\
                "Are you sure that you want to leave the file as is and " \
                "consider all the rejected patch chunks as resolved?\n\n" \
                "Doing so may delete them from a shelve, for example, which " \
                "would mean that you would lose them forever!\n\n"
                "Click Yes to accept the file as is or No to continue resolving " \
                "the rejected patch chunks."),
                QMessageBox.Yes, QMessageBox.No)
            if action == QMessageBox.Yes:
                acceptresolution = True

        if acceptresolution:
            f = QFile(self.path)
            f.open(QIODevice.WriteOnly)
            self.editor.write(f)
            self.saveSettings()
            super(RejectsDialog, self).accept()

    def reject(self):
        self.saveSettings()
        super(RejectsDialog, self).reject()

class RejectBrowser(qscilib.Scintilla):
    'Display a rejected diff hunk in an easily copy/pasted format'
    def __init__(self, parent):
        super(RejectBrowser, self).__init__(parent)

        self.setFrameStyle(0)
        self.setReadOnly(True)
        self.setUtf8(True)

        self.installEventFilter(qscilib.KeyPressInterceptor(self))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.menuRequested)
        self.setCaretLineVisible(False)

        self.setMarginType(1, qsci.SymbolMargin)
        self.setMarginLineNumbers(1, False)
        self.setMarginWidth(1, QFontMetrics(self.font()).width('XX'))
        self.setMarginSensitivity(1, True)
        self.addedMark = self.markerDefine(qsci.Plus, -1)
        self.removedMark = self.markerDefine(qsci.Minus, -1)
        self.addedColor = self.markerDefine(qsci.Background, -1)
        self.removedColor = self.markerDefine(qsci.Background, -1)
        self.setMarkerBackgroundColor(QColor('lightgreen'), self.addedColor)
        self.setMarkerBackgroundColor(QColor('cyan'), self.removedColor)
        mask = (1 << self.addedMark) | (1 << self.removedMark) | \
               (1 << self.addedColor) | (1 << self.removedColor)
        self.setMarginMarkerMask(1, mask)
        lexer = lexers.get_diff_lexer(self)
        self.setLexer(lexer)

    def menuRequested(self, point):
        point = self.viewport().mapToGlobal(point)
        return self.createStandardContextMenu().exec_(point)

    def showChunk(self, lines):
        utext = []
        added = []
        removed = []
        for i, line in enumerate(lines):
            utext.append(hglib.tounicode(line[1:]))
            if line[0] == '+':
                added.append(i)
            elif line[0] == '-':
                removed.append(i)
        self.markerDeleteAll(-1)
        self.setText(u''.join(utext))
        for i in added:
            self.markerAdd(i, self.addedMark)
            self.markerAdd(i, self.addedColor)
        for i in removed:
            self.markerAdd(i, self.removedMark)
            self.markerAdd(i, self.removedColor)

def run(ui, *pats, **opts):
    if len(pats) != 1:
        qtlib.ErrorMsgBox(_('Filename required'),
                          _('You must provide the path to a file'))
        import sys; sys.exit()
    path = pats[0]
    if path.endswith('.rej'):
        path = path[:-4]
    dlg = RejectsDialog(path, None)
    return dlg
