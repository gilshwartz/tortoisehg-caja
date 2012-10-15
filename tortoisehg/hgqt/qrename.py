# qrename.py - QRename dialog for TortoiseHg
#
# Copyright 2010 Steve Borho <steve@borho.org>
# Copyright 2010 Johan Samyn <johan.samyn@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.util import hglib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import cmdui, qtlib

class QRenameDialog(QDialog):

    output = pyqtSignal(QString, QString)
    makeLogVisible = pyqtSignal(bool)

    def __init__(self, repo, patchname, parent):
        super(QRenameDialog, self).__init__(parent)
        self.setWindowTitle(_('Patch rename - %s') % repo.displayname)

        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(400)
        self.repo = repo
        self.oldpatchname = patchname
        self.newpatchname = ''

        self.setLayout(QVBoxLayout())

        lbl = QLabel(_('Rename patch <b>%s</b> to:') %
                     hglib.tounicode(self.oldpatchname))
        self.layout().addWidget(lbl)

        self.le = QLineEdit(hglib.tounicode(self.oldpatchname))
        self.layout().addWidget(self.le)

        self.cmd = cmdui.Runner(True, self)
        self.cmd.output.connect(self.output)
        self.cmd.makeLogVisible.connect(self.makeLogVisible)
        self.cmd.commandFinished.connect(self.onCommandFinished)

        BB = QDialogButtonBox
        bbox = QDialogButtonBox(BB.Ok|BB.Cancel)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        self.layout().addWidget(bbox)
        self.bbox = bbox

        self.focus = self.le

    @pyqtSlot(int)
    def onCommandFinished(self, ret):
        self.repo.decrementBusyCount()
        self.reject()

    def accept(self):
        self.newpatchname = hglib.fromunicode(self.le.text())
        if self.newpatchname != self.oldpatchname:
            res = checkPatchname(self.repo.root, self.repo.thgactivemqname,
                                    self.newpatchname, self)
            if not res:
                return
            cmdline = ['qrename', '--repository', self.repo.root, '--',
                       self.oldpatchname, self.newpatchname]
            self.repo.incrementBusyCount()
            self.cmd.run(cmdline)
        else:
            self.close()

def checkPatchname(reporoot, activequeue, newpatchname, parent):
    if activequeue == 'patches':
        pn = 'patches'
    else:
        pn = 'patches-%s' % activequeue
    patchfile = os.sep.join([reporoot, ".hg", pn, newpatchname])
    if os.path.exists(patchfile):
        dlg = CheckPatchnameDialog(newpatchname, parent)
        choice = dlg.exec_()
        if choice == 1:
            # add .OLD to existing patchfile
            try:
                os.rename(patchfile, patchfile + '.OLD')
            except (OSError, IOError), inst:
                qtlib.ErrorMsgBox(self.errTitle,
                        _('Could not rename existing patchfile'),
                        hglib.tounicode(str(inst)))
                return False
            return True
        elif choice == 2:
            # overwite existing patchfile
            try:
                os.remove(patchfile)
            except (OSError, IOError), inst:
                qtlib.ErrorMsgBox(self.errTitle,
                        _('Could not delete existing patchfile'),
                        hglib.tounicode(str(inst)))
                return False
            return True
        elif choice == 3:
            # go back and change the new name
            return False
        else:
            return False
    else:
        return True

class CheckPatchnameDialog(QDialog):

    def __init__(self, patchname, parent):
        super(CheckPatchnameDialog, self).__init__(parent)
        self.setWindowTitle(_('QRename - Check patchname'))

        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)
        self.patchname = patchname

        self.vbox = QVBoxLayout()
        self.vbox.setSpacing(4)

        lbl = QLabel(_('Patch name <b>%s</b> already exists:')
                        % (self.patchname))
        self.vbox.addWidget(lbl)

        self.extensionradio = \
                QRadioButton(_('Add .OLD extension to existing patchfile'))
        self.vbox.addWidget(self.extensionradio)
        self.overwriteradio = QRadioButton(_('Overwrite existing patchfile'))
        self.vbox.addWidget(self.overwriteradio)
        self.backradio = QRadioButton(_('Go back and change new patchname'))
        self.vbox.addWidget(self.backradio)

        self.extensionradio.toggled.connect(self.onExtensionRadioChecked)
        self.overwriteradio.toggled.connect(self.onOverwriteRadioChecked)
        self.backradio.toggled.connect(self.onBackRadioChecked)

        self.choice = 0
        self.extensionradio.setChecked(True)
        self.extensionradio.setFocus()

        self.setLayout(self.vbox)

        BB = QDialogButtonBox
        bbox = QDialogButtonBox(BB.Ok|BB.Cancel)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        self.layout().addWidget(bbox)
        self.bbox = bbox

    @pyqtSlot()
    def onExtensionRadioChecked(self):
        if self.extensionradio.isChecked():
            self.choice = 1

    @pyqtSlot()
    def onOverwriteRadioChecked(self):
        if self.overwriteradio.isChecked():
            self.choice = 2

    @pyqtSlot()
    def onBackRadioChecked(self):
        if self.backradio.isChecked():
            self.choice = 3

    def accept(self):
        self.done(self.choice)
        self.close()

    def reject(self):
        self.done(0)
