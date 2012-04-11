# rename.py - TortoiseHg's dialogs for handling renames
#
# Copyright 2009 Steve Borho <steve@borho.org>
# Copyright 2010 Johan Samyn <johan.samyn@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os, sys

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import util, error

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import cmdui, qtlib, thgrepo, manifestmodel
from tortoisehg.util import hglib, paths

# TODO: this dialog should take a repo argument, not ui

class RenameDialog(QDialog):
    """TortoiseHg rename dialog"""

    output = pyqtSignal(QString, QString)
    makeLogVisible = pyqtSignal(bool)
    progress = pyqtSignal(QString, object, QString, QString, object)

    def __init__(self, ui, pats, parent=None, **opts):
        super(RenameDialog, self).__init__(parent)
        self.iscopy = (opts.get('alias') == 'copy')
        # pats: local; src, dest: unicode
        src, dest = self.init_data(ui, pats)
        self.init_view(src, dest)

    def init_data(self, ui, pats):
        """calculate initial values for widgets"""
        fname = ''
        target = ''
        cwd = os.getcwd()
        try:
            self.root = paths.find_root()
            self.repo = thgrepo.repository(ui, path=self.root)
        except (error.RepoError):
            qtlib.ErrorMsgBox(_('Error'),
                    _('Could not find or initialize the repository '
                      'from folder<p>%s</p>' % cwd))
            return ('', '')
        try:
            fname = hglib.canonpath(self.root, cwd, pats[0])
            target = hglib.canonpath(self.root, cwd, pats[1])
        except:
            pass
        os.chdir(self.root)
        fname = hglib.tounicode(util.normpath(fname))
        if target:
            target = hglib.tounicode(util.normpath(target))
        else:
            target = fname
        return (fname, target)

    def init_view(self, src, dest):
        """define the view"""

        # widgets
        self.src_lbl = QLabel(_('Source:'))
        self.src_lbl.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        self.src_txt = QLineEdit(src)
        self.src_txt.setMinimumWidth(300)
        self.src_btn = QPushButton(_('Browse...'))
        self.dest_lbl = QLabel(_('Destination:'))
        self.dest_lbl.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        self.dest_txt = QLineEdit(dest)
        self.dest_btn = QPushButton(_('Browse...'))
        self.copy_chk = QCheckBox(_('Copy source -> destination'))

        comp = manifestmodel.ManifestCompleter(self)
        comp.setModel(manifestmodel.ManifestModel(self.repo, parent=comp))
        self.src_txt.setCompleter(comp)
        self.dest_txt.setCompleter(comp)

        # some extras
        self.dummy_lbl = QLabel('')
        self.hgcmd_lbl = QLabel(_('Hg command:'))
        self.hgcmd_lbl.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        self.hgcmd_txt = QLineEdit()
        self.hgcmd_txt.setReadOnly(True)
        self.show_command(self.compose_command(self.get_src(), self.get_dest()))
        self.keep_open_chk = QCheckBox(_('Always show output'))

        # command widget
        self.cmd = cmdui.Widget(True, False, self)
        self.cmd.commandStarted.connect(self.command_started)
        self.cmd.commandFinished.connect(self.command_finished)
        self.cmd.commandCanceling.connect(self.command_canceling)
        self.cmd.output.connect(self.output)
        self.cmd.makeLogVisible.connect(self.makeLogVisible)
        self.cmd.progress.connect(self.progress)
        self.cmd.setHidden(True)

        # bottom buttons
        self.rename_btn = QPushButton('')
        self.rename_btn.setDefault(True)
        self.rename_btn.setFocus(True)
        self.close_btn = QPushButton(_('&Close'))
        self.close_btn.setAutoDefault(False)
        self.detail_btn = QPushButton(_('&Detail'))
        self.detail_btn.setAutoDefault(False)
        self.detail_btn.setHidden(True)
        self.cancel_btn = QPushButton(_('Cancel'))
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.setHidden(True)

        # connecting slots
        self.src_txt.textChanged.connect(self.src_dest_edited)
        self.src_btn.clicked.connect(self.src_btn_clicked)
        self.dest_txt.textChanged.connect(self.src_dest_edited)
        self.dest_btn.clicked.connect(self.dest_btn_clicked)
        self.copy_chk.toggled.connect(self.copy_chk_toggled)
        self.rename_btn.clicked.connect(self.rename)
        self.detail_btn.clicked.connect(self.detail_clicked)
        self.close_btn.clicked.connect(self.close)
        self.cancel_btn.clicked.connect(self.cancel_clicked)

        # main layout
        self.grid = QGridLayout()
        self.grid.setSpacing(6)
        self.grid.addWidget(self.src_lbl, 0, 0)
        self.grid.addWidget(self.src_txt, 0, 1)
        self.grid.addWidget(self.src_btn, 0, 2)
        self.grid.addWidget(self.dest_lbl, 1, 0)
        self.grid.addWidget(self.dest_txt, 1, 1)
        self.grid.addWidget(self.dest_btn, 1, 2)
        self.grid.addWidget(self.copy_chk, 2, 1)
        self.grid.addWidget(self.dummy_lbl, 3, 1)
        self.grid.addWidget(self.hgcmd_lbl, 4, 0)
        self.grid.addWidget(self.hgcmd_txt, 4, 1)
        self.grid.addWidget(self.keep_open_chk, 5, 1)
        self.hbox = QHBoxLayout()
        self.hbox.addWidget(self.detail_btn)
        self.hbox.addStretch(0)
        self.hbox.addWidget(self.rename_btn)
        self.hbox.addWidget(self.close_btn)
        self.hbox.addWidget(self.cancel_btn)
        self.vbox = QVBoxLayout()
        self.vbox.setSpacing(6)
        self.vbox.addLayout(self.grid)
        self.vbox.addWidget(self.cmd)
        self.vbox.addLayout(self.hbox)

        # dialog setting
        self.setWindowIcon(qtlib.geticon('hg-rename'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.copy_chk.setChecked(self.iscopy)
        self.setLayout(self.vbox)
        self.layout().setSizeConstraint(QLayout.SetFixedSize)
        self.dest_txt.setFocus()
        self._readsettings()
        self.setRenameCopy()

    def setRenameCopy(self):
        if self.windowTitle() == '':
            self.reponame = self.repo.displayname
        if self.copy_chk.isChecked():
            wt = (_('Copy - %s') % self.reponame)
            self.msgTitle = _('Copy')
            self.errTitle = _('Copy Error')
        else:
            wt = (_('Rename - %s') % self.reponame)
            self.msgTitle = _('Rename')
            self.errTitle = _('Rename Error')
        self.rename_btn.setText(self.msgTitle)
        self.setWindowTitle(wt)

    def get_src(self):
        return hglib.fromunicode(self.src_txt.text())

    def get_dest(self):
        return hglib.fromunicode(self.dest_txt.text())

    def src_dest_edited(self):
        self.show_command(self.compose_command(self.get_src(), self.get_dest()))

    def src_btn_clicked(self):
        """Select the source file of folder"""
        self.get_file_or_folder('src')

    def dest_btn_clicked(self):
        """Select the destination file of folder"""
        self.get_file_or_folder('dest')

    def get_file_or_folder(self, mode):
        if mode == 'src':
            curr = self.get_src()
            if os.path.isfile(curr):
                caption = _('Select Source File')
            else:
                caption = _('Select Source Folder')
        else:
            curr = self.get_dest()
            if os.path.isfile(curr):
                caption = _('Select Destination File')
            else:
                caption = _('Select Destination Folder')
        FD = QFileDialog
        if os.path.isfile(curr):
            path = FD.getOpenFileName(parent=self, caption=caption,
                    options=FD.ReadOnly)
        else:
            path = FD.getExistingDirectory(parent=self, caption=caption,
                    options=FD.ShowDirsOnly | FD.ReadOnly)
        if path:
            path = util.normpath(unicode(path))
            pathprefix = util.normpath(hglib.tounicode(self.root)) + '/'
            if not path.startswith(pathprefix):
                return
            relpath = path[len(pathprefix):]
            if mode == 'src':
                self.src_txt.setText(relpath)
            else:
                self.dest_txt.setText(relpath)

    def copy_chk_toggled(self):
        self.setRenameCopy()
        self.show_command(self.compose_command(self.get_src(), self.get_dest()))

    def isCaseFoldingOnWin(self):
        fullsrc = os.path.abspath(self.get_src())
        fulldest = os.path.abspath(self.get_dest())
        return (fullsrc.upper() == fulldest.upper() and sys.platform == 'win32')

    def compose_command(self, src, dest):
        'src and dest are expected to be in local encoding'
        if self.copy_chk.isChecked():
            cmdline = ['copy']
        else:
            cmdline = ['rename']
        cmdline += ['-R', self.repo.root]
        cmdline.append('-v')
        if self.isCaseFoldingOnWin():
            cmdline.append('-A')
        cmdline.append(src)
        cmdline.append(dest)
        return cmdline

    def show_command(self, cmdline):
        self.hgcmd_txt.setText(hglib.tounicode('hg ' + ' '.join(cmdline)))

    def rename(self):
        """execute the rename"""

        # check inputs
        src = self.get_src()
        dest = self.get_dest()
        if not os.path.exists(src):
            qtlib.WarningMsgBox(self.msgTitle, _('Source does not exists.'))
            return
        fullsrc = os.path.abspath(src)
        if not fullsrc.startswith(self.repo.root):
            qtlib.ErrorMsgBox(self.errTitle,
                    _('The source must be within the repository tree.'))
            return
        fulldest = os.path.abspath(dest)
        if not fulldest.startswith(self.repo.root):
            qtlib.ErrorMsgBox(self.errTitle,
                    _('The destination must be within the repository tree.'))
            return
        if src == dest:
            qtlib.ErrorMsgBox(self.errTitle,
                    _('Please give a destination that differs from the source'))
            return
        if (os.path.isfile(dest) and not self.isCaseFoldingOnWin()):
            res = qtlib.QuestionMsgBox(self.msgTitle, '<p>%s</p><p>%s</p>' %
                    (_('Destination file already exists.'),
                    _('Are you sure you want to overwrite it ?')),
                    defaultbutton=QMessageBox.No)
            if not res:
                return

        cmdline = self.compose_command(src, dest)
        self.show_command(cmdline)
        if self.isCaseFoldingOnWin():
            # We do the rename ourselves if it's a pure casefolding
            # action on Windows. Because there is no way to make Hg
            # do 'hg mv foo Foo' correctly there.
            if self.copy_chk.isChecked():
                qtlib.ErrorMsgBox(self.errTitle,
                        _('Cannot do a pure casefolding copy on Windows'))
                return
            else:
                try:
                    targetdir = os.path.dirname(fulldest)
                    if not os.path.isdir(targetdir):
                        os.makedirs(targetdir)
                    os.rename(fullsrc, fulldest)
                except (OSError, IOError), inst:
                    if self.copy_chk.isChecked():
                        txt = _('The following error was caught while copying:')
                    else:
                        txt = _('The following error was caught while renaming:')
                    qtlib.ErrorMsgBox(self.errTitle, txt,
                            hglib.tounicode(str(inst)))
                    return
        self.cmd.run(cmdline)

    def detail_clicked(self):
        if self.cmd.outputShown():
            self.cmd.setShowOutput(False)
        else:
            self.cmd.setShowOutput(True)

    def cancel_clicked(self):
        self.cmd.cancel()

    def command_started(self):
        self.src_txt.setEnabled(False)
        self.src_btn.setEnabled(False)
        self.dest_txt.setEnabled(False)
        self.dest_btn.setEnabled(False)
        self.cmd.setShown(True)
        self.rename_btn.setHidden(True)
        self.close_btn.setHidden(True)
        self.cancel_btn.setShown(True)
        self.detail_btn.setShown(True)

    def command_finished(self, ret):
        if (ret is not 0 or self.cmd.outputShown()
                or self.keep_open_chk.isChecked()):
            if not self.cmd.outputShown():
                self.detail_btn.click()
            self.cancel_btn.setHidden(True)
            self.close_btn.setShown(True)
            self.close_btn.setAutoDefault(True)
            self.close_btn.setFocus()
        else:
            self.reject()

    def command_canceling(self):
        self.cancel_btn.setDisabled(True)

    def closeEvent(self, event):
        self._writesettings()
        super(RenameDialog, self).closeEvent(event)

    def _readsettings(self):
        s = QSettings()
        self.restoreGeometry(s.value('rename/geom').toByteArray())

    def _writesettings(self):
        s = QSettings()
        s.setValue('rename/geom', self.saveGeometry())

def run(ui, *pats, **opts):
    return RenameDialog(ui, pats, **opts)
