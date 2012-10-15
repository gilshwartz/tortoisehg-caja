# thgimport.py - Import dialog for TortoiseHg
#
# Copyright 2009 Yuki KODAMA <endflow.net@gmail.com>
# Copyright 2010 David Wilhelm <dave@jumbledpile.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import shutil
import tempfile

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import hg, ui, error

from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import cmdui, cslist, qtlib, thgrepo, commit

_FILE_FILTER = "%s;;%s" % (_("Patch files (*.diff *.patch)"),
                           _("All files (*)"))

# TODO: handle --mq options from command line or MQ widget

class ImportDialog(QDialog):
    """Dialog to import patches"""
    patchImported = pyqtSignal()

    def __init__(self, repo, parent, **opts):
        super(ImportDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags()
                            & ~Qt.WindowContextHelpButtonHint
                            | Qt.WindowMaximizeButtonHint)
        self.setWindowIcon(qtlib.geticon('hg-import'))

        self.tempfiles = []
        self.repo = repo

        # base layout box
        box = QVBoxLayout()
        box.setSpacing(6)

        ## main layout grid
        self.grid = grid = QGridLayout()
        grid.setSpacing(6)
        box.addLayout(grid)

        ### source input
        self.src_combo = QComboBox()
        self.src_combo.setEditable(True)
        self.src_combo.setMinimumWidth(310)
        self.file_btn = QPushButton(_('Browse...'))
        self.file_btn.setAutoDefault(False)
        self.file_btn.clicked.connect(self.browsefiles)
        self.dir_btn = QPushButton(_('Browse Directory...'))
        self.dir_btn.setAutoDefault(False)
        self.dir_btn.clicked.connect(self.browsedir)
        self.clip_btn = QPushButton(_('Import from Clipboard'))
        self.clip_btn.setAutoDefault(False)
        self.clip_btn.clicked.connect(self.getcliptext)
        grid.addWidget(QLabel(_('Source:')), 0, 0)
        grid.addWidget(self.src_combo, 0, 1)
        srcbox = QHBoxLayout()
        srcbox.addWidget(self.file_btn)
        srcbox.addWidget(self.dir_btn)
        srcbox.addWidget(self.clip_btn)
        grid.addLayout(srcbox, 1, 1)
        self.p0chk = QCheckBox(_('Do not strip paths (-p0), '
                                 'required for SVN patches'))
        grid.addWidget(self.p0chk, 2, 1, Qt.AlignLeft)

        ### patch list
        self.cslist = cslist.ChangesetList(self.repo)
        self.cslistrow = cslistrow = 4
        self.cslistcol = cslistcol = 1
        grid.addWidget(self.cslist, cslistrow, cslistcol,
                       Qt.AlignLeft | Qt.AlignTop)
        grid.addWidget(QLabel(_('Preview:')), 3, 0, Qt.AlignLeft | Qt.AlignTop)
        statbox = QHBoxLayout()
        self.status = QLabel("")
        statbox.addWidget(self.status)
        self.targetcombo = QComboBox()
        self.targetcombo.currentIndexChanged.connect(self.updatestatus)
        self.targetcombo.addItem(_('Repository'))
        self.targetcombo.addItem(_('Shelf'))
        self.targetcombo.addItem(_('Working Directory'))
        cur = self.repo.getcurrentqqueue()
        if cur:
            self.targetcombo.addItem(hglib.tounicode(cur))
        statbox.addWidget(self.targetcombo)
        grid.addItem(statbox, 3, 1)

        ## command widget
        self.cmd = cmdui.Widget(True, False, self)
        self.cmd.commandStarted.connect(self.command_started)
        self.cmd.commandFinished.connect(self.command_finished)
        self.cmd.commandCanceling.connect(self.command_canceling)
        grid.setRowStretch(cslistrow, 1)
        grid.setColumnStretch(cslistcol, 1)
        box.addWidget(self.cmd)

        self.stlabel = QLabel(_('Checking working directory status...'))
        self.stlabel.linkActivated.connect(self.commitActivated)
        box.addWidget(self.stlabel)
        QTimer.singleShot(0, self.checkStatus)

        ## bottom buttons
        buttons = QDialogButtonBox()
        self.cancel_btn = buttons.addButton(QDialogButtonBox.Cancel)
        self.cancel_btn.clicked.connect(self.cancel_clicked)
        self.close_btn = buttons.addButton(QDialogButtonBox.Close)
        self.close_btn.clicked.connect(self.reject)
        self.close_btn.setAutoDefault(False)
        self.import_btn = buttons.addButton(_('&Import'),
                                            QDialogButtonBox.ActionRole)
        self.import_btn.clicked.connect(self.thgimport)
        self.detail_btn = buttons.addButton(_('Detail'),
                                            QDialogButtonBox.ResetRole)
        self.detail_btn.setAutoDefault(False)
        self.detail_btn.setCheckable(True)
        self.detail_btn.toggled.connect(self.detail_toggled)
        box.addWidget(buttons)

        # signal handlers
        self.src_combo.editTextChanged.connect(lambda *a: self.preview())
        self.src_combo.lineEdit().returnPressed.connect(self.thgimport)
        self.p0chk.toggled.connect(lambda *a: self.preview())

        # dialog setting
        self.setLayout(box)
        self.layout().setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.setWindowTitle(_('Import - %s') % self.repo.displayname)
        #self.setWindowIcon(qtlib.geticon('import'))

        # prepare to show
        self.src_combo.lineEdit().selectAll()
        self.cslist.setHidden(False)
        self.cmd.setHidden(True)
        self.cancel_btn.setHidden(True)
        self.detail_btn.setHidden(True)
        self.p0chk.setHidden(False)
        self.preview()

    ### Private Methods ###

    def commitActivated(self):
        dlg = commit.CommitDialog(self.repo, [], {}, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()
        self.checkStatus()

    def checkStatus(self):
        self.repo.dirstate.invalidate()
        wctx = self.repo[None]
        M, A, R = wctx.status()[:3]
        if M or A or R:
            text = _('Working directory is not clean!  '
                     '<a href="view">View changes...</a>')
            self.stlabel.setText(text)
        else:
            self.stlabel.clear()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Refresh):
            self.checkStatus()
        else:
            return super(ImportDialog, self).keyPressEvent(event)

    def resizeEvent(self, event):
        w = self.grid.cellRect(self.cslistrow, self.cslistcol).width()
        h = self.grid.cellRect(self.cslistrow, self.cslistcol).height()
        self.cslist.resize(w, h)

    def browsefiles(self):
        caption = _("Select patches")
        filelist = QFileDialog.getOpenFileNames(parent=self, caption=caption,
                                                directory=self.repo.root,
                                                filter=_FILE_FILTER)
        if filelist:
            # Qt file browser uses '/' in paths, even on Windows.
            nl = QStringList([QDir.toNativeSeparators(x) for x in filelist])
            self.src_combo.setEditText(nl.join(os.pathsep))
            self.src_combo.setFocus()

    def browsedir(self):
        caption = _("Select Directory containing patches")
        path = QFileDialog.getExistingDirectory(parent=self,
                                                directory=self.repo.root,
                                                caption=caption)
        if path:
            self.src_combo.setEditText(QDir.toNativeSeparators(path))
            self.src_combo.setFocus()

    def getcliptext(self):
        text = hglib.fromunicode(QApplication.clipboard().text())
        if not text:
            return
        filename = self.writetempfile(text)
        curtext = self.src_combo.currentText()
        if curtext:
            self.src_combo.setEditText(curtext + os.pathsep + filename)
        else:
            self.src_combo.setEditText(filename)

    def updatestatus(self):
        items = self.cslist.curitems
        count = items and len(items) or 0
        countstr = qtlib.markup(_("%s patches") % count, weight='bold')
        if count:
            self.targetcombo.setVisible(True)
            text = _('%s will be imported to ') % countstr
        else:
            self.targetcombo.setVisible(False)
            text = qtlib.markup(_('Nothing to import'), weight='bold',
                                fg='red')
        self.status.setText(text)

    def preview(self):
        patches = self.getfilepaths()
        if not patches:
            self.cslist.clear()
            self.import_btn.setDisabled(True)
        else:
            self.cslist.update([os.path.abspath(p) for p in patches])
            self.import_btn.setEnabled(True)
        self.updatestatus()

    def getfilepaths(self):
        src = hglib.fromunicode(self.src_combo.currentText())
        if not src:
            return []
        files = []
        for path in src.split(os.pathsep):
            path = path.strip('\r\n\t ')
            if not os.path.exists(path) or path in files:
                continue
            if os.path.isfile(path):
                files.append(path)
            elif os.path.isdir(path):
                entries = os.listdir(path)
                for entry in sorted(entries):
                    _file = os.path.join(path, entry)
                    if os.path.isfile(_file) and not _file in files:
                        files.append(_file)
        return files

    def setfilepaths(self, paths):
        """Set file paths of patches to import; paths is in locale encoding"""
        self.src_combo.setEditText(
            os.pathsep.join(hglib.tounicode(p) for p in paths))

    def thgimport(self):
        if self.cslist.curitems is None:
            return
        idx = self.targetcombo.currentIndex()
        if idx == 1:
            # import to shelf
            existing = self.repo.thgshelves()
            if not os.path.exists(self.repo.shelfdir):
                os.mkdir(self.repo.shelfdir)
            for file in self.cslist.curitems:
                shutil.copy(file, self.repo.shelfdir)
            return
        hmcmd = ('import', 'copy', 'import --no-commit', 'qimport')[idx]
        cmdline = hmcmd.split(' ') + ['--repository', self.repo.root]
        if self.p0chk.isChecked():
            cmdline.append('-p0')
        cmdline.extend(['--verbose', '--'])
        cmdline.extend(self.cslist.curitems)

        self.repo.incrementBusyCount()
        self.cmd.run(cmdline)

    def writetempfile(self, text):
        fd, filename = tempfile.mkstemp(suffix='.patch', prefix='thg-import-')
        try:
            os.write(fd, text)
        finally:
            os.close(fd)
        self.tempfiles.append(filename)
        return filename

    def unlinktempfiles(self):
        for path in self.tempfiles:
            os.unlink(path)

    ### Override Handlers ###

    def accept(self):
        self.unlinktempfiles()
        super(ImportDialog, self).accept()

    def reject(self):
        self.unlinktempfiles()
        super(ImportDialog, self).reject()

    ### Signal Handlers ###

    def cancel_clicked(self):
        self.cmd.cancel()
        self.reject()

    def detail_toggled(self, checked):
        self.cmd.setShowOutput(checked)

    def command_started(self):
        self.cmd.setShown(True)
        self.import_btn.setHidden(True)
        self.close_btn.setHidden(True)
        self.cancel_btn.setShown(True)
        self.detail_btn.setShown(True)

    def command_finished(self, ret):
        self.repo.decrementBusyCount()
        if ret == 0:
            self.patchImported.emit()
        if ret is not 0 or self.cmd.outputShown():
            self.detail_btn.setChecked(True)
            self.close_btn.setShown(True)
            self.close_btn.setAutoDefault(True)
            self.close_btn.setFocus()
            self.cancel_btn.setHidden(True)
            self.import_btn.setHidden(False)
        else:
            self.accept()

    def command_canceling(self):
        self.cancel_btn.setDisabled(True)

def run(ui, *pats, **opts):
    repo = thgrepo.repository(ui, path=paths.find_root())
    dlg = ImportDialog(repo, None, **opts)
    dlg.setfilepaths(pats)
    return dlg
