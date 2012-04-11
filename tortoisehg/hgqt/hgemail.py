# hgemail.py - TortoiseHg's dialog for sending patches via email
#
# Copyright 2007 TK Soh <teekaysoh@gmail.com>
# Copyright 2007 Steve Borho <steve@borho.org>
# Copyright 2010 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os, tempfile, re
from StringIO import StringIO
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from mercurial import error, extensions, util, cmdutil
from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import cmdui, lexers, qtlib, thgrepo
from tortoisehg.hgqt.hgemail_ui import Ui_EmailDialog

class EmailDialog(QDialog):
    """Dialog for sending patches via email"""
    def __init__(self, repo, revs, parent=None, outgoing=False,
                 outgoingrevs=None):
        """Create EmailDialog for the given repo and revs

        :revs: List of revisions to be sent.
        :outgoing: Enable outgoing bundle support. You also need to set
                   outgoing revisions to `revs`.
        :outgoingrevs: Target revision of outgoing bundle.
                       (Passed as `hg email --bundle --rev {rev}`)
        """
        super(EmailDialog, self).__init__(parent)
        self.setWindowFlags(Qt.Window)
        self._repo = repo
        self._outgoing = outgoing
        self._outgoingrevs = outgoingrevs or []

        self._qui = Ui_EmailDialog()
        self._qui.setupUi(self)

        self._initchangesets(revs)
        self._initpreviewtab()
        self._initenvelopebox()
        self._qui.bundle_radio.toggled.connect(self._updateforms)
        self._initintrobox()
        self._readhistory()
        self._filldefaults()
        self._updateforms()
        self._readsettings()
        QShortcut(QKeySequence('CTRL+Return'), self, self.accept)
        QShortcut(QKeySequence('Ctrl+Enter'), self, self.accept)

    def closeEvent(self, event):
        self._writesettings()
        super(EmailDialog, self).closeEvent(event)

    def _readsettings(self):
        s = QSettings()
        self.restoreGeometry(s.value('email/geom').toByteArray())
        self._qui.intro_changesets_splitter.restoreState(
            s.value('email/intro_changesets_splitter').toByteArray())

    def _writesettings(self):
        s = QSettings()
        s.setValue('email/geom', self.saveGeometry())
        s.setValue('email/intro_changesets_splitter',
                   self._qui.intro_changesets_splitter.saveState())

    def _readhistory(self):
        s = QSettings()
        for k in ('to', 'cc', 'from', 'flag'):
            w = getattr(self._qui, '%s_edit' % k)
            w.addItems(s.value('email/%s_history' % k).toStringList())
            w.setCurrentIndex(-1)  # unselect

    def _writehistory(self):
        def itercombo(w):
            if w.currentText():
                yield w.currentText()
            for i in xrange(w.count()):
                if w.itemText(i) != w.currentText():
                    yield w.itemText(i)

        s = QSettings()
        for k in ('to', 'cc', 'from', 'flag'):
            w = getattr(self._qui, '%s_edit' % k)
            s.setValue('email/%s_history' % k, list(itercombo(w))[:10])

    def _initchangesets(self, revs):
        def purerevs(revs):
            return hglib.revrange(self._repo,
                                  iter(str(e) for e in revs))

        self._changesets = _ChangesetsModel(self._repo,
                                            # TODO: [':'] is inefficient
                                            revs=purerevs(revs or [':']),
                                            selectedrevs=purerevs(revs),
                                            parent=self)
        self._changesets.dataChanged.connect(self._updateforms)
        self._qui.changesets_view.setModel(self._changesets)

    @property
    def _ui(self):
        return self._repo.ui

    @property
    def _revs(self):
        """Returns list of revisions to be sent"""
        return self._changesets.selectedrevs

    def _filldefaults(self):
        """Fill form by default values"""
        def getfromaddr(ui):
            """Get sender address in the same manner as patchbomb"""
            addr = ui.config('email', 'from') or ui.config('patchbomb', 'from')
            if addr:
                return addr
            try:
                return ui.username()
            except error.Abort:
                return ''

        self._qui.to_edit.setEditText(
            hglib.tounicode(self._ui.config('email', 'to', '')))
        self._qui.cc_edit.setEditText(
            hglib.tounicode(self._ui.config('email', 'cc', '')))
        self._qui.from_edit.setEditText(hglib.tounicode(getfromaddr(self._ui)))

        self.setdiffformat(self._ui.configbool('diff', 'git') and 'git' or 'hg')

    def setdiffformat(self, format):
        """Set diff format, 'hg', 'git' or 'plain'"""
        try:
            radio = getattr(self._qui, '%spatch_radio' % format)
        except AttributeError:
            raise ValueError('unknown diff format: %r' % format)

        radio.setChecked(True)

    def getdiffformat(self):
        """Selected diff format"""
        for e in self._qui.patch_frame.children():
            m = re.match(r'(\w+)patch_radio', str(e.objectName()))
            if m and e.isChecked():
                return m.group(1)

        return 'hg'

    def getextraopts(self):
        """Dict of extra options"""
        opts = {}
        for e in self._qui.extra_frame.children():
            m = re.match(r'(\w+)_check', str(e.objectName()))
            if m:
                opts[m.group(1)] = e.isChecked()

        return opts

    def _patchbombopts(self, **opts):
        """Generate opts for patchbomb by form values"""
        def headertext(s):
            # QLineEdit may contain newline character
            return re.sub(r'\s', ' ', hglib.fromunicode(s))

        opts['to'] = [headertext(self._qui.to_edit.currentText())]
        opts['cc'] = [headertext(self._qui.cc_edit.currentText())]
        opts['from'] = headertext(self._qui.from_edit.currentText())
        opts['in_reply_to'] = headertext(self._qui.inreplyto_edit.text())
        opts['flag'] = [headertext(self._qui.flag_edit.currentText())]

        if self._qui.bundle_radio.isChecked():
            assert self._outgoing  # only outgoing bundle is supported
            opts['rev'] = map(str, self._outgoingrevs)
            opts['bundle'] = True
        else:
            opts['rev'] = map(str, self._revs)

        def diffformat():
            n = self.getdiffformat()
            if n == 'hg':
                return {}
            else:
                return {n: True}
        opts.update(diffformat())

        opts.update(self.getextraopts())

        def writetempfile(s):
            fd, fname = tempfile.mkstemp(prefix='thg_emaildesc_')
            try:
                os.write(fd, s)
                return fname
            finally:
                os.close(fd)

        opts['intro'] = self._qui.writeintro_check.isChecked()
        if opts['intro']:
            opts['subject'] = headertext(self._qui.subject_edit.text())
            opts['desc'] = writetempfile(hglib.fromunicode(self._qui.body_edit.toPlainText()))
            # TODO: change patchbomb not to use temporary file

        # Include the repo in the command so it can be found when thg is not
        # run from within a hg path
        opts['repository'] = self._repo.root

        return opts

    def _isvalid(self):
        """Filled all required values?"""
        for e in ('to_edit', 'from_edit'):
            if not getattr(self._qui, e).currentText():
                return False

        if self._qui.writeintro_check.isChecked() and not self._qui.subject_edit.text():
            return False

        if not self._revs:
            return False

        return True

    @pyqtSlot()
    def _updateforms(self):
        """Update availability of form widgets"""
        valid = self._isvalid()
        self._qui.send_button.setEnabled(valid)
        self._qui.main_tabs.setTabEnabled(self._previewtabindex(), valid)
        self._qui.writeintro_check.setEnabled(not self._introrequired())

        self._qui.bundle_radio.setEnabled(
            self._outgoing and self._changesets.isselectedall())
        self._changesets.setReadOnly(self._qui.bundle_radio.isChecked())
        if self._qui.bundle_radio.isChecked():
            # workaround to disable preview for outgoing bundle because it
            # may freeze main thread
            self._qui.main_tabs.setTabEnabled(self._previewtabindex(), False)

        if self._introrequired():
            self._qui.writeintro_check.setChecked(True)

    def _initenvelopebox(self):
        for e in ('to_edit', 'from_edit'):
            getattr(self._qui, e).editTextChanged.connect(self._updateforms)

    def accept(self):
        # TODO: want to pass patchbombopts directly
        def cmdargs(opts):
            args = []
            for k, v in opts.iteritems():
                if isinstance(v, bool):
                    if v:
                        args.append('--%s' % k.replace('_', '-'))
                else:
                    for e in isinstance(v, basestring) and [v] or v:
                        args += ['--%s' % k.replace('_', '-'), e]

            return args

        hglib.loadextension(self._ui, 'patchbomb')

        opts = self._patchbombopts()
        try:
            cmd = cmdui.Dialog(['email'] + cmdargs(opts), parent=self)
            cmd.setWindowTitle(_('Sending Email'))
            cmd.setShowOutput(False)
            cmd.finished.connect(cmd.deleteLater)
            if cmd.exec_():
                self._writehistory()
        finally:
            if 'desc' in opts:
                os.unlink(opts['desc'])  # TODO: don't use tempfile

    def _initintrobox(self):
        self._qui.intro_box.hide()  # hidden by default
        self._qui.subject_edit.textChanged.connect(self._updateforms)
        self._qui.writeintro_check.toggled.connect(self._updateforms)

    def _introrequired(self):
        """Is intro message required?"""
        return len(self._revs) > 1 or self._qui.bundle_radio.isChecked()

    def _initpreviewtab(self):
        def initqsci(w):
            w.setUtf8(True)
            w.setReadOnly(True)
            w.setMarginWidth(1, 0)  # hide area for line numbers
            self.lexer = lex = lexers.get_diff_lexer(self)
            fh = qtlib.getfont('fontdiff')
            fh.changed.connect(self.forwardFont)
            lex.setFont(fh.font())
            w.setLexer(lex)
            # TODO: better way to setup diff lexer
          
        initqsci(self._qui.preview_edit)

        self._qui.main_tabs.currentChanged.connect(self._refreshpreviewtab)
        self._refreshpreviewtab(self._qui.main_tabs.currentIndex())

    def forwardFont(self, font):
        if self.lexer:
            self.lexer.setFont(font)

    @pyqtSlot(int)
    def _refreshpreviewtab(self, index):
        """Generate preview text if current tab is preview"""
        if self._previewtabindex() != index:
            return

        self._qui.preview_edit.setText(self._preview())

    def _preview(self):
        """Generate preview text by running patchbomb"""
        def loadpatchbomb():
            hglib.loadextension(self._ui, 'patchbomb')
            return extensions.find('patchbomb')

        def wrapui(ui):
            buf = StringIO()
            # TODO: common way to prepare pure ui
            newui = ui.copy()
            newui.setconfig('ui', 'interactive', False)
            newui.setconfig('diff', 'git', False)
            newui.write = lambda *args, **opts: buf.write(''.join(args))
            newui.status = lambda *args, **opts: None
            return newui, buf

        def stripheadmsg(s):
            # TODO: skip until first Content-type: line ??
            return '\n'.join(s.splitlines()[3:])

        ui, buf = wrapui(self._ui)
        opts = self._patchbombopts(test=True)
        try:
            # TODO: fix hgext.patchbomb's implementation instead
            if 'PAGER' in os.environ:
                del os.environ['PAGER']

            loadpatchbomb().patchbomb(ui, self._repo, **opts)
            return stripheadmsg(hglib.tounicode(buf.getvalue()))
        finally:
            if 'desc' in opts:
                os.unlink(opts['desc'])  # TODO: don't use tempfile

    def _previewtabindex(self):
        """Index of preview tab"""
        return self._qui.main_tabs.indexOf(self._qui.preview_tab)

    @pyqtSlot()
    def on_settings_button_clicked(self):
        from tortoisehg.hgqt import settings
        if settings.SettingsDialog(parent=self, focus='email.from').exec_():
            # not use repo.configChanged because it can clobber user input
            # accidentally.
            self._repo.invalidateui()  # force reloading config immediately
            self._filldefaults()

    @pyqtSlot()
    def on_selectall_button_clicked(self):
        self._changesets.selectAll()

    @pyqtSlot()
    def on_selectnone_button_clicked(self):
        self._changesets.selectNone()

