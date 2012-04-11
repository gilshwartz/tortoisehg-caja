# qscilib.py - Utility codes for QsciScintilla
#
# Copyright 2010 Steve Borho <steve@borho.org>
# Copyright 2010 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import re

from mercurial import util

from tortoisehg.util import hglib
from tortoisehg.hgqt import qtlib
from tortoisehg.hgqt.i18n import _

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.Qsci import *

class _SciImSupport(object):
    """Patch for QsciScintilla to implement improved input method support

    See http://doc.trolltech.com/4.7/qinputmethodevent.html
    """

    PREEDIT_INDIC_ID = QsciScintilla.INDIC_MAX
    """indicator for highlighting preedit text"""

    def __init__(self, sci):
        self._sci = sci
        self._preeditpos = (0, 0)  # (line, index) where preedit text starts
        self._preeditlen = 0
        self._preeditcursorpos = 0  # relative pos where preedit cursor exists
        self._undoactionbegun = False
        self._setuppreeditindic()

    def removepreedit(self):
        """Remove the previous preedit text

        original pos: preedit cursor
        final pos: target cursor
        """
        l, i = self._sci.getCursorPosition()
        i -= self._preeditcursorpos
        self._preeditcursorpos = 0
        try:
            self._sci.setSelection(
                self._preeditpos[0], self._preeditpos[1],
                self._preeditpos[0], self._preeditpos[1] + self._preeditlen)
            self._sci.removeSelectedText()
        finally:
            self._sci.setCursorPosition(l, i)

    def commitstr(self, start, repllen, commitstr):
        """Remove the repl string followed by insertion of the commit string

        original pos: target cursor
        final pos: end of committed text (= start of preedit text)
        """
        l, i = self._sci.getCursorPosition()
        i += start
        self._sci.setSelection(l, i, l, i + repllen)
        self._sci.removeSelectedText()
        self._sci.insert(commitstr)
        self._sci.setCursorPosition(l, i + len(commitstr))
        if commitstr:
            self.endundo()

    def insertpreedit(self, text):
        """Insert preedit text

        original pos: start of preedit text
        final pos: start of preedit text (unchanged)
        """
        if text and not self._preeditlen:
            self.beginundo()
        l, i = self._sci.getCursorPosition()
        self._sci.insert(text)
        self._updatepreeditpos(l, i, len(text))
        if not self._preeditlen:
            self.endundo()

    def movepreeditcursor(self, pos):
        """Move the cursor to the relative pos inside preedit text"""
        self._preeditcursorpos = min(pos, self._preeditlen)
        l, i = self._preeditpos
        self._sci.setCursorPosition(l, i + self._preeditcursorpos)

    def beginundo(self):
        if self._undoactionbegun:
            return
        self._sci.beginUndoAction()
        self._undoactionbegun = True

    def endundo(self):
        if not self._undoactionbegun:
            return
        self._sci.endUndoAction()
        self._undoactionbegun = False

    def _updatepreeditpos(self, l, i, len):
        """Update the indicator and internal state for preedit text"""
        self._sci.SendScintilla(QsciScintilla.SCI_SETINDICATORCURRENT,
                                self.PREEDIT_INDIC_ID)
        self._preeditpos = (l, i)
        self._preeditlen = len
        if len <= 0:  # have problem on sci
            return
        p = self._sci.positionFromLineIndex(*self._preeditpos)
        q = self._sci.positionFromLineIndex(self._preeditpos[0],
                                            self._preeditpos[1] + len)
        self._sci.SendScintilla(QsciScintilla.SCI_INDICATORFILLRANGE,
                                p, q - p)  # q - p != len

    def _setuppreeditindic(self):
        """Configure the style of preedit text indicator"""
        self._sci.SendScintilla(QsciScintilla.SCI_INDICSETSTYLE,
                                self.PREEDIT_INDIC_ID,
                                QsciScintilla.INDIC_PLAIN)

