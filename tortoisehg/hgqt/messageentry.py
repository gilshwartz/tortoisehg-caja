# messageentry.py - TortoiseHg's commit message editng widget
#
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.Qsci import QsciScintilla, QsciLexerMakefile

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, qscilib

class MessageEntry(qscilib.Scintilla):

    def __init__(self, parent, getCheckedFunc=None):
        super(MessageEntry, self).__init__(parent)
        self.setEdgeColor(QColor('LightSalmon'))
        self.setEdgeMode(QsciScintilla.EdgeLine)
        self.setReadOnly(False)
        self.setMarginWidth(1, 0)
        self.setFont(qtlib.getfont('fontcomment').font())
        self.setCaretWidth(10)
        self.setCaretLineBackgroundColor(QColor("#e6fff0"))
        self.setCaretLineVisible(True)
        self.setAutoIndent(True)
        self.setAutoCompletionThreshold(2)
        self.setAutoCompletionSource(QsciScintilla.AcsAPIs)
        self.setAutoCompletionFillupsEnabled(True)
        self.setLexer(QsciLexerMakefile(self))
        font = qtlib.getfont('fontcomment').font()
        self.fontHeight = QFontMetrics(font).height()
        self.lexer().setFont(font)
        self.lexer().setColor(QColor(Qt.red), QsciLexerMakefile.Error)
        self.setMatchedBraceBackgroundColor(Qt.yellow)
        self.setIndentationsUseTabs(False)
        self.setBraceMatching(QsciScintilla.SloppyBraceMatch)
        #self.setIndentationGuidesBackgroundColor(QColor("#e6e6de"))
        #self.setFolding(QsciScintilla.BoxedFoldStyle)
        # http://www.riverbankcomputing.com/pipermail/qscintilla/2009-February/000461.html
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # default message entry widgets to word wrap, user may override
        self.setWrapMode(QsciScintilla.WrapWord)

        self.getChecked = getCheckedFunc
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.menuRequested)


    def menuRequested(self, point):
        line = self.lineAt(point)
        point = self.viewport().mapToGlobal(point)

        def apply():
            line = 0
            while True:
                line = self.reflowBlock(line)
                if line is None:
                    break;
        def paste():
            files = self.getChecked()
            self.insert(', '.join(files))
        def settings():
            from tortoisehg.hgqt.settings import SettingsDialog
            dlg = SettingsDialog(True, focus='tortoisehg.summarylen')
            dlg.exec_()

        menu = self.createStandardContextMenu()
        menu.addSeparator()
        if self.getChecked:
            action = menu.addAction(_('Paste &Filenames'))
            action.triggered.connect(paste)
        for name, func in [(_('App&ly Format'), apply),
                           (_('C&onfigure Format'), settings)]:
            def add(name, func):
                action = menu.addAction(name)
                action.triggered.connect(func)
            add(name, func)
        return menu.exec_(point)

    def refresh(self, repo):
        self.setEdgeColumn(repo.summarylen)
        self.setIndentationWidth(repo.tabwidth)
        self.setTabWidth(repo.tabwidth)
        self.summarylen = repo.summarylen

    def reflowBlock(self, line):
        lines = self.text().split('\n', QString.KeepEmptyParts)
        if line >= len(lines):
            return None
        if not len(lines[line]) > 1:
            return line+1

        # find boundaries (empty lines or bounds)
        b = line
        while b and len(lines[b-1]) > 1:
            b = b - 1
        e = line
        while e+1 < len(lines) and len(lines[e+1]) > 1:
            e = e + 1
        group = QStringList([lines[l].simplified() for l in xrange(b, e+1)])
        sentence = group.join(' ')
        parts = sentence.split(' ', QString.SkipEmptyParts)

        outlines = QStringList()
        line = QStringList()
        partslen = 0
        for part in parts:
            if partslen + len(line) + len(part) + 1 > self.summarylen:
                if line:
                    outlines.append(line.join(' '))
                line, partslen = QStringList(), 0
            line.append(part)
            partslen += len(part)
        if line:
            outlines.append(line.join(' '))

        self.beginUndoAction()
        self.setSelection(b, 0, e+1, 0)
        self.removeSelectedText()
        self.insertAt(outlines.join('\n')+'\n', b, 0)
        self.endUndoAction()
        self.setCursorPosition(b, 0)
        return b + len(outlines) + 1

    def moveCursorToEnd(self):
        lines = self.lines()
        if lines:
            lines -= 1
            pos = self.lineLength(lines)
            self.setCursorPosition(lines, pos)
            self.ensureLineVisible(lines)
            self.horizontalScrollBar().setSliderPosition(0)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_E:
            line, col = self.getCursorPosition()
            self.reflowBlock(line)
        elif event.key() == Qt.Key_Backtab:
            event.accept()
            newev = QKeyEvent(event.type(), Qt.Key_Tab, Qt.ShiftModifier)
            super(MessageEntry, self).keyPressEvent(newev)
        else:
            super(MessageEntry, self).keyPressEvent(event)

    def resizeEvent(self, event):
        super(MessageEntry, self).resizeEvent(event)
        self.showHScrollBar(self.frameGeometry().height() > self.fontHeight * 3)

    def minimumSizeHint(self):
        size = super(MessageEntry, self).minimumSizeHint()
        size.setHeight(self.fontHeight * 3 / 2)
        return size
