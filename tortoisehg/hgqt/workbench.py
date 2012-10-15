# workbench.py - main TortoiseHg Window
#
# Copyright (C) 2007-2010 Logilab. All rights reserved.
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.
"""
Main Qt4 application for TortoiseHg
"""

import os
import sys
import getpass # used to get the username on the workbench server
from mercurial import ui, util
from mercurial.error import RepoError
from tortoisehg.util import paths, hglib

from tortoisehg.hgqt import thgrepo, cmdui, qtlib, mq
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt.repowidget import RepoWidget
from tortoisehg.hgqt.reporegistry import RepoRegistryView
from tortoisehg.hgqt.logcolumns import ColumnSelectDialog
from tortoisehg.hgqt.docklog import LogDockWidget
from tortoisehg.hgqt.settings import SettingsDialog
from tortoisehg.hgqt.run import portable_start_fork

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.QtNetwork import QLocalServer, QLocalSocket

class ThgTabBar(QTabBar):
    def mouseReleaseEvent(self, event):

        if event.button() == Qt.MidButton:
            self.tabCloseRequested.emit(self.tabAt(event.pos()))

        super(ThgTabBar, self).mouseReleaseEvent(event)

class Workbench(QMainWindow):
    """hg repository viewer/browser application"""
    finished = pyqtSignal(int)
    activeRepoChanged = pyqtSignal(QString)

    def __init__(self, createserver=False):
        QMainWindow.__init__(self)
        self.progressDialog = QProgressDialog('TortoiseHg - Initializing Workbench', QString(), 0, 100)
        self.progressDialog.setAutoClose(False)

        self.ui = ui.ui()

        self.setupUi()
        self.setWindowTitle(_('TortoiseHg Workbench'))
        self.reporegistry = rr = RepoRegistryView(self)
        rr.setObjectName('RepoRegistryView')
        rr.showMessage.connect(self.showMessage)
        rr.openRepo.connect(self.openRepo)
        rr.removeRepo.connect(self.removeRepo)
        rr.progressReceived.connect(self.progress)
        rr.hide()
        self.addDockWidget(Qt.LeftDockWidgetArea, rr)
        self.activeRepoChanged.connect(rr.setActiveTabRepo)

        self.mqpatches = p = mq.MQPatchesWidget(self)
        p.setObjectName('MQPatchesWidget')
        p.showMessage.connect(self.showMessage)
        p.hide()
        self.addDockWidget(Qt.LeftDockWidgetArea, p)

        self.log = LogDockWidget(self)
        self.log.setObjectName('Log')
        self.log.progressReceived.connect(self.statusbar.progress)
        self.log.hide()
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log)

        self._setupActions()

        self.restoreSettings()
        self.repoTabChanged()
        self.setAcceptDrops(True)
        if os.name == 'nt':
            # Allow CTRL+Q to close Workbench on Windows
            QShortcut(QKeySequence('CTRL+Q'), self, self.close)
        if sys.platform == 'darwin':
            self.dockMenu = QMenu(self)
            self.dockMenu.addAction(_('New Workbench...'),
                                    self.newWorkbench)
            self.dockMenu.addAction(_('New Repository...'),
                                    self.newRepository)
            self.dockMenu.addAction(_('Clone Repository...'),
                                    self.cloneRepository)
            self.dockMenu.addAction(_('Open Repository...'),
                                    self.openRepository)
            qt_mac_set_dock_menu(self.dockMenu)

        # Create the actions that will be displayed on the context menu
        self.createActions()
        self.lastClosedRepoRootList = []
        self.progressDialog.close()
        self.progressDialog = None

        self.server = None
        if createserver:
            # Enable the Workbench Server that is used to maintain a single workbench instance
            self.createWorkbenchServer()

    def setupUi(self):
        desktopgeom = qApp.desktop().availableGeometry()
        self.resize(desktopgeom.size() * 0.8)

        self.setWindowIcon(qtlib.geticon('hg-log'))

        self.repoTabsWidget = tw = QTabWidget()
        # FIXME setTabBar() is protected method
        tw.setTabBar(ThgTabBar())
        tw.setDocumentMode(True)
        tw.setTabsClosable(True)
        tw.setMovable(True)
        tw.tabBar().hide()
        tw.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        tw.tabBar().customContextMenuRequested.connect(self.tabBarContextMenuRequest)
        tw.lastClickedTab = -1 # No tab clicked yet

        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sp.setHorizontalStretch(1)
        sp.setVerticalStretch(1)
        sp.setHeightForWidth(tw.sizePolicy().hasHeightForWidth())
        tw.setSizePolicy(sp)
        tw.tabCloseRequested.connect(self.repoTabCloseRequested)
        tw.currentChanged.connect(self.repoTabChanged)

        self.setCentralWidget(tw)
        self.statusbar = cmdui.ThgStatusBar(self)
        self.setStatusBar(self.statusbar)

    def _setupActions(self):
        """Setup actions, menus and toolbars"""
        self.menubar = QMenuBar(self)
        self.setMenuBar(self.menubar)

        self.menuFile = self.menubar.addMenu(_("&File"))
        self.menuView = self.menubar.addMenu(_("&View"))
        self.menuViewregistryopts = QMenu(_('Workbench Toolbars'), self)
        self.menuRepository = self.menubar.addMenu(_("&Repository"))
        self.menuHelp = self.menubar.addMenu(_("&Help"))

        self.edittbar = QToolBar(_("Edit Toolbar"), objectName='edittbar')
        self.addToolBar(self.edittbar)
        self.docktbar = QToolBar(_("Dock Toolbar"), objectName='docktbar')
        self.addToolBar(self.docktbar)
        self.synctbar = QToolBar(_('Sync Toolbar'), objectName='synctbar')
        self.addToolBar(self.synctbar)
        self.tasktbar = QToolBar(_('Task Toolbar'), objectName='taskbar')
        self.addToolBar(self.tasktbar)
        self.customtbar = QToolBar(_('Custom Toolbar'), objectName='custombar')
        self.addToolBar(self.customtbar)

        # availability map of actions; applied by updateMenu()
        self._actionavails = {'repoopen': []}
        self._actionvisibles = {'repoopen': []}

        modifiedkeysequence = qtlib.modifiedkeysequence
        newaction = self._addNewAction
        newseparator = self._addNewSeparator

        newaction(_("New &Workbench..."), self.newWorkbench,
                  shortcut='Shift+Ctrl+W', menu='file', icon='hg-log')
        newseparator(menu='file')
        newaction(_("&New Repository..."), self.newRepository,
                  shortcut='New', menu='file', icon='hg-init')
        newaction(_("Clone Repository..."), self.cloneRepository,
                  shortcut=modifiedkeysequence('New', modifier='Shift'),
                  menu='file', icon='hg-clone')
        newseparator(menu='file')
        newaction(_("&Open Repository..."), self.openRepository,
                  shortcut='Open', menu='file')
        newaction(_("&Close Repository"), self.closeRepository,
                  shortcut='Close', enabled='repoopen', menu='file')
        newseparator(menu='file')
        newaction(_('&Settings...'), self.editSettings, icon='settings_user',
                  shortcut='Preferences', menu='file')
        newseparator(menu='file')
        newaction(_("E&xit"), self.close, shortcut='Quit', menu='file')

        a = self.reporegistry.toggleViewAction()
        a.setText(_('Show Repository Registry'))
        a.setShortcut('Ctrl+Shift+O')
        a.setIcon(qtlib.geticon('thg-reporegistry'))
        self.docktbar.addAction(a)
        self.menuView.addAction(a)

        a = self.mqpatches.toggleViewAction()
        a.setText(_('Show Patch Queue'))
        a.setIcon(qtlib.geticon('thg-mq'))
        self.docktbar.addAction(a)
        self.menuView.addAction(a)

        a = self.log.toggleViewAction()
        a.setText(_('Show Output &Log'))
        a.setShortcut('Ctrl+L')
        a.setIcon(qtlib.geticon('thg-console'))
        self.docktbar.addAction(a)
        self.menuView.addAction(a)

        newseparator(menu='view')
        self.menuViewregistryopts = self.menuView.addMenu(_('Repository Registry Options'))
        self.actionShowPaths = \
        newaction(_("Show Paths"), self.reporegistry.showPaths,
                  checkable=True, menu='viewregistryopts')

        self.actionShowSubrepos = \
            newaction(_("Show Subrepos on Registry"),
                self.reporegistry.setShowSubrepos,
                  checkable=True, menu='viewregistryopts')

        self.actionShowNetworkSubrepos = \
            newaction(_("Show Subrepos for remote repositories"),
                self.reporegistry.setShowNetworkSubrepos,
                  checkable=True, menu='viewregistryopts')

        self.actionShowShortPaths = \
            newaction(_("Show Short Paths"),
                self.reporegistry.setShowShortPaths,
                  checkable=True, menu='viewregistryopts')

        newseparator(menu='view')
        newaction(_("Choose Log Columns..."), self.setHistoryColumns,
                  menu='view')
        self.actionSaveRepos = \
        newaction(_("Save Open Repositories On Exit"), checkable=True,
                  menu='view')
        newseparator(menu='view')

        self.actionGroupTaskView = QActionGroup(self)
        self.actionGroupTaskView.triggered.connect(self.onSwitchRepoTaskTab)
        def addtaskview(icon, label, name):
            a = newaction(label, icon=None, checkable=True, data=name,
                          enabled='repoopen', menu='view')
            a.setIcon(qtlib.geticon(icon))
            self.actionGroupTaskView.addAction(a)
            self.tasktbar.addAction(a)
            return a

        # note that 'grep' and 'search' are equivalent
        taskdefs = {
            'commit': ('hg-commit', _('&Commit')),
            'mq': ('thg-qrefresh', _('MQ Patch')),
            'pbranch': ('branch', _('&Patch Branch')),
            'log': ('hg-log', _("Revision &Details")),
            'manifest': ('hg-annotate', _('&Manifest')),
            'grep': ('hg-grep', _('&Search')),
            'sync': ('thg-sync', _('S&ynchronize')),
        }
        tasklist = self.ui.configlist(
            'tortoisehg', 'workbench.task-toolbar', [])
        if tasklist == []:
            tasklist = ['log', 'commit', 'mq', 'sync', 'manifest',
                'grep', 'pbranch']

        self.actionSelectTaskMQ = None
        self.actionSelectTaskPbranch = None

        for taskname in tasklist:
            taskname = taskname.strip()
            taskinfo = taskdefs.get(taskname, None)
            if taskinfo is None:
                newseparator(toolbar='task')
                continue
            tbar = addtaskview(taskinfo[0], taskinfo[1], taskname)
            if taskname == 'mq':
                self.actionSelectTaskMQ = tbar
            elif taskname == 'pbranch':
                self.actionSelectTaskPbranch = tbar

        newseparator(menu='view')

        newaction(_("&Refresh"), self._repofwd('reload'), icon='view-refresh',
                  shortcut='Refresh', enabled='repoopen',
                  menu='view', toolbar='edit',
                  tooltip=_('Refresh current repository'))
        newaction(_("Refresh &Task Tab"), self._repofwd('reloadTaskTab'),
                  enabled='repoopen',
                  shortcut=modifiedkeysequence('Refresh', modifier='Shift'),
                  tooltip=_('Refresh only the current task tab'),
                  menu='view')
        newaction(_("Load all revisions"), self.loadall,
                  enabled='repoopen', menu='view', shortcut='Shift+Ctrl+A',
                  tooltip=_('Load all revisions into graph'))
        newaction(_("&Goto revision..."), self.gotorev,
                  enabled='repoopen', menu='view', shortcut='Ctrl+/',
                  tooltip=_('Go to a specific revision'))

        newaction(_("Web Server..."), self.serve, enabled='repoopen',
                  menu='repository')
        newseparator(menu='repository')
        newaction(_("Shelve..."), self._repofwd('shelve'), icon='shelve',
                  enabled='repoopen', menu='repository')
        newaction(_("Import..."), self._repofwd('thgimport'), icon='hg-import',
                  enabled='repoopen', menu='repository')
        newseparator(menu='repository')
        newaction(_("Verify"), self._repofwd('verify'), enabled='repoopen',
                  menu='repository')
        newaction(_("Recover"), self._repofwd('recover'),
                  enabled='repoopen', menu='repository')
        newseparator(menu='repository')
        newaction(_("Resolve..."), self._repofwd('resolve'), icon='hg-merge',
                  enabled='repoopen', menu='repository')
        newseparator(menu='repository')
        newaction(_("Rollback/Undo..."), self._repofwd('rollback'),
                  shortcut='Ctrl+u',
                  enabled='repoopen', menu='repository')
        newseparator(menu='repository')
        newaction(_("Purge..."), self._repofwd('purge'), enabled='repoopen',
                  icon='hg-purge', menu='repository')
        newseparator(menu='repository')
        newaction(_("Bisect..."), self._repofwd('bisect'),
                  enabled='repoopen', menu='repository')
        newseparator(menu='repository')
        newaction(_("Explore"), self.explore, shortcut='Shift+Ctrl+X',
                  icon='system-file-manager', enabled='repoopen',
                  menu='repository')
        newaction(_("Terminal"), self.terminal, shortcut='Shift+Ctrl+T',
                  icon='utilities-terminal', enabled='repoopen',
                  menu='repository')

        newaction(_("Help"), self.onHelp, menu='help', icon='help-browser')
        newaction(_("Explorer Help"), self.onHelpExplorer, menu='help')
        visiblereadme = 'repoopen'
        if  self.ui.config('tortoisehg', 'readme', None):
            visiblereadme = True
        newaction(_("README"), self.onReadme, menu='help', icon='help-readme',
                  visible=visiblereadme, shortcut='Ctrl+F1')
        newseparator(menu='help')
        newaction(_("About Qt"), QApplication.aboutQt, menu='help')
        newaction(_("About TortoiseHg"), self.onAbout, menu='help',
                  icon='thg-logo')

        newseparator(toolbar='edit')
        self.actionCurrentRev = \
        newaction(_("Go to current revision"), self._repofwd('gotoParent'), icon='go-home',
                  tooltip=_('Go to current revision'),
                  enabled=True, toolbar='edit', shortcut='Ctrl+.')
        self.actionGoTo = \
        newaction(_("Go to a specific revision"), self.gotorev, icon='go-to-rev',
                  tooltip=_('Go to a specific revision'),
                  enabled=True, toolbar='edit')
        self.actionBack = \
        newaction(_("Back"), self._repofwd('back'), icon='go-previous',
                  enabled=False, toolbar='edit')
        self.actionForward = \
        newaction(_("Forward"), self._repofwd('forward'), icon='go-next',
                  enabled=False, toolbar='edit')
        newseparator(toolbar='edit', menu='View')

        self.filtertbaction = \
        newaction(_('Filter Toolbar'), self._repotogglefwd('toggleFilterBar'),
                  icon='view-filter', shortcut='Ctrl+S', enabled='repoopen',
                  toolbar='edit', menu='View', checkable=True,
                  tooltip=_('Filter graph with revision sets or branches'))

        menu = QMenu(_('Workbench Toolbars'), self)
        menu.addAction(self.edittbar.toggleViewAction())
        menu.addAction(self.docktbar.toggleViewAction())
        menu.addAction(self.synctbar.toggleViewAction())
        menu.addAction(self.tasktbar.toggleViewAction())
        menu.addAction(self.customtbar.toggleViewAction())
        self.menuView.addMenu(menu)

        newaction(_('Incoming'), self._repofwd('incoming'), icon='hg-incoming',
                  tooltip=_('Check for incoming changes from selected URL'),
                  enabled='repoopen', toolbar='sync')
        newaction(_('Pull'), self._repofwd('pull'), icon='hg-pull',
                  tooltip=_('Pull incoming changes from selected URL'),
                  enabled='repoopen', toolbar='sync')
        newaction(_('Outgoing'), self._repofwd('outgoing'), icon='hg-outgoing',
                   tooltip=_('Detect outgoing changes to selected URL'),
                   enabled='repoopen', toolbar='sync')
        newaction(_('Push'), self._repofwd('push'), icon='hg-push',
                  tooltip=_('Push outgoing changes to selected URL'),
                  enabled='repoopen', toolbar='sync')

        self.updateMenu()

    def _setupCustomTools(self, ui):
        tools, toollist = hglib.tortoisehgtools(ui,
            selectedlocation='workbench.custom-toolbar')
        # Clear the existing "custom" toolbar
        self.customtbar.clear()
        # and repopulate it again with the tool configuration
        # for the current repository
        if not tools:
            return
        for name in toollist:
            if name == '|':
                self._addNewSeparator(toolbar='custom')
                continue
            info = tools.get(name, None)
            if info is None:
                continue
            command = info.get('command', None)
            if not command:
                continue
            showoutput = info.get('showoutput', False)
            label = info.get('label', name)
            tooltip = info.get('tooltip', _("Execute custom tool '%s'") % label)
            icon = info.get('icon', 'tools-spanner-hammer')

            self._addNewAction(label,
                self._repofwd('runCustomCommand', [command, showoutput]),
                icon=icon, tooltip=tooltip,
                enabled=True, toolbar='custom')

    def _addNewAction(self, text, slot=None, icon=None, shortcut=None,
                  checkable=False, tooltip=None, data=None, enabled=None,
                  visible=None, menu=None, toolbar=None):
        """Create new action and register it

        :slot: function called if action triggered or toggled.
        :checkable: checkable action. slot will be called on toggled.
        :data: optional data stored on QAction.
        :enabled: bool or group name to enable/disable action.
        :visible: bool or group name to show/hide action.
        :shortcut: QKeySequence, key sequence or name of standard key.
        :menu: name of menu to add this action.
        :toolbar: name of toolbar to add this action.
        """
        action = QAction(text, self, checkable=checkable)
        if slot:
            if checkable:
                action.toggled.connect(slot)
            else:
                action.triggered.connect(slot)
        if icon:
            if toolbar:
                action.setIcon(qtlib.geticon(icon))
            else:
                action.setIcon(qtlib.getmenuicon(icon))
        if shortcut:
            keyseq = qtlib.keysequence(shortcut)
            if isinstance(keyseq, QKeySequence.StandardKey):
                action.setShortcuts(keyseq)
            else:
                action.setShortcut(keyseq)
        if tooltip:
            action.setToolTip(tooltip)
        if data is not None:
            action.setData(data)
        if isinstance(enabled, bool):
            action.setEnabled(enabled)
        elif enabled:
            self._actionavails[enabled].append(action)
        if isinstance(visible, bool):
            action.setVisible(visible)
        elif visible:
            self._actionvisibles[visible].append(action)
        if menu:
            getattr(self, 'menu%s' % menu.title()).addAction(action)
        if toolbar:
            getattr(self, '%stbar' % toolbar).addAction(action)
        return action

    def _addNewSeparator(self, menu=None, toolbar=None):
        """Insert a separator action; returns nothing"""
        if menu:
            getattr(self, 'menu%s' % menu.title()).addSeparator()
        if toolbar:
            getattr(self, '%stbar' % toolbar).addSeparator()

    def _action_defs(self):
        a = [("closetab", _("Close tab"), '',
                _("Close tab"), self.closeLastClickedTab),
             ("closeothertabs", _("Close other tabs"), '',
                _("Close other tabs"), self.closeNotLastClickedTabs),
             ("reopenlastclosed", _("Undo close tab"), '',
                _("Reopen last closed tab"), self.reopenLastClosedTabs),
             ("reopenlastclosedgroup", _("Undo close other tabs"), '',
                _("Reopen last closed tab group"), self.reopenLastClosedTabs),
             ]
        return a

    def createActions(self):
        self._actions = {}
        for name, desc, icon, tip, cb in self._action_defs():
            self._actions[name] = QAction(desc, self)
        QTimer.singleShot(0, self.configureActions)

    def configureActions(self):
        for name, desc, icon, tip, cb in self._action_defs():
            act = self._actions[name]
            if icon:
                act.setIcon(qtlib.getmenuicon(icon))
            if tip:
                act.setStatusTip(tip)
            if cb:
                act.triggered.connect(cb)
            self.addAction(act)

    @pyqtSlot(QPoint)
    def tabBarContextMenuRequest(self, point):
        # Activate the clicked tab
        clickedwidget = qApp.widgetAt(self.repoTabsWidget.mapToGlobal(point))
        if not clickedwidget or \
            not isinstance(clickedwidget, ThgTabBar):
            return
        self.repoTabsWidget.lastClickedTab = -1

        clickedtabindex = clickedwidget.tabAt(point)
        if clickedtabindex > -1:
            self.repoTabsWidget.lastClickedTab = clickedtabindex
        else:
            self.repoTabsWidget.lastClickedTab = self.repoTabsWidget.currentIndex()

        actionlist = ['closetab', 'closeothertabs']

        existingClosedRepoList = []

        for reporoot in self.lastClosedRepoRootList:
            if os.path.isdir(reporoot):
                existingClosedRepoList.append(reporoot)
        self.lastClosedRepoRootList = existingClosedRepoList

        if len(self.lastClosedRepoRootList) > 1:
            actionlist += ['', 'reopenlastclosedgroup']
        elif len(self.lastClosedRepoRootList) > 0:
            actionlist += ['', 'reopenlastclosed']

        contextmenu = QMenu(self)
        for act in actionlist:
            if act:
                contextmenu.addAction(self._actions[act])
            else:
                contextmenu.addSeparator()

        if actionlist:
            contextmenu.exec_(self.repoTabsWidget.mapToGlobal(point))

    def closeLastClickedTab(self):
        if self.repoTabsWidget.lastClickedTab > -1:
            self.repoTabCloseRequested(self.repoTabsWidget.lastClickedTab)

    def _closeOtherTabs(self, tabIndex):
        if tabIndex > -1:
            tb = self.repoTabsWidget.tabBar()
            tb.setCurrentIndex(tabIndex)
            closedRepoRootList = []
            for idx in range(tb.count()-1, -1, -1):
                if idx != tabIndex:
                    self.repoTabCloseRequested(idx)
                    # repoTabCloseRequested updates self.lastClosedRepoRootList
                    closedRepoRootList += self.lastClosedRepoRootList
            self.lastClosedRepoRootList = closedRepoRootList


    def closeNotLastClickedTabs(self):
        self._closeOtherTabs(self.repoTabsWidget.lastClickedTab)

    def onSwitchRepoTaskTab(self, action):
        rw = self.repoTabsWidget.currentWidget()
        if rw:
            rw.switchToNamedTaskTab(str(action.data().toString()))

    @pyqtSlot(QString, bool)
    def openRepo(self, root, reuse):
        """ Open repo by openRepoSignal from reporegistry [unicode] """
        root = hglib.fromunicode(root)
        self._openRepo(root, reuse)

    def removeRepo(self, root):
        """ Close tab if the repo is removed from reporegistry [unicode] """
        root = hglib.fromunicode(root)
        for i in xrange(self.repoTabsWidget.count()):
            w = self.repoTabsWidget.widget(i)
            if hglib.tounicode(w.repo.root) == os.path.normpath(root):
                self.repoTabCloseRequested(i)
                return

    @pyqtSlot(QString)
    def openLinkedRepo(self, path):
        uri = path.split('?')
        path = uri[0]
        rev = None
        if len(uri) > 1:
            rev = hglib.fromunicode(uri[1])
        rw = self.showRepo(path)
        if rw:
            if rev:
                rw.goto(rev)
            else:
                # assumes that the request comes from commit widget; in this
                # case, the user is going to commit changes to this repo.
                rw.taskTabsWidget.setCurrentIndex(rw.commitTabIndex)

    @pyqtSlot(QString)
    def showRepo(self, root):
        """Activate the repo tab or open it if not available [unicode]"""
        root = hglib.fromunicode(root)
        for i in xrange(self.repoTabsWidget.count()):
            w = self.repoTabsWidget.widget(i)
            if hglib.tounicode(w.repo.root) == os.path.normpath(root):
                self.repoTabsWidget.setCurrentIndex(i)
                return w
        return self._openRepo(root, False)

    @pyqtSlot(QString, QString)
    def showClonedRepo(self, root, src=None):
        """Activate the repo tab or open it on if not available [unicode]

        This method simply calls showRepo, ignoring the second argument on the received signal
        """
        self.showRepo(root)

    @pyqtSlot(unicode, QString)
    def setRevsetFilter(self, path, filter):
        for i in xrange(self.repoTabsWidget.count()):
            w = self.repoTabsWidget.widget(i)
            if hglib.tounicode(w.repo.root) == path:
                w.filterbar.revsetle.setText(filter)
                w.filterbar.returnPressed()
                return

    def find_root(self, url):
        p = hglib.fromunicode(url.toLocalFile())
        return paths.find_root(p)

    def dragEnterEvent(self, event):
        d = event.mimeData()
        for u in d.urls():
            root = self.find_root(u)
            if root:
                event.setDropAction(Qt.LinkAction)
                event.accept()
                break

    def dropEvent(self, event):
        accept = False
        d = event.mimeData()
        for u in d.urls():
            root = self.find_root(u)
            if root:
                self.showRepo(hglib.tounicode(root))
                accept = True
        if accept:
            event.setDropAction(Qt.LinkAction)
            event.accept()

    def updateMenu(self):
        """Enable actions when repoTabs are opened or closed or changed"""

        # Update actions affected by repo open/close
        someRepoOpen = self.repoTabsWidget.count() > 0
        for action in self._actionavails['repoopen']:
            action.setEnabled(someRepoOpen)
        for action in self._actionvisibles['repoopen']:
            action.setVisible(someRepoOpen)

        # Update actions affected by repo open/close/change
        self.updateTaskViewMenu()
        self.updateToolBarActions()
        tw = self.repoTabsWidget
        if ((tw.count() == 0) or
            ((tw.count() == 1) and
             not self.ui.configbool('tortoisehg', 'forcerepotab', False))):
            tw.tabBar().hide()
        else:
            tw.tabBar().show()
        self._updateWindowTitle()

    def _updateWindowTitle(self):
        tw = self.repoTabsWidget
        w = tw.currentWidget()
        if tw.count() == 0:
            self.setWindowTitle(_('TortoiseHg Workbench'))
        elif w.repo.shortname != w.repo.displayname:
            self.setWindowTitle(_('%s - TortoiseHg Workbench - %s') %
                                (w.title(), w.repo.displayname))
        else:
            self.setWindowTitle(_('%s - TortoiseHg Workbench') % w.title())

    def updateToolBarActions(self):
        w = self.repoTabsWidget.currentWidget()
        if w:
            self.filtertbaction.setChecked(w.filterBarVisible())

    def updateTaskViewMenu(self):
        'Update task tab menu for current repository'
        if self.repoTabsWidget.count() == 0:
            for a in self.actionGroupTaskView.actions():
                a.setChecked(False)
            if self.actionSelectTaskMQ is not None:
                self.actionSelectTaskMQ.setVisible(False)
            if self.actionSelectTaskPbranch is not None:
                self.actionSelectTaskPbranch.setVisible(False)
        else:
            repoWidget = self.repoTabsWidget.currentWidget()
            exts = repoWidget.repo.extensions()
            if self.actionSelectTaskMQ is not None:
                self.actionSelectTaskMQ.setVisible('mq' in exts)
            if self.actionSelectTaskPbranch is not None:
                self.actionSelectTaskPbranch.setVisible('pbranch' in exts)
            taskIndex = repoWidget.taskTabsWidget.currentIndex()
            for name, idx in repoWidget.namedTabs.iteritems():
                if idx == taskIndex:
                    break
            for action in self.actionGroupTaskView.actions():
                if str(action.data().toString()) == name:
                    action.setChecked(True)

    @pyqtSlot()
    def updateHistoryActions(self):
        'Update back / forward actions'
        rw = self.repoTabsWidget.currentWidget()
        if not rw:
            return
        self.actionBack.setEnabled(rw.canGoBack())
        self.actionForward.setEnabled(rw.canGoForward())

    def repoTabCloseSelf(self, widget):
        self.repoTabsWidget.setCurrentWidget(widget)
        index = self.repoTabsWidget.currentIndex()
        if widget.closeRepoWidget():
            w = self.repoTabsWidget.widget(index)
            try:
                reporoot = w.repo.root
            except:
                reporoot = ''
            self.repoTabsWidget.removeTab(index)
            widget.deleteLater()
            self.updateMenu()
            self.lastClosedRepoRootList = [reporoot]

    def repoTabCloseRequested(self, index):
        tw = self.repoTabsWidget
        if 0 <= index < tw.count():
            w = tw.widget(index)
            try:
                reporoot = w.repo.root
            except:
                reporoot = ''
            if w and w.closeRepoWidget():
                tw.removeTab(index)
                w.deleteLater()
                self.updateMenu()
                self.lastClosedRepoRootList = [reporoot]

    def reopenLastClosedTabs(self):
        for n, reporoot in enumerate(self.lastClosedRepoRootList):
            self.progress(_('Reopening tabs'), n,
                _('Reopening repository %s') % reporoot, '', len(self.lastClosedRepoRootList))
            if os.path.isdir(reporoot):
                self.showRepo(reporoot)
        self.lastClosedRepoRootList = []
        self.progress(_('Reopening tabs'), len(self.lastClosedRepoRootList),
            _('All repositories open'), '', len(self.lastClosedRepoRootList))

    def repoTabChanged(self, index=0):
        w = self.repoTabsWidget.currentWidget()
        if w:
            self.updateHistoryActions()
            self.updateMenu()
            if w.repo:
                root = w.repo.root
                self.activeRepoChanged.emit(hglib.tounicode(root))
                self._setupCustomTools(w.repo.ui)
        else:
            self.activeRepoChanged.emit("")
        repo = w and w.repo or None
        self.log.setRepository(repo)
        self.mqpatches.setrepo(repo)

    #@pyqtSlot(unicode)
    def _updateRepoTabTitle(self, title):
        index = self.repoTabsWidget.indexOf(self.sender())
        self.repoTabsWidget.setTabText(index, title)
        if index == self.repoTabsWidget.currentIndex():
            self._updateWindowTitle()

    def addRepoTab(self, repo, bundle):
        '''opens the given repo in a new tab'''
        rw = RepoWidget(repo, self, bundle=bundle)
        rw.showMessageSignal.connect(self.showMessage)
        rw.closeSelfSignal.connect(self.repoTabCloseSelf)
        rw.progress.connect(lambda tp, p, i, u, tl:
            self.statusbar.progress(tp, p, i, u, tl, repo.root))
        rw.output.connect(self.log.output)
        rw.makeLogVisible.connect(self.log.setShown)
        rw.beginSuppressPrompt.connect(self.log.beginSuppressPrompt)
        rw.endSuppressPrompt.connect(self.log.endSuppressPrompt)
        rw.revisionSelected.connect(self.updateHistoryActions)
        rw.repoLinkClicked.connect(self.openLinkedRepo)
        rw.taskTabsWidget.currentChanged.connect(self.updateTaskViewMenu)
        rw.toolbarVisibilityChanged.connect(self.updateToolBarActions)
        rw.shortNameChanged.connect(self.reporegistry.shortNameChanged)
        rw.baseNodeChanged.connect(self.reporegistry.baseNodeChanged)
        rw.repoChanged.connect(self.reporegistry.repoChanged)

        tw = self.repoTabsWidget
        # We can open new tabs next to the current one or next to the last tab
        openTabAfterCurrent = self.ui.configbool('tortoisehg',
            'opentabsaftercurrent', True)
        if openTabAfterCurrent:
            index = self.repoTabsWidget.insertTab(
                tw.currentIndex()+1, rw, rw.title())
        else:
            index = self.repoTabsWidget.addTab(rw, rw.title())
        tw.setTabToolTip(index, hglib.tounicode(repo.root))
        tw.setCurrentIndex(index)
        rw.titleChanged.connect(self._updateRepoTabTitle)
        rw.showIcon.connect(
            lambda icon: tw.setTabIcon(tw.indexOf(rw), icon))
        self.reporegistry.addRepo(repo.root)

        self.updateMenu()
        return rw



    def showMessage(self, msg):
        self.statusbar.showMessage(msg)

    @pyqtSlot(QString, object, QString, QString, object)
    def progress(self, topic, pos, item, unit, total=100, root=None):
        if self.progressDialog:
            if pos is None:
                self.progressDialog.close()
                return
            if total is None:
                total = 100
            pos = round(pos)
            total = round(total)
            self.progressDialog.setWindowTitle('TortoiseHg - %s' % topic)
            self.progressDialog.setLabelText('%s (%d / %d)' % (item, pos, total))
            self.progressDialog.setMaximum(total)
            self.progressDialog.show()
            self.progressDialog.setValue(pos)
        else:
            self.statusbar.progress(topic, pos, item, unit, total, root)

    def setHistoryColumns(self, *args):
        """Display the column selection dialog"""
        w = self.repoTabsWidget.currentWidget()
        dlg = ColumnSelectDialog('workbench', _('Workbench'),
                                 w and w.repoview.model() or None)
        if dlg.exec_() == QDialog.Accepted:
            if w:
                w.repoview.model().updateColumns()
                w.repoview.resizeColumns()

    def _repotogglefwd(self, name):
        """Return function to forward action to the current repo tab"""
        def forwarder(checked):
            w = self.repoTabsWidget.currentWidget()
            if w:
                getattr(w, name)(checked)
        return forwarder

    def _repofwd(self, name, params=[], namedparams={}):
        """Return function to forward action to the current repo tab"""
        def forwarder():
            w = self.repoTabsWidget.currentWidget()
            if w:
                getattr(w, name)(*params, **namedparams)

        return forwarder

    def serve(self):
        w = self.repoTabsWidget.currentWidget()
        if w:
            from tortoisehg.hgqt import run
            run.serve(w.repo.ui, root=w.repo.root)

    def loadall(self):
        w = self.repoTabsWidget.currentWidget()
        if w:
            w.repoview.model().loadall()

    def gotorev(self):
        rev, ok = qtlib.getTextInput(self,
                                     _("Goto revision"),
                                     _("Enter revision identifier"))
        w = self.repoTabsWidget.currentWidget()
        if ok and w:
            w.repoview.goto(rev)

    def newWorkbench(self):
        portable_start_fork(['--new'])

    def newRepository(self):
        """ Run init dialog """
        from tortoisehg.hgqt.hginit import InitDialog
        repoWidget = self.repoTabsWidget.currentWidget()
        if repoWidget:
            path = os.path.dirname(repoWidget.repo.root)
        else:
            path = os.getcwd()
        dlg = InitDialog([path], parent=self)
        dlg.finished.connect(dlg.deleteLater)
        if dlg.exec_():
            path = dlg.getPath()
            self._openRepo(path, False)

    def cloneRepository(self):
        """ Run clone dialog """
        from tortoisehg.hgqt.clone import CloneDialog
        repoWidget = self.repoTabsWidget.currentWidget()
        if repoWidget:
            root = repoWidget.repo.root
            args = [root, root + '-clone']
        else:
            args = []
        dlg = CloneDialog(args, parent=self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.clonedRepository.connect(self.showClonedRepo)
        dlg.exec_()

    def openRepository(self):
        """ Open repo from File menu """
        caption = _('Select repository directory to open')
        repoWidget = self.repoTabsWidget.currentWidget()
        if repoWidget:
            cwd = os.path.dirname(repoWidget.repo.root)
        else:
            cwd = os.getcwd()
        cwd = hglib.tounicode(cwd)
        FD = QFileDialog
        path = FD.getExistingDirectory(self, caption, cwd,
                                       FD.ShowDirsOnly | FD.ReadOnly)
        self._openRepo(hglib.fromunicode(path), False)

    def _openRepo(self, root, reuse, bundle=None):
        if root and not root.startswith('ssh://'):
            if reuse:
                for rw in self._findrepowidget(root):
                    self.repoTabsWidget.setCurrentWidget(rw)
                    return
            try:
                repo = thgrepo.repository(path=root)
                return self.addRepoTab(repo, bundle)
            except RepoError, e:
                qtlib.WarningMsgBox(_('Failed to open repository'),
                                    hglib.tounicode(str(e)), parent=self)
        return None

    def _findrepowidget(self, root):
        """Iterates RepoWidget for the specified root"""
        def normpathandcase(path):
            return os.path.normcase(util.normpath(path))
        tw = self.repoTabsWidget
        for idx in range(tw.count()):
            rw = tw.widget(idx)
            if normpathandcase(rw.repo.root) == normpathandcase(root):
                yield rw

    def onAbout(self, *args):
        """ Display about dialog """
        from tortoisehg.hgqt.about import AboutDialog
        ad = AboutDialog(self)
        ad.finished.connect(ad.deleteLater)
        ad.exec_()

    def onHelp(self, *args):
        """ Display online help """
        qtlib.openhelpcontents('workbench.html')

    def onHelpExplorer(self, *args):
        """ Display online help for shell extension """
        qtlib.openhelpcontents('explorer.html')

    def onReadme(self, *args):
        """ Display the README file or URL for the current repo, or the global README if no repo is open"""
        readme = None
        def getCurrentReadme(repo):
            """
            Get the README file that is configured for the current repo.

            README files can be set in 3 ways, which are checked in the following order of decreasing priority:
            - From the tortoisehg.readme key on the current repo's configuration file
            - An existing "README" file found on the repository root
                * Valid README files are those called README and whose extension is one of the following:
                    ['', '.txt', '.html', '.pdf', '.doc', '.docx', '.ppt', '.pptx',
                     '.markdown', '.textile', '.rdoc', '.org', '.creole',
                     '.mediawiki','.rst', '.asciidoc', '.pod']
                * Note that the match is CASE INSENSITIVE on ALL OSs.
            - From the tortoisehg.readme key on the user's global configuration file
            """
            readme = None
            if repo:
                # Try to get the README configured for the repo of the current tab
                readmeglobal = self.ui.config('tortoisehg', 'readme', None)
                if readmeglobal:
                    # Note that repo.ui.config() falls back to the self.ui.config()
                    # if the key is not set on the current repo's configuration file
                    readme = repo.ui.config('tortoisehg', 'readme', None)
                    if readmeglobal != readme:
                        # The readme is set on the current repo configuration file
                        return readme

                # Otherwise try to see if there is a file at the root of the repository
                # that matches any of the valid README file names (in a non case-sensitive way)
                # Note that we try to match the valid README names in order
                validreadmes = ['readme.txt', 'read.me', 'readme.html',
                                'readme.pdf', 'readme.doc', 'readme.docx', 'readme.ppt', 'readme.pptx',
                                'readme.md', 'readme.markdown', 'readme.mkdn', 'readme.rst', 'readme.textile', 'readme.rdoc',
                                'readme.asciidoc', 'readme.org', 'readme.creole',
                                'readme.mediawiki', 'readme.pod', 'readme']

                readmefiles = [filename for filename in os.listdir(repo.root) if filename.lower().startswith('read')]
                for validname in validreadmes:
                    for filename in readmefiles:
                        if filename.lower() == validname:
                            return repo.wjoin(filename)

            # Otherwise try use the global setting (or None if readme is just not configured)
            return readmeglobal

        w = self.repoTabsWidget.currentWidget()
        if w:
            # Try to get the help doc from the current repo tap
            readme = getCurrentReadme(w.repo)

        if readme:
            qtlib.openlocalurl(os.path.expandvars(os.path.expandvars(readme)))
        else:
            qtlib.WarningMsgBox(_("README not configured"),
                _("A README file is not configured for the current repository.<p>"
                "To configure a README file for a repository, "
                "open the repository settings file, add a '<i>readme</i>' "
                "key to the '<i>tortoisehg</i>' section, and set it "
                "to the filename or URL of your repository's README file."))

    def storeSettings(self):
        s = QSettings()
        wb = "Workbench/"
        s.setValue(wb + 'geometry', self.saveGeometry())
        s.setValue(wb + 'windowState', self.saveState())
        s.setValue(wb + 'showPaths', self.actionShowPaths.isChecked())
        s.setValue(wb + 'showSubrepos', self.actionShowSubrepos.isChecked())
        s.setValue(wb + 'showNetworkSubrepos',
            self.actionShowNetworkSubrepos.isChecked())
        s.setValue(wb + 'showShortPaths', self.actionShowShortPaths.isChecked())
        s.setValue(wb + 'saveRepos', self.actionSaveRepos.isChecked())
        repostosave = []
        lastactiverepo = ''
        if self.actionSaveRepos.isChecked():
            tw = self.repoTabsWidget
            for idx in range(tw.count()):
                rw = tw.widget(idx)
                repostosave.append(hglib.tounicode(rw.repo.root))
            cw = tw.currentWidget()
            if cw is not None:
                lastactiverepo = hglib.tounicode(cw.repo.root)
        s.setValue(wb + 'lastactiverepo', lastactiverepo)
        s.setValue(wb + 'openrepos', (',').join(repostosave))

    def restoreSettings(self):
        s = QSettings()
        wb = "Workbench/"
        self.restoreGeometry(s.value(wb + 'geometry').toByteArray())
        self.restoreState(s.value(wb + 'windowState').toByteArray())

        # Load the repo registry settings. Note that we must allow the
        # repo registry to assemble itself before toggling its settings
        # Also the view path setttings should be enabled last, once we have
        # loaded the repo subrepositories (if needed)

        # Normally, checking the "show subrepos" and the "show network subrepos"
        # settings will trigger a reload of the repo registry.
        # To avoid reloading it twice (every time we set one of its view
        # settings), we tell the setters to avoid reloading the repo tree
        # model, and then we  manually reload the model
        ssr = s.value(wb + 'showSubrepos',
            defaultValue=QVariant(True)).toBool()
        snsr = s.value(wb + 'showNetworkSubrepos',
            defaultValue=QVariant(True)).toBool()
        ssp = s.value(wb + 'showShortPaths',
            defaultValue=QVariant(True)).toBool()
        self.reporegistry.setShowSubrepos(ssr, False)
        self.reporegistry.setShowNetworkSubrepos(snsr, False)
        self.reporegistry.setShowShortPaths(ssp)

        # Note that calling setChecked will NOT reload the model if the new
        # setting is the same as the one in the repo registry
        QTimer.singleShot(0, lambda: self.actionShowSubrepos.setChecked(ssr))
        QTimer.singleShot(0, lambda: self.actionShowNetworkSubrepos.setChecked(snsr))
        QTimer.singleShot(0, lambda: self.actionShowShortPaths.setChecked(ssp))

        # Manually reload the model now, to apply the settings
        self.reporegistry.reloadModel()

        save = s.value(wb + 'saveRepos').toBool()
        self.actionSaveRepos.setChecked(save)

        # Reload the all the repos that were open on the last session
        # This may be a lengthy operation, which happens before the Workbench GUI is open
        # We use a progress dialog to let the user know that the workbench is being loaded
        openreposvalue = unicode(s.value(wb + 'openrepos').toString())
        if openreposvalue:
            openrepos = openreposvalue.split(',')
        else:
            openrepos = []
        for n, upath in enumerate(openrepos):
            self.progress(_('Reopening tabs'), n,
                          _('Reopening repository %s') % upath, '',
                          len(openrepos))
            QCoreApplication.processEvents()
            self._openRepo(hglib.fromunicode(upath), False)
            QCoreApplication.processEvents()
        self.progress(_('Reopening tabs'), len(openrepos),
                      _('All repositories open'), '', len(openrepos))

        # Activate the tab that was last active on the last session (if any)
        # Note that if a "root" has been passed to the "thg" command,
        # this will have no effect
        lastactiverepo = hglib.fromunicode(s.value(wb + 'lastactiverepo').toString())
        if lastactiverepo != '':
            self._openRepo(lastactiverepo, True)

        # Clear the lastactiverepo and the openrepos list once the workbench state
        # has been reload, so that opening additional workbench windows does not
        # reopen these repos again
        s.setValue(wb + 'openrepos', '')
        s.setValue(wb + 'lastactiverepo', '')

        # Allow repo registry to assemble itself before toggling path state
        sp = s.value(wb + 'showPaths').toBool()
        QTimer.singleShot(0, lambda: self.actionShowPaths.setChecked(sp))

    def goto(self, root, rev):
        for rw in self._findrepowidget(root):
            rw.goto(rev)

    def closeEvent(self, event):
        if not self.closeRepoTabs():
            event.ignore()
        else:
            self.storeSettings()
            self.reporegistry.close()
            if self.server:
                self.server.close()
            # mimic QDialog exit
            self.finished.emit(0)

    def closeRepoTabs(self):
        '''returns False if close should be aborted'''
        tw = self.repoTabsWidget
        for idx in range(tw.count()):
            rw = tw.widget(idx)
            if not rw.closeRepoWidget():
                tw.setCurrentWidget(rw)
                return False
        return True

    def closeRepository(self):
        """close the current repo tab"""
        self.repoTabCloseRequested(self.repoTabsWidget.currentIndex())

    def explore(self):
        w = self.repoTabsWidget.currentWidget()
        if w:
            qtlib.openlocalurl(w.repo.root)

    def terminal(self):
        w = self.repoTabsWidget.currentWidget()
        if w:
            qtlib.openshell(w.repo.root, w.repo.displayname)

    def editSettings(self):
        tw = self.repoTabsWidget
        w = tw.currentWidget()
        twrepo = (w and w.repo.root or '')
        sd = SettingsDialog(configrepo=False, focus='tortoisehg.authorcolor',
                            parent=self, root=twrepo)
        sd.exec_()

    def createWorkbenchServer(self):
        self.server = QLocalServer()
        self.server.newConnection.connect(self.newConnection)
        self.server.listen(qApp.applicationName()+ '-' + getpass.getuser())

    def newConnection(self):
        socket = self.server.nextPendingConnection()
        if socket:
            socket.waitForReadyRead(10000)
            root = str(socket.readAll())
            if root and root != '[echo]':
                self._openRepo(root, reuse=True)

                # Bring the workbench window to the front
                # This assumes that the client process has
                # called allowSetForegroundWindow(-1) right before
                # sending the request
                self.setWindowState(self.windowState() & ~Qt.WindowMinimized
                                    | Qt.WindowActive)
                self.show()
                self.raise_()
                self.activateWindow()
                # Revoke the blanket permission to set the foreground window
                allowSetForegroundWindow(os.getpid())

            socket.write(QByteArray(root))
            socket.flush()

def allowSetForegroundWindow(processid=-1):
    """Allow a given process to set the foreground window"""
    # processid = -1 means ASFW_ANY (i.e. allow any process)
    if os.name == 'nt':
        # on windows we must explicitly allow bringing the main window to
        # the foreground. To do so we must use ctypes
        try:
            from ctypes import windll
            windll.user32.AllowSetForegroundWindow(processid)
        except ImportError:
            pass

def connectToExistingWorkbench(root=None):
    """
    Connect and send data to an existing workbench server

    For the connection to be successful, the server must loopback the data
    that we send to it.

    Normally the data that is sent will be a repository root path, but we can
    also send "echo" to check that the connection works (i.e. that there is a
    server)
    """
    if root:
        data = root
    else:
        data = '[echo]'
    socket = QLocalSocket()
    socket.connectToServer(qApp.applicationName() + '-' + getpass.getuser(),
        QIODevice.ReadWrite)
    if socket.waitForConnected(10000):
        # Momentarily let any process set the foreground window
        # The server process with revoke this permission as soon as it gets
        # the request
        allowSetForegroundWindow()
        socket.write(QByteArray(data))
        socket.flush()
        socket.waitForReadyRead(10000)
        reply = socket.readAll()
        if data == reply:
            return True
    return False

def run(ui, *pats, **opts):
    root = opts.get('root') or paths.find_root()
    if root and pats:
        repo = thgrepo.repository(ui, root)
        pats = hglib.canonpaths(pats)
        if len(pats) == 1 and os.path.isfile(repo.wjoin(pats[0])):
            from tortoisehg.hgqt.filedialogs import FileLogDialog
            fname = pats[0]
            ufname = hglib.tounicode(fname)
            dlg = FileLogDialog(repo, fname, None)
            dlg.setWindowTitle(_('Hg file log viewer [%s] - %s') % (
                repo.displayname, ufname))
            return dlg

    # Before starting the workbench, we must check if we must try to reuse an
    # existing workbench window (we don't by default)
    # Note that if the "single workbench mode" is enabled, and there is no
    # existing workbench window, we must tell the Workbench object to create
    # the workbench server
    singleworkbenchmode = ui.configbool('tortoisehg', 'workbench.single', True)
    mustcreateserver = False
    if singleworkbenchmode:
        newworkbench = opts.get('newworkbench')
        if root and not newworkbench:
            if connectToExistingWorkbench(root):
                # The were able to connect to an existing workbench server, and
                # it confirmed that it has opened the selected repo for us
                sys.exit(0)
            # there is no pre-existing workbench server
            serverexists = False
        else:
            serverexists = connectToExistingWorkbench('[echo]')
        # When in " single workbench mode", we must create a server if there
        # is not one already
        mustcreateserver = not serverexists

    w = Workbench(createserver=mustcreateserver)
    if root:
        root = hglib.tounicode(root)
        bundle = opts.get('bundle')
        if bundle:
            w._openRepo(root, False, bundle=bundle)
        else:
            w.showRepo(root)

        if pats:
            q = []
            for pat in pats:
                f = repo.wjoin(pat)
                if os.path.isdir(f):
                    q.append('file("%s/**")' % pat)
                elif os.path.isfile(f):
                    q.append('file("%s")' % pat)
            w.setRevsetFilter(root, ' or '.join(q))
    if w.repoTabsWidget.count() <= 0:
        w.reporegistry.setVisible(True)
    return w
