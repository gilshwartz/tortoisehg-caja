# reporegistry.py - registry for a user's repositories
#
# Copyright 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os

from mercurial import commands, error, hg, ui, util

from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, repotreemodel, clone, settings

from PyQt4.QtCore import *
from PyQt4.QtGui import *

def settingsfilename():
    """Return path to thg-reporegistry.xml as unicode"""
    s = QSettings()
    dir = os.path.dirname(unicode(s.fileName()))
    return dir + '/' + 'thg-reporegistry.xml'


class RepoTreeView(QTreeView):
    showMessage = pyqtSignal(QString)
    menuRequested = pyqtSignal(object, object)
    openRepo = pyqtSignal(QString, bool)
    dropAccepted = pyqtSignal()
    updateSettingsFile = pyqtSignal()

    def __init__(self, parent):
        QTreeView.__init__(self, parent, allColumnsShowFocus=True)
        self.selitem = None
        self.msg = ''

        self.setHeaderHidden(True)
        self.setExpandsOnDoubleClick(False)
        self.setMouseTracking(True)

        # enable drag and drop
        # (see http://doc.qt.nokia.com/4.6/model-view-dnd.html)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setAutoScroll(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)
        self.setEditTriggers(QAbstractItemView.DoubleClicked
                             | QAbstractItemView.EditKeyPressed)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        QShortcut('Return', self, self.showFirstTabOrOpen).setContext(
                  Qt.WidgetShortcut)
        QShortcut('Enter', self, self.showFirstTabOrOpen).setContext(
                  Qt.WidgetShortcut)
        QShortcut('Delete', self, self.removeSelected).setContext(
                  Qt.WidgetShortcut)

    def contextMenuEvent(self, event):
        if not self.selitem:
            return
        self.menuRequested.emit(event.globalPos(), self.selitem)

    def dragEnterEvent(self, event):
        if event.source() is self:
            # Use the default event handler for internal dragging
            super(RepoTreeView, self).dragEnterEvent(event)
            return

        d = event.mimeData()
        for u in d.urls():
            root = paths.find_root(hglib.fromunicode(u.toLocalFile()))
            if root:
                event.setDropAction(Qt.LinkAction)
                event.accept()
                self.setState(QAbstractItemView.DraggingState)
                break

    def dropLocation(self, event):
        index = self.indexAt(event.pos())

        # Determine where the item was dropped.
        target = index.internalPointer()
        if not target.isRepo():
            group = index
            row = -1
        else:
            indicator = self.dropIndicatorPosition()
            group = index.parent()
            row = index.row()
            if indicator == QAbstractItemView.BelowItem:
                row = index.row() + 1

        return index, group, row

    def startDrag(self, supportedActions):
        indexes = self.selectedIndexes()
        # Make sure that all selected items are of the same type
        if len(indexes) == 0:
            # Nothing to drag!
            return

        # Make sure that all items that we are dragging are of the same type
        firstItem = indexes[0].internalPointer()
        selectionInstanceType = type(firstItem)
        for idx in indexes[1:]:
            if selectionInstanceType != type(idx.internalPointer()):
                # Cannot drag mixed type items
                return

        # Each item type may support different drag & drop actions
        # For instance, suprepo items support Copy actions only
        supportedActions = firstItem.getSupportedDragDropActions()

        super(RepoTreeView, self).startDrag(supportedActions)

    def dropEvent(self, event):
        data = event.mimeData()
        index, group, row = self.dropLocation(event)

        if index:
            if event.source() is self:
                # Event is an internal move, so pass it to the model
                col = 0
                drop = self.model().dropMimeData(data, event.dropAction(), row,
                                                 col, group)
                if drop:
                    event.accept()
                    self.dropAccepted.emit()
            else:
                # Event is a drop of an external repo
                accept = False
                for u in data.urls():
                    root = paths.find_root(hglib.fromunicode(u.toLocalFile()))
                    if root and not self.model().getRepoItem(root):
                        self.model().addRepo(group, root, row)
                        accept = True
                if accept:
                    event.setDropAction(Qt.LinkAction)
                    event.accept()
                    self.dropAccepted.emit()
        self.setAutoScroll(False)
        self.setState(QAbstractItemView.NoState)
        self.viewport().update()
        self.setAutoScroll(True)

    def mouseMoveEvent(self, event):
        self.msg  = ''
        pos = event.pos()
        idx = self.indexAt(pos)
        if idx.isValid():
            item = idx.internalPointer()
            self.msg  = item.details()
        self.showMessage.emit(self.msg)

        if event.buttons() == Qt.NoButton:
            # Bail out early to avoid tripping over this bug:
            # http://bugreports.qt.nokia.com/browse/QTBUG-10180
            return
        super(RepoTreeView, self).mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self.msg != '':
            self.showMessage.emit('')

    def mouseDoubleClickEvent(self, event):
        if self.selitem and self.selitem.internalPointer().isRepo():
            # We can only open mercurial repositories and subrepositories
            repotype = self.selitem.internalPointer().repotype()
            if repotype == 'hg':
                self.showFirstTabOrOpen()
            else:
                qtlib.WarningMsgBox(
                    _('Unsupported repository type (%s)') % repotype,
                    _('Cannot open non mercurial repositories or subrepositories'),
                    parent=self)
        else:
            # a double-click on non-repo rows opens an editor
            super(RepoTreeView, self).mouseDoubleClickEvent(event)

    def selectionChanged(self, selected, deselected):
        selection = self.selectedIndexes()
        if len(selection) == 0:
            self.selitem = None
        else:
            self.selitem = selection[0]

    def sizeHint(self):
        size = super(RepoTreeView, self).sizeHint()
        size.setWidth(QFontMetrics(self.font()).width('M') * 15)
        return size

    def showFirstTabOrOpen(self):
        'Enter or double click events, show existing or open a new repowidget'
        if self.selitem and self.selitem.internalPointer().isRepo():
            root = self.selitem.internalPointer().rootpath()
            self.openRepo.emit(hglib.tounicode(root), True)

    def removeSelected(self):
        'remove selected repository'
        s = self.selitem
        item = s.internalPointer()
        if 'remove' not in item.menulist():  # check capability
            return
        if not item.okToDelete():
            labels = [(QMessageBox.Yes, _('&Delete')),
                      (QMessageBox.No, _('Cancel'))]
            if not qtlib.QuestionMsgBox(_('Confirm Delete'),
                                    _("Delete Group '%s' and all its entries?")%
                                    item.name, labels=labels, parent=self):
                return
        m = self.model()
        row = s.row()
        parent = s.parent()
        m.removeRows(row, 1, parent)
        self.selectionChanged(None, None)
        self.updateSettingsFile.emit()

