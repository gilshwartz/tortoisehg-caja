# branchop.py - branch operations dialog for TortoiseHg commit tool
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.hgqt.i18n import _
from tortoisehg.util import hglib

from tortoisehg.hgqt import qtlib

class BranchOpDialog(QDialog):
    'Dialog for manipulating wctx.branch()'
    def __init__(self, repo, oldbranchop, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('%s - branch operation') % repo.displayname)
        self.setWindowIcon(qtlib.geticon('branch'))
        layout = QVBoxLayout()
        self.setLayout(layout)
        wctx = repo[None]

        if len(wctx.parents()) == 2:
            lbl = QLabel('<b>'+_('Select branch of merge commit')+'</b>')
            layout.addWidget(lbl)
            branchCombo = QComboBox()
            # If both parents belong to the same branch, do not duplicate the
            # branch name in the branch select combo
            branchlist = [p.branch() for p in wctx.parents()]
            if branchlist[0] == branchlist[1]:
                branchlist = [branchlist[0]]
            for b in branchlist:
                branchCombo.addItem(hglib.tounicode(b))
            layout.addWidget(branchCombo)
        else:
            text = '<b>'+_('Changes take effect on next commit')+'</b>'
            lbl = QLabel(text)
            layout.addWidget(lbl)

            grid = QGridLayout()
            nochange = QRadioButton(_('No branch changes'))
            newbranch = QRadioButton(_('Open a new named branch'))
            closebranch = QRadioButton(_('Close current branch'))
            branchCombo = QComboBox()
            branchCombo.setEditable(True)

            wbu = hglib.tounicode(wctx.branch())
            for name in repo.namedbranches:
                if name == wbu:
                    continue
                branchCombo.addItem(hglib.tounicode(name))
            branchCombo.activated.connect(self.accept)

            grid.addWidget(nochange, 0, 0)
            grid.addWidget(newbranch, 1, 0)
            grid.addWidget(branchCombo, 1, 1)
            grid.addWidget(closebranch, 2, 0)
            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 1)
            layout.addLayout(grid)
            layout.addStretch()

            newbranch.toggled.connect(branchCombo.setEnabled)
            branchCombo.setEnabled(False)
            if oldbranchop is None:
                nochange.setChecked(True)
            elif oldbranchop == False:
                closebranch.setChecked(True)
            else:
                assert type(oldbranchop) == QString
                bc = branchCombo
                names = [bc.itemText(i) for i in xrange(bc.count())]
                if oldbranchop in names:
                    bc.setCurrentIndex(names.index(oldbranchop))
                else:
                    bc.addItem(oldbranchop)
                    bc.setCurrentIndex(len(names))
                newbranch.setChecked(True)
            self.closebranch = closebranch

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(BB.Ok).setAutoDefault(True)
        layout.addWidget(bb)
        self.bb = bb
        self.branchCombo = branchCombo
        QShortcut(QKeySequence('Ctrl+Return'), self, self.accept)
        QShortcut(QKeySequence('Ctrl+Enter'), self, self.accept)
        QShortcut(QKeySequence('Escape'), self, self.reject)

    def accept(self):
        '''Branch operation is one of:
            None  - leave wctx branch name untouched
            False - close current branch
            QString - open new named branch
        '''
        if self.branchCombo.isEnabled():
            self.branchop = self.branchCombo.currentText()
        elif self.closebranch.isChecked():
            self.branchop = False
        else:
            self.branchop = None
        QDialog.accept(self)