class _ChangesetsModel(QAbstractTableModel):  # TODO: use component of log viewer?
    _COLUMNS = [('rev', lambda ctx: '%d:%s' % (ctx.rev(), ctx)),
                ('author', lambda ctx: hglib.username(ctx.user())),
                ('date', lambda ctx: util.shortdate(ctx.date())),
                ('description', lambda ctx: ctx.longsummary())]

    def __init__(self, repo, revs, selectedrevs, parent=None):
        super(_ChangesetsModel, self).__init__(parent)
        self._repo = repo
        self._revs = list(reversed(sorted(revs)))
        self._selectedrevs = set(selectedrevs)
        self._readonly = False

    @property
    def revs(self):
        return self._revs

    @property
    def selectedrevs(self):
        """Return the list of selected revisions"""
        return list(sorted(self._selectedrevs))

    def isselectedall(self):
        return len(self._revs) == len(self._selectedrevs)

    def data(self, index, role):
        if not index.isValid():
            return QVariant()

        rev = self._revs[index.row()]
        if index.column() == 0 and role == Qt.CheckStateRole:
            return rev in self._selectedrevs and Qt.Checked or Qt.Unchecked
        if role == Qt.DisplayRole:
            coldata = self._COLUMNS[index.column()][1]
            return QVariant(hglib.tounicode(coldata(self._repo.changectx(rev))))

        return QVariant()

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or self._readonly:
            return False

        rev = self._revs[index.row()]
        if index.column() == 0 and role == Qt.CheckStateRole:
            origvalue = rev in self._selectedrevs
            if value == Qt.Checked:
                self._selectedrevs.add(rev)
            else:
                self._selectedrevs.remove(rev)

            if origvalue != (rev in self._selectedrevs):
                self.dataChanged.emit(index, index)

            return True

        return False

    def setReadOnly(self, readonly):
        self._readonly = readonly

    def flags(self, index):
        v = super(_ChangesetsModel, self).flags(index)
        if index.column() == 0 and not self._readonly:
            return Qt.ItemIsUserCheckable | v
        else:
            return v

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0  # no child
        return len(self._revs)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0  # no child
        return len(self._COLUMNS)

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return QVariant()

        return QVariant(self._COLUMNS[section][0].capitalize())

    def selectAll(self):
        self._selectedrevs = set(self._revs)
        self.updateAll()

    def selectNone(self):
        self._selectedrevs = set()
        self.updateAll()

    def updateAll(self):
        first = self.createIndex(0, 0)
        last = self.createIndex(len(self._revs) - 1, 0)
        self.dataChanged.emit(first, last)

def run(ui, *revs, **opts):
    # TODO: same options as patchbomb
    if opts.get('rev'):
        if revs:
            raise util.Abort(_('use only one form to specify the revision'))
        revs = opts.get('rev')

    # TODO: repo should be a required argument?
    repo = opts.get('repo') or thgrepo.repository(ui, paths.find_root())

    try:
        return EmailDialog(repo, revs, outgoing=opts.get('outgoing', False),
                           outgoingrevs=opts.get('outgoingrevs', None))
    except error.RepoLookupError, e:
        qtlib.ErrorMsgBox(_('Failed to open Email dialog'),
                          hglib.tounicode(e.message))
