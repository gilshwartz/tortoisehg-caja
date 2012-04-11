# revdetails.py - TortoiseHg revision details widget
#
# Copyright (C) 2007-2010 Logilab. All rights reserved.
# Copyright (C) 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.

import os

from mercurial import commands, util

from tortoisehg.util import hglib

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt.filelistmodel import HgFileListModel
from tortoisehg.hgqt.filelistview import HgFileListView
from tortoisehg.hgqt.fileview import HgFileView
from tortoisehg.hgqt.revpanel import RevPanelWidget
from tortoisehg.hgqt.filedialogs import FileLogDialog, FileDiffDialog
from tortoisehg.hgqt import thgrepo, qtlib, qscilib, visdiff, revert

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class RevDetailsWidget(QWidget, qtlib.TaskWidget):

    showMessage = pyqtSignal(QString)
    linkActivated = pyqtSignal(unicode)
    grepRequested = pyqtSignal(unicode, dict)
    revisionSelected = pyqtSignal(int)
    updateToRevision = pyqtSignal(int)

    filecontextmenu = None
    subrepocontextmenu = None

    def __init__(self, repo, parent):
        QWidget.__init__(self, parent)

        self.repo = repo
        self.ctx = repo[None]
        self.splitternames = []
        self._diff_dialogs = {}
        self._nav_dialogs = {}

        self.setupUi()
        self.createActions()
        self.setupModels()

        self._deschtmlize = qtlib.descriptionhtmlizer(repo.ui)
        repo.configChanged.connect(self._updatedeschtmlizer)

    def setRepo(self, repo):
        self.repo = repo
        self.fileview.setRepo(repo)
        self.filelist.setRepo(repo)

    def setupUi(self):
        SP = QSizePolicy
        sp = SP(SP.Preferred, SP.Expanding)
        sp.setHorizontalStretch(0)
        sp.setVerticalStretch(0)
        sp.setHeightForWidth(self.sizePolicy().hasHeightForWidth())
        self.setSizePolicy(sp)

        # + basevbox -------------------------------------------------------+
        # |+ filelistsplit ........                                         |
        # | + filelistframe (vbox)    | + panelframe (vbox)                 |
        # |  + filelisttbar           |  + revpanel                         |
        # +---------------------------+-------------------------------------+
        # |  + filelist               |  + messagesplitter                  |
        # |                           |  :+ message                         |
        # |                           |  :----------------------------------+
        # |                           |   + fileview                        |
        # +---------------------------+-------------------------------------+

        basevbox = QVBoxLayout(self)
        basevbox.setSpacing(0)
        basevbox.setMargin(0)
        basevbox.setContentsMargins(2, 2, 2, 2)

        self.filelistsplit = QSplitter(self)
        basevbox.addWidget(self.filelistsplit)

        self.splitternames.append('filelistsplit')

        sp = SP(SP.Expanding, SP.Expanding)
        sp.setHorizontalStretch(0)
        sp.setVerticalStretch(0)
        sp.setHeightForWidth(self.filelistsplit.sizePolicy().hasHeightForWidth())
        self.filelistsplit.setSizePolicy(sp)
        self.filelistsplit.setOrientation(Qt.Horizontal)
        self.filelistsplit.setChildrenCollapsible(False)

        self.filelisttbar = QToolBar(_('File List Toolbar'))
        self.filelisttbar.setIconSize(QSize(16,16))
        self.filelist = HgFileListView(self.repo, self, True)
        self.filelist.linkActivated.connect(self.linkActivated)
        self.filelist.setContextMenuPolicy(Qt.CustomContextMenu)
        self.filelist.customContextMenuRequested.connect(self.menuRequest)
        self.filelist.doubleClicked.connect(self.onDoubleClick)

        self.filelistframe = QFrame(self.filelistsplit)
        sp = SP(SP.Preferred, SP.Preferred)
        sp.setHorizontalStretch(3)
        sp.setVerticalStretch(0)
        sp.setHeightForWidth(
            self.filelistframe.sizePolicy().hasHeightForWidth())
        self.filelistframe.setSizePolicy(sp)
        self.filelistframe.setFrameShape(QFrame.NoFrame)
        vbox = QVBoxLayout()
        vbox.setSpacing(0)
        vbox.setMargin(0)
        vbox.addWidget(self.filelisttbar)
        vbox.addWidget(self.filelist)
        self.filelistframe.setLayout(vbox)

        self.fileviewframe = QFrame(self.filelistsplit)
        sp = SP(SP.Preferred, SP.Preferred)
        sp.setHorizontalStretch(7)
        sp.setVerticalStretch(0)
        sp.setHeightForWidth(
            self.fileviewframe.sizePolicy().hasHeightForWidth())
        self.fileviewframe.setSizePolicy(sp)
        self.fileviewframe.setFrameShape(QFrame.NoFrame)

        vbox = QVBoxLayout(self.fileviewframe)
        vbox.setSpacing(0)
        vbox.setSizeConstraint(QLayout.SetDefaultConstraint)
        vbox.setMargin(0)
        panelframevbox = vbox

        self.messagesplitter = QSplitter(self.fileviewframe)
        self.splitternames.append('messagesplitter')
        sp = SP(SP.Preferred, SP.Expanding)
        sp.setHorizontalStretch(0)
        sp.setVerticalStretch(0)
        sp.setHeightForWidth(self.messagesplitter.sizePolicy().hasHeightForWidth())
        self.messagesplitter.setSizePolicy(sp)
        self.messagesplitter.setMinimumSize(QSize(50, 50))
        self.messagesplitter.setFrameShape(QFrame.NoFrame)
        self.messagesplitter.setLineWidth(0)
        self.messagesplitter.setMidLineWidth(0)
        self.messagesplitter.setOrientation(Qt.Vertical)
        self.messagesplitter.setOpaqueResize(True)
        self.message = QTextBrowser(self.messagesplitter,
                                    lineWrapMode=QTextEdit.NoWrap,
                                    openLinks=False)
        self.message.minimumSizeHint = lambda: QSize(0, 25)
        self.message.anchorClicked.connect(
            lambda url: self.linkActivated.emit(url.toString()))

        sp = SP(SP.Expanding, SP.Expanding)
        sp.setHorizontalStretch(0)
        sp.setVerticalStretch(2)
        sp.setHeightForWidth(self.message.sizePolicy().hasHeightForWidth())
        self.message.setSizePolicy(sp)
        self.message.setMinimumSize(QSize(0, 0))
        f = qtlib.getfont('fontcomment')
        self.message.setFont(f.font())
        f.changed.connect(self.forwardFont)

        self.fileview = HgFileView(self.repo, self.messagesplitter)
        sp = SP(SP.Expanding, SP.Expanding)
        sp.setHorizontalStretch(0)
        sp.setVerticalStretch(5)
        sp.setHeightForWidth(self.fileview.sizePolicy().hasHeightForWidth())
        self.fileview.setSizePolicy(sp)
        self.fileview.setMinimumSize(QSize(0, 0))
        self.fileview.linkActivated.connect(self.linkActivated)
        self.fileview.setFont(qtlib.getfont('fontdiff').font())
        self.fileview.showMessage.connect(self.showMessage)
        self.fileview.grepRequested.connect(self.grepRequested)
        self.fileview.revisionSelected.connect(self.revisionSelected)
        self.filelist.fileSelected.connect(self.fileview.displayFile)
        self.filelist.clearDisplay.connect(self.fileview.clearDisplay)

        self.revpanel = RevPanelWidget(self.repo)
        self.revpanel.linkActivated.connect(self.linkActivated)

        panelframevbox.addWidget(self.revpanel)
        panelframevbox.addSpacing(5)
        panelframevbox.addWidget(self.messagesplitter)

    def forwardFont(self, font):
        self.message.setFont(font)

    def setupModels(self):
        self.filelistmodel = model = HgFileListModel(self)
        self.filelistmodel.showMessage.connect(self.showMessage)
        self.filelist.setModel(model)
        self.actionShowAllMerge.toggled.connect(model.toggleFullFileList)

    def createActions(self):
        self.actionUpdate = a = self.filelisttbar.addAction(
            qtlib.geticon('hg-update'), _('Update to this revision'))
        a.triggered.connect(lambda: self.updateToRevision.emit(self.ctx.rev()))
        self.filelisttbar.addSeparator()
        self.actionShowAllMerge = QAction(_('Show All'), self)
        self.actionShowAllMerge.setToolTip(
            _('Toggle display of all files and the direction they were merged'))
        self.actionShowAllMerge.setCheckable(True)
        self.actionShowAllMerge.setChecked(False)
        self.actionShowAllMerge.setEnabled(False)
        self.filelisttbar.addAction(self.actionShowAllMerge)

        self.actionNextLine = QAction('Next line', self)
        self.actionNextLine.setShortcut(Qt.SHIFT + Qt.Key_Down)
        self.actionNextLine.triggered.connect(self.fileview.nextLine)
        self.addAction(self.actionNextLine)
        self.actionPrevLine = QAction('Prev line', self)
        self.actionPrevLine.setShortcut(Qt.SHIFT + Qt.Key_Up)
        self.actionPrevLine.triggered.connect(self.fileview.prevLine)
        self.addAction(self.actionPrevLine)
        self.actionNextCol = QAction('Next column', self)
        self.actionNextCol.setShortcut(Qt.SHIFT + Qt.Key_Right)
        self.actionNextCol.triggered.connect(self.fileview.nextCol)
        self.addAction(self.actionNextCol)
        self.actionPrevCol = QAction('Prev column', self)
        self.actionPrevCol.setShortcut(Qt.SHIFT + Qt.Key_Left)
        self.actionPrevCol.triggered.connect(self.fileview.prevCol)
        self.addAction(self.actionPrevCol)

        self._actions = {}
        for name, desc, icon, key, tip, cb in [
            ('navigate', _('File history'), 'hg-log', 'Shift+Return',
              _('Show the history of the selected file'), self.navigate),
            ('diffnavigate', _('Compare file revisions'), 'compare-files', None,
              _('Compare revisions of the selected file'), self.diffNavigate),
            ('diff', _('Visual Diff'), 'visualdiff', 'Ctrl+D',
              _('View file changes in external diff tool'), self.vdiff),
            ('ldiff', _('Visual Diff to Local'), 'ldiff', 'Shift+Ctrl+D',
              _('View changes to current in external diff tool'),
              self.vdifflocal),
            ('edit', _('View at Revision'), 'view-at-revision', 'Alt+Ctrl+E',
              _('View file as it appeared at this revision'), self.editfile),
            ('save', _('Save at Revision'), None, 'Alt+Ctrl+S',
              _('Save file as it appeared at this revision'), self.savefile),
            ('ledit', _('Edit Local'), 'edit-file', 'Shift+Ctrl+E',
              _('Edit current file in working copy'), self.editlocal),
            ('revert', _('Revert to Revision'), 'hg-revert', 'Alt+Ctrl+T',
              _('Revert file(s) to contents at this revision'),
              self.revertfile),
            ('opensubrepo', _('Open subrepository'), 'thg-repository-open',
              'Alt+Ctrl+O', _('Open the selected subrepository'),
              self.opensubrepo),
            ('explore', _('Explore subrepository'), 'system-file-manager',
              'Alt+Ctrl+E', _('Open the selected subrepository'),
              self.explore),
            ('terminal', _('Open terminal in subrepository'),
              'utilities-terminal', 'Alt+Ctrl+T', 
              _('Open a shell terminal in the selected subrepository root'),
              self.terminal),
            ]:
            act = QAction(desc, self)
            if icon:
                act.setIcon(qtlib.getmenuicon(icon))
            if key:
                act.setShortcut(key)
            if tip:
                act.setStatusTip(tip)
            if cb:
                act.triggered.connect(cb)
            self._actions[name] = act
            self.addAction(act)

    def onRevisionSelected(self, rev):
        'called by repowidget when repoview changes revisions'
        self.ctx = ctx = self.repo.changectx(rev)
        self.revpanel.set_revision(rev)
        self.revpanel.update(repo = self.repo)
        self.message.setHtml('<pre>%s</pre>'
                             % self._deschtmlize(ctx.description()))
        real = type(rev) is int
        wd = rev is None
        for act in ['navigate', 'diffnavigate', 'ldiff', 'edit', 'save']:
            self._actions[act].setEnabled(real)
        for act in ['diff', 'revert']:
            self._actions[act].setEnabled(real or wd)
        self.actionShowAllMerge.setEnabled(len(ctx.parents()) == 2)
        self.fileview.setContext(ctx)
        self.filelist.setContext(ctx)

    @pyqtSlot()
    def _updatedeschtmlizer(self):
        self._deschtmlize = qtlib.descriptionhtmlizer(self.repo.ui)
        self.onRevisionSelected(self.ctx.rev())  # regenerate desc html

    def reload(self):
        'Task tab is reloaded, or repowidget is refreshed'
        rev = self.ctx.rev()
        if type(self.ctx.rev()) is int and len(self.repo) <= self.ctx.rev():
            rev = 'tip'
        self.onRevisionSelected(rev)

    def navigate(self, filename=None):
        self._navigate(filename, FileLogDialog, self._nav_dialogs)

    def diffNavigate(self, filename=None):
        self._navigate(filename, FileDiffDialog, self._diff_dialogs)

    def vdiff(self):
        filenames = self.filelist.getSelectedFiles()
        if not filenames:
            return
        opts = {'change':self.ctx.rev()}
        dlg = visdiff.visualdiff(self.repo.ui, self.repo, filenames, opts)
        if dlg:
            dlg.exec_()

    def vdifflocal(self):
        filenames = self.filelist.getSelectedFiles()
        if not filenames:
            return
        assert type(self.ctx.rev()) is int
        opts = {'rev':['rev(%d)' % (self.ctx.rev())]}
        dlg = visdiff.visualdiff(self.repo.ui, self.repo, filenames, opts)
        if dlg:
            dlg.exec_()

    def editfile(self):
        filenames = self.filelist.getSelectedFiles()
        if not filenames:
            return
        rev = self.ctx.rev()
        if rev is None:
            qtlib.editfiles(self.repo, filenames, parent=self)
        else:
            base, _ = visdiff.snapshot(self.repo, filenames, self.ctx)
            files = [os.path.join(base, filename)
                     for filename in filenames]
            qtlib.editfiles(self.repo, files, parent=self)

    def savefile(self):
        filenames = self.filelist.getSelectedFiles()
        if not filenames:
            return
        rev = self.ctx.rev()
        for curfile in filenames:
            wfile = util.localpath(curfile)
            wfile, ext = os.path.splitext(os.path.basename(wfile))
            if wfile:
                filename = "%s@%d%s" % (wfile, rev, ext)
            else:
                filename = "%s@%d" % (ext, rev)

            result = QFileDialog.getSaveFileName(parent=self, caption=_("Save file to"),
                                                 directory=filename) 
            if not result:
                continue
            cwd = os.getcwd()
            try:
                os.chdir(self.repo.root)
                try:
                    commands.cat(self.repo.ui, self.repo,
                        curfile,
                        rev = rev,
                        output = hglib.fromunicode(result))
                except (util.Abort, IOError), e:
                    QMessageBox.critical(self, _('Unable to save file'), hglib.tounicode(str(e)))
            finally:
                os.chdir(cwd)

    def editlocal(self):
        filenames = self.filelist.getSelectedFiles()
        if not filenames:
            return
        qtlib.editfiles(self.repo, filenames, parent=self)

    def revertfile(self):
        fileSelection = self.filelist.getSelectedFiles()
        if len(fileSelection) == 0:
            return
        rev = self.ctx.rev()
        if rev is None:
            rev = self.ctx.p1().rev()
        dlg = revert.RevertDialog(self.repo, fileSelection, rev, self)
        dlg.exec_()

    def _navigate(self, filename, dlgclass, dlgdict):
        if not filename:
            filename = self.filelist.getSelectedFiles()[0]
        if filename is not None and len(self.repo.file(filename))>0:
            if filename not in dlgdict:
                dlg = dlgclass(self.repo, filename,
                               repoviewer=self.window())
                dlgdict[filename] = dlg
                ufname = hglib.tounicode(filename)
                dlg.setWindowTitle(_('Hg file log viewer - %s') % ufname)
                dlg.setWindowIcon(qtlib.geticon('hg-log'))
            dlg = dlgdict[filename]
            dlg.goto(self.ctx.rev())
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()

    def opensubrepo(self):
        path = os.path.join(self.repo.root, self.filelist.currentFile())
        if os.path.isdir(path):
            self.linkActivated.emit(u'subrepo:'+hglib.tounicode(path))
        else:
            QMessageBox.warning(self,
                _("Cannot open subrepository"),
                _("The selected subrepository does not exist on the working directory"))

    def explore(self):
        root = self.repo.wjoin(self.filelist.currentFile())
        if os.path.isdir(root):
            QDesktopServices.openUrl(QUrl.fromLocalFile(root))

    def terminal(self):
        root = self.repo.wjoin(self.filelist.currentFile())
        if os.path.isdir(root):
            qtlib.openshell(root, self.filelist.currentFile())

    #@pyqtSlot(QModelIndex)
    def onDoubleClick(self, index):
        model = self.filelist.model()
        itemissubrepo = (model.dataFromIndex(index)['status'] == 'S')
        if itemissubrepo:
            self.opensubrepo()
        else:
            self.vdiff()

    @pyqtSlot(QPoint)
    def menuRequest(self, point):
        index = self.filelist.currentIndex()
        if not index.isValid():
            return
        model = self.filelist.model()
        data = model.dataFromIndex(index)
        if not data:
            return
        itemissubrepo = (data['status'] == 'S')

        # Subrepos and regular items have different context menus
        if itemissubrepo:
            contextmenu = self.subrepocontextmenu
            actionlist = ['opensubrepo', 'explore', 'terminal']
        else:
            contextmenu = self.filecontextmenu
            actionlist = ['diff', 'ldiff', 'edit', 'save', 'ledit', 'revert',
                        'navigate', 'diffnavigate']

        if not contextmenu:
            contextmenu = QMenu(self)
            for act in actionlist:
                if act:
                    contextmenu.addAction(self._actions[act])
                else:
                    contextmenu.addSeparator()

            if itemissubrepo:
                self.subrepocontextmenu = contextmenu
            else:
                self.filecontextmenu = contextmenu

        if len(self.filelist.getSelectedFiles()) > 1 and not itemissubrepo:
            singlefileactions = False
        else:
            singlefileactions = True
        self._actions['navigate'].setEnabled(singlefileactions)
        self._actions['diffnavigate'].setEnabled(singlefileactions)

        if actionlist:
            contextmenu.exec_(self.filelist.viewport().mapToGlobal(point))

    def saveSettings(self, s):
        wb = "RevDetailsWidget/"
        for n in self.splitternames:
            s.setValue(wb + n, getattr(self, n).saveState())
        s.setValue(wb + 'revpanel.expanded', self.revpanel.is_expanded())
        self.fileview.saveSettings(s, 'revpanel/fileview')

    def loadSettings(self, s):
        wb = "RevDetailsWidget/"
        for n in self.splitternames:
            getattr(self, n).restoreState(s.value(wb + n).toByteArray())
        expanded = s.value(wb + 'revpanel.expanded', False).toBool()
        self.revpanel.set_expanded(expanded)
        self.fileview.loadSettings(s, 'revpanel/fileview')
