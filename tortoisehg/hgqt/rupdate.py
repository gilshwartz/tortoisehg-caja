# Copyright 2011 Ryan Seto <mr.werewolf@gmail.com>
#
# rupdate.py - Remote Update dialog for TortoiseHg
#
# This dialog lets users update a remote ssh repository.
#
# Requires a copy of the rupdate plugin found at:
#     http://bitbucket.org/MrWerewolf/rupdate
#
# Also, enable the plugin with the following in mercurial.ini:
#
# [extensions]
# rupdate = /path/to/rupdate
#
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import error, node, merge as mergemod

from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import cmdui, csinfo, thgrepo, resolve, hgrcutil
from tortoisehg.hgqt.update import UpdateDialog

class rUpdateDialog(UpdateDialog):

    def __init__(self, repo, rev=None, parent=None, opts={}):
        super(rUpdateDialog, self).__init__(repo, rev, parent, opts)

        # Get configured paths
        self.paths = {}
        fn = self.repo.join('hgrc')
        fn, cfg = hgrcutil.loadIniFile([fn], self)
        if 'paths' in cfg:
            for alias in cfg['paths']:
                self.paths[ alias ] = cfg['paths'][alias]

        ### target path combo
        self.path_combo = pcombo = QComboBox()
        pcombo.setEditable(True)

        for alias in self.paths:
            pcombo.addItem(hglib.tounicode(self.paths[alias]))

        ### shift existing items down a row.
        for i in range(self.grid.count()-1, -1, -1):
            row, col, rowSp, colSp = self.grid.getItemPosition(i)
            item = self.grid.takeAt(i)
            self.grid.removeItem(item)
            self.grid.addItem(item, row + 1, col, rowSp, colSp, item.alignment())

        ### add target path combo to grid
        self.grid.addWidget(QLabel(_('Location:')), 0, 0)
        self.grid.addWidget(pcombo, 0, 1)

        ### Options
        self.discard_chk.setText(_('Discard remote changes, no backup '
                                       '(-C/--clean)'))
        self.push_chk = QCheckBox(_('Perform a push before updating'
                                        ' (-p/--push)'))
        self.newbranch_chk = QCheckBox(_('Allow pushing new branches'
                                        ' (--new-branch)'))
        self.force_chk = QCheckBox(_('Force push to remote location'
                                        ' (-f/--force)'))
        self.optbox.removeWidget(self.showlog_chk)
        self.optbox.addWidget(self.push_chk)
        self.optbox.addWidget(self.newbranch_chk)
        self.optbox.addWidget(self.force_chk)
        self.optbox.addWidget(self.showlog_chk)

        #### Persisted Options
        self.push_chk.setChecked(
            QSettings().value('rupdate/push', False).toBool())
        
        self.newbranch_chk.setChecked(
            QSettings().value('rupdate/newbranch', False).toBool())

        self.showlog_chk.setChecked(
            QSettings().value('rupdate/showlog', False).toBool())

        # prepare to show
        self.push_chk.setHidden(True)
        self.newbranch_chk.setHidden(True)
        self.force_chk.setHidden(True)
        self.showlog_chk.setHidden(True)
        self.update_info()

        # expand options if a hidden one is checked
        self.show_options(self.hiddenSettingIsChecked())

    ### Private Methods ###

    def hiddenSettingIsChecked(self):
        # This might be called from the super class before all options are built.
        # So, we need to check to make sure these options exist first.
        if (getattr(self, "push_chk", None) and self.push_chk.isChecked()
            ) or (getattr(self, "newbranch_chk", None) and self.newbranch_chk.isChecked()
            ) or (getattr(self, "force_chk", None) and self.force_chk.isChecked()
            ) or (getattr(self, "showlog_chk", None) and self.showlog_chk.isChecked()):
            return True
        else:
            return False

    def saveSettings(self):
        QSettings().setValue('rupdate/push', self.push_chk.isChecked())
        QSettings().setValue('rupdate/newbranch', self.newbranch_chk.isChecked())
        QSettings().setValue('rupdate/showlog', self.showlog_chk.isChecked())

    def update_info(self):
        super(rUpdateDialog, self).update_info()
        
        # Keep update button enabled.
        self.update_btn.setDisabled(False)

    def update(self):
        self.saveSettings()
        cmdline = ['rupdate']

        if self.discard_chk.isChecked():
            cmdline.append('--clean')
        if self.push_chk.isChecked():
            cmdline.append('--push')
        if self.newbranch_chk.isChecked():
            cmdline.append('--new-branch')
        if self.force_chk.isChecked():
            cmdline.append('--force')

        dest = hglib.fromunicode(self.path_combo.currentText())
        cmdline.append('-d')
        cmdline.append(dest)

        # Refer to the revision by the short hash.
        rev = hglib.fromunicode(self.rev_combo.currentText())
        revShortHash = node.short(self.repo[rev].node())
        cmdline.append(revShortHash)

        # start updating
        self.repo.incrementBusyCount()
        self.cmd.run(cmdline)

    ### Signal Handlers ###

    def show_options(self, visible):
        # Like hiddenSettingIsChecked(), need to make sure these options exist first.
        if getattr(self, "push_chk", None): self.push_chk.setShown(visible)
        if getattr(self, "newbranch_chk", None): self.newbranch_chk.setShown(visible)
        if getattr(self, "force_chk", None): self.force_chk.setShown(visible)
        if getattr(self, "showlog_chk", None): self.showlog_chk.setShown(visible)

    def command_started(self):
        super(rUpdateDialog, self).command_started()
        self.update_btn.setHidden(False)

def run(ui, *pats, **opts):
    from tortoisehg.util import paths
    repo = thgrepo.repository(ui, path=paths.find_root())
    rev = None
    if opts.get('rev'):
        rev = opts.get('rev')
    elif len(pats) == 1:
        rev = pats[0]
    return rUpdateDialog(repo, rev, None, opts)
