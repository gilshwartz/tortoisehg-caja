# bisect.py - Bisect dialog for TortoiseHg
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

class BisectDialog(QDialog):
    def __init__(self, repo, opts, parent=None):
        super(BisectDialog, self).__init__(parent)
        self.setWindowTitle(_('Bisect - %s') % repo.displayname)
        self.setWindowIcon(qtlib.geticon('hg-bisect'))

        self.setWindowFlags(Qt.Window)
        self.repo = repo

        # base layout box
        box = QVBoxLayout()
        box.setSpacing(6)
        self.setLayout(box)

        hbox = QHBoxLayout()
        hbox.addWidget(QLabel(_('Known good revision:')))
        gle = QLineEdit()
        gle.setText(opts.get('good', ''))
        hbox.addWidget(gle, 1)
        gb = QPushButton(_('Accept'))
        hbox.addWidget(gb)
        box.addLayout(hbox)

        hbox = QHBoxLayout()
        hbox.addWidget(QLabel(_('Known bad revision:')))
        ble = QLineEdit()
        ble.setText(opts.get('bad', ''))
        ble.setEnabled(False)
        hbox.addWidget(ble, 1)
        bb = QPushButton(_('Accept'))
        bb.setEnabled(False)
        hbox.addWidget(bb)
        box.addLayout(hbox)

        ## command widget
        self.cmd = cmdui.Widget(True, False, self)
        self.cmd.setShowOutput(True)
        box.addWidget(self.cmd, 1)

        hbox = QHBoxLayout()
        goodrev = QPushButton(_('Revision is Good'))
        hbox.addWidget(goodrev)
        badrev = QPushButton(_('Revision is Bad'))
        hbox.addWidget(badrev)
        skiprev = QPushButton(_('Skip this Revision'))
        hbox.addWidget(skiprev)
        box.addLayout(hbox)

        hbox = QHBoxLayout()
        box.addLayout(hbox)
        lbl = QLabel()
        hbox.addWidget(lbl)
        hbox.addStretch(1)
        closeb = QPushButton(_('Close'))
        hbox.addWidget(closeb)
        closeb.clicked.connect(self.reject)

        self.nextbuttons = (goodrev, badrev, skiprev)
        for b in self.nextbuttons:
            b.setEnabled(False)
        self.lastrev = None

        def cmdFinished(ret):
            if ret != 0:
                lbl.setText(_('Error encountered.'))
                return
            repo.dirstate.invalidate()
            ctx = repo['.']
            if ctx.rev() == self.lastrev:
                lbl.setText(_('Culprit found.'))
                return
            self.lastrev = ctx.rev()
            for b in self.nextbuttons:
                b.setEnabled(True)
            lbl.setText('%s: %d (%s) -> %s' % (_('Revision'), ctx.rev(), ctx,
                        _('Test this revision and report findings. '
                          '(good/bad/skip)')))
        self.cmd.commandFinished.connect(cmdFinished)

        prefix = ['bisect', '--repository', repo.root]

        def gverify():
            good = hglib.fromunicode(gle.text().simplified())
            try:
                ctx = repo[good]
                self.goodrev = ctx.rev()
                gb.setEnabled(False)
                gle.setEnabled(False)
                bb.setEnabled(True)
                ble.setEnabled(True)
                ble.setFocus()
            except error.RepoLookupError, e:
                self.cmd.core.stbar.showMessage(hglib.tounicode(str(e)))
            except util.Abort, e:
                if e.hint:
                    err = _('%s (hint: %s)') % (hglib.tounicode(str(e)),
                                                hglib.tounicode(e.hint))
                else:
                    err = hglib.tounicode(str(e))
                self.cmd.core.stbar.showMessage(err)
        def bverify():
            bad = hglib.fromunicode(ble.text().simplified())
            try:
                ctx = repo[bad]
                self.badrev = ctx.rev()
                ble.setEnabled(False)
                bb.setEnabled(False)
                cmds = []
                cmds.append(prefix + ['--reset'])
                cmds.append(prefix + ['--good', str(self.goodrev)])
                cmds.append(prefix + ['--bad', str(self.badrev)])
                self.cmd.run(*cmds)
            except error.RepoLookupError, e:
                self.cmd.core.stbar.showMessage(hglib.tounicode(str(e)))
            except util.Abort, e:
                if e.hint:
                    err = _('%s (hint: %s)') % (hglib.tounicode(str(e)),
                                                hglib.tounicode(e.hint))
                else:
                    err = hglib.tounicode(str(e))
                self.cmd.core.stbar.showMessage(err)

        gb.pressed.connect(gverify)
        bb.pressed.connect(bverify)
        gle.returnPressed.connect(gverify)
        ble.returnPressed.connect(bverify)

        def goodrevision():
            for b in self.nextbuttons:
                b.setEnabled(False)
            self.cmd.run(prefix + ['--good', '.'])
        def badrevision():
            for b in self.nextbuttons:
                b.setEnabled(False)
            self.cmd.run(prefix + ['--bad', '.'])
        def skiprevision():
            for b in self.nextbuttons:
                b.setEnabled(False)
            self.cmd.run(prefix + ['--skip', '.'])
        goodrev.clicked.connect(goodrevision)
        badrev.clicked.connect(badrevision)
        skiprev.clicked.connect(skiprevision)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
        super(BisectDialog, self).keyPressEvent(event)


def run(ui, *pats, **opts):
    from tortoisehg.util import paths
    from tortoisehg.hgqt import thgrepo
    repo = thgrepo.repository(ui, path=paths.find_root())
    return BisectDialog(repo, opts)