class RepoRegistryView(QDockWidget):

    showMessage = pyqtSignal(QString)
    openRepo = pyqtSignal(QString, bool)
    removeRepo = pyqtSignal(QString)
    progressReceived = pyqtSignal(QString, object, QString, QString, object)

    def __init__(self, parent, showSubrepos=False, showNetworkSubrepos=False,
            showShortPaths=False):
        QDockWidget.__init__(self, parent)

        self.watcher = None
        self.showSubrepos = showSubrepos
        self.showNetworkSubrepos = showNetworkSubrepos
        self.showShortPaths = showShortPaths

        self.setFeatures(QDockWidget.DockWidgetClosable |
                         QDockWidget.DockWidgetMovable  |
                         QDockWidget.DockWidgetFloatable)
        self.setWindowTitle(_('Repository Registry'))

        mainframe = QFrame()
        mainframe.setLayout(QVBoxLayout())
        self.setWidget(mainframe)
        mainframe.layout().setContentsMargins(0, 0, 0, 0)

        self.contextmenu = QMenu(self)
        self.tview = tv = RepoTreeView(self)

        sfile = settingsfilename()
        tv.setModel(repotreemodel.RepoTreeModel(sfile, self,
            showSubrepos=self.showSubrepos,
            showNetworkSubrepos=self.showNetworkSubrepos))

        mainframe.layout().addWidget(tv)

        tv.setIndentation(10)
        tv.setFirstColumnSpanned(0, QModelIndex(), True)
        tv.setColumnHidden(1, True)

        tv.showMessage.connect(self.showMessage)
        tv.menuRequested.connect(self.onMenuRequest)
        tv.openRepo.connect(self.openRepo)
        tv.updateSettingsFile.connect(self.updateSettingsFile)
        tv.dropAccepted.connect(self.dropAccepted)

        self.createActions()
        QTimer.singleShot(0, self.expand)

        # Setup a file system watcher to update the reporegistry
        # anytime it is modified by another thg instance
        # Note that we must make sure that the settings file exists before
        # setting thefile watcher
        if not os.path.exists(sfile):
            if not os.path.exists(os.path.dirname(sfile)):
                os.makedirs(os.path.dirname(sfile))
            tv.model().write(sfile)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.addPath(sfile)
        self.watcher.fileChanged.connect(self.modifiedSettings)
        self._pendingReloadModel = False
        self._activeTabRepo = None

    def setShowSubrepos(self, show, reloadModel=True):
        if self.showSubrepos != show:
            self.showSubrepos = show
            if reloadModel:
                self.reloadModel()

    def setShowNetworkSubrepos(self, show, reloadModel=True):
        if self.showNetworkSubrepos != show:
            self.showNetworkSubrepos = show
            if reloadModel:
                self.reloadModel()

    def setShowShortPaths(self, show):
        if self.showShortPaths != show:
            self.showShortPaths = show
            #self.tview.model().showShortPaths = show
            self.tview.model().updateCommonPaths(show)
            self.tview.dataChanged(QModelIndex(), QModelIndex())

    def updateSettingsFile(self):
        # If there is a settings watcher, we must briefly stop watching the
        # settings file while we save it, otherwise we'll get the update signal
        # that we do not want
        sfile = settingsfilename()
        if self.watcher:
            self.watcher.removePath(sfile)
        self.tview.model().write(sfile)
        if self.watcher:
            self.watcher.addPath(sfile)

        # Whenver the settings file must be updated, it is also time to ensure
        # that the commonPaths are up to date
        QTimer.singleShot(0, self.tview.model().updateCommonPaths)

    @pyqtSlot()
    def dropAccepted(self):
        # Whenever a drag and drop operation is completed, update the settings
        # file
        QTimer.singleShot(0, self.updateSettingsFile)

    @pyqtSlot(QString)
    def modifiedSettings(self):
        UPDATE_DELAY = 2 # seconds

        # Do not update the repo registry more often than
        # once every UPDATE_DELAY seconds
        if not self._pendingReloadModel:
            # There are no pending updates:
            # -> schedule and update in UPDATE_DELAY seconds.
            # If other update notifications arrive from now
            # until now + UPDATE_DELAY, they will be ignored and "rolled into"
            # the pending update
            self._pendingReloadModel = True
            QTimer.singleShot(1000 * UPDATE_DELAY, self.reloadModel)

    def reloadModel(self):
        oldmodel = self.tview.model()
        self.tview.setModel(
            repotreemodel.RepoTreeModel(settingsfilename(), self,
                self.showSubrepos, self.showNetworkSubrepos,
                self.showShortPaths))
        oldmodel.deleteLater()
        self.expand()
        self._pendingReloadModel = False

    def _getItemAndAncestors(self, it):
        """Create a list of ancestors (including the selected item)"""
        from repotreeitem import RepoGroupItem
        itchain = [it]
        while(not isinstance(itchain[-1], RepoGroupItem)):
            itchain.append(itchain[-1].parent())
        return reversed(itchain)

    def expand(self):
        self.tview.expandToDepth(0)

    def scrollTo(self, it=None, scrollHint=RepoTreeView.EnsureVisible):
        if not it:
            return

        # Create a list of ancestors (including the selected item)
        itchain = self._getItemAndAncestors(it)

        m = self.tview.model()
        idx = self.tview.rootIndex()
        for it in itchain:
            idx = m.index(it.row(), 0, idx)
        self.tview.scrollTo(idx, hint=scrollHint)

    def addRepo(self, root, groupname=None):
        """
        Add a repo to the repo registry, optionally specifying the parent repository group

        The main use of this method is when the workbench has opened a new repowidget
        """
        m = self.tview.model()
        it = m.getRepoItem(root, lookForSubrepos=True)
        if it == None:
            group = None
            if groupname:
                # Get the group index of the RepoGroup corresponding to the target group name
                for it in m.rootItem.childs:
                    if groupname == it.name:
                        rootidx = self.tview.rootIndex()
                        group = m.index(it.row(), 0, rootidx)
                        break
            m.addRepo(group, root, -1)
            self.updateSettingsFile()

    def setActiveTabRepo(self, root):
        """"
        The selected tab has changed on the workbench
        Unmark the previously selected tab and mark the new one as selected on
        the Repo Registry as well
        """
        root = hglib.fromunicode(root)
        if self._activeTabRepo:
            self._activeTabRepo.setActive(False)
        m = self.tview.model()
        it = m.getRepoItem(root, lookForSubrepos=True)
        if it:
            self._activeTabRepo = it
            it.setActive(True)
            self.tview.dataChanged(QModelIndex(), QModelIndex())

            # Make sure that the active tab is visible by expanding its parent
            # and scrolling to it if necessary
            self.scrollTo(it)

    def showPaths(self, show):
        self.tview.setColumnHidden(1, not show)
        self.tview.setHeaderHidden(not show)
        if show:
            self.tview.resizeColumnToContents(0)
            self.tview.resizeColumnToContents(1)

    def close(self):
        # We must stop monitoring the settings file and then we can save it
        sfile = settingsfilename()
        self.watcher.removePath(sfile)
        self.tview.model().write(sfile)

    def _action_defs(self):
        a = [("reloadRegistry", _("Refresh repository list"), 'view-refresh',
                _("Refresh the Repository Registry list"), self.reloadModel),
             ("open", _("Open"), 'thg-repository-open',
                _("Open the repository in a new tab"), self.open),
             ("openAll", _("Open All"), 'thg-repository-open',
                _("Open all repositories in new tabs"), self.openAll),
             ("newGroup", _("New Group"), 'new-group',
                _("Create a new group"), self.newGroup),
             ("rename", _("Rename"), None,
                _("Rename the entry"), self.startRename),
             ("settings", _("Settings..."), 'settings_user',
                _("View the repository's settings"), self.startSettings),
             ("remove", _("Remove from registry"), 'menudelete',
                _("Remove the node and all its subnodes."
                  " Repositories are not deleted from disk."),
                  self.removeSelected),
             ("clone", _("Clone..."), 'hg-clone',
                _("Clone Repository"), self.cloneRepo),
             ("explore", _("Explore"), 'system-file-manager',
                _("Open the repository in a file browser"), self.explore),
             ("terminal", _("Terminal"), 'utilities-terminal',
                _("Open a shell terminal in the repository root"), self.terminal),
             ("add", _("Add repository..."), 'hg',
                _("Add a repository to this group"), self.addNewRepo),
             ("addsubrepo", _("Add a subrepository..."), 'thg-add-subrepo',
                _("Convert an existing repository into a subrepository"),
                self.addSubrepo),
             ("copypath", _("Copy path"), '',
                _("Copy the root path of the repository to the clipboard"),
                self.copyPath),
             ("sortbyname", _("Sort by name"), '',
                _("Sort the group by short name"), self.sortbyname),
             ("sortbypath", _("Sort by path"), '',
                _("Sort the group by full path"), self.sortbypath),
             ("sortbyhgsub", _("Sort by .hgsub"), '',
                _("Order the subrepos as in .hgsub"), self.sortbyhgsub),
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

    def onMenuRequest(self, point, selitem):
        menulist = selitem.internalPointer().menulist()
        if not menulist:
            return
        self.addtomenu(self.contextmenu, menulist)
        self.selitem = selitem
        self.contextmenu.exec_(point)

    def addtomenu(self, menu, actlist):
        menu.clear()
        for act in actlist:
            if isinstance(act, basestring) and act in self._actions:
                menu.addAction(self._actions[act])
            elif isinstance(act, tuple) and len(act) == 2:
                submenu = menu.addMenu(act[0])
                self.addtomenu(submenu, act[1])
            else:
                menu.addSeparator()

    #
    ## Menu action handlers
    #

    def cloneRepo(self):
        root = self.selitem.internalPointer().rootpath()
        d = clone.CloneDialog(args=[root, root + '-clone'], parent=self)
        d.finished.connect(d.deleteLater)
        d.clonedRepository.connect(self.openClone)
        d.show()

    def explore(self):
        root = self.selitem.internalPointer().rootpath()
        qtlib.openlocalurl(root)

    def terminal(self):
        repoitem = self.selitem.internalPointer()
        qtlib.openshell(repoitem.rootpath(), repoitem.shortname())

    def addNewRepo(self):
        'menu action handler for adding a new repository'
        caption = _('Select repository directory to add')
        FD = QFileDialog
        path = FD.getExistingDirectory(caption=caption,
                                       options=FD.ShowDirsOnly | FD.ReadOnly)
        if path:
            root = paths.find_root(hglib.fromunicode(path))
            if root and not self.tview.model().getRepoItem(root):
                try:
                    self.tview.model().addRepo(self.selitem, root)
                except error.RepoError:
                    qtlib.WarningMsgBox(
                        _('Failed to add repository'),
                        _('%s is not a valid repository') % path, parent=self)
                    return

    def addSubrepo(self):
        'menu action handler for adding a new subrepository'
        root = hglib.tounicode(self.selitem.internalPointer().rootpath())
        caption = _('Select an existing repository to add as a subrepo')
        FD = QFileDialog
        path = unicode(FD.getExistingDirectory(caption=caption,
            directory=root, options=FD.ShowDirsOnly | FD.ReadOnly))
        if path:
            path = os.path.normcase(os.path.normpath(path))
            sroot = paths.find_root(path)

            root = os.path.normcase(os.path.normpath(root))

            if not sroot:
                qtlib.WarningMsgBox(_('Cannot add subrepository'),
                    _('%s is not a valid repository') % path,
                    parent=self)
                return
            elif not os.path.isdir(sroot):
                qtlib.WarningMsgBox(_('Cannot add subrepository'),
                    _('"%s" is not a folder') % sroot,
                    parent=self)
                return
            elif sroot == root:
                qtlib.WarningMsgBox(_('Cannot add subrepository'),
                    _('A repository cannot be added as a subrepo of itself'),
                    parent=self)
                return
            elif root != paths.find_root(os.path.dirname(path)):
                qtlib.WarningMsgBox(_('Cannot add subrepository'),
                    _('The selected folder:<br><br>%s<br><br>'
                    'is not inside the target repository.<br><br>'
                    'This may be allowed but is greatly discouraged.<br>'
                    'If you want to add a non trivial subrepository mapping '
                    'you must manually edit the <i>.hgsub</i> file') % root, parent=self)
                return
            else:
                # The selected path is the root of a repository that is inside
                # the selected repository

                # Use forward slashes for relative subrepo root paths
                srelroot = sroot[len(root)+1:]
                srelroot = util.pconvert(srelroot)

                # Is is already on the selected repository substate list?
                try:
                    repo = hg.repository(ui.ui(), hglib.fromunicode(root))
                except:
                    qtlib.WarningMsgBox(_('Cannot open repository'),
                        _('The selected repository:<br><br>%s<br><br>'
                        'cannot be open!') % root, parent=self)
                    return

                if hglib.fromunicode(srelroot) in repo['.'].substate:
                    qtlib.WarningMsgBox(_('Subrepository already exists'),
                        _('The selected repository:<br><br>%s<br><br>'
                        'is already a subrepository of:<br><br>%s<br><br>'
                        'as: "%s"') % (sroot, root, srelroot), parent=self)
                    return
                else:
                    # Already a subrepo!

                    # Read the current .hgsub file contents
                    lines = []
                    hasHgsub = os.path.exists(repo.wjoin('.hgsub'))
                    if hasHgsub:
                        try:
                            fsub = repo.wopener('.hgsub', 'r')
                            lines = fsub.readlines()
                            fsub.close()
                        except:
                            qtlib.WarningMsgBox(
                                _('Failed to add subrepository'),
                                _('Cannot open the .hgsub file in:<br><br>%s') \
                                % root, parent=self)
                            return

                    # Make sure that the selected subrepo (or one of its
                    # subrepos!) is not already on the .hgsub file
                    linesep = ''
                    for line in lines:
                        line = hglib.tounicode(line)
                        spath = line.split("=")[0].strip()
                        if not spath:
                            continue
                        if not linesep:
                            linesep = hglib.getLineSeparator(line)
                        spath = util.pconvert(spath)
                        if line.startswith(srelroot):
                            qtlib.WarningMsgBox(
                                _('Failed to add repository'),
                                _('The .hgsub file already contains the '
                                'line:<br><br>%s') % line, parent=self)
                            return

                    # Append the new subrepo to the end of the .hgsub file
                    lines.append(hglib.fromunicode('%s = %s'
                                                   % (srelroot, srelroot)))
                    lines = [line.strip(linesep) for line in lines]

                    # and update the .hgsub file
                    try:
                        fsub = repo.wopener('.hgsub', 'w')
                        fsub.write(linesep.join(lines))
                        fsub.close()
                        if not hasHgsub:
                            commands.add(ui.ui(), repo, repo.wjoin('.hgsub'))
                        qtlib.InfoMsgBox(
                            _('Subrepo added to .hgsub file'),
                            _('The selected subrepo:<br><br><i>%s</i><br><br>'
                            'has been added to the .hgsub file of the repository:<br><br><i>%s</i><br><br>'
                            'Remember that in order to finish adding the '
                            'subrepo <i>you must still <u>commit</u></i> the '
                            'changes to the .hgsub file in order to confirm '
                            'the addition of the subrepo.') \
                            % (srelroot, root), parent=self)
                    except:
                        qtlib.WarningMsgBox(
                            _('Failed to add repository'),
                            _('Cannot update the .hgsub file in:<br><br>%s') \
                            % root, parent=self)
                return

            qtlib.WarningMsgBox(
                _('Failed to add repository'),
                _('"%s" is not a valid repository inside "%s"') % \
                (path, root), parent=self)
            return

    def startSettings(self):
        root = self.selitem.internalPointer().rootpath()
        sd = settings.SettingsDialog(configrepo=True, focus='web.name',
                                     parent=self, root=root)
        sd.finished.connect(sd.deleteLater)
        sd.exec_()

    def openAll(self):
        for root in self.selitem.internalPointer().childRoots():
            self.openRepo.emit(hglib.tounicode(root), False)

    def openClone(self, root=None, sourceroot=None):
        m = self.tview.model()
        src = m.getRepoItem(hglib.fromunicode(sourceroot))
        if src:
            groupname = src.parent().name
        else:
            groupname = None
        self.open(root, groupname)

    def open(self, root=None, groupname=None):
        'open context menu action, open repowidget unconditionally'
        if not root:
            root = self.selitem.internalPointer().rootpath()
            repotype = self.selitem.internalPointer().repotype()
        else:
            root = hglib.fromunicode(root)
            if os.path.exists(os.path.join(root, '.hg')):
                repotype = 'hg'
            else:
                repotype = 'unknown'
        if repotype == 'hg':
            if groupname:
                self.addRepo(root, groupname)
            self.openRepo.emit(hglib.tounicode(root), False)
        else:
            qtlib.WarningMsgBox(
                _('Unsupported repository type (%s)') % repotype,
                _('Cannot open non mercurial repositories or subrepositories'),
                parent=self)

    def copyPath(self):
        clip = QApplication.clipboard()
        clip.setText(hglib.tounicode(self.selitem.internalPointer().rootpath()))

    def startRename(self):
        self.tview.edit(self.tview.currentIndex())

    def newGroup(self):
        self.tview.model().addGroup(_('New Group'))

    def removeSelected(self):
        ip = self.selitem.internalPointer()
        if ip.isRepo():
            root = ip.rootpath()
        else:
            root = None

        self.tview.removeSelected()

        if root is not None:
            self.removeRepo.emit(hglib.tounicode(root))

    def sortbyname(self):
        childs = self.selitem.internalPointer().childs
        self.tview.model().sortchilds(childs, lambda x: x.shortname().lower())

    def sortbypath(self):
        childs = self.selitem.internalPointer().childs
        self.tview.model().sortchilds(childs, lambda x: util.normpath(x.rootpath()))

    def sortbyhgsub(self):
        ip = self.selitem.internalPointer()
        repo = hg.repository(ui.ui(), ip.rootpath())
        ctx = repo['.']
        wfile = '.hgsub'
        if wfile not in ctx:
            return self.sortbypath()
        data = ctx[wfile].data().strip()
        data = data.split('\n')
        getsubpath = lambda x: x.split('=')[0].strip()
        abspath = lambda x: util.normpath(repo.wjoin(x))
        hgsuborder = [abspath(getsubpath(x)) for x in data]
        def keyfunc(x):
            try:
                return hgsuborder.index(util.normpath(x.rootpath()))
            except:
                # If an item is not found, place it at the top
                return 0
        self.tview.model().sortchilds(ip.childs, keyfunc)

    @pyqtSlot(QString, QString)
    def shortNameChanged(self, uroot, uname):
        it = self.tview.model().getRepoItem(hglib.fromunicode(uroot))
        if it:
            it.setShortName(uname)
            self.tview.model().layoutChanged.emit()

    @pyqtSlot(QString, object)
    def baseNodeChanged(self, uroot, basenode):
        it = self.tview.model().getRepoItem(hglib.fromunicode(uroot))
        if it:
            it.setBaseNode(basenode)

    @pyqtSlot(QString)
    def repoChanged(self, uroot):
        m = self.tview.model()
        changedrootpath = hglib.fromunicode(QDir.fromNativeSeparators(uroot))

        def isAboveOrBelowUroot(testedpath):
            """Return True if rootpath is contained or contains uroot"""
            r1 = hglib.fromunicode(QDir.fromNativeSeparators(testedpath)) + "/"
            r2 = changedrootpath + "/"
            return r1.startswith(r2) or r2.startswith(r1)

        m.loadSubrepos(m.rootItem, isAboveOrBelowUroot)

    @pyqtSlot(int, int, QString, QString)
    def updateProgress(self, pos, max, topic, item):
        if pos == max:
            #self.progressReceived.emit('Updating repository registry', None, '', '', None)
            self.progressReceived.emit(topic, None, item, '', None)
        else:
            #self.progressReceived.emit('Updating repository registry', pos, 'reporegistry-%s' % topic, '', max)
            self.progressReceived.emit(topic, pos, item, '', max)
