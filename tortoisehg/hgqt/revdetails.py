# revdetails.py - TortoiseHg revision details widget
#
# Copyright (C) 2007-2010 Logilab. All rights reserved.
# Copyright (C) 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt.filelistmodel import HgFileListModel
from tortoisehg.hgqt.filelistview import HgFileListView
from tortoisehg.hgqt.fileview import HgFileView
from tortoisehg.hgqt.revpanel import RevPanelWidget
from tortoisehg.hgqt import filectxactions, qtlib

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class RevDetailsWidget(QWidget, qtlib.TaskWidget):

    showMessage = pyqtSignal(QString)
    linkActivated = pyqtSignal(unicode)
    grepRequested = pyqtSignal(unicode, dict)
    revisionSelected = pyqtSignal(int)
    updateToRevision = pyqtSignal(int)

    def __init__(self, repo, parent):
        QWidget.__init__(self, parent)

        self.repo = repo
        self.ctx = repo[None]
        self.splitternames = []

        self.setupUi()
        self.createActions()
        self.setupModels()

        self._deschtmlize = qtlib.descriptionhtmlizer(repo.ui)
        repo.configChanged.connect(self._updatedeschtmlizer)

    def setRepo(self, repo):
        self.repo = repo
        self.fileview.setRepo(repo)
        self.filelist.setRepo(repo)
        self._fileactions.setRepo(repo)

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
        self.filelist.fileSelected.connect(self.updateItemFileActions)
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

        # Because filelist.fileSelected, i.e. currentRowChanged, is emitted
        # *before* selection changed, we cannot rely only on fileSelected.
        # On fileSelected, getSelectedFiles() happens to return the previous
        # selection, even though currentFile() works as expected.
        self.filelist.selectionModel().selectionChanged.connect(
            self.updateItemFileActions)

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

        self._fileactions = filectxactions.FilectxActions(self.repo, self,
                                                          rev=self.ctx.rev())
        self._fileactions.linkActivated.connect(self.linkActivated)
        self.addActions(self._fileactions.actions())

    def onRevisionSelected(self, rev):
        'called by repowidget when repoview changes revisions'
        self.ctx = ctx = self.repo.changectx(rev)
        self.revpanel.set_revision(rev)
        self.revpanel.update(repo = self.repo)
        msg = ctx.description()
        inlinetags = self.repo.ui.configbool('tortoisehg', 'issue.inlinetags')
        if ctx.tags() and inlinetags:
            msg = ' '.join(['[%s]' % tag for tag in ctx.tags()]) + ' ' + msg
        self.message.setHtml('<pre>%s</pre>'
                             % self._deschtmlize(msg))
        self._fileactions.setRev(rev)
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
        if (type(self.ctx.rev()) is int and len(self.repo) <= self.ctx.rev()
            or (rev is not None  # wctxrev in repo raises TypeError
                and rev not in self.repo
                and rev not in self.repo.thgmqunappliedpatches)):
            rev = 'tip'
        self.onRevisionSelected(rev)

    #@pyqtSlot(QModelIndex)
    def onDoubleClick(self, index):
        model = self.filelist.model()
        itemstatus = model.dataFromIndex(index)['status']
        itemissubrepo = (itemstatus == 'S')
        if itemissubrepo:
            self._fileactions.opensubrepo()
        elif itemstatus == 'C':
            self._fileactions.editfile()
        else:
            self._fileactions.vdiff()

    @pyqtSlot(QPoint)
    def menuRequest(self, point):
        index = self.filelist.currentIndex()
        if not index.isValid():
            return
        model = self.filelist.model()
        data = model.dataFromIndex(index)
        if not data:
            return
        contextmenu = self._fileactions.menu()
        if contextmenu:
            contextmenu.exec_(self.filelist.viewport().mapToGlobal(point))

    @pyqtSlot()
    def updateItemFileActions(self):
        index = self.filelist.currentIndex()
        model = self.filelist.model()
        data = model.dataFromIndex(index)
        if not data:
            return
        itemissubrepo = (data['status'] == 'S')
        self._fileactions.setPaths_(self.filelist.getSelectedFiles(),
                                    self.filelist.currentFile(),
                                    itemissubrepo)

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
