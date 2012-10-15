# tag.py - Tag dialog for TortoiseHg
#
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from tortoisehg.util import hglib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, cmdui, i18n

from PyQt4.QtCore import *
from PyQt4.QtGui import *

keep = i18n.keepgettext()

class TagDialog(QDialog):

    showMessage = pyqtSignal(QString)
    output = pyqtSignal(QString, QString)
    makeLogVisible = pyqtSignal(bool)

    def __init__(self, repo, tag='', rev='tip', parent=None, opts={}):
        super(TagDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() & \
                            ~Qt.WindowContextHelpButtonHint)

        self.repo = repo
        self.setWindowTitle(_('Tag - %s') % repo.displayname)
        self.setWindowIcon(qtlib.geticon('hg-tag'))

        # base layout box
        base = QVBoxLayout()
        base.setSpacing(0)
        base.setContentsMargins(*(0,)*4)
        base.setSizeConstraint(QLayout.SetFixedSize)
        self.setLayout(base)

        # main layout box
        box = QVBoxLayout()
        box.setSpacing(8)
        box.setContentsMargins(*(8,)*4)
        self.layout().addLayout(box)

        form = QFormLayout(fieldGrowthPolicy=QFormLayout.AllNonFixedFieldsGrow)
        box.addLayout(form)

        ctx = repo[rev]
        form.addRow(_('Revision:'), QLabel('%d (%s)' % (ctx.rev(), ctx)))
        self.rev = ctx.rev()

        ### tag combo
        self.tagCombo = QComboBox()
        self.tagCombo.setEditable(True)
        self.tagCombo.setEditText(hglib.tounicode(tag))
        self.tagCombo.currentIndexChanged.connect(self.updateStates)
        self.tagCombo.editTextChanged.connect(self.updateStates)
        form.addRow(_('Tag:'), self.tagCombo)

        self.tagRevLabel = QLabel('')
        form.addRow(_('Tagged:'), self.tagRevLabel)

        ### options
        expander = qtlib.ExpanderLabel(_('Options'), False)
        expander.expanded.connect(self.show_options)
        box.addWidget(expander)

        optbox = QVBoxLayout()
        optbox.setSpacing(6)
        box.addLayout(optbox)

        hbox = QHBoxLayout()
        hbox.setSpacing(0)
        optbox.addLayout(hbox)

        self.localCheckBox = QCheckBox(_('Local tag'))
        self.localCheckBox.toggled.connect(self.updateStates)
        self.replaceCheckBox = QCheckBox(_('Replace existing tag (-f/--force)'))
        self.replaceCheckBox.toggled.connect(self.updateStates)
        optbox.addWidget(self.localCheckBox)
        optbox.addWidget(self.replaceCheckBox)

        self.englishCheckBox = QCheckBox(_('Use English commit message'))
        engmsg = repo.ui.configbool('tortoisehg', 'engmsg', False)
        self.englishCheckBox.setChecked(engmsg)
        optbox.addWidget(self.englishCheckBox)

        self.customCheckBox = QCheckBox(_('Use custom commit message:'))
        self.customCheckBox.toggled.connect(self.customMessageToggle)
        self.customTextLineEdit = QLineEdit()
        optbox.addWidget(self.customCheckBox)
        optbox.addWidget(self.customTextLineEdit)

        ## bottom buttons
        BB = QDialogButtonBox
        bbox = QDialogButtonBox(BB.Close)
        bbox.rejected.connect(self.reject)
        self.addBtn = bbox.addButton(_('&Add'), BB.ActionRole)
        self.removeBtn = bbox.addButton(_('&Remove'), BB.ActionRole)
        box.addWidget(bbox)

        self.addBtn.clicked.connect(self.onAddTag)
        self.removeBtn.clicked.connect(self.onRemoveTag)

        ## horizontal separator
        self.sep = QFrame()
        self.sep.setFrameShadow(QFrame.Sunken)
        self.sep.setFrameShape(QFrame.HLine)
        base.addWidget(self.sep)

        ## status line
        self.status = qtlib.StatusLabel()
        self.status.setContentsMargins(4, 2, 4, 4)
        base.addWidget(self.status)

        self.cmd = cmdui.Runner(False, self)
        self.cmd.output.connect(self.output)
        self.cmd.makeLogVisible.connect(self.makeLogVisible)
        self.cmd.commandFinished.connect(self.onCommandFinished)

        repo.repositoryChanged.connect(self.refresh)
        self.customTextLineEdit.setDisabled(True)
        self.replaceCheckBox.setChecked(bool(opts.get('force')))
        self.localCheckBox.setChecked(bool(opts.get('local')))
        if not opts.get('local') and opts.get('message'):
            msg = hglib.tounicode(opts['message'])
            self.customCheckBox.setChecked(True)
            self.customTextLineEdit.setText(msg)
        self.clear_statue()
        self.show_options(False)
        self.tagCombo.setFocus()
        self.refresh()

    @pyqtSlot()
    def refresh(self):
        """ update display on dialog with recent repo data """
        cur = self.tagCombo.currentText()

        tags = list(self.repo.tags())
        tags.sort(reverse=True)
        self.tagCombo.clear()
        for tag in tags:
            if tag in ('tip', 'qbase', 'qtip', 'qparent'):
                continue
            self.tagCombo.addItem(hglib.tounicode(tag))
        if cur:
            self.tagCombo.setEditText(cur)
        else:
            self.tagCombo.clearEditText()
            self.updateStates()

    @pyqtSlot()
    def updateStates(self):
        """ update bottom button sensitives based on rev and tag """
        tagu = self.tagCombo.currentText()
        tag = hglib.fromunicode(tagu)

        # check tag existence
        if tag:
            exists = tag in self.repo.tags()
            if exists:
                tagtype = self.repo.tagtype(tag)
                islocal = 'local' == tagtype
                try:
                    ctx = self.repo[self.repo.tags()[tag]]
                    trev = ctx.rev()
                    thash = str(ctx)
                except:
                    trev, thash, local = 0, '????????', ''
                self.localCheckBox.setChecked(islocal)
                self.localCheckBox.setEnabled(False)
                local = islocal and _('local') or ''
                self.tagRevLabel.setText('%d (%s) %s' % (trev, thash, local))
                samerev = trev == self.rev
            else:
                islocal = self.localCheckBox.isChecked()
                self.localCheckBox.setEnabled(True)
                self.tagRevLabel.clear()

            force = self.replaceCheckBox.isChecked()
            custom = self.customCheckBox.isChecked()
            self.addBtn.setEnabled(not exists or (force and not samerev))
            if exists and not samerev:
                self.addBtn.setText(_('Move'))
            else:
                self.addBtn.setText(_('Add'))
            self.removeBtn.setEnabled(exists)
            self.englishCheckBox.setEnabled(not islocal)
            self.customCheckBox.setEnabled(not islocal)
            self.customTextLineEdit.setEnabled(not islocal and custom)
        else:
            self.addBtn.setEnabled(False)
            self.removeBtn.setEnabled(False)
            self.localCheckBox.setEnabled(False)
            self.englishCheckBox.setEnabled(False)
            self.customCheckBox.setEnabled(False)
            self.customTextLineEdit.setEnabled(False)
            self.tagRevLabel.clear()

    def customMessageToggle(self, checked):
        self.customTextLineEdit.setEnabled(checked)
        if checked:
            self.customTextLineEdit.setFocus()

    def show_options(self, visible):
        self.localCheckBox.setVisible(visible)
        self.replaceCheckBox.setVisible(visible)
        self.englishCheckBox.setVisible(visible)
        self.customCheckBox.setVisible(visible)
        self.customTextLineEdit.setVisible(visible)

    def set_status(self, text, icon):
        self.status.setShown(True)
        self.sep.setShown(True)
        self.status.set_status(text, icon)
        self.showMessage.emit(text)

    def clear_statue(self):
        self.status.setHidden(True)
        self.sep.setHidden(True)

    def onCommandFinished(self, ret):
        if ret == 0:
            self.finishfunc()

    def onAddTag(self):
        if self.cmd.core.running():
            self.set_status(_('Repository command still running'), False)
            return

        tagu = self.tagCombo.currentText()
        tag = hglib.fromunicode(tagu)
        local = self.localCheckBox.isChecked()
        force = self.replaceCheckBox.isChecked()
        english = self.englishCheckBox.isChecked()
        if self.customCheckBox.isChecked():
            message = self.customTextLineEdit.text()
        else:
            message = None

        exists = tag in self.repo.tags()
        if exists and not force:
            self.set_status(_("Tag '%s' already exists") % tagu, False)
            return
        if not local:
            parents = self.repo.parents()
            if len(parents) > 1:
                self.set_status(_('uncommitted merge'), False)
                return
            p1 = parents[0]
            if not force and p1.node() not in self.repo._branchheads:
                self.set_status(_('not at a branch head (use force)'), False)
                return
            if not message:
                ctx = self.repo[self.rev]
                if exists:
                    origctx = self.repo[self.repo.tags()[tag]]
                    msgset = keep._('Moved tag %s to changeset %s' \
                        ' (from changeset %s)')
                    message = (english and msgset['id'] or msgset['str']) \
                       % (tagu, str(ctx), str(origctx))
                else:
                    msgset = keep._('Added tag %s for changeset %s')
                    message = (english and msgset['id'] or msgset['str']) \
                               % (tagu, str(ctx))
            message = hglib.fromunicode(message)

        def finished():
            if exists:
                self.set_status(_("Tag '%s' has been moved") % tagu, True)
            else:
                self.set_status(_("Tag '%s' has been added") % tagu, True)

        user = qtlib.getCurrentUsername(self, self.repo)
        if not user:
            return
        cmd = ['tag', '--repository', self.repo.root, '--rev', str(self.rev),
               '--user', user]
        if local:
            cmd.append('--local')
        else:
            cmd.append('--message=%s' % message)
        if force:
            cmd.append('--force')
        cmd.append(tag)
        self.finishfunc = finished
        self.cmd.run(cmd)

    def onRemoveTag(self):
        if self.cmd.core.running():
            self.set_status(_('Repository command still running'), False)
            return

        tagu = self.tagCombo.currentText()
        tag = hglib.fromunicode(tagu)
        local = self.localCheckBox.isChecked()
        force = self.replaceCheckBox.isChecked()
        english = self.englishCheckBox.isChecked()
        if self.customCheckBox.isChecked():
            message = self.customTextLineEdit.text()
        else:
            message = None

        tagtype = self.repo.tagtype(tag)
        if local:
            if tagtype != 'local':
                self.set_status(_("tag '%s' is not a local tag") % tagu, False)
                return
        else:
            if tagtype != 'global':
                self.set_status(_("tag '%s' is not a global tag") % tagu, False)
                return
            parents = self.repo.parents()
            if len(parents) > 1:
                self.set_status(_('uncommitted merge'), False)
                return
            p1 = parents[0]
            if not force and p1.node() not in self.repo._branchheads:
                self.set_status(_('not at a branch head (use force)'), False)
                return
            if not message:
                msgset = keep._('Removed tag %s')
                message = (english and msgset['id'] or msgset['str']) % tagu
            message = hglib.fromunicode(message)

        def finished():
            self.set_status(_("Tag '%s' has been removed") % tagu, True)

        cmd = ['tag', '--repository', self.repo.root, '--remove']
        if local:
            cmd.append('--local')
        else:
            cmd.append('--message=%s' % message)
        cmd.append(tag)
        self.finishfunc = finished
        self.cmd.run(cmd)

    def reject(self):
        if self.cmd.core.running():
            self.set_status(_('Repository command still running'), False)
            return

        # prevent signals from reaching deleted objects
        self.repo.repositoryChanged.disconnect(self.refresh)
        super(TagDialog, self).reject()

def run(ui, *pats, **opts):
    kargs = {}
    tag = len(pats) > 0 and pats[0] or None
    if tag:
        kargs['tag'] = tag
    rev = opts.get('rev')
    if rev:
        kargs['rev'] = rev
    from tortoisehg.util import paths
    from tortoisehg.hgqt import thgrepo
    repo = thgrepo.repository(ui, path=paths.find_root())
    return TagDialog(repo, opts=opts, **kargs)
