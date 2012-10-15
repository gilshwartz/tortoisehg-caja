# quickop.py - TortoiseHg's dialog for quick dirstate operations
#
# Copyright 2009 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import sys

from mercurial import util

from tortoisehg.util import hglib, shlib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, status, cmdui, lfprompt

from PyQt4.QtCore import *
from PyQt4.QtGui import *

LABELS = { 'add': (_('Checkmark files to add'), _('Add')),
           'forget': (_('Checkmark files to forget'), _('Forget')),
           'revert': (_('Checkmark files to revert'), _('Revert')),
           'remove': (_('Checkmark files to remove'), _('Remove')),}

ICONS = { 'add': 'fileadd',
           'forget': 'hg-remove',
           'revert': 'hg-revert',
           'remove': 'hg-remove',}

class QuickOpDialog(QDialog):
    """ Dialog for performing quick dirstate operations """
    def __init__(self, repo, command, pats, parent):
        QDialog.__init__(self, parent)
        self.setWindowFlags(Qt.Window)
        self.pats = pats
        self.repo = repo
        os.chdir(repo.root)

        # Handle rm alias
        if command == 'rm':
            command = 'remove'
        self.command = command

        self.setWindowTitle(_('%s - hg %s') % (repo.displayname, command))
        self.setWindowIcon(qtlib.geticon(ICONS[command]))

        layout = QVBoxLayout()
        layout.setMargin(0)
        self.setLayout(layout)

        toplayout = QVBoxLayout()
        toplayout.setContentsMargins(5, 5, 5, 0)
        layout.addLayout(toplayout)

        hbox = QHBoxLayout()
        lbl = QLabel(LABELS[command][0])
        slbl = QLabel()
        hbox.addWidget(lbl)
        hbox.addStretch(1)
        hbox.addWidget(slbl)
        self.status_label = slbl
        toplayout.addLayout(hbox)

        types = { 'add'    : 'I?',
                  'forget' : 'MAR!C',
                  'revert' : 'MAR!',
                  'remove' : 'MAR!CI?',
                }
        filetypes = types[self.command]

        checktypes = { 'add'    : '?',
                       'forget' : '',
                       'revert' : 'MAR!',
                       'remove' : '',
                     }
        defcheck = checktypes[self.command]

        opts = {}
        for s, val in status.statusTypes.iteritems():
            opts[val.name] = s in filetypes

        opts['checkall'] = True # pre-check all matching files
        stwidget = status.StatusWidget(repo, pats, opts, self,
                                       defcheck=defcheck)
        toplayout.addWidget(stwidget, 1)

        hbox = QHBoxLayout()
        if self.command == 'revert':
            ## no backup checkbox
            chk = QCheckBox(_('Do not save backup files (*.orig)'))
        elif self.command == 'remove':
            ## force checkbox
            chk = QCheckBox(_('Force removal of modified files (--force)'))
        else:
            chk = None
        if chk:
            self.chk = chk
            hbox.addWidget(chk)

        self.statusbar = cmdui.ThgStatusBar(self)
        stwidget.showMessage.connect(self.statusbar.showMessage)

        self.cmd = cmd = cmdui.Runner(True, self)
        cmd.commandStarted.connect(self.commandStarted)
        cmd.commandFinished.connect(self.commandFinished)
        cmd.progress.connect(self.statusbar.progress)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Close)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(BB.Ok).setDefault(True)
        bb.button(BB.Ok).setText(LABELS[command][1])
        hbox.addStretch()
        hbox.addWidget(bb)
        toplayout.addLayout(hbox)
        self.bb = bb

        if self.command == 'add':
            if 'largefiles' in self.repo.extensions():
                self.addLfilesButton = QPushButton(_('Add &Largefiles'))
            else:
                self.addLfilesButton = None
            if self.addLfilesButton:
                self.addLfilesButton.clicked.connect(self.addLfiles)
                bb.addButton(self.addLfilesButton, BB.ActionRole)

        layout.addWidget(self.statusbar)

        s = QSettings()
        stwidget.loadSettings(s, 'quickop')
        self.restoreGeometry(s.value('quickop/geom').toByteArray())
        if hasattr(self, 'chk'):
            if self.command == 'revert':
                self.chk.setChecked(s.value('quickop/nobackup', True).toBool())
            elif self.command == 'remove':
                self.chk.setChecked(s.value('quickop/forceremove', False).toBool())
        self.stwidget = stwidget
        self.stwidget.refreshWctx()
        QShortcut(QKeySequence('Ctrl+Return'), self, self.accept)
        QShortcut(QKeySequence('Ctrl+Enter'), self, self.accept)
        qtlib.newshortcutsforstdkey(QKeySequence.Refresh, self,
                                    self.stwidget.refreshWctx)
        QShortcut(QKeySequence('Escape'), self, self.reject)

    def commandStarted(self):
        self.bb.button(QDialogButtonBox.Ok).setEnabled(False)

    def commandFinished(self, ret):
        self.bb.button(QDialogButtonBox.Ok).setEnabled(True)
        if ret == 0:
            shlib.shell_notify(self.files)
            self.reject()

    def accept(self):
        cmdline = [self.command]
        if hasattr(self, 'chk') and self.chk.isChecked():
            if self.command == 'revert':
                cmdline.append('--no-backup')
            elif self.command == 'remove':
                cmdline.append('--force')
        files = self.stwidget.getChecked()
        if not files:
            qtlib.WarningMsgBox(_('No files selected'),
                                _('No operation to perform'),
                                parent=self)
            return
        self.repo.bfstatus = True
        self.repo.lfstatus = True
        repostate = self.repo.status()
        self.repo.bfstatus = False
        self.repo.lfstatus = False
        if self.command == 'remove':
            if not self.chk.isChecked():
                modified = repostate[0]
                selmodified = []
                for wfile in files:
                    if wfile in modified:
                        selmodified.append(wfile)
                if selmodified:
                    prompt = qtlib.CustomPrompt(_('Confirm Remove'),
                                                _('You have selected one or more files that have been '
                                                  'modified.  By default, these files will not be '
                                                  'removed.  What would you like to do?'), self,
                                                (_('Remove &Unmodified Files'),
                                                 _('Remove &All Selected Files'), _('Cancel')),
                                                0, 2, selmodified)
                    ret = prompt.run()
                    if ret == 1:
                        cmdline.append('--force')
                    elif ret == 2:
                        return
            unknown, ignored = repostate[4:6]
            for wfile in files:
                if wfile in unknown or wfile in ignored:
                    try:
                        util.unlink(wfile)
                    except EnvironmentError:
                        pass
                    files.remove(wfile)
        elif self.command == 'add':
            if 'largefiles' in self.repo.extensions():
                self.addWithPrompt(files)
                return
        if files:
            cmdline.extend(files)
            self.files = files
            self.cmd.run(cmdline)
        else:
            self.reject()

    def reject(self):
        if self.cmd.core.running():
            self.cmd.core.cancel()
        elif not self.stwidget.canExit():
            return
        else:
            s = QSettings()
            self.stwidget.saveSettings(s, 'quickop')
            s.setValue('quickop/geom', self.saveGeometry())
            if hasattr(self, 'chk'):
                if self.command == 'revert':
                    s.setValue('quickop/nobackup', self.chk.isChecked())
                elif self.command == 'remove':
                    s.setValue('quickop/forceremove', self.chk.isChecked())
            QDialog.reject(self)

    def addLfiles(self):
        if 'largefiles' in self.repo.extensions():
            cmdline = ['add', '--large']
        files = self.stwidget.getChecked()
        if not files:
            qtlib.WarningMsgBox(_('No files selected'),
                                _('No operation to perform'),
                                parent=self)
            return
        cmdline.extend(files)
        self.files = files
        self.cmd.run(cmdline)

    def addWithPrompt(self, files):
        result = lfprompt.promptForLfiles(self, self.repo.ui, self.repo, files)
        if not result:
            return
        files, lfiles = result
        if files:
            cmdline = ['add']
            cmdline.extend(files)
            self.files = files
            self.cmd.run(cmdline)
        if lfiles:
            if 'largefiles' in self.repo.extensions():
                cmdline = ['add', '--large']
            cmdline.extend(lfiles)
            self.files = lfiles
            self.cmd.run(cmdline)

instance = None
class HeadlessQuickop(QWidget):
    def __init__(self, repo, cmdline):
        QWidget.__init__(self)
        self.files = cmdline[1:]
        os.chdir(repo.root)
        self.cmd = cmdui.Runner(True, self)
        self.cmd.commandFinished.connect(self.commandFinished)
        self.cmd.run(cmdline)
        self.hide()

    def commandFinished(self, ret):
        if ret == 0:
            shlib.shell_notify(self.files)
            sys.exit(0)

def run(ui, *pats, **opts):
    pats = hglib.canonpaths(pats)
    if opts.get('canonpats'):
        pats = list(pats) + opts['canonpats']

    from tortoisehg.util import paths
    from tortoisehg.hgqt import thgrepo
    repo = thgrepo.repository(ui, path=paths.find_root())

    command = opts['alias']
    imm = repo.ui.config('tortoisehg', 'immediate', '')
    if command in imm.lower():
        cmdline = [command] + pats
        global instance
        instance = HeadlessQuickop(repo, cmdline)
        return None
    else:
        return QuickOpDialog(repo, command, pats, None)
