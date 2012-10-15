# thgstrip.py - MQ strip dialog for TortoiseHg
#
# Copyright 2009 Yuki KODAMA <endflow.net@gmail.com>
# Copyright 2010 David Wilhelm <dave@jumbledpile.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import inspect

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import hg, ui, error

from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _, ngettext
from tortoisehg.hgqt import cmdui, cslist, qtlib, thgrepo

class StripDialog(QDialog):
    """Dialog to strip changesets"""

    showBusyIcon = pyqtSignal(QString)
    hideBusyIcon = pyqtSignal(QString)

    def __init__(self, repo=None, rev=None, parent=None, opts={}):
        super(StripDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.setWindowIcon(qtlib.geticon('menudelete'))

        self.ui = ui.ui()
        if repo:
            self.repo = repo
        else:
            root = paths.find_root()
            if root:
                self.repo = thgrepo.repository(self.ui, path=root)
            else:
                raise 'not repository'

        # base layout box
        box = QVBoxLayout()
        box.setSpacing(6)

        ## main layout grid
        self.grid = grid = QGridLayout()
        grid.setSpacing(6)
        box.addLayout(grid)

        ### target revision combo
        self.rev_combo = combo = QComboBox()
        combo.setEditable(True)
        grid.addWidget(QLabel(_('Strip:')), 0, 0)
        grid.addWidget(combo, 0, 1)
        grid.addWidget(QLabel(_('Preview:')), 1, 0, Qt.AlignLeft | Qt.AlignTop)
        self.status = QLabel("")
        grid.addWidget(self.status, 1, 1, Qt.AlignLeft | Qt.AlignTop)

        if rev is None:
            rev = self.repo.dirstate.branch()
        else:
            rev = str(rev)
        combo.addItem(hglib.tounicode(rev))
        combo.setCurrentIndex(0)
        for name in self.repo.namedbranches:
            combo.addItem(name)

        tags = list(self.repo.tags())
        tags.sort(reverse=True)
        for tag in tags:
            combo.addItem(hglib.tounicode(tag))

        ### preview box, contained in scroll area, contains preview grid
        self.cslist = cslist.ChangesetList(self.repo)
        self.cslistrow = cslistrow = 2
        self.cslistcol = cslistcol = 1
        grid.addWidget(self.cslist, cslistrow, cslistcol,
                       Qt.AlignLeft | Qt.AlignTop)

        ### options
        optbox = QVBoxLayout()
        optbox.setSpacing(6)
        expander = qtlib.ExpanderLabel(_('Options:'), False)
        expander.expanded.connect(self.show_options)
        grid.addWidget(expander, 3, 0, Qt.AlignLeft | Qt.AlignTop)
        grid.addLayout(optbox, 3, 1)

        self.discard_chk = QCheckBox(_('Discard local changes, no backup (-f/--force)'))
        self.nobackup_chk = QCheckBox(_('No backup (-n/--nobackup)'))
        optbox.addWidget(self.discard_chk)
        optbox.addWidget(self.nobackup_chk)

        self.discard_chk.setChecked(bool(opts.get('force')))
        self.nobackup_chk.setChecked(bool(opts.get('nobackup')))

        ## command widget
        self.cmd = cmdui.Widget(True, True, self)
        self.cmd.commandStarted.connect(self.command_started)
        self.cmd.commandFinished.connect(self.command_finished)
        self.cmd.commandCanceling.connect(self.command_canceling)
        box.addWidget(self.cmd)

        ## bottom buttons
        buttons = QDialogButtonBox()
        self.cancel_btn = buttons.addButton(QDialogButtonBox.Cancel)
        self.cancel_btn.clicked.connect(self.cancel_clicked)
        self.close_btn = buttons.addButton(QDialogButtonBox.Close)
        self.close_btn.clicked.connect(self.reject)
        self.close_btn.setAutoDefault(False)
        self.strip_btn = buttons.addButton(_('&Strip'),
                                           QDialogButtonBox.ActionRole)
        self.strip_btn.clicked.connect(self.strip)
        self.detail_btn = buttons.addButton(_('Detail'),
                                            QDialogButtonBox.ResetRole)
        self.detail_btn.setAutoDefault(False)
        self.detail_btn.setCheckable(True)
        self.detail_btn.toggled.connect(self.detail_toggled)
        grid.setRowStretch(cslistrow, 1)
        grid.setColumnStretch(cslistcol, 1)
        box.addWidget(buttons)

        # signal handlers
        self.rev_combo.editTextChanged.connect(lambda *a: self.preview())
        self.rev_combo.lineEdit().returnPressed.connect(self.strip)
        self.discard_chk.toggled.connect(lambda *a: self.preview())

        # dialog setting
        self.setLayout(box)
        self.layout().setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.setWindowTitle(_('Strip - %s') % self.repo.displayname)
        #self.setWindowIcon(qtlib.geticon('strip'))

        # prepare to show
        self.rev_combo.lineEdit().selectAll()
        self.cslist.setHidden(False)
        self.cmd.setHidden(True)
        self.cancel_btn.setHidden(True)
        self.detail_btn.setHidden(True)
        self.nobackup_chk.setHidden(True)
        self.preview()

    ### Private Methods ###

    def resizeEvent(self, event):
        w = self.grid.cellRect(self.cslistrow, self.cslistcol).width()
        h = self.grid.cellRect(self.cslistrow, self.cslistcol).height()
        self.cslist.resize(w, h)

    def get_rev(self):
        """Return the integer revision number of the input or None"""
        revstr = hglib.fromunicode(self.rev_combo.currentText())
        if not revstr:
            return None
        try:
            rev = self.repo[revstr].rev()
        except (error.RepoError, error.LookupError):
            return None
        return rev

    def updatecslist(self, uselimit=True):
        """Update the cs list and return the success status as a bool"""
        rev = self.get_rev()
        if rev is None:
            return False
        cl = self.repo.changelog
        if inspect.getargspec(cl.descendants)[1]:  # hg<2.3: *revs
            striprevs = list(cl.descendants(rev))
        else:
            striprevs = list(cl.descendants([rev]))
        striprevs.append(rev)
        striprevs.sort()
        self.cslist.clear()
        self.cslist.update(striprevs)
        return True

    def preview(self):
        if self.updatecslist():
            striprevs = self.cslist.curitems
            cstext = ngettext(
                "<b>%d changeset</b> will be stripped",
                "<b>%d changesets</b> will be stripped",
                len(striprevs)) % len(striprevs)
            self.status.setText(cstext)
            self.strip_btn.setEnabled(True)
        else:
            self.cslist.clear()
            self.cslist.updatestatus()
            cstext = qtlib.markup(_('Unknown revision!'), fg='red',
                                  weight='bold')
            self.status.setText(cstext)
            self.strip_btn.setDisabled(True)

    def strip(self):
        cmdline = ['strip', '--repository', self.repo.root, '--verbose']
        rev = hglib.fromunicode(self.rev_combo.currentText())
        if not rev:
            return
        cmdline.append(rev)

        if self.discard_chk.isChecked():
            cmdline.append('--force')
        else:
            try:
                node = self.repo[rev]
            except (error.LookupError, error.RepoLookupError, error.RepoError):
                return
            def isclean():
                """return whether WD is changed"""
                wc = self.repo[None]
                return not (wc.modified() or wc.added() or wc.removed())
            if not isclean():
                main = _("Detected uncommitted local changes.")
                text = _("Do you want to discard them and continue?")
                labels = ((QMessageBox.Yes, _('&Yes (--force)')),
                          (QMessageBox.No, _('&No')))
                if qtlib.QuestionMsgBox(_('Confirm Strip'), main, text,
                                        labels=labels, parent=self):
                    cmdline.append('--force')
                else:
                    return

        # backup options
        if self.nobackup_chk.isChecked():
            cmdline.append('--nobackup')

        # start the strip
        self.repo.incrementBusyCount()
        self.cmd.run(cmdline)

    ### Signal Handlers ###

    def cancel_clicked(self):
        self.cmd.cancel()
        self.reject()

    def detail_toggled(self, checked):
        self.cmd.setShowOutput(checked)

    def show_options(self, visible):
        self.nobackup_chk.setShown(visible)

    def command_started(self):
        self.cmd.setShown(True)
        self.strip_btn.setHidden(True)
        self.close_btn.setHidden(True)
        self.cancel_btn.setShown(True)
        self.detail_btn.setShown(True)
        self.showBusyIcon.emit('hg-remove')

    def command_finished(self, ret):
        self.hideBusyIcon.emit('hg-remove')
        self.repo.decrementBusyCount()
        if ret is not 0 or self.cmd.outputShown():
            self.detail_btn.setChecked(True)
            self.close_btn.setShown(True)
            self.close_btn.setAutoDefault(True)
            self.close_btn.setFocus()
            self.cancel_btn.setHidden(True)
        else:
            self.accept()

    def command_canceling(self):
        self.cancel_btn.setDisabled(True)

def run(ui, *pats, **opts):
    rev = None
    if opts.get('rev'):
        rev = opts.get('rev')
    elif len(pats) == 1:
        rev = pats[0]
    return StripDialog(rev=rev, opts=opts)