class Scintilla(QsciScintilla):

    _stdMenu = None

    def __init__(self, parent=None):
        super(Scintilla, self).__init__(parent)
        self.setUtf8(True)
        self.textChanged.connect(self._resetfindcond)
        self._resetfindcond()

    def inputMethodQuery(self, query):
        if query == Qt.ImMicroFocus:
            return self.cursorRect()
        return super(Scintilla, self).inputMethodQuery(query)

    def inputMethodEvent(self, event):
        if self.isReadOnly():
            return

        self.removeSelectedText()
        self._imsupport.removepreedit()
        self._imsupport.commitstr(event.replacementStart(),
                                  event.replacementLength(),
                                  event.commitString())
        self._imsupport.insertpreedit(event.preeditString())
        for a in event.attributes():
            if a.type == QInputMethodEvent.Cursor:
                self._imsupport.movepreeditcursor(a.start)
            # TODO TextFormat

        event.accept()

    @util.propertycache
    def _imsupport(self):
        return _SciImSupport(self)

    def cursorRect(self):
        """Return a rectangle (in viewport coords) including the cursor"""
        l, i = self.getCursorPosition()
        p = self.positionFromLineIndex(l, i)
        x = self.SendScintilla(QsciScintilla.SCI_POINTXFROMPOSITION, 0, p)
        y = self.SendScintilla(QsciScintilla.SCI_POINTYFROMPOSITION, 0, p)
        w = self.SendScintilla(QsciScintilla.SCI_GETCARETWIDTH)
        return QRect(x, y, w, self.textHeight(l))

    def createStandardContextMenu(self):
        """Create standard context menu"""
        if not self._stdMenu:
            self._stdMenu = QMenu(self)
        else:
            self._stdMenu.clear()
        if not self.isReadOnly():
            a = self._stdMenu.addAction(_('Undo'), self.undo, QKeySequence.Undo)
            a.setEnabled(self.isUndoAvailable())
            a = self._stdMenu.addAction(_('Redo'), self.redo, QKeySequence.Redo)
            a.setEnabled(self.isRedoAvailable())
            self._stdMenu.addSeparator()
            a = self._stdMenu.addAction(_('Cut'), self.cut, QKeySequence.Cut)
            a.setEnabled(self.hasSelectedText())
        a = self._stdMenu.addAction(_('Copy'), self.copy, QKeySequence.Copy)
        a.setEnabled(self.hasSelectedText())
        if not self.isReadOnly():
            self._stdMenu.addAction(_('Paste'), self.paste, QKeySequence.Paste)
            a = self._stdMenu.addAction(_('Delete'), self.removeSelectedText,
                               QKeySequence.Delete)
            a.setEnabled(self.hasSelectedText())
        self._stdMenu.addSeparator()
        self._stdMenu.addAction(_('Select All'),
                                self.selectAll, QKeySequence.SelectAll)
        self._stdMenu.addSeparator()
        qsci = QsciScintilla
        wrapmenu = QMenu(_('Wrap'), self)
        for name, mode in ((_('None', 'wrap mode'), qsci.WrapNone),
                           (_('Word'), qsci.WrapWord),
                           (_('Character'), qsci.WrapCharacter)):
            def mkaction(n, m):
                a = wrapmenu.addAction(n)
                a.setCheckable(True)
                a.setChecked(self.wrapMode() == m)
                a.triggered.connect(lambda: self.setWrapMode(m))
            mkaction(name, mode)
        wsmenu = QMenu(_('Whitespace'), self)
        for name, mode in ((_('Visible'), qsci.WsVisible),
                           (_('Invisible'), qsci.WsInvisible),
                           (_('AfterIndent'), qsci.WsVisibleAfterIndent)):
            def mkaction(n, m):
                a = wsmenu.addAction(n)
                a.setCheckable(True)
                a.setChecked(self.whitespaceVisibility() == m)
                a.triggered.connect(lambda: self.setWhitespaceVisibility(m))
            mkaction(name, mode)
        vsmenu = QMenu(_('EolnVisibility'), self)
        for name, mode in ((_('Visible'), True),
                           (_('Invisible'), False)):
            def mkaction(n, m):
                a = vsmenu.addAction(n)
                a.setCheckable(True)
                a.setChecked(self.eolVisibility() == m)
                a.triggered.connect(lambda: self.setEolVisibility(m))
            mkaction(name, mode)
        self._stdMenu.addMenu(wrapmenu)
        self._stdMenu.addMenu(wsmenu)
        self._stdMenu.addMenu(vsmenu)
        return self._stdMenu

    def saveSettings(self, qs, prefix):
        qs.setValue(prefix+'/wrap', self.wrapMode())
        qs.setValue(prefix+'/whitespace', self.whitespaceVisibility())
        qs.setValue(prefix+'/eol', self.eolVisibility())

    def loadSettings(self, qs, prefix):
        self.setWrapMode(qs.value(prefix+'/wrap').toInt()[0])
        self.setWhitespaceVisibility(qs.value(prefix+'/whitespace').toInt()[0])
        self.setEolVisibility(qs.value(prefix+'/eol').toBool())

    @pyqtSlot(unicode, bool, bool, bool)
    def find(self, exp, icase=True, wrap=False, forward=True):
        """Find the next/prev occurence; returns True if found

        This method tries to imitate the behavior of QTextEdit.find(),
        unlike combo of QsciScintilla.findFirst() and findNext().
        """
        cond = (exp, True, not icase, False, wrap, forward)
        if cond == self.__findcond:
            return self.findNext()
        else:
            self.__findcond = cond
            return self.findFirst(*cond)

    @pyqtSlot()
    def _resetfindcond(self):
        self.__findcond = ()

    @pyqtSlot(unicode, bool)
    def highlightText(self, match, icase=False):
        """Highlight text matching to the given regexp pattern [unicode]

        The previous highlight is cleared automatically.
        """
        try:
            flags = 0
            if icase:
                flags |= re.IGNORECASE
            pat = re.compile(unicode(match).encode('utf-8'), flags)
        except re.error:
            return  # it could be partial pattern while user typing

        self.clearHighlightText()
        self.SendScintilla(self.SCI_SETINDICATORCURRENT,
                           self._highlightIndicator)

        if len(match) == 0:
            return

        # NOTE: pat and target text are *not* unicode because scintilla
        # requires positions in byte. For accuracy, it should do pattern
        # match in unicode, then calculating byte length of substring::
        #
        #     text = unicode(self.text())
        #     for m in pat.finditer(text):
        #         p = len(text[:m.start()].encode('utf-8'))
        #         self.SendScintilla(self.SCI_INDICATORFILLRANGE,
        #             p, len(m.group(0).encode('utf-8')))
        #
        # but it doesn't to avoid possible performance issue.
        for m in pat.finditer(unicode(self.text()).encode('utf-8')):
            self.SendScintilla(self.SCI_INDICATORFILLRANGE,
                               m.start(), m.end() - m.start())

    @pyqtSlot()
    def clearHighlightText(self):
        self.SendScintilla(self.SCI_SETINDICATORCURRENT,
                           self._highlightIndicator)
        self.SendScintilla(self.SCI_INDICATORCLEARRANGE, 0, self.length())

    @util.propertycache
    def _highlightIndicator(self):
        """Return indicator number for highlight after initializing it"""
        id = self._imsupport.PREEDIT_INDIC_ID - 1
        self.SendScintilla(self.SCI_INDICSETSTYLE, id, self.INDIC_ROUNDBOX)
        self.SendScintilla(self.SCI_INDICSETUNDER, id, True)
        self.SendScintilla(self.SCI_INDICSETFORE, id, 0x00ffff) # 0xbbggrr
        # document says alpha value is 0 to 255, but it looks 0 to 100
        self.SendScintilla(self.SCI_INDICSETALPHA, id, 100)
        return id

    def showHScrollBar(self, show=True):
        self.SendScintilla(self.SCI_SETHSCROLLBAR, show)

