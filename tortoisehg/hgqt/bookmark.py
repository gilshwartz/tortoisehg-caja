# bookmark.py - Bookmark dialog for TortoiseHg
#
# Copyright 2010 Michal De Wildt <michael.dewildt@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import error

from tortoisehg.util import hglib, i18n
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, cmdui

keep = i18n.keepgettext()

class BookmarkDialog(QDialog):
    showMessage = pyqtSignal(QString)
    output = pyqtSignal(QString, QString)
    makeLogVisible = pyqtSignal(bool)

    def __init__(self, repo, rev, parent):
        super(BookmarkDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() & \
                            ~Qt.WindowContextHelpButtonHint)
        self.repo = repo
        self.rev = rev
        self.node = repo[rev].node()

        # base layout box
        base = QVBoxLayout()
        base.setSpacing(0)
        base.setContentsMargins(*(0,)*4)
        base.setSizeConstraint(QLayout.SetFixedSize)
        self.setLayout(base)

        box = QVBoxLayout()
        box.setSpacing(8)
        box.setContentsMargins(*(8,)*4)
        self.layout().addLayout(box)

        ## main layout grid
        form = QFormLayout(fieldGrowthPolicy=QFormLayout.AllNonFixedFieldsGrow)
        box.addLayout(form)

        form.addRow(_('Revision:'), QLabel('%d (%s)' % (rev, repo[rev])))

        ### bookmark combo
        self.bookmarkCombo = QComboBox()
        self.bookmarkCombo.setEditable(True)
        self.bookmarkCombo.currentIndexChanged.connect(self.bookmarkTextChanged)
        self.bookmarkCombo.editTextChanged.connect(self.bookmarkTextChanged)
        form.addRow(_('Bookmark:'), self.bookmarkCombo)

        ### Rename input
        self.newNameEdit = QLineEdit()
        self.newNameEdit.textEdited.connect(self.bookmarkTextChanged)
        form.addRow(_('New Name:'), self.newNameEdit)

        ## bottom buttons
        BB = QDialogButtonBox
        bbox = QDialogButtonBox()
        self.addBtn = bbox.addButton(_('&Add'), BB.ActionRole)
        self.renameBtn = bbox.addButton(_('Re&name'), BB.ActionRole)
        self.removeBtn = bbox.addButton(_('&Remove'), BB.ActionRole)
        self.moveBtn = bbox.addButton(_('&Move'), BB.ActionRole)
        bbox.addButton(BB.Close)
        bbox.rejected.connect(self.reject)
        box.addWidget(bbox)

        self.addBtn.clicked.connect(self.add_bookmark)
        self.renameBtn.clicked.connect(self.rename_bookmark)
        self.removeBtn.clicked.connect(self.remove_bookmark)
        self.moveBtn.clicked.connect(self.move_bookmark)

        ## horizontal separator
        self.sep = QFrame()
        self.sep.setFrameShadow(QFrame.Sunken)
        self.sep.setFrameShape(QFrame.HLine)
        self.layout().addWidget(self.sep)

        ## status line
        self.status = qtlib.StatusLabel()
        self.status.setContentsMargins(4, 2, 4, 4)
        self.layout().addWidget(self.status)

        # dialog setting
        self.setWindowTitle(_('Bookmark - %s') % self.repo.displayname)
        self.setWindowIcon(qtlib.geticon('hg-bookmarks'))

        self.cmd = cmdui.Runner(False, self)
        self.cmd.output.connect(self.output)
        self.cmd.makeLogVisible.connect(self.makeLogVisible)
        self.cmd.commandFinished.connect(self.commandFinished)

        # prepare to show
        self.clear_status()
        self.refresh()
        self.repo.repositoryChanged.connect(self.refresh)
        self.bookmarkCombo.setFocus()
        self.bookmarkTextChanged()

    def refresh(self):
        """ update display on dialog with recent repo data """
        # add bookmarks to drop-down list
        marks = self.repo._bookmarks.keys()[:]
        marks.sort(reverse=True)
        cur = self.bookmarkCombo.currentText()
        self.bookmarkCombo.clear()
        for bookmark in marks:
            self.bookmarkCombo.addItem(hglib.tounicode(bookmark))
        if cur:
            self.bookmarkCombo.setEditText(cur)
        else:
            self.bookmarkTextChanged()

    @pyqtSlot()
    def bookmarkTextChanged(self):
        bookmark = self.bookmarkCombo.currentText()
        bookmarklocal = hglib.fromunicode(bookmark)
        if bookmarklocal in self.repo._bookmarks:
            curnode = self.repo._bookmarks[bookmarklocal]
            self.addBtn.setEnabled(False)
            self.newNameEdit.setEnabled(True)
            self.removeBtn.setEnabled(True)
            self.renameBtn.setEnabled(bool(self.newNameEdit.text()))
            self.moveBtn.setEnabled(self.node != curnode)
        else:
            self.addBtn.setEnabled(bool(bookmark))
            self.removeBtn.setEnabled(False)
            self.moveBtn.setEnabled(False)
            self.renameBtn.setEnabled(False)
            self.newNameEdit.setEnabled(False)

    def set_status(self, text, icon=None):
        self.status.setShown(True)
        self.sep.setShown(True)
        self.status.set_status(text, icon)
        self.showMessage.emit(text)

    def clear_status(self):
        self.status.setHidden(True)
        self.sep.setHidden(True)

    def commandFinished(self, ret):
        if ret is 0:
            self.bookmarkCombo.clearEditText()
            self.newNameEdit.setText('')
            self.finishfunc()

    def add_bookmark(self):
        bookmark = self.bookmarkCombo.currentText()
        bookmarklocal = hglib.fromunicode(bookmark)
        if bookmarklocal in self.repo._bookmarks:
            self.set_status(_('A bookmark named "%s" already exists') %
                            bookmark, False)
            return

        def finished():
            self.set_status(_("Bookmark '%s' has been added") % bookmark, True)

        cmdline = ['bookmark', '--repository', self.repo.root,
                   '--rev', str(self.rev), bookmarklocal]
        self.cmd.run(cmdline)
        self.finishfunc = finished

    def move_bookmark(self):
        bookmark = self.bookmarkCombo.currentText()
        bookmarklocal = hglib.fromunicode(bookmark)
        if bookmarklocal not in self.repo._bookmarks:
            self.set_status(_('Bookmark named "%s" does not exist') %
                            bookmark, False)
            return

        def finished():
            self.set_status(_("Bookmark '%s' has been moved") % bookmark, True)

        cmdline = ['bookmark', '--repository', self.repo.root,
                   '--rev', str(self.rev), '--force', bookmarklocal]
        self.cmd.run(cmdline)
        self.finishfunc = finished

    def remove_bookmark(self):
        bookmark = self.bookmarkCombo.currentText()
        bookmarklocal = hglib.fromunicode(bookmark)
        if bookmarklocal not in self.repo._bookmarks:
            self.set_status(_("Bookmark '%s' does not exist") % bookmark, False)
            return

        def finished():
            self.set_status(_("Bookmark '%s' has been removed") % bookmark, True)

        cmdline = ['bookmark', '--repository', self.repo.root,
                   '--delete', bookmarklocal]
        self.cmd.run(cmdline)
        self.finishfunc = finished

    def rename_bookmark(self):
        name = self.bookmarkCombo.currentText()
        namelocal = hglib.fromunicode(name)

        newname = self.newNameEdit.text()
        newnamelocal = hglib.fromunicode(newname)
        if namelocal not in self.repo._bookmarks:
            self.set_status(_("Bookmark '%s' does not exist") % name, False)
            return

        if newnamelocal in self.repo._bookmarks:
            self.set_status(_('A bookmark named "%s" already exists') %
                            newname, False)
            return

        def finished():
            self.set_status(_("Bookmark '%s' has been renamed to '%s'") %
                            (name, newname), True)

        cmdline = ['bookmark', '--repository', self.repo.root,
                   '--rename', namelocal, newnamelocal]
        self.cmd.run(cmdline)
        self.finishfunc = finished

    def reject(self):
        # prevent signals from reaching deleted objects
        self.repo.repositoryChanged.disconnect(self.refresh)
        super(BookmarkDialog, self).reject()
