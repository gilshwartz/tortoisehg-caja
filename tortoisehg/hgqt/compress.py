# compress.py - History compression dialog for TortoiseHg
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

import os

from mercurial import revset, merge as mergemod

from tortoisehg.util import hglib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, csinfo, cmdui, commit, thgrepo

BB = QDialogButtonBox

class CompressDialog(QDialog):
    showMessage = pyqtSignal(QString)

    def __init__(self, repo, revs, parent):
        super(CompressDialog, self).__init__(parent)
        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)
        self.repo = repo
        self.revs = revs

        box = QVBoxLayout()
        box.setSpacing(8)
        box.setContentsMargins(*(6,)*4)
        self.setLayout(box)

        style = csinfo.panelstyle(selectable=True)

        srcb = QGroupBox( _('Compress changesets up to and including'))
        srcb.setLayout(QVBoxLayout())
        srcb.layout().setContentsMargins(*(2,)*4)
        source = csinfo.create(self.repo, revs[0], style, withupdate=True)
        srcb.layout().addWidget(source)
        self.layout().addWidget(srcb)

        destb = QGroupBox( _('Onto destination'))
        destb.setLayout(QVBoxLayout())
        destb.layout().setContentsMargins(*(2,)*4)
        dest = csinfo.create(self.repo, revs[1], style, withupdate=True)
        destb.layout().addWidget(dest)
        self.destcsinfo = dest
        self.layout().addWidget(destb)

        self.cmd = cmdui.Widget(True, True, self)
        self.cmd.commandFinished.connect(self.commandFinished)
        self.cmd.setShowOutput(True)
        self.showMessage.connect(self.cmd.stbar.showMessage)
        self.cmd.stbar.linkActivated.connect(self.linkActivated)
        self.layout().addWidget(self.cmd, 2)

        bbox = QDialogButtonBox()
        self.cancelbtn = bbox.addButton(QDialogButtonBox.Cancel)
        self.cancelbtn.clicked.connect(self.reject)
        self.compressbtn = bbox.addButton(_('Compress'),
                                            QDialogButtonBox.ActionRole)
        self.compressbtn.clicked.connect(self.compress)
        self.layout().addWidget(bbox)
        self.bbox = bbox

        self.showMessage.emit(_('Checking...'))
        QTimer.singleShot(0, self.checkStatus)

        self.setMinimumWidth(480)
        self.setMaximumHeight(800)
        self.resize(0, 340)
        self.setWindowTitle(_('Compress - %s') % repo.displayname)

    def checkStatus(self):
        repo = self.repo
        class CheckThread(QThread):
            def __init__(self, parent):
                QThread.__init__(self, parent)
                self.dirty = False

            def run(self):
                wctx = repo[None]
                if len(wctx.parents()) > 1:
                    self.dirty = True
                elif wctx.dirty():
                    self.dirty = True
                else:
                    for root, path, status in thgrepo.recursiveMergeStatus(repo):
                        if status == 'u':
                            self.dirty = True
                            break
        def completed():
            self.th.wait()
            if self.th.dirty:
                self.compressbtn.setEnabled(False)
                txt = _('Before compress, you must <a href="commit">'
                        '<b>commit</b></a> or <a href="discard">'
                        '<b>discard</b></a> changes.')
            else:
                self.compressbtn.setEnabled(True)
                txt = _('You may continue the compress')
            self.showMessage.emit(txt)
        self.th = CheckThread(self)
        self.th.finished.connect(completed)
        self.th.start()

    def compress(self):
        self.cancelbtn.setShown(False)
        uc = ['update', '--repository', self.repo.root, '--clean', '--rev',
              str(self.revs[1])]
        rc = ['revert', '--repository', self.repo.root, '--all', '--rev', 
              str(self.revs[0])]
        self.repo.incrementBusyCount()
        self.cmd.run(uc, rc)

    def commandFinished(self, ret):
        self.repo.decrementBusyCount()
        self.showMessage.emit(_('Changes have been moved, you must now commit'))
        self.compressbtn.setText(_('Commit', 'action button'))
        self.compressbtn.clicked.disconnect(self.compress)
        self.compressbtn.clicked.connect(self.commit)

    def commit(self):
        tip, base = self.revs
        func = hglib.revsetmatch(self.repo.ui, '%s::%s' % (base, tip))
        revcount = len(self.repo)
        revs = [c for c in func(self.repo, range(revcount)) if c != base]
        descs = [self.repo[c].description() for c in revs]
        self.repo.opener('cur-message.txt', 'w').write('\n* * *\n'.join(descs))

        dlg = commit.CommitDialog(self.repo, [], {}, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()
        self.showMessage.emit(_('Compress is complete, old history untouched'))
        self.compressbtn.setText(_('Close'))
        self.compressbtn.clicked.disconnect(self.commit)
        self.compressbtn.clicked.connect(self.accept)

    def linkActivated(self, cmd):
        if cmd == 'commit':
            dlg = commit.CommitDialog(self.repo, [], {}, self)
            dlg.finished.connect(dlg.deleteLater)
            dlg.exec_()
            self.checkStatus()
        elif cmd == 'discard':
            labels = [(QMessageBox.Yes, _('&Discard')),
                      (QMessageBox.No, _('Cancel'))]
            if not qtlib.QuestionMsgBox(_('Confirm Discard'),
                     _('Discard outstanding changes to working directory?'),
                     labels=labels, parent=self):
                return
            def finished(ret):
                self.repo.decrementBusyCount()
                if ret == 0:
                    self.checkStatus()
            cmdline = ['update', '--clean', '--repository', self.repo.root,
                       '--rev', '.']
            self.runner = cmdui.Runner(False, self)
            self.runner.commandFinished.connect(finished)
            self.repo.incrementBusyCount()
            self.runner.run(cmdline)