class SearchToolBar(QToolBar):
    conditionChanged = pyqtSignal(unicode, bool, bool)
    """Emitted (pattern, icase, wrap) when search condition changed"""

    searchRequested = pyqtSignal(unicode, bool, bool, bool)
    """Emitted (pattern, icase, wrap, forward) when requested"""

    def __init__(self, parent=None, hidable=False, settings=None):
        super(SearchToolBar, self).__init__(_('Search'), parent,
                                            objectName='search',
                                            iconSize=QSize(16, 16))
        if hidable:
            self._close_button = QToolButton(icon=qtlib.geticon('window-close'),
                                             shortcut=Qt.Key_Escape)
            self._close_button.clicked.connect(self.hide)
            self.addWidget(self._close_button)

        self._le = QLineEdit()
        if hasattr(self._le, 'setPlaceholderText'): # Qt >= 4.7
            self._le.setPlaceholderText(_('### regular expression ###'))
        else:
            self._lbl = QLabel(_('Regexp:'),
                               toolTip=_('Regular expression search pattern'))
            self.addWidget(self._lbl)
            self._lbl.setBuddy(self._le)
        self._le.returnPressed.connect(self._emitSearchRequested)
        self.addWidget(self._le)
        self._chk = QCheckBox(_('Ignore case'))
        self.addWidget(self._chk)
        self._wrapchk = QCheckBox(_('Wrap search'))
        self.addWidget(self._wrapchk)
        self._bt = QPushButton(_('Search'), enabled=False)
        self._bt.clicked.connect(self._emitSearchRequested)
        self._le.textChanged.connect(lambda s: self._bt.setEnabled(bool(s)))
        self.addWidget(self._bt)

        self.setFocusProxy(self._le)

        def defaultsettings():
            s = QSettings()
            s.beginGroup('searchtoolbar')
            return s
        self._settings = settings or defaultsettings()
        self.searchRequested.connect(self._writesettings)
        self._readsettings()

        self._le.textChanged.connect(self._emitConditionChanged)
        self._chk.toggled.connect(self._emitConditionChanged)
        self._wrapchk.toggled.connect(self._emitConditionChanged)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.FindNext):
            self._emitSearchRequested(forward=True)
            return
        if event.matches(QKeySequence.FindPrevious):
            self._emitSearchRequested(forward=False)
            return
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            return  # handled by returnPressed
        super(SearchToolBar, self).keyPressEvent(event)

    def wheelEvent(self, event):
        if event.delta() > 0:
            self._emitSearchRequested(forward=False)
            return
        if event.delta() < 0:
            self._emitSearchRequested(forward=True)
            return
        super(SearchToolBar, self).wheelEvent(event)

    def setVisible(self, visible=True):
        super(SearchToolBar, self).setVisible(visible)
        if visible:
            self._le.setFocus()
            self._le.selectAll()

    def _readsettings(self):
        self.setCaseInsensitive(self._settings.value('icase', False).toBool())
        self.setWrapAround(self._settings.value('wrap', False).toBool())

    @pyqtSlot()
    def _writesettings(self):
        self._settings.setValue('icase', self.caseInsensitive())
        self._settings.setValue('wrap', self.wrapAround())

    @pyqtSlot()
    def _emitConditionChanged(self):
        self.conditionChanged.emit(self.pattern(), self.caseInsensitive(),
                                   self.wrapAround())

    @pyqtSlot()
    def _emitSearchRequested(self, forward=True):
        self.searchRequested.emit(self.pattern(), self.caseInsensitive(),
                                  self.wrapAround(), forward)

    def pattern(self):
        """Returns the current search pattern [unicode]"""
        return self._le.text()

    def setPattern(self, text):
        """Set the search pattern [unicode]"""
        self._le.setText(text)

    def caseInsensitive(self):
        """True if case-insensitive search is requested"""
        return self._chk.isChecked()

    def setCaseInsensitive(self, icase):
        self._chk.setChecked(icase)

    def wrapAround(self):
        """True if wrap search is requested"""
        return self._wrapchk.isChecked()

    def setWrapAround(self, wrap):
        self._wrapchk.setChecked(wrap)

    @pyqtSlot(unicode)
    def search(self, text):
        """Request search with the given pattern"""
        self.setPattern(text)
        self._emitSearchRequested()

