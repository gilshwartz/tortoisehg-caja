# matching.py - Find similar (matching) revisions dialog for TortoiseHg
#
# Copyright 2012 Angel Ezquerra <angel.ezquerra@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from mercurial import error, revset

from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import cmdui, csinfo, qtlib, thgrepo, resolve

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class MatchDialog(QDialog):

    revmatch = pyqtSignal(QString)

    def __init__(self, repo, rev=None, parent=None, opts={}):
        super(MatchDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() & \
                            ~Qt.WindowContextHelpButtonHint)

        self.revsetexpression = ''
        self._finished = False
        self.repo = repo

        # base layout box
        box = QVBoxLayout()
        box.setSpacing(6)

        ## main layout grid
        self.grid = QGridLayout()
        self.grid.setSpacing(6)
        box.addLayout(self.grid)

        ### matched revision combo
        self.rev_combo = combo = QComboBox()
        combo.setEditable(True)
        self.grid.addWidget(QLabel(_('Find revisions matching fields of:')), 0, 0)
        self.grid.addWidget(combo, 0, 1)

        # Give the combo box a minimum width that will ensure that the dialog is
        # large enough to fit the additional progress bar that will appear when
        # updating subrepositories.
        combo.setMinimumWidth(450)

        if rev is None:
            rev = self.repo.dirstate.branch()
        else:
            rev = str(rev)
        combo.addItem(hglib.tounicode(rev))
        combo.setCurrentIndex(0)
        # make it easy to match the workding directory parent revision
        combo.addItem(hglib.tounicode('.'))

        tags = list(self.repo.tags()) + repo._bookmarks.keys()
        tags.sort(reverse=True)
        for tag in tags:
            combo.addItem(hglib.tounicode(tag))

        ### matched revision info
        self.rev_to_match_info_text = QLabel()
        self.rev_to_match_info_text.setShown(False)
        style = csinfo.panelstyle(contents=('cset', 'branch', 'close', 'user',
               'dateage', 'parents', 'children', 'tags', 'graft', 'transplant',
               'p4', 'svn', 'converted'), selectable=True,
               expandable=True)
        factory = csinfo.factory(self.repo, style=style)
        self.rev_to_match_info = factory()
        self.rev_to_match_info_lbl = QLabel(_('Revision to Match:'))
        self.grid.addWidget(self.rev_to_match_info_lbl, 1, 0, Qt.AlignLeft | Qt.AlignTop)
        self.grid.addWidget(self.rev_to_match_info, 1, 1)
        self.grid.addWidget(self.rev_to_match_info_text, 1, 1)

        ### fields that will be matched
        self.optbox = QVBoxLayout()
        self.optbox.setSpacing(6)
        expander = qtlib.ExpanderLabel(_('Fields to match:'), False)
        expander.expanded.connect(self.show_options)
        row = self.grid.rowCount()
        self.grid.addWidget(expander, row, 0, Qt.AlignLeft | Qt.AlignTop)
        self.grid.addLayout(self.optbox, row, 1)

        self.summary_chk = QCheckBox(_('Summary (first description line)'))
        self.description_chk = QCheckBox(_('Description'))
        self.desc_btngroup = QButtonGroup()
        self.desc_btngroup.setExclusive(False)
        self.desc_btngroup.addButton(self.summary_chk)
        self.desc_btngroup.addButton(self.description_chk)
        self.desc_btngroup.buttonClicked.connect(self._selectSummaryOrDescription)

        self.author_chk = QCheckBox(_('Author'))
        self.date_chk = QCheckBox(_('Date'))
        self.files_chk = QCheckBox(_('Files'))
        self.diff_chk = QCheckBox(_('Diff contents'))
        self.substate_chk = QCheckBox(_('Subrepo states'))
        self.branch_chk = QCheckBox(_('Branch'))
        self.parents_chk = QCheckBox(_('Parents'))
        self.phase_chk = QCheckBox(_('Phase'))
        self._hideable_chks = (self.branch_chk, self.phase_chk, self.parents_chk,)

        has_diff_matching = hglib.hgversion >= "2.3"

        self.optbox.addWidget(self.summary_chk)
        self.optbox.addWidget(self.description_chk)
        self.optbox.addWidget(self.author_chk)
        self.optbox.addWidget(self.date_chk)
        self.optbox.addWidget(self.files_chk)
        if has_diff_matching:
            # if mercurial does not have a "diff" matching mode,
            # we simply "hide" the diff checkbox,
            # to make the saveSettings() method simpler
            self.optbox.addWidget(self.diff_chk)
        self.optbox.addWidget(self.substate_chk)
        self.optbox.addWidget(self.branch_chk)
        self.optbox.addWidget(self.parents_chk)
        self.optbox.addWidget(self.phase_chk)

        s = QSettings()

        #### Persisted Options
        self.summary_chk.setChecked(s.value('matching/summary', False).toBool())
        self.description_chk.setChecked(s.value('matching/description', True).toBool())
        self.author_chk.setChecked(s.value('matching/author', True).toBool())
        self.branch_chk.setChecked(s.value('matching/branch', False).toBool())
        self.date_chk.setChecked(s.value('matching/date', True).toBool())
        self.files_chk.setChecked(s.value('matching/files', False).toBool())
        self.diff_chk.setChecked(s.value('matching/diff', False).toBool())
        self.parents_chk.setChecked(s.value('matching/parents', False).toBool())
        self.phase_chk.setChecked(s.value('matching/phase', False).toBool())
        self.substate_chk.setChecked(s.value('matching/substate', False).toBool())

        ## bottom buttons
        buttons = QDialogButtonBox()
        self.close_btn = buttons.addButton(QDialogButtonBox.Close)
        self.close_btn.clicked.connect(self.reject)
        self.close_btn.setAutoDefault(False)
        self.match_btn = buttons.addButton(_('&Match'),
                                            QDialogButtonBox.ActionRole)
        self.match_btn.clicked.connect(self.match)
        box.addWidget(buttons)

        # signal handlers
        self.rev_combo.editTextChanged.connect(self.update_info)

        # dialog setting
        self.setLayout(box)
        self.layout().setSizeConstraint(QLayout.SetFixedSize)
        self.setWindowTitle(_('Find matches - %s') % self.repo.displayname)
        self.setWindowIcon(qtlib.geticon('hg-update'))

        # prepare to show
        self.update_info()
        if not self.match_btn.isEnabled():
            self.rev_combo.lineEdit().selectAll()  # need to change rev

        # expand options if a hidden one is checked
        hiddenOptionsChecked = self.hiddenSettingIsChecked()
        self.show_options(hiddenOptionsChecked)
        expander.set_expanded(hiddenOptionsChecked)

    ### Private Methods ###
    def hiddenSettingIsChecked(self):
        for chk in self._hideable_chks:
            if chk.isChecked():
                return True
        return False

    def saveSettings(self):
        s = QSettings()
        s.setValue('matching/summary', self.summary_chk.isChecked())
        s.setValue('matching/description', self.description_chk.isChecked())
        s.setValue('matching/author', self.author_chk.isChecked())
        s.setValue('matching/branch', self.branch_chk.isChecked())
        s.setValue('matching/date', self.date_chk.isChecked())
        s.setValue('matching/files', self.files_chk.isChecked())
        s.setValue('matching/diff', self.diff_chk.isChecked())
        s.setValue('matching/parents', self.parents_chk.isChecked())
        s.setValue('matching/phase', self.phase_chk.isChecked())
        s.setValue('matching/substate', self.substate_chk.isChecked())

    def update_info(self, *args):
        def set_csinfo_mode(mode):
            """Show the csinfo widget or the info text label"""
            # hide first, then show
            if mode:
                self.rev_to_match_info_text.setShown(False)
                self.rev_to_match_info.setShown(True)
            else:
                self.rev_to_match_info.setShown(False)
                self.rev_to_match_info_text.setShown(True)
        def csinfo_update(ctx):
            self.rev_to_match_info.update(ctx)
            set_csinfo_mode(True)
        def csinfo_set_text(text):
            self.rev_to_match_info_text.setText(text)
            set_csinfo_mode(False)

        self.rev_to_match_info_lbl.setText(_('Revision to Match:'))
        new_rev = hglib.fromunicode(self.rev_combo.currentText())
        if new_rev.lower() == 'null':
            self.match_btn.setEnabled(True)
            return
        try:
            csinfo_update(self.repo[new_rev])
            return
        except (error.LookupError, error.RepoLookupError, error.RepoError):
            pass

        # If we get this far, assume we are matching a revision set
        validrevset = False
        try:
            func = revset.match(self.repo.ui, new_rev)
            rset = [c for c in func(self.repo, range(len(self.repo)))]
            if len(rset) > 1:
                self.rev_to_match_info_lbl.setText(_('Revisions to Match:'))
                csinfo_set_text(_('Match any of <b><i>%d</i></b> revisions') \
                    % len(rset))
            else:
                self.rev_to_match_info_lbl.setText(_('Revision to Match:'))
                csinfo_update(rset[0])
            validrevset = True
        except (error.LookupError, error.RepoLookupError):
            csinfo_set_text(_('<b>Unknown revision!</b>'))
        except (error.ParseError):
            csinfo_set_text(_('<b>Parse Error!</b>'))
        if validrevset:
            self.match_btn.setEnabled(True)
        else:
            self.match_btn.setDisabled(True)

    def match(self):
        self.saveSettings()
        fieldmap = {
            'summary': self.summary_chk,
            'description': self.description_chk,
            'author': self.author_chk,
            'branch': self.branch_chk,
            'date': self.date_chk,
            'files': self.files_chk,
            'diff': self.diff_chk,
            'parents': self.parents_chk,
            'phase': self.phase_chk,
            'substate': self.substate_chk,
        }
        fields = []
        for (field, chk) in fieldmap.items():
            if chk.isChecked():
                fields.append(field)

        rev = hglib.fromunicode(self.rev_combo.currentText())
        if fields:
            self.revsetexpression = "matching(%s, '%s')" % (rev, ' '.join(fields))
        else:
            self.revsetexpression = "matching(%s)" % (rev)
        self.accept()

    ### Signal Handlers ###

    def show_options(self, visible):
        for chk in self._hideable_chks:
            chk.setShown(visible)

    @pyqtSlot(QAbstractButton)
    def _selectSummaryOrDescription(self, btn):
        # Uncheck all other buttons
        for b in self.desc_btngroup.buttons():
            if not (b is btn):
                b.setChecked(False)
