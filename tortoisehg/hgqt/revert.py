# revert.py - File revert dialog for TortoiseHg
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import util, error

from tortoisehg.util import hglib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import cmdui, qtlib

class RevertDialog(QDialog):
    def __init__(self, repo, wfiles, rev, parent):
        if rev is None:
            qtlib.WarningMsgBox(_('Cannot revert to working directory'),
                                _('Reverting to the working directory revision '
                                'does not make sense'),
                                parent=parent)
            raise ValueError(_('Cannot revert to working directory'))

        super(RevertDialog, self).__init__(parent)
        self.setWindowTitle(_('Revert - %s') % repo.displayname)

        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)
        self.repo = repo
        self.wfiles = [repo.wjoin(wfile) for wfile in wfiles]
        self.rev = str(rev)

        self.setLayout(QVBoxLayout())

        if len(wfile) == 1:
            lblText = _('<b>Revert %s to its contents'
                        ' at revision %d?</b>') % (
                      hglib.tounicode(wfiles[0]), rev)
        else:
            lblText = _('<b>Revert %d files to their contents'
                        ' at revision %d?</b>') % (
                      len(wfiles), rev)
        lbl = QLabel(lblText)
        self.layout().addWidget(lbl)

        self.allchk = QCheckBox(_('Revert all files to this revision'))
        self.layout().addWidget(self.allchk)

        self.cmd = cmdui.Runner(True, self)
        self.cmd.commandFinished.connect(self.finished)

        BB = QDialogButtonBox
        bbox = QDialogButtonBox(BB.Ok|BB.Cancel)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        self.layout().addWidget(bbox)
        self.bbox = bbox

    def accept(self):
        if self.allchk.isChecked():
            if not qtlib.QuestionMsgBox(_('Confirm Revert'),
                     _('Reverting all files will discard changes and '
                       'leave affected files in a modified state.<br>'
                       '<br>Are you sure you want to use revert?<br><br>'
                       '(use update to checkout another revision)'),
                       parent=self):
                return
            cmdline = ['revert', '--repository', self.repo.root, '--all']
        else:
            cmdline = ['revert', '--repository', self.repo.root]
            cmdline.extend(self.wfiles)
        cmdline += ['--rev', self.rev]
        self.bbox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.cmd.run(cmdline)

    def finished(self, ret):
        if ret == 0:
            self.reject()