class KeyPressInterceptor(QObject):
    """Grab key press events important for dialogs

    Usage::
        sci = qscilib.Scintilla(self)
        sci.installEventFilter(KeyPressInterceptor(self))
    """

    def __init__(self, parent=None, keys=None, keyseqs=None):
        super(KeyPressInterceptor, self).__init__(parent)
        self._keys = set((Qt.Key_Escape,))
        self._keyseqs = set((QKeySequence.Refresh,))
        if keys:
            self._keys.update(keys)
        if keyseqs:
            self._keyseqs.update(keyseqs)

    def eventFilter(self, watched, event):
        if event.type() != QEvent.KeyPress:
            return super(KeyPressInterceptor, self).eventFilter(
                watched, event)
        if self._isinterceptable(event):
            event.ignore()
            return True
        return False

    def _isinterceptable(self, event):
        if event.key() in self._keys:
            return True
        if util.any(event.matches(e) for e in self._keyseqs):
            return True
        return False

def fileEditor(filename, **opts):
    'Open a simple modal file editing dialog'
    dialog = QDialog()
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
    dialog.setWindowTitle(filename)
    dialog.setLayout(QVBoxLayout())
    editor = Scintilla()
    editor.setBraceMatching(QsciScintilla.SloppyBraceMatch)
    editor.installEventFilter(KeyPressInterceptor(dialog))
    editor.setMarginLineNumbers(1, True)
    editor.setMarginWidth(1, '000')
    editor.setLexer(QsciLexerProperties())
    if opts.get('foldable'):
        editor.setFolding(QsciScintilla.BoxedTreeFoldStyle)
    dialog.layout().addWidget(editor)

    searchbar = SearchToolBar(dialog, hidable=True)
    searchbar.searchRequested.connect(editor.find)
    searchbar.conditionChanged.connect(editor.highlightText)
    searchbar.hide()
    def showsearchbar():
        searchbar.show()
        searchbar.setFocus(Qt.OtherFocusReason)
    QShortcut(QKeySequence.Find, dialog, showsearchbar)
    dialog.layout().addWidget(searchbar)

    BB = QDialogButtonBox
    bb = QDialogButtonBox(BB.Save|BB.Cancel)
    bb.accepted.connect(dialog.accept)
    bb.rejected.connect(dialog.reject)
    dialog.layout().addWidget(bb)

    s = QSettings()
    geomname = 'editor-geom'
    desktopgeom = qApp.desktop().availableGeometry()
    dialog.resize(desktopgeom.size() * 0.5)
    dialog.restoreGeometry(s.value(geomname).toByteArray())

    ret = QDialog.Rejected
    try:
        f = QFile(filename)
        f.open(QIODevice.ReadOnly)
        editor.read(f)
        editor.setModified(False)
        ret = dialog.exec_()
        if ret == QDialog.Accepted:
            f = QFile(filename)
            f.open(QIODevice.WriteOnly)
            editor.write(f)
        s.setValue(geomname, dialog.saveGeometry())
    except EnvironmentError, e:
        qtlib.WarningMsgBox(_('Unable to read/write config file'),
                            hglib.tounicode(str(e)), parent=dialog)
    return ret
