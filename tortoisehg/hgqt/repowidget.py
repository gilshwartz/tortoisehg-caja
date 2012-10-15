# repowidget.py - TortoiseHg repository widget
#
# Copyright (C) 2007-2010 Logilab. All rights reserved.
# Copyright (C) 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.

import binascii
import os
import shlex, subprocess, functools # used by runCustomCommand
from mercurial import revset, error, patch, phases

from tortoisehg.util import hglib, shlib, paths
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib
from tortoisehg.hgqt.qtlib import QuestionMsgBox, InfoMsgBox, WarningMsgBox
from tortoisehg.hgqt.qtlib import DemandWidget
from tortoisehg.hgqt.repomodel import HgRepoListModel
from tortoisehg.hgqt import cmdui, update, tag, backout, merge, visdiff
from tortoisehg.hgqt import archive, thgimport, thgstrip, run, purge, bookmark
from tortoisehg.hgqt import bisect, rebase, resolve, thgrepo, compress, mq
from tortoisehg.hgqt import qdelete, qreorder, qfold, qrename, shelve
from tortoisehg.hgqt import matching, graft

from tortoisehg.hgqt.repofilter import RepoFilterBar
from tortoisehg.hgqt.repoview import HgRepoView
from tortoisehg.hgqt.revdetails import RevDetailsWidget
from tortoisehg.hgqt.commit import CommitWidget
from tortoisehg.hgqt.manifestdialog import ManifestWidget
from tortoisehg.hgqt.sync import SyncWidget
from tortoisehg.hgqt.grep import SearchWidget
from tortoisehg.hgqt.pbranch import PatchBranchWidget

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class RepoWidget(QWidget):

    showMessageSignal = pyqtSignal(QString)
    closeSelfSignal = pyqtSignal(QWidget)
    toolbarVisibilityChanged = pyqtSignal()

    output = pyqtSignal(QString, QString)
    progress = pyqtSignal(QString, object, QString, QString, object)
    makeLogVisible = pyqtSignal(bool)
    beginSuppressPrompt = pyqtSignal()
    endSuppressPrompt = pyqtSignal()

    repoChanged = pyqtSignal(QString)

    revisionSelected = pyqtSignal(object)

    titleChanged = pyqtSignal(unicode)
    """Emitted when changed the expected title for the RepoWidget tab"""

    showIcon = pyqtSignal(QIcon)

    shortNameChanged = pyqtSignal(QString, QString)
    baseNodeChanged = pyqtSignal(QString, object)

    repoLinkClicked = pyqtSignal(unicode)
    """Emitted when clicked a link to open repository"""

    def __init__(self, repo, parent=None, bundle=None):
        QWidget.__init__(self, parent, acceptDrops=True)

        self.repo = repo
        repo.repositoryChanged.connect(self.repositoryChanged)
        repo.repositoryDestroyed.connect(self.repositoryDestroyed)
        repo.configChanged.connect(self.configChanged)
        self.revsetfilter = False
        self.bundle = None  # bundle file name [local encoding]
        self.bundlesource = None  # source URL of incoming bundle [unicode]
        self.outgoingMode = False
        self.revset = []
        self.busyIcons = []
        self.namedTabs = {}
        self.repolen = len(repo)
        self.shortname = None
        self.basenode = None
        self.destroyed.connect(self.repo.thginvalidate)

        # Determine the "initial revision" that must be shown when
        # opening the repo.
        # The "initial revision" can be selected via the settings, and it can
        # have 3 possible values:
        # - "current":    Select the current (i.e. working dir parent) revision
        # - "tip":        Select tip of the repository
        # - "workingdir": Select the working directory pseudo-revision
        initialRevision= \
            self.repo.ui.config('tortoisehg', 'initialrevision', 'current').lower()

        initialRevisionDict = {
            'current': '.',
            'tip': 'tip',
            'workingdir': None
        }
        if initialRevision in initialRevisionDict:
            default_rev = initialRevisionDict[initialRevision]
        else:
            # By default we'll select the current (i.e. working dir parent) revision
            default_rev = '.'

        if repo.parents()[0].rev() == -1:
            self._reload_rev = 'tip'
        else:
            self._reload_rev = default_rev
        self.currentMessage = ''
        self.dirty = False

        self.setupUi()
        self.createActions()
        self.loadSettings()
        self.setupModels()

        if bundle:
            self.setBundle(bundle)

        self.runner = cmdui.Runner(False, self)
        self.runner.output.connect(self.output)
        self.runner.progress.connect(self.progress)
        self.runner.makeLogVisible.connect(self.makeLogVisible)
        self.runner.commandStarted.connect(self.beginSuppressPrompt)
        self.runner.commandFinished.connect(self.endSuppressPrompt)
        self.runner.commandFinished.connect(self.onCommandFinished)

        # Select the widget chosen by the user
        defaultWidget = \
            self.repo.ui.config(
                'tortoisehg', 'defaultwidget', 'revdetails').lower()
        widgetDict = {
            'revdetails': self.logTabIndex,
            'commit': self.commitTabIndex,
            'mq': self.mqTabIndex,
            'sync': self.syncTabIndex,
            'manifest': self.manifestTabIndex,
            'search': self.grepTabIndex
        }
        if initialRevision == 'workingdir':
            # Do not allow selecting the revision details widget when the
            # selected revision is the working directory pseudo-revision
            widgetDict['revdetails'] = self.commitTabIndex

        if defaultWidget in widgetDict:
            widgetIndex = widgetDict[defaultWidget]
            # Note: if the mq extension is not enabled, self.mqTabIndex will
            #       be negative
            if widgetIndex > 0:
                self.taskTabsWidget.setCurrentIndex(widgetIndex)
        self.output.connect(self._showOutputOnInfoBar)

    def setupUi(self):
        SP = QSizePolicy

        self.repotabs_splitter = QSplitter(orientation=Qt.Vertical)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(0)

        self._infobarlayout = QVBoxLayout()  # placeholder for InfoBar
        self.layout().addLayout(self._infobarlayout)

        self.filterbar = RepoFilterBar(self.repo, self)
        self.layout().addWidget(self.filterbar)

        self.filterbar.branchChanged.connect(self.setBranch)
        self.filterbar.progress.connect(self.progress)
        self.filterbar.showMessage.connect(self.showMessage)
        self.filterbar.setRevisionSet.connect(self.setRevisionSet)
        self.filterbar.clearRevisionSet.connect(self._unapplyRevisionSet)
        self.filterbar.filterToggled.connect(self.filterToggled)
        self.filterbar.hide()
        self.revsetfilter = self.filterbar.filtercb.isChecked()

        self.layout().addWidget(self.repotabs_splitter)

        cs = ('workbench', _('Workbench Log Columns'))
        self.repoview = view = HgRepoView(self.repo, 'repoWidget', cs, self)
        view.revisionClicked.connect(self.onRevisionClicked)
        view.revisionSelected.connect(self.onRevisionSelected)
        view.revisionAltClicked.connect(self.onRevisionSelected)
        view.revisionActivated.connect(self.onRevisionActivated)
        view.showMessage.connect(self.showMessage)
        view.menuRequested.connect(self.viewMenuRequest)

        sp = SP(SP.Expanding, SP.Expanding)
        sp.setHorizontalStretch(0)
        sp.setVerticalStretch(1)
        sp.setHeightForWidth(self.repoview.sizePolicy().hasHeightForWidth())
        view.setSizePolicy(sp)
        view.setFrameShape(QFrame.StyledPanel)

        self.repotabs_splitter.addWidget(self.repoview)
        self.repotabs_splitter.setCollapsible(0, True)
        self.repotabs_splitter.setStretchFactor(0, 1)

        self.taskTabsWidget = tt = QTabWidget()
        self.repotabs_splitter.addWidget(self.taskTabsWidget)
        self.repotabs_splitter.setStretchFactor(1, 1)
        tt.setDocumentMode(True)
        self.updateTaskTabs()

        self.revDetailsWidget = w = RevDetailsWidget(self.repo, self)
        self.revDetailsWidget.filelisttbar.setStyleSheet(qtlib.tbstylesheet)
        w.linkActivated.connect(self._openLink)
        w.revisionSelected.connect(self.repoview.goto)
        w.grepRequested.connect(self.grep)
        w.showMessage.connect(self.showMessage)
        w.updateToRevision.connect(lambda rev: self.updateToRevision())
        self.logTabIndex = idx = tt.addTab(w, qtlib.geticon('hg-log'), '')
        self.namedTabs['log'] = idx
        tt.setTabToolTip(idx, _("Revision details", "tab tooltip"))

        self.commitDemand = w = DemandWidget('createCommitWidget', self)
        self.commitTabIndex = idx = tt.addTab(w, qtlib.geticon('hg-commit'), '')
        self.namedTabs['commit'] = idx
        tt.setTabToolTip(idx, _("Commit", "tab tooltip"))

        if 'mq' in self.repo.extensions():
            self.mqDemand = w = DemandWidget('createMQWidget', self)
            self.mqTabIndex = idx = tt.addTab(w, qtlib.geticon('thg-qrefresh'), '')
            tt.setTabToolTip(idx, _("MQ Patch", "tab tooltip"))
            self.namedTabs['mq'] = idx
        else:
            self.mqTabIndex = -1

        self.syncDemand = w = DemandWidget('createSyncWidget', self)
        self.syncTabIndex = idx = tt.addTab(w, qtlib.geticon('thg-sync'), '')
        self.namedTabs['sync'] = idx
        tt.setTabToolTip(idx, _("Synchronize", "tab tooltip"))

        self.manifestDemand = w = DemandWidget('createManifestWidget', self)
        self.manifestTabIndex = idx = tt.addTab(w, qtlib.geticon('hg-annotate'), '')
        self.namedTabs['manifest'] = idx
        tt.setTabToolTip(idx, _('Manifest', "tab tooltip"))

        self.grepDemand = w = DemandWidget('createGrepWidget', self)
        self.grepTabIndex = idx = tt.addTab(w, qtlib.geticon('hg-grep'), '')
        self.namedTabs['grep'] = idx
        tt.setTabToolTip(idx, _("Search", "tab tooltip"))

        if 'pbranch' in self.repo.extensions():
            self.pbranchDemand = w = DemandWidget('createPatchBranchWidget', self)
            self.pbranchTabIndex = idx = tt.addTab(w, qtlib.geticon('branch'), '')
            tt.setTabToolTip(idx, _("Patch Branch", "tab tooltip"))
            self.namedTabs['pbranch'] = idx
        else:
            self.pbranchTabIndex = -1

        self.taskTabsWidget.currentChanged.connect(
            self._refreshCommitTabIfNeeded)

    @pyqtSlot(QString)
    def switchToNamedTaskTab(self, tabname):
        tabname = str(tabname)
        if tabname in self.namedTabs:
            idx = self.namedTabs[tabname]
            # refresh status even if current widget is already a 'commit'
            if (tabname == 'commit'
                and self.taskTabsWidget.currentIndex() == idx):
                self._refreshCommitTabIfNeeded()
            self.taskTabsWidget.setCurrentIndex(idx)

            # restore default splitter position if task tab is invisible
            if self.repotabs_splitter.sizes()[1] == 0:
                self.repotabs_splitter.setSizes([1, 1])

    def title(self):
        """Returns the expected title for this widget [unicode]"""
        if self.bundle:
            return _('%s <incoming>') % self.repo.shortname
        elif self.repomodel.branch():
            return u'%s [%s]' % (self.repo.shortname, self.repomodel.branch())
        else:
            return self.repo.shortname

    def filterBarVisible(self):
        return self.filterbar.isVisible()

    @pyqtSlot(bool)
    def toggleFilterBar(self, checked):
        """Toggle display repowidget filter bar"""
        self.filterbar.setVisible(checked)

    @pyqtSlot(unicode)
    def _openLink(self, link):
        link = unicode(link)
        handlers = {'cset': self.goto,
                    'log': lambda a: self.makeLogVisible.emit(True),
                    'subrepo': self.repoLinkClicked.emit,
                    'shelve' : self.shelve}
        if ':' in link:
            scheme, param = link.split(':', 1)
            hdr = handlers.get(scheme)
            if hdr:
                return hdr(param)
        if os.path.isabs(link):
            qtlib.openlocalurl(link)
        else:
            QDesktopServices.openUrl(QUrl(link))

    def setInfoBar(self, cls, *args, **kwargs):
        """Show the given infobar at top of RepoWidget

        If the priority of the current infobar is higher than new one,
        the request is silently ignored.
        """
        cleared = self.clearInfoBar(priority=cls.infobartype)
        if not cleared:
            return
        w = cls(*args, **kwargs)
        w.linkActivated.connect(self._openLink)
        self._infobarlayout.insertWidget(0, w)
        w.setFocus()  # to handle key press by InfoBar
        return w

    @pyqtSlot()
    def clearInfoBar(self, priority=None):
        """Close current infobar if available; return True if got empty"""
        it = self._infobarlayout.itemAt(0)
        if not it:
            return True
        if priority is None or it.widget().infobartype <= priority:
            # removes current infobar explicitly, because close() seems to
            # delay deletion until next eventloop.
            self._infobarlayout.removeItem(it)
            it.widget().close()
            return True
        else:
            return False

    @pyqtSlot(unicode, unicode)
    def _showOutputOnInfoBar(self, msg, label, maxlines=2, maxwidth=140):
        labelslist = unicode(label).split()
        if 'ui.error' in labelslist:
            # Limit the text shown on the info bar to maxlines lines of up to maxwidth chars
            msglines = unicode(msg).strip().splitlines()
            infolines = []
            for line in msglines[0:maxlines]:
                if len(line) > maxwidth:
                    line = line[0:maxwidth] + ' ...'
                infolines.append(line)
            if len(msglines) > maxlines and not infolines[-1].endswith('...'):
                infolines[-1] += ' ...'
            self.setInfoBar(qtlib.CommandErrorInfoBar, '\n'.join(infolines))

    @pyqtSlot(unicode)
    def _showMessageOnInfoBar(self, msg):
        if msg:
            self.setInfoBar(qtlib.StatusInfoBar, msg)
        else:
            self.clearInfoBar(priority=qtlib.StatusInfoBar.infobartype)

    def createCommitWidget(self):
        pats, opts = {}, {}
        cw = CommitWidget(self.repo, pats, opts, True, self, rev=self.rev)
        cw.buttonHBox.addWidget(cw.commitSetupButton())
        cw.loadSettings(QSettings(), 'workbench')

        cw.output.connect(self.output)
        cw.progress.connect(self.progress)
        cw.makeLogVisible.connect(self.makeLogVisible)
        cw.beginSuppressPrompt.connect(self.beginSuppressPrompt)
        cw.endSuppressPrompt.connect(self.endSuppressPrompt)
        cw.linkActivated.connect(self._openLink)
        cw.showMessage.connect(self.showMessage)
        QTimer.singleShot(0, cw.reload)
        return cw

    def createManifestWidget(self):
        if isinstance(self.rev, basestring):
            rev = None
        else:
            rev = self.rev
        w = ManifestWidget(self.repo, rev, self)
        w.loadSettings(QSettings(), 'workbench')
        w.revChanged.connect(self.repoview.goto)
        w.linkActivated.connect(self._openLink)
        w.showMessage.connect(self.showMessage)
        w.grepRequested.connect(self.grep)
        w.revsetFilterRequested.connect(self.setFilter)
        return w

    def createSyncWidget(self):
        sw = SyncWidget(self.repo, self)
        sw.output.connect(self.output)
        sw.progress.connect(self.progress)
        sw.makeLogVisible.connect(self.makeLogVisible)
        sw.beginSuppressPrompt.connect(self.beginSuppressPrompt)
        sw.endSuppressPrompt.connect(self.endSuppressPrompt)
        sw.syncStarted.connect(self.clearInfoBar)
        sw.outgoingNodes.connect(self.setOutgoingNodes)
        sw.showMessage.connect(self.showMessage)
        sw.showMessage.connect(self._showMessageOnInfoBar)
        sw.incomingBundle.connect(self.setBundle)
        sw.pullCompleted.connect(self.onPullCompleted)
        sw.pushCompleted.connect(self.pushCompleted)
        sw.showBusyIcon.connect(self.onShowBusyIcon)
        sw.hideBusyIcon.connect(self.onHideBusyIcon)
        sw.refreshTargets(self.rev)
        sw.switchToRequest.connect(self.switchToNamedTaskTab)
        return sw

    @pyqtSlot(QString)
    def onShowBusyIcon(self, iconname):
        self.busyIcons.append(iconname)
        self.showIcon.emit(qtlib.geticon(self.busyIcons[-1]))

    @pyqtSlot(QString)
    def onHideBusyIcon(self, iconname):
        if iconname in self.busyIcons:
            self.busyIcons.remove(iconname)
        if self.busyIcons:
            self.showIcon.emit(qtlib.geticon(self.busyIcons[-1]))
        else:
            self.showIcon.emit(QIcon())

    @pyqtSlot(QString)
    def setFilter(self, filter):
        self.filterbar.revsetle.setText(filter)
        self.filterbar.setVisible(True)
        self.filterbar.returnPressed()

    @pyqtSlot(QString, QString)
    def setBundle(self, bfile, bsource=None):
        if self.bundle:
            self.clearBundle()
        self.bundle = hglib.fromunicode(bfile)
        self.bundlesource = bsource
        oldlen = len(self.repo)
        self.repo = thgrepo.repository(self.repo.ui, self.repo.root,
                                       bundle=self.bundle)
        self.repoview.setRepo(self.repo)
        self.revDetailsWidget.setRepo(self.repo)
        self.manifestDemand.forward('setRepo', self.repo)
        self.filterbar.revsetle.setText('incoming()')
        self.filterbar.setEnableFilter(False)
        self.titleChanged.emit(self.title())
        newlen = len(self.repo)
        self.revset = range(oldlen, newlen)
        self.repomodel.revset = self.revset
        self.reload(invalidate=False)
        self.repoview.resetBrowseHistory(self.revset)
        self._reload_rev = self.revset[0]

        w = self.setInfoBar(qtlib.ConfirmInfoBar,
            _('Found %d incoming changesets') % len(self.revset))
        assert w
        w.acceptButton.setText(_('Accept'))
        w.acceptButton.setToolTip(_('Pull incoming changesets into '
                                    'your repository'))
        w.rejectButton.setText(_('Reject'))
        w.rejectButton.setToolTip(_('Reject incoming changesets'))
        w.accepted.connect(self.acceptBundle)
        w.rejected.connect(self.rejectBundle)

    def clearBundle(self):
        self.filterbar.setEnableFilter(True)
        self.filterbar.revsetle.setText('')
        self.revset = []
        self.repomodel.revset = self.revset
        self.bundle = None
        self.bundlesource = None
        self.titleChanged.emit(self.title())
        self.repo = thgrepo.repository(self.repo.ui, self.repo.root)
        self.repoview.setRepo(self.repo)
        self.revDetailsWidget.setRepo(self.repo)
        self.manifestDemand.forward('setRepo', self.repo)

    def onPullCompleted(self):
        if self.bundle:
            # create a new bundlerepo instance; revision numbers may change
            brepo = thgrepo.repository(self.repo.ui, self.repo.root,
                                       bundle=self.bundle)
            repo = thgrepo.repository(self.repo.ui, self.repo.root)
            if len(repo) == len(brepo):
                # all bundle revisions pulled
                self.clearBundle()
                self.reload(invalidate=False)
            else:
                # refresh revset with remaining revisions
                self.revset = range(len(repo), len(brepo))
                self.repo = brepo
                self.repoview.setRepo(brepo)
                self.revDetailsWidget.setRepo(brepo)
                self.manifestDemand.forward('setRepo', brepo)
                self.reload(invalidate=False)
                self.repomodel.revset = self.revset
                self.repoview.resetBrowseHistory(self.revset)
                self._reload_rev = self.revset[0]

    def acceptBundle(self):
        if self.bundle:
            self.taskTabsWidget.setCurrentIndex(self.syncTabIndex)
            self.syncDemand.pullBundle(self.bundle, None, self.bundlesource)

    def pullBundleToRev(self):
        if self.bundle:
            self.taskTabsWidget.setCurrentIndex(self.syncTabIndex)
            self.syncDemand.pullBundle(self.bundle, self.rev,
                                       self.bundlesource)

    def rejectBundle(self):
        self.clearBundle()
        self.reload(invalidate=False)

    @pyqtSlot()
    def clearRevisionSet(self):
        self.filterbar.revsetle.clear()
        return self._unapplyRevisionSet()

    @pyqtSlot()
    def _unapplyRevisionSet(self):
        self.toolbarVisibilityChanged.emit()
        self.outgoingMode = False
        if not self.revset:
            return False
        self.revset = []
        if self.revsetfilter:
            self.reload()
            return True
        else:
            self.repomodel.revset = []
            self.refresh()
        return False

    def setRevisionSet(self, revisions):
        revs = revisions[:]
        revs.sort(reverse=True)
        self.revset = revs
        if self.revsetfilter:
            self.reload()
        else:
            self.repomodel.revset = self.revset
            self.refresh()
        self.repoview.resetBrowseHistory(self.revset)
        self._reload_rev = self.revset[0]

    @pyqtSlot(bool)
    def filterToggled(self, checked):
        self.revsetfilter = checked
        if self.revset:
            self.repomodel.filterbyrevset = checked
            self.reload()
            self.repoview.resetBrowseHistory(self.revset, self.rev)

    def setOutgoingNodes(self, nodes):
        self.filterbar.revsetle.setText('outgoing()')
        self.setRevisionSet([self.repo[n].rev() for n in nodes])
        self.outgoingMode = True

        w = self.setInfoBar(qtlib.ConfirmInfoBar,
                            _('%d outgoing changesets') % len(nodes))
        assert w

        # Read the tortoisehg.defaultpush setting to determine what to push
        # by default, and set the button label and action accordingly
        acceptbuttontext = _('Push')
        defaultpush = self.repo.ui.config('tortoisehg', 'defaultpush', 'all')
        rev = None
        branch = None
        pushall = False
        if defaultpush == 'branch':
            branch = self.repo['.'].branch()
            acceptbuttontext = _('Push current branch (%s)') \
                % hglib.tounicode(branch)
        elif defaultpush == 'revision':
            rev = self.repo['.'].rev()
            acceptbuttontext = _('Push current revision (%d)') % rev
        else:
            pushall = True

        w.acceptButton.setText(acceptbuttontext)
        w.accepted.connect(lambda: self.push(False,
            rev=rev, branch=branch, pushall=pushall))  # TODO: to the same URL
        w.rejected.connect(self.clearRevisionSet)

    def createGrepWidget(self):
        upats = {}
        gw = SearchWidget(upats, self.repo, self)
        gw.setRevision(self.repoview.current_rev)
        gw.showMessage.connect(self.showMessage)
        gw.progress.connect(self.progress)
        gw.revisionSelected.connect(self.goto)
        return gw

    def createMQWidget(self):
        mqw = mq.MQWidget(self.repo, self)
        mqw.output.connect(self.output)
        mqw.progress.connect(self.progress)
        mqw.makeLogVisible.connect(self.makeLogVisible)
        mqw.showMessage.connect(self.showMessage)
        return mqw

    def createPatchBranchWidget(self):
        pbw = PatchBranchWidget(self.repo, parent=self)
        pbw.output.connect(self.output)
        pbw.progress.connect(self.progress)
        pbw.makeLogVisible.connect(self.makeLogVisible)
        return pbw

    def reponame(self):
        return self.repo.shortname

    @property
    def rev(self):
        """Returns the current active revision"""
        return self.repoview.current_rev

    def showMessage(self, msg):
        self.currentMessage = msg
        if self.isVisible():
            self.showMessageSignal.emit(msg)

    def showEvent(self, event):
        QWidget.showEvent(self, event)
        self.showMessageSignal.emit(self.currentMessage)
        if self.dirty:
            print 'page was dirty, reloading...'
            self.reload()
            self.dirty = False

    def createActions(self):
        QShortcut(QKeySequence('CTRL+P'), self, self.gotoParent)
        self.generateSingleMenu()
        self.generatePairMenu()
        self.generateUnappliedPatchMenu()
        self.generateMultipleSelectionMenu()
        self.generateBundleMenu()
        self.generateOutgoingMenu()
    def detectPatches(self, paths):
        filepaths = []
        for p in paths:
            if not os.path.isfile(p):
                continue
            try:
                pf = open(p, 'rb')
                earlybytes = pf.read(4096)
                if '\0' in earlybytes:
                    continue
                pf.seek(0)
                filename, message, user, date, branch, node, p1, p2 = \
                        patch.extract(self.repo.ui, pf)
                if filename:
                    filepaths.append(p)
                    os.unlink(filename)
            except Exception:
                pass
        return filepaths

    def dragEnterEvent(self, event):
        paths = [unicode(u.toLocalFile()) for u in event.mimeData().urls()]
        if self.detectPatches(paths):
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dropEvent(self, event):
        paths = [unicode(u.toLocalFile()) for u in event.mimeData().urls()]
        patches = self.detectPatches(paths)
        if not patches:
            return
        event.setDropAction(Qt.CopyAction)
        event.accept()
        self.thgimport(patches)

    ## Begin Workbench event forwards

    def back(self):
        self.repoview.back()

    def forward(self):
        self.repoview.forward()

    def bisect(self):
        dlg = bisect.BisectDialog(self.repo, {}, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def resolve(self):
        dlg = resolve.ResolveDialog(self.repo, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def thgimport(self, paths=None):
        dlg = thgimport.ImportDialog(self.repo, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.patchImported.connect(self.gotoTip)
        if paths:
            dlg.setfilepaths(paths)
        dlg.exec_()

    def shelve(self, arg=None):
        dlg = shelve.ShelveDialog(self.repo, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def verify(self):
        cmdline = ['--repository', self.repo.root, 'verify', '--verbose']
        dlg = cmdui.Dialog(cmdline, self)
        dlg.setWindowIcon(qtlib.geticon('hg-verify'))
        dlg.setWindowTitle(_('%s - verify repository') % self.repo.shortname)
        dlg.setWindowFlags(dlg.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
            | Qt.WindowMaximizeButtonHint)

        dlg.exec_()

    def recover(self):
        cmdline = ['--repository', self.repo.root, 'recover', '--verbose']
        dlg = cmdui.Dialog(cmdline, self)
        dlg.setWindowIcon(qtlib.geticon('hg-recover'))
        dlg.setWindowTitle(_('%s - recover repository') % self.repo.shortname)
        dlg.setWindowFlags(dlg.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
            | Qt.WindowMaximizeButtonHint)

        dlg.exec_()

    def rollback(self):
        def read_undo():
            if os.path.exists(self.repo.sjoin('undo')):
                try:
                    args = self.repo.opener('undo.desc', 'r').read().splitlines()
                    if args[1] != 'commit':
                        return None
                    return args[1], int(args[0])
                except (IOError, IndexError, ValueError):
                    pass
            return None
        data = read_undo()
        if data is None:
            InfoMsgBox(_('No transaction available'),
                       _('There is no rollback transaction available'))
            return
        elif data[0] == 'commit':
            if not QuestionMsgBox(_('Undo last commit?'),
                   _('Undo most recent commit (%d), preserving file changes?') %
                   data[1]):
                return
        else:
            if not QuestionMsgBox(_('Undo last transaction?'),
                    _('Rollback to revision %d (undo %s)?') %
                    (data[1]-1, data[0])):
                return
            try:
                rev = self.repo['.'].rev()
            except Exception, e:
                InfoMsgBox(_('Repository Error'),
                           _('Unable to determine working copy revision\n') +
                           hglib.tounicode(e))
                return
            if rev >= data[1] and not QuestionMsgBox(
                    _('Remove current working revision?'),
                    _('Your current working revision (%d) will be removed '
                      'by this rollback, leaving uncommitted changes.\n '
                      'Continue?' % rev)):
                    return
        cmdline = ['rollback', '--repository', self.repo.root, '--verbose']
        self.runCommand(cmdline)

    def purge(self):
        dlg = purge.PurgeDialog(self.repo, self)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.showMessage.connect(self.showMessage)
        dlg.progress.connect(self.progress)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    ## End workbench event forwards

    @pyqtSlot(unicode, dict)
    def grep(self, pattern='', opts={}):
        """Open grep task tab"""
        opts = dict((str(k), str(v)) for k, v in opts.iteritems())
        self.taskTabsWidget.setCurrentIndex(self.grepTabIndex)
        self.grepDemand.setSearch(pattern, **opts)

    def setupModels(self):
        # Filter revision set in case revisions were removed
        self.revset = [r for r in self.revset if r < len(self.repo)]
        self.repomodel = HgRepoListModel(self.repo, self.repoview.colselect[0],
                                         self.filterbar.branch(), self.revset,
                                         self.revsetfilter, self)
        self.repomodel.filled.connect(self.modelFilled)
        self.repomodel.loaded.connect(self.modelLoaded)
        self.repomodel.showMessage.connect(self.showMessage)
        oldmodel = self.repoview.model()
        self.repoview.setModel(self.repomodel)
        if oldmodel:
            oldmodel.deleteLater()
        try:
            self._last_series = self.repo.mq.series[:]
        except AttributeError:
            self._last_series = []

    def modelFilled(self):
        'initial batch of revisions loaded'
        self.repoview.goto(self._reload_rev) # emits revisionSelected
        self.repoview.resizeColumns()
        if self.repo.shortname != self.shortname:
            self.shortname = self.repo.shortname
            self.shortNameChanged.emit(hglib.tounicode(self.repo.root),
                                       self.shortname)
        if len(self.repo) and self.repo[0].node() != self.basenode:
            self.basenode = self.repo[0].node()
            self.baseNodeChanged.emit(hglib.tounicode(self.repo.root),
                                      self.basenode)

    def modelLoaded(self):
        'all revisions loaded (graph generator completed)'
        # Perhaps we can update a GUI element later, to indicate full load
        pass

    def onRevisionClicked(self, rev):
        'User clicked on a repoview row'
        self.clearInfoBar(qtlib.InfoBar.INFO)
        tw = self.taskTabsWidget
        cw = tw.currentWidget()
        if not cw.canswitch():
            return
        ctx = self.repo.changectx(rev)
        if rev is None or ('mq' in self.repo.extensions() and 'qtip' in ctx.tags()
                           and self.repo['.'].rev() == rev):
            # Clicking on working copy or on the topmost applied patch
            # (_if_ it is also the working copy parent) switches to the commit tab
            tw.setCurrentIndex(self.commitTabIndex)
        else:
            # Clicking on a normal revision switches from commit tab
            tw.setCurrentIndex(self.logTabIndex)

    def onRevisionSelected(self, rev):
        'View selection changed, could be a reload'
        self.showMessage('')
        if self.repomodel.graph is None:
            return
        try:
            self.revDetailsWidget.onRevisionSelected(rev)
            self.revisionSelected.emit(rev)
            if type(rev) != str:
                # Regular patch or working directory
                if self.manifestDemand.isHidden():
                    self.manifestDemand.forward('selectRev', rev)
                else:
                    self.manifestDemand.forward('setRev', rev)
                self.grepDemand.forward('setRevision', rev)
                self.syncDemand.forward('refreshTargets', rev)
                self.commitDemand.forward('setRev', rev)
            else:
                # unapplied patch
                if self.manifestDemand.isHidden():
                    self.manifestDemand.forward('selectRev', None)
                else:
                    self.manifestDemand.forward('setRev', None)
        except (IndexError, error.RevlogError, error.Abort), e:
            self.showMessage(hglib.tounicode(str(e)))

    def gotoParent(self):
        self.goto('.')

    def gotoTip(self):
        self.repoview.clearSelection()
        self.goto('tip')

    def goto(self, rev):
        self._reload_rev = rev
        self.repoview.goto(rev)

    def onRevisionActivated(self, rev):
        qgoto = False
        if isinstance(rev, basestring):
            qgoto = True
        else:
            ctx = self.repo.changectx(rev)
            if 'qparent' in ctx.tags() or ctx.thgmqappliedpatch():
                qgoto = True
            if 'qtip' in ctx.tags():
                qgoto = False
        if qgoto:
            self.qgotoSelectedRevision()
        else:
            self.visualDiffRevision()

    def reload(self, invalidate=True):
        'Initiate a refresh of the repo model, rebuild graph'
        try:
            if invalidate:
                self.repo.thginvalidate()
            self.rebuildGraph()
            self.reloadTaskTab()
        except EnvironmentError, e:
            self.showMessage(hglib.tounicode(str(e)))

    def rebuildGraph(self):
        'Called by repositoryChanged signals, and during reload'
        self.showMessage('')

        if len(self.repo) < self.repolen:
            # repo has been stripped, invalidate active revision sets
            if self.bundle:
                self.clearBundle()
                self.showMessage(_('Repository stripped, incoming preview '
                                   'cleared'))
            elif self.revset:
                self.revset = []
                self.filterbar.revsetle.clear()
                self.showMessage(_('Repository stripped, revision set cleared'))
        if not self.bundle:
            self.repolen = len(self.repo)

        self._reload_rev = self.rev
        if self.rev is None:
            pass
        elif type(self.rev) is str:
            try:
                if self.rev not in self.repo.mq.series:
                    # patch is no longer in the series, find a neighbor
                    idx = self._last_series.index(self._reload_rev) - 1
                    self._reload_rev = self._last_series[idx]
                    while self._reload_rev not in self.repo.mq.series and idx:
                        idx -= 1
                        self._reload_rev = self._last_series[idx]
            except (AttributeError, IndexError, ValueError):
                self._reload_rev = 'tip'
        elif len(self.repo) <= self.rev:
            self._reload_rev = 'tip'

        self.setupModels()
        self.filterbar.refresh()
        self.repoview.saveSettings()

    def reloadTaskTab(self):
        tti = self.taskTabsWidget.currentIndex()
        if tti == self.logTabIndex:
            ttw = self.revDetailsWidget
        elif tti == self.commitTabIndex:
            ttw = self.commitDemand.get()
        elif tti == self.manifestTabIndex:
            ttw = self.manifestDemand.get()
        elif tti == self.syncTabIndex:
            ttw = self.syncDemand.get()
        elif tti == self.grepTabIndex:
            ttw = self.grepDemand.get()
        elif tti == self.pbranchTabIndex:
            ttw = self.pbranchDemand.get()
        elif tti == self.mqTabIndex:
            ttw = self.mqDemand.get()
        if ttw:
            ttw.reload()

    def refresh(self):
        'Refresh the repo model view, clear cached data'
        self.repo.thginvalidate()
        self.repomodel.invalidate()
        self.revDetailsWidget.reload()
        self.filterbar.refresh()

    def repositoryDestroyed(self):
        'Repository has detected itself to be deleted'
        self.closeSelfSignal.emit(self)

    def repositoryChanged(self):
        'Repository has detected a changelog / dirstate change'
        if self.isVisible():
            try:
                self.rebuildGraph()
            except (error.RevlogError, error.RepoError), e:
                self.showMessage(hglib.tounicode(str(e)))
                self.repomodel = HgRepoListModel(None,
                                                 self.repoview.colselect[0],
                                                 None, None, False, self)
                self.repoview.setModel(self.repomodel)
        else:
            self.dirty = True

        # Update the repo registry entries related to the current repo
        self.repoChanged.emit(hglib.tounicode(self.repo.root))

    def configChanged(self):
        'Repository is reporting its config files have changed'
        self.repomodel.invalidate()
        self.revDetailsWidget.reload()
        self.titleChanged.emit(self.title())
        self.updateTaskTabs()
        if self.repo.shortname != self.shortname:
            self.shortname = self.repo.shortname
            self.shortNameChanged.emit(hglib.tounicode(self.repo.root),
                                       self.shortname)

    def updateTaskTabs(self):
        val = self.repo.ui.config('tortoisehg', 'tasktabs', 'off').lower()
        if val == 'east':
            self.taskTabsWidget.setTabPosition(QTabWidget.East)
            self.taskTabsWidget.tabBar().show()
        elif val == 'west':
            self.taskTabsWidget.setTabPosition(QTabWidget.West)
            self.taskTabsWidget.tabBar().show()
        else:
            self.taskTabsWidget.tabBar().hide()

    @pyqtSlot(QString, bool)
    def setBranch(self, branch, allparents):
        'Change the branch filter'
        self.repomodel.setBranch(branch=branch, allparents=allparents)
        self.titleChanged.emit(self.title())
        if self.revset:
            self.repoview.resetBrowseHistory(self.revset, self.rev)

    ##
    ## Workbench methods
    ##

    def canGoBack(self):
        return self.repoview.canGoBack()

    def canGoForward(self):
        return self.repoview.canGoForward()

    def loadSettings(self):
        s = QSettings()
        repoid = str(self.repo[0])
        self.revDetailsWidget.loadSettings(s)
        self.filterbar.loadSettings(s)
        self.repotabs_splitter.restoreState(
            s.value('repowidget/splitter-'+repoid).toByteArray())
        QTimer.singleShot(0, lambda: self.toolbarVisibilityChanged.emit())

    def okToContinue(self):
        if not self.commitDemand.canExit():
            self.taskTabsWidget.setCurrentIndex(self.commitTabIndex)
            self.showMessage(_('Commit tab cannot exit'))
            return False
        if not self.syncDemand.canExit():
            self.taskTabsWidget.setCurrentIndex(self.syncTabIndex)
            self.showMessage(_('Sync tab cannot exit'))
            return False
        if 'mq' in self.repo.extensions():
            if not self.mqDemand.canExit():
                self.taskTabsWidget.setCurrentIndex(self.mqTabIndex)
                self.showMessage(_('MQ tab cannot exit'))
                return False
        if not self.grepDemand.canExit():
            self.taskTabsWidget.setCurrentIndex(self.grepTabIndex)
            self.showMessage(_('Search tab cannot exit'))
            return False
        if self.runner.core.running():
            self.showMessage(_('Repository command still running'))
            return False
        return True

    def closeRepoWidget(self):
        '''returns False if close should be aborted'''
        if not self.okToContinue():
            return False
        s = QSettings()
        if self.isVisible():
            try:
                repoid = str(self.repo[0])
                s.setValue('repowidget/splitter-'+repoid,
                           self.repotabs_splitter.saveState())
            except EnvironmentError:
                pass
        self.revDetailsWidget.saveSettings(s)
        self.commitDemand.forward('saveSettings', s, 'workbench')
        self.manifestDemand.forward('saveSettings', s, 'workbench')
        self.grepDemand.forward('saveSettings', s)
        self.filterbar.saveSettings(s)
        self.repoview.saveSettings(s)
        return True

    def incoming(self):
        self.syncDemand.get().incoming()

    def pull(self):
        self.syncDemand.get().pull()
    def outgoing(self):
        self.syncDemand.get().outgoing()
    def push(self, confirm=True, **kwargs):
        """Call sync push.

        If confirm is False, the user will not be prompted for
        confirmation. If confirm is True, the prompt might be used.
        """
        self.syncDemand.get().push(confirm, **kwargs)
        self.outgoingMode = False

    @pyqtSlot()
    def pushCompleted(self):
        if not self.clearRevisionSet():
            self.reload()

    ##
    ## Repoview context menu
    ##

    def viewMenuRequest(self, point, selection):
        'User requested a context menu in repo view widget'

        # selection is a list of the currently selected revisions.
        # Integers for changelog revisions, None for the working copy,
        # or strings for unapplied patches.

        if len(selection) == 0:
            return

        self.menuselection = selection
        if self.bundle:
            if len(selection) == 1:
                self.bundlemenu.exec_(point)
            return
        if self.outgoingMode:
            if len(selection) == 1:
                self.outgoinmcmenu.exec_(point)
                return

        allunapp = False
        if 'mq' in self.repo.extensions():
            for rev in selection:
                if not self.repo.changectx(rev).thgmqunappliedpatch():
                    break
            else:
                allunapp = True
        if allunapp:
            self.unappliedPatchMenu(point, selection)
        elif len(selection) == 1:
            self.singleSelectionMenu(point, selection)
        elif len(selection) == 2:
            self.doubleSelectionMenu(point, selection)
        else:
            self.multipleSelectionMenu(point, selection)

    def singleSelectionMenu(self, point, selection):
        ctx = self.repo.changectx(self.rev)
        applied = ctx.thgmqappliedpatch()
        working = self.rev is None
        tags = ctx.tags()

        for item in self.singlecmenuitems:
            enabled = item.enableFunc(applied, working, tags)
            item.setEnabled(enabled)

        self.singlecmenu.exec_(point)

    def doubleSelectionMenu(self, point, selection):
        for r in selection:
            # No pair menu if working directory or unapplied patch
            if type(r) is not int:
                return
        self.paircmenu.exec_(point)

    def multipleSelectionMenu(self, point, selection):
        for r in selection:
            # No multi menu if working directory or unapplied patch
            if type(r) is not int:
                return
        self.multicmenu.exec_(point)

    def unappliedPatchMenu(self, point, selection):
        q = self.repo.mq
        ispushable = False
        unapplied = 0
        for i in xrange(q.seriesend(), len(q.series)):
            pushable, reason = q.pushable(i)
            if pushable:
                if unapplied == 0:
                    qnext = q.series[i]
                if self.rev == q.series[i]:
                    ispushable = True
                unapplied += 1
        self.unappacts[0].setEnabled(ispushable and len(selection) == 1)
        self.unappacts[1].setEnabled(ispushable and len(selection) == 1 and \
                                     self.rev != qnext)
        self.unappacts[2].setEnabled('qtip' in self.repo.tags())
        self.unappacts[3].setEnabled(True)
        self.unappacts[4].setEnabled(unapplied > 1)
        self.unappacts[5].setEnabled(len(selection) == 1)
        self.unappcmenu.exec_(point)

    def generateSingleMenu(self, mode=None):
        items = []
        # This menu will never be opened for an unapplied patch, they
        # have their own menu.
        #
        # iswd = working directory
        # isrev = the changeset has an integer revision number
        # isctx = changectx or workingctx
        # fixed = the changeset is considered permanent
        # applied = an applied patch
        # qgoto = applied patch or qparent
        isrev   = lambda ap, wd, tags: not wd
        iswd   = lambda ap, wd, tags: bool(wd)
        isctx   = lambda ap, wd, tags: True
        fixed   = lambda ap, wd, tags: not (ap or wd)
        applied = lambda ap, wd, tags: ap
        qgoto   = lambda ap, wd, tags: ('qparent' in tags) or \
                                       (ap)

        exs = self.repo.extensions()

        def entry(menu, ext=None, func=None, desc=None, icon=None, cb=None):
            if ext and ext not in exs:
                return
            if desc is None:
                menu.addSeparator()
                return
            act = QAction(desc, self)
            act.triggered.connect(cb)
            if icon:
                act.setIcon(qtlib.getmenuicon(icon))
            act.enableFunc = func
            menu.addAction(act)
            items.append(act)
        menu = QMenu(self)
        if mode == 'outgoing':
            submenu = menu.addMenu(_('Push'))
            entry(submenu, None, isrev, _('Push all'), 'hg-push',
                  self.pushAll)
            entry(submenu, None, isrev, _('Push to here'), '',
                  self.pushToRevision)
            entry(submenu, None, isrev, _('Push selected branch'), '',
                  self.pushBranch)
            entry(menu)
        entry(menu, None, isrev, _('Update...'), 'hg-update',
              self.updateToRevision)
        entry(menu)
        entry(menu, None, isctx, _('Diff to parent...'), 'visualdiff',
              self.visualDiffRevision)
        entry(menu, None, isrev, _('Diff to local...'), 'ldiff',
              self.visualDiffToLocal)
        entry(menu, None, isctx, _('Browse at rev...'), 'hg-annotate',
              self.manifestRevision)
        entry(menu, None, isrev, _('Similar revisions...'), 'view-filter',
              self.matchRevision)
        entry(menu)
        entry(menu, None, fixed, _('Merge with local...'), 'hg-merge',
              self.mergeWithRevision)
        entry(menu)
        entry(menu, None, fixed, _('Tag...'), 'hg-tag',
              self.tagToRevision)
        entry(menu, None, fixed, _('Bookmark...'), 'hg-bookmarks',
              self.bookmarkRevision)
        entry(menu)
        entry(menu, None, fixed, _('Backout...'), 'hg-revert',
              self.backoutToRevision)
        entry(menu)

        entry(menu, None, isrev, _('Copy hash'), 'copy-hash',
              self.copyHash)
        entry(menu)

        submenu = menu.addMenu(_('Export'))
        entry(submenu, None, isrev, _('Export patch...'), 'hg-export',
              self.exportRevisions)
        entry(submenu, None, isrev, _('Email patch...'), 'mail-forward',
              self.emailRevision)
        entry(submenu, None, isrev, _('Archive...'), 'hg-archive',
              self.archiveRevision)
        entry(submenu, None, isrev, _('Bundle rev and descendants...'),
              'menurelocate', self.bundleRevisions)
        entry(submenu, None, isctx, _('Copy patch'), 'copy-patch',
              self.copyPatch)
        entry(menu)

        submenu = menu.addMenu(_('Change phase to'))
        for pnum, pname in enumerate(phases.phasenames):
            entry(submenu, None, isrev, pname, None,
                  functools.partial(self.changePhase, pnum))
        entry(menu)

        entry(menu, None, fixed, _('Graft to local...'), 'hg-transplant',
              self.graftRevisions)

        if 'mq' in exs or 'rebase' in exs:
            submenu = menu.addMenu(_('Modify history'))
            entry(submenu, 'mq', qgoto, _('Unapply patch (QGoto parent)'), 'hg-qgoto',
                  self.qgotoParentRevision)
            entry(submenu, 'mq', fixed, _('Import to MQ'), 'qimport',
                  self.qimportRevision)
            entry(submenu, 'mq', applied, _('Finish patch'), 'qfinish',
                  self.qfinishRevision)
            entry(submenu, 'mq', applied, _('Rename patch...'), None,
                  self.qrename)
            entry(submenu, 'mq')
            entry(submenu, 'rebase', fixed, _('Rebase...'), 'hg-rebase',
                  self.rebaseRevision)
            entry(submenu, 'rebase')
            entry(submenu, 'mq', fixed, _('Strip...'), 'menudelete',
                  self.stripRevision)

        entry(menu, 'reviewboard', fixed, _('Post to Review Board...'), 'reviewboard',
              self.sendToReviewBoard)

        entry(menu, 'rupdate', fixed, _('Remote Update...'), 'hg-update',
              self.rupdate)

        def _setupCustomSubmenu(menu):
            tools, toollist = hglib.tortoisehgtools(self.repo.ui,
                selectedlocation='workbench.revdetails.custom-menu')
            if not tools:
                return

            istrue = lambda ap, wd, tags: True
            enablefuncs = {
                'istrue': istrue, 'iswd': iswd, 'isrev': isrev, 'isctx': isctx,
                'fixed': fixed, 'applied': applied, 'qgoto': qgoto
            }

            entry(menu)
            submenu = menu.addMenu(_('Custom Tools'))
            for name in toollist:
                if name == '|':
                    entry(submenu)
                    continue
                info = tools.get(name, None)
                if info is None:
                    continue
                command = info.get('command', None)
                if not command:
                    continue
                showoutput = info.get('showoutput', False)
                label = info.get('label', name)
                icon = info.get('icon', 'tools-spanner-hammer')
                enable = info.get('enable', 'istrue').lower()
                if enable in enablefuncs:
                    enable = enablefuncs[enable]
                else:
                    continue
                menufunc = functools.partial(self.runCustomCommand, command,
                    showoutput)
                entry(submenu, None, enable, label, icon, menufunc)

        _setupCustomSubmenu(menu)

        if mode == 'outgoing':
            self.outgoinmcmenu = menu
            self.outgoinmcmenuitems = items
        else:
            self.singlecmenu = menu
            self.singlecmenuitems = items

    def _gotoAncestor(self):
        ancestor = self.repo[self.menuselection[0]]
        for rev in self.menuselection[1:]:
            ctx = self.repo[rev]
            ancestor = ancestor.ancestor(ctx)
        self.goto(ancestor.rev())

    def generatePairMenu(self):
        def dagrange():
            revA, revB = self.menuselection
            if revA > revB:
                B, A = self.menuselection
            else:
                A, B = self.menuselection
            func = revset.match(self.repo.ui, '%s::%s' % (A, B))
            return [c for c in func(self.repo, range(len(self.repo)))]

        def exportPair():
            self.exportRevisions(self.menuselection)
        def exportDiff():
            root = self.repo.root
            filename = '%s_%d_to_%d.diff' % (os.path.basename(root),
                                             self.menuselection[0],
                                             self.menuselection[1])
            file = QFileDialog.getSaveFileName(self, _('Write diff file'),
                               hglib.tounicode(os.path.join(root, filename)))
            if not file:
                return
            diff = self.copyPatch(returnval=True)
            try:
                f = open(file, "wb")
                try:
                    f.write(diff)
                finally:
                    f.close()
            except Exception, e:
                WarningMsgBox(_('Repository Error'),
                              _('Unable to write diff file'))
        def exportDagRange():
            l = dagrange()
            if l:
                self.exportRevisions(l)
        def diffPair():
            revA, revB = self.menuselection
            dlg = visdiff.visualdiff(self.repo.ui, self.repo, [],
                    {'rev':(str(revA), str(revB))})
            if dlg:
                dlg.exec_()
        def emailPair():
            run.email(self.repo.ui, rev=self.menuselection, repo=self.repo)
        def emailDagRange():
            l = dagrange()
            if l:
                run.email(self.repo.ui, rev=l, repo=self.repo)
        def bundleDagRange():
            l = dagrange()
            if l:
                self.bundleRevisions(base=l[0], tip=l[-1])
        def bisectNormal():
            revA, revB = self.menuselection
            opts = {'good':str(revA), 'bad':str(revB)}
            dlg = bisect.BisectDialog(self.repo, opts, self)
            dlg.finished.connect(dlg.deleteLater)
            dlg.exec_()
        def bisectReverse():
            revA, revB = self.menuselection
            opts = {'good':str(revB), 'bad':str(revA)}
            dlg = bisect.BisectDialog(self.repo, opts, self)
            dlg.finished.connect(dlg.deleteLater)
            dlg.exec_()
        def compressDlg():
            ctxa = self.repo[self.menuselection[0]]
            ctxb = self.repo[self.menuselection[1]]
            if ctxa.ancestor(ctxb) == ctxb:
                revs = self.menuselection[:]
            elif ctxa.ancestor(ctxb) == ctxa:
                revs = [self.menuselection[1], self.menuselection[0]]
            else:
                InfoMsgBox(_('Unable to compress history'),
                           _('Selected changeset pair not related'))
                return
            dlg = compress.CompressDialog(self.repo, revs, self)
            dlg.finished.connect(dlg.deleteLater)
            dlg.exec_()

        menu = QMenu(self)
        for name, cb, icon in (
                (_('Visual Diff...'), diffPair, 'visualdiff'),
                (_('Export Diff...'), exportDiff, 'hg-export'),
                (None, None, None),
                (_('Export Selected...'), exportPair, 'hg-export'),
                (_('Email Selected...'), emailPair, 'mail-forward'),
                (None, None, None),
                (_('Export DAG Range...'), exportDagRange, 'hg-export'),
                (_('Email DAG Range...'), emailDagRange, 'mail-forward'),
                (_('Bundle DAG Range...'), bundleDagRange, 'menurelocate'),
                (None, None, None),
                (_('Bisect - Good, Bad...'), bisectNormal, 'hg-bisect-good-bad'),
                (_('Bisect - Bad, Good...'), bisectReverse, 'hg-bisect-bad-good'),
                (_('Compress History...'), compressDlg, 'hg-compress'),
                (None, None, None),
                (_('Goto common ancestor'), self._gotoAncestor, 'hg-merge'),
                (_('Similar revisions...'), self.matchRevision, 'view-filter'),
                (None, None, None),
                (_('Graft Selected to local...'), self.graftRevisions, 'hg-transplant'),
                ):
            if name is None:
                menu.addSeparator()
                continue
            a = QAction(name, self)
            if icon:
                a.setIcon(qtlib.getmenuicon(icon))
            a.triggered.connect(cb)
            menu.addAction(a)

        if 'reviewboard' in self.repo.extensions():
            menu.addSeparator()
            a = QAction(_('Post Selected to Review Board...'), self)
            a.triggered.connect(self.sendToReviewBoard)
            menu.addAction(a)
        self.paircmenu = menu

    def generateUnappliedPatchMenu(self):
        def qdeleteact():
            """Delete unapplied patch(es)"""
            dlg = qdelete.QDeleteDialog(self.repo, self.menuselection, self)
            dlg.finished.connect(dlg.deleteLater)
            dlg.output.connect(self.output)
            dlg.makeLogVisible.connect(self.makeLogVisible)
            dlg.exec_()
        def qreorderact():
            def checkGuardsOrComments():
                cont = True
                for p in self.repo.mq.fullseries:
                    if '#' in p:
                        cont = QuestionMsgBox('Confirm qreorder',
                                _('<p>ATTENTION!<br>'
                                  'Guard or comment found.<br>'
                                  'Reordering patches will destroy them.<br>'
                                  '<br>Continue?</p>'), parent=self,
                                  defaultbutton=QMessageBox.No)
                        break
                return cont
            if checkGuardsOrComments():
                dlg = qreorder.QReorderDialog(self.repo, self)
                dlg.finished.connect(dlg.deleteLater)
                dlg.exec_()
        def qfoldact():
            dlg = qfold.QFoldDialog(self.repo, self.menuselection, self)
            dlg.finished.connect(dlg.deleteLater)
            dlg.output.connect(self.output)
            dlg.makeLogVisible.connect(self.makeLogVisible)
            dlg.exec_()

        menu = QMenu(self)
        acts = []
        for name, cb, icon in (
            (_('Apply patch (QGoto)'), self.qgotoSelectedRevision, 'hg-qgoto'),
            (_('QPush --move'), self.qpushMoveRevision, 'hg-qpush'),
            (_('Fold patches...'), qfoldact, 'hg-qfold'),
            (_('Delete patches...'), qdeleteact, 'hg-qdelete'),
            (_('Reorder patches...'), qreorderact, 'hg-qreorder'),
            (_('Rename patch...'), self.qrename, None)):
            act = QAction(name, self)
            act.triggered.connect(cb)
            if icon:
                act.setIcon(qtlib.getmenuicon(icon))
            acts.append(act)
            menu.addAction(act)
        self.unappcmenu = menu
        self.unappacts = acts

    def generateMultipleSelectionMenu(self):
        def exportSel():
            self.exportRevisions(self.menuselection)
        def emailSel():
            run.email(self.repo.ui, rev=self.menuselection, repo=self.repo)
        menu = QMenu(self)
        for name, cb, icon in (
                (_('Export Selected...'), exportSel, 'hg-export'),
                (_('Email Selected...'), emailSel, 'mail-forward'),
                (None, None, None),
                (_('Goto common ancestor'), self._gotoAncestor, 'hg-merge'),
                (_('Similar revisions...'), self.matchRevision, 'view-filter'),
                (None, None, None),
                (_('Graft Selected to local...'), self.graftRevisions, 'hg-transplant'),
                ):
            if name is None:
                menu.addSeparator()
                continue
            a = QAction(name, self)
            if icon:
                a.setIcon(qtlib.getmenuicon(icon))
            a.triggered.connect(cb)
            menu.addAction(a)

        if 'reviewboard' in self.repo.extensions():
            a = QAction(_('Post Selected to Review Board...'), self)
            a.triggered.connect(self.sendToReviewBoard)
            menu.addAction(a)
        self.multicmenu = menu

    def generateBundleMenu(self):
        menu = QMenu(self)
        for name, cb, icon in (
                (_('Pull to here...'), self.pullBundleToRev, 'hg-pull-to-here'),
                (_('Visual diff...'), self.visualDiffRevision, 'visualdiff'),
                ):
            a = QAction(name, self)
            a.triggered.connect(cb)
            if icon:
                a.setIcon(qtlib.getmenuicon(icon))
            menu.addAction(a)
        self.bundlemenu = menu
    def generateOutgoingMenu(self):
        self.generateSingleMenu(mode='outgoing')

    def exportRevisions(self, revisions):
        if not revisions:
            revisions = [self.rev]
        if len(revisions) == 1:
            if isinstance(self.rev, int):
                defaultpath = self.repo.wjoin('%d.patch' % self.rev)
            else:
                defaultpath = self.repo.root

            ret = QFileDialog.getSaveFileName(self, _('Export patch'),
                                              hglib.tounicode(defaultpath),
                                              _('Patch Files (*.patch)'))
            if not ret:
                return
            epath = hglib.fromunicode(ret)
            strdir = os.path.dirname(epath)
            udir = hglib.tounicode(strdir)
            custompath = True
        else:
            udir = QFileDialog.getExistingDirectory(self, _('Export patch'),
                                                   hglib.tounicode(self.repo.root))
            if not udir:
                return
            strdir = hglib.fromunicode(udir)
            epath = os.path.join(strdir,
                                 hglib.fromunicode(self.repo.shortname)+'_%r.patch')
            custompath = False

        cmdline = ['export', '--repository', self.repo.root, '--verbose',
                   '--output', epath]

        existingRevisions = []
        for rev in revisions:
            if custompath:
                path = epath
            else:
                path = epath % rev
            if os.path.exists(path):
                if os.path.isfile(path):
                    existingRevisions.append(rev)
                else:
                    QMessageBox.warning(self,
                        _('Cannot export revision'),
                        (_('Cannot export revision %s into the file named:'
                        '\n\n%s\n') % (rev, hglib.tounicode(epath % rev))) + \
                        _('There is already an existing folder '
                        'with that same name.'))
                    return
            cmdline.extend(['--rev', str(rev)])

        if existingRevisions:
            buttonNames = [_("Replace"), _("Append"), _("Abort")]

            warningMessage = \
                _('There are existing patch files for %d revisions (%s) '
                'in the selected location (%s).\n\n') \
                % (len(existingRevisions),
                    " ,".join([str(rev) for rev in existingRevisions]),
                    udir)

            warningMessage += \
                _('What do you want to do?\n') + u'\n' + \
                u'- ' + _('Replace the existing patch files.\n') + \
                u'- ' + _('Append the changes to the existing patch files.\n') + \
                u'- ' + _('Abort the export operation.\n')

            res = qtlib.CustomPrompt(_('Patch files already exist'),
                warningMessage,
                self,
                buttonNames, 0, 2).run()

            if buttonNames[res] == _("Replace"):
                # Remove the existing patch files
                for rev in existingRevisions:
                    if custompath:
                        os.remove(epath)
                    else:
                        os.remove(epath % rev)
            elif buttonNames[res] == _("Abort"):
                return

        self.runCommand(cmdline)

        if len(revisions) == 1:
            # Show a message box with a link to the export folder and to the
            # exported file
            rev = revisions[0]
            patchfilename = os.path.normpath(epath)
            patchdirname = os.path.normpath(os.path.dirname(epath))
            patchshortname = os.path.basename(patchfilename)
            if patchdirname.endswith(os.path.sep):
                patchdirname = patchdirname[:-1]
            qtlib.InfoMsgBox(_('Patch exported'),
                _('Revision #%d (%s) was exported to:<p>'
                '<a href="file:///%s">%s</a>%s'
                '<a href="file:///%s">%s</a>') \
                % (rev, str(self.repo[rev]),
                hglib.tounicode(patchdirname), hglib.tounicode(patchdirname), os.path.sep,
                hglib.tounicode(patchfilename), hglib.tounicode(patchshortname)))
        else:
            # Show a message box with a link to the export folder
            qtlib.InfoMsgBox(_('Patches exported'),
                _('%d patches were exported to:<p>'
                '<a href="file:///%s">%s</a>') \
                % (len(revisions),
                hglib.tounicode(strdir),
                hglib.tounicode(strdir)))

    def visualDiffRevision(self):
        opts = dict(change=self.rev)
        dlg = visdiff.visualdiff(self.repo.ui, self.repo, [], opts)
        if dlg:
            dlg.exec_()
            dlg.deleteLater()

    def visualDiffToLocal(self):
        if self.rev is None:
            return
        opts = dict(rev=['rev(%d)' % self.rev])
        dlg = visdiff.visualdiff(self.repo.ui, self.repo, [], opts)
        if dlg:
            dlg.exec_()
            dlg.deleteLater()

    def updateToRevision(self):
        dlg = update.UpdateDialog(self.repo, self.rev, self)
        dlg.output.connect(self.output)
        dlg.makeLogVisible.connect(self.makeLogVisible)
        dlg.progress.connect(self.progress)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def matchRevision(self):
        hasmatching = True
        try:
            # hg >= 2.2
            from mercurial.revset import matching as matchingkeyword
        except:
            hasmatching = False
        if hasmatching:
            revlist = self.rev
            if len(self.menuselection) > 1:
                revlist = '|'.join([str(rev) for rev in self.menuselection])
            dlg = matching.MatchDialog(self.repo, revlist, self)
            if dlg.exec_():
                self.setFilter(dlg.revsetexpression)
        else:
            # We cannot find similar revisions
            # without the matching revset keyword
            qtlib.WarningMsgBox(_('Incorrect Mercurial version'),
                _('In order to use the "Find Similar revisions" '
                'functionality, you must use a mercurial version above 2.1.'))

    def pushAll(self):
        self.syncDemand.forward('push', False, pushall=True)

    def pushToRevision(self):
        # Do not ask for confirmation
        self.syncDemand.forward('push', False, rev=self.rev)

    def pushBranch(self):
        # Do not ask for confirmation
        self.syncDemand.forward('push', False,
            branch=self.repo[self.rev].branch())

    def manifestRevision(self):
        run.manifest(self.repo.ui, repo=self.repo, rev=self.rev)

    def mergeWithRevision(self):
        dlg = merge.MergeDialog(self.rev, self.repo, self)
        dlg.exec_()
        dlg.deleteLater()

    def tagToRevision(self):
        dlg = tag.TagDialog(self.repo, rev=str(self.rev), parent=self)
        dlg.showMessage.connect(self.showMessage)
        dlg.output.connect(self.output)
        dlg.makeLogVisible.connect(self.makeLogVisible)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def bookmarkRevision(self):
        dlg = bookmark.BookmarkDialog(self.repo, self.rev, self)
        dlg.showMessage.connect(self.showMessage)
        dlg.output.connect(self.output)
        dlg.makeLogVisible.connect(self.makeLogVisible)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def graftRevisions(self):
        """Graft selected revision on top of working directory parent"""
        revlist = []
        for rev in sorted(self.repoview.selectedRevisions()):
            revlist.append(str(rev))
        if not revlist:
            revlist = [self.rev]
        opts = {'source' : revlist, 'dest': self.repo['.'].rev()}
        dlg = graft.GraftDialog(self.repo, self, **opts)
        dlg.finished.connect(dlg.deleteLater)
        if dlg.valid:
            dlg.exec_()

    def backoutToRevision(self):
        dlg = backout.BackoutDialog(self.rev, self.repo, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def stripRevision(self):
        'Strip the selected revision and all descendants'
        dlg = thgstrip.StripDialog(self.repo, rev=str(self.rev), parent=self)
        dlg.showBusyIcon.connect(self.onShowBusyIcon)
        dlg.hideBusyIcon.connect(self.onHideBusyIcon)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def sendToReviewBoard(self):
        run.postreview(self.repo.ui, rev=self.repoview.selectedRevisions(),
          repo=self.repo)

    def rupdate(self):
        import rupdate
        dlg = rupdate.rUpdateDialog(self.repo, self.rev, self)
        dlg.output.connect(self.output)
        dlg.makeLogVisible.connect(self.makeLogVisible)
        dlg.progress.connect(self.progress)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def emailRevision(self):
        run.email(self.repo.ui, rev=self.repoview.selectedRevisions(),
                  repo=self.repo)

    def archiveRevision(self):
        dlg = archive.ArchiveDialog(self.repo.ui, self.repo, self.rev, self)
        dlg.makeLogVisible.connect(self.makeLogVisible)
        dlg.output.connect(self.output)
        dlg.progress.connect(self.progress)
        dlg.exec_()

    def bundleRevisions(self, base=None, tip=None):
        root = self.repo.root
        if base is None or base is False:
            base = self.rev
        data = dict(name=os.path.basename(root), base=base)
        if tip is None:
            filename = '%(name)s_%(base)s_and_descendants.hg' % data
        else:
            data.update(rev=tip)
            filename = '%(name)s_%(base)s_to_%(rev)s.hg' % data

        file = QFileDialog.getSaveFileName(self, _('Write bundle'),
                           hglib.tounicode(os.path.join(root, filename)))
        if not file:
            return

        cmdline = ['bundle', '--verbose', '--repository', root]
        parents = [r.rev() == -1 and 'null' or str(r.rev())
                   for r in self.repo[base].parents()]
        for p in parents:
            cmdline.extend(['--base', p])
        if tip:
            cmdline.extend(['--rev', str(tip)])
        else:
            cmdline.extend(['--rev', 'heads(descendants(%s))' % base])
        cmdline.append(hglib.fromunicode(file))
        self.runCommand(cmdline)

    def copyPatch(self, returnval=False):
        from mercurial import commands
        _ui = self.repo.ui
        _ui.pushbuffer()
        try:
            if self.rev and len(self.menuselection) == 1:
                class Writable(object):
                    def write(self, *args, **opts): _ui.write(*args, **opts)
                    def close(self): pass
                commands.export(_ui, self.repo, self.rev, output=Writable())
            else:
                revs = self.rev and self.menuselection or None
                commands.diff(_ui, self.repo, rev=revs)
        except NameError:
            raise
        except Exception, e:
            _ui.popbuffer()
            self.showMessage(hglib.tounicode(str(e)))
            if 'THGDEBUG' in os.environ:
                import traceback
                traceback.print_exc()
            return
        output = _ui.popbuffer()
        if returnval:
            return output
        else:
            QApplication.clipboard().setText(hglib.tounicode(output))

    def copyHash(self):
        clip = QApplication.clipboard()
        clip.setText(binascii.hexlify(self.repo[self.rev].node()))

    def changePhase(self, phase):
        currentphase = self.repo[self.rev].phase()
        if currentphase == phase:
            # There is nothing to do, we are already in the target phase
            return
        phasestr = phases.phasenames[phase]
        cmdlines = ['phase', '--rev', '%s' % self.rev,
               '--repository', self.repo.root,
               ('--%s' % phasestr)]
        if currentphase < phase:
            # Ask the user if he wants to force the transition
            title = _('Backwards phase change requested')
            main = _('Do you really want to <i>force</i> a backwards phase transition?')
            text = _('You are trying to move the phase of revision %d backwards,\n'
                    'from "<i>%s</i>" to "<i>%s</i>".\n\n'
                    'However, "<i>%s</i>" is a lower phase level than "<i>%s</i>".\n\n'
                    'Moving the phase backwards is not recommended.\n'
                    'For example, it may result in having multiple heads\nif you '
                    'modify a revision that you have already pushed\nto a server.\n\n'
                    'Please be careful!') % (self.rev, phases.phasenames[currentphase], phasestr, phasestr,
                                            phases.phasenames[currentphase])
            labels = ((QMessageBox.Yes, _('&Force')),
                      (QMessageBox.No, _('&Cancel')))
            if not qtlib.QuestionMsgBox(title, main, text,
                    labels=labels, parent=self):
                return
            cmdlines.append('--force')
        self.runCommand(cmdlines)
        self.reload()

    def rebaseRevision(self):
        """Rebase selected revision on top of working directory parent"""
        opts = {'source' : self.rev, 'dest': self.repo['.'].rev()}
        dlg = rebase.RebaseDialog(self.repo, self, **opts)
        dlg.finished.connect(dlg.deleteLater)
        dlg.exec_()

    def qimportRevision(self):
        """QImport revision and all descendents to MQ"""
        if 'qparent' in self.repo.tags():
            endrev = 'qparent'
        else:
            endrev = ''

        # Check whether there are existing patches in the MQ queue whose name
        # collides with the revisions that are going to be imported
        func = revset.match(self.repo.ui, '%s::%s' % (self.rev, endrev))
        revList = [c for c in func(self.repo, range(len(self.repo)))]

        if endrev and not revList:
            # There is a qparent but the revision list is empty
            # This means that the qparent is not a descendant of the
            # selected revision
            QMessageBox.warning(self, _('Cannot import selected revision'),
                _('The selected revision (rev #%d) cannot be imported '
                'because it is not a descendant of ''qparent'' (rev #%d)') \
                % (self.rev, self.repo['qparent'].rev()))
            return

        patchdir = self.repo.join('patches')
        def patchExists(p):
            return os.path.exists(os.path.join(patchdir, p))

        # Note that the following two arrays are both ordered by "rev"
        defaultPatchNames = ['%d.diff' % rev for rev in revList]
        defaultPatchesExist = [patchExists(p) for p in defaultPatchNames]
        if any(defaultPatchesExist):
            # We will qimport each revision one by one, starting from the newest
            # To do so, we will find a valid and unique patch name for each
            # revision that we must qimport (i.e. a filename that does not
            # already exist)
            # and then we will import them one by one starting from the newest
            # one, using these unique names
            def getUniquePatchName(baseName):
                maxRetries = 99
                for n in range(1, maxRetries):
                    patchName = baseName + '_%02d.diff' % n
                    if not patchExists(patchName):
                        return patchName
                return baseName

            patchNames = {}
            for n, rev in enumerate(revList):
                if defaultPatchesExist[n]:
                    patchNames[rev] = getUniquePatchName(str(rev))
                else:
                    # The default name is safe
                    patchNames[rev] = defaultPatchNames[n]

            # qimport each revision individually, starting from the topmost one
            revList.reverse()
            cmdlines = []
            for rev in revList:
                cmdlines.append(['qimport', '--rev', '%s' % rev,
                           '--repository', self.repo.root,
                           '--name', patchNames[rev]])
            self.runCommand(*cmdlines)
        else:
            # There were no collisions with existing patch names, we can
            # simply qimport the whole revision set in a single go
            cmdline = ['qimport', '--rev', '%s::%s' % (self.rev, endrev),
                       '--repository', self.repo.root]
            self.runCommand(cmdline)

    def qfinishRevision(self):
        """Finish applied patches up to and including selected revision"""
        cmdline = ['qfinish', 'qbase::%s' % self.rev,
                   '--repository', self.repo.root]
        self.runCommand(cmdline)

    def qgotoParentRevision(self):
        """Apply an unapplied patch, or qgoto the parent of an applied patch"""
        self.qgotoRevision(self.rev, unapplySelected=True)

    def qgotoSelectedRevision(self):
        self.qgotoRevision(self.rev, unapplySelected=False)

    def qgotoRevision(self, rev, unapplySelected=True):
        """Make REV the top applied patch"""
        # If unapplySelected is true and rev is an applied patch
        # it will be unapplied (qgoto its parent)
        # Otherwise, qgoto the selected revision
        def qpopAll(repo):
            cmdline = ['qpop', '--all', '--repository', repo.root]
            self.runCommand(cmdline)

        ctx = self.repo.changectx(self.rev)
        if 'qparent'in ctx.tags():
            return qpopAll(self.repo)
        try:
            applied = ctx.thgmqappliedpatch()
            mqpatch = True
        except:
            applied = True
            mqpatch = False

        if unapplySelected and mqpatch and applied and 'qparent' in ctx.p1().tags():
            return qpopAll(self.repo)

        if not applied:
            patchname = self.repo.changectx(self.rev).thgmqpatchname()
        else:
            if unapplySelected:
                thgp = self.repo.changectx(self.repo.changectx(self.rev).p1().node())
            else:
                thgp = self.repo.changectx(self.repo.changectx(self.rev).node())
            patchname = thgp.thgmqpatchname()
        self.taskTabsWidget.setCurrentIndex(self.mqTabIndex)
        self.mqDemand.forward('qgotoRevision', patchname)

    def qrename(self):
        sel = self.menuselection[0]
        if not isinstance(sel, str):
            sel = self.repo.changectx(sel).thgmqpatchname()
        dlg = qrename.QRenameDialog(self.repo, sel, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.output.connect(self.output)
        dlg.makeLogVisible.connect(self.makeLogVisible)
        dlg.exec_()

    def qpushMoveRevision(self):
        """Make REV the top applied patch"""
        ctx = self.repo.changectx(self.rev)
        patchname = ctx.thgmqpatchname()
        cmdline = ['qpush', '--move', str(patchname),
                   '--repository', self.repo.root]
        self.runCommand(cmdline)

    def onCommandFinished(self, ret):
        self.repo.decrementBusyCount()
        shlib.shell_notify([self.repo.root])


    def runCustomCommand(self, command, showoutput=False):
        """Execute 'custom commands', on the selected repository"""
        # Perform variable expansion
        # This is done in two steps:
        # 1. Expand environment variables
        command = os.path.expandvars(command).strip()
        if not command:
            InfoMsgBox(_('Invalid command'),
                       _('The selected command is empty'))
            return

        # 2. Expand internal workbench variables
        vars = {
            'ROOT': self.repo.root,
            'REVID': str(self.repo[self.rev]),
            'REV': self.rev
        }
        for var in vars:
            command = command.replace('{%s}' % var, str(vars[var]))

        # Show the Output Log if configured to do so
        if showoutput:
            self.makeLogVisible.emit(True)

        # If the use wants to run mercurial, do so via our usual runCommand method
        cmd = shlex.split(command)
        if cmd[0].lower() == 'hg':
            cmd = cmd[1:]
            if '--repository' not in cmd:
                cmd += ['--repository', self.repo.root]
            return self.runCommand(cmd)

        # Otherwise, run the selected command in the brackground
        try:
            res = subprocess.Popen(command, cwd=self.repo.root)
        except OSError, ex:
            res = 1
            qtlib.ErrorMsgBox(_('Failed to execute custom command'),
                _('The command "%s" could not be executed.') % hglib.tounicode(command),
                _('The following error message was returned:\n\n"%s"\n\n'
                'Please check that the command path is valid and '
                'that it is a valid application') % hglib.tounicode(ex.strerror))
        return res

    def runCommand(self, *cmdlines):
        if self.runner.core.running():
            InfoMsgBox(_('Unable to start'),
                       _('Previous command is still running'))
            return
        self.repo.incrementBusyCount()
        self.runner.run(*cmdlines)

    @pyqtSlot()
    def _refreshCommitTabIfNeeded(self):
        """Refresh the Commit tab if the user settings require it"""
        if self.taskTabsWidget.currentIndex() != self.commitTabIndex:
            return

        refreshwd = self.repo.ui.config('tortoisehg', 'refreshwdstatus', 'auto')
        # Valid refreshwd values are 'auto', 'always' and 'alwayslocal'
        if refreshwd != 'auto':
            if refreshwd == 'always' \
                    or not paths.netdrive_status(self.repo.root):
                self.commitDemand.forward('refreshWctx')
