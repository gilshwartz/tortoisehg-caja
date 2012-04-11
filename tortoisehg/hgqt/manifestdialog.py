# manifestdialog.py - Dialog and widget for TortoiseHg manifest view
#
# Copyright (C) 2003-2010 LOGILAB S.A. <http://www.logilab.fr/>
# Copyright (C) 2010 Yuya Nishihara <yuya@tcha.org>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import error

from tortoisehg.util import paths, hglib

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, fileview, status, thgrepo
from tortoisehg.hgqt import visdiff, revert, revpanel, workbench
from tortoisehg.hgqt.filedialogs import FileLogDialog, FileDiffDialog
from tortoisehg.hgqt.manifestmodel import ManifestModel

class ManifestDialog(QMainWindow):
    """
    Qt4 dialog to display all files of a repo at a given revision
    """

    finished = pyqtSignal(int)
    linkActivated = pyqtSignal(QString)

    def __init__(self, repo, rev=None, parent=None):
        QMainWindow.__init__(self, parent)
        self._repo = repo
        self.setWindowIcon(qtlib.geticon('hg-annotate'))
        self.resize(400, 300)

        self._manifest_widget = ManifestWidget(repo, rev)
        self._manifest_widget.revChanged.connect(self._updatewindowtitle)
        self._manifest_widget.pathChanged.connect(self._updatewindowtitle)
        self._manifest_widget.grepRequested.connect(self._openSearchWidget)
        self._manifest_widget.setContentsMargins(10, 10, 10, 10)
        self.setCentralWidget(self._manifest_widget)
        self.addToolBar(self._manifest_widget.toolbar)

        self.setStatusBar(QStatusBar())
        self._manifest_widget.showMessage.connect(self.statusBar().showMessage)
        self._manifest_widget.linkActivated.connect(self.linkActivated)

        self._readsettings()
        self._updatewindowtitle()

    @pyqtSlot()
    def _updatewindowtitle(self):
        self.setWindowTitle(_('Manifest %s@%s') % (
            self._manifest_widget.path, self._manifest_widget.rev))

    def closeEvent(self, event):
        self._writesettings()
        super(ManifestDialog, self).closeEvent(event)
        self.finished.emit(0)  # mimic QDialog exit

    def _readsettings(self):
        s = QSettings()
        self.restoreGeometry(s.value('manifest/geom').toByteArray())
        self._manifest_widget.loadSettings(s, 'manifest')

    def _writesettings(self):
        s = QSettings()
        s.setValue('manifest/geom', self.saveGeometry())
        self._manifest_widget.saveSettings(s, 'manifest')

    def setSource(self, path, rev, line=None):
        self._manifest_widget.setSource(path, rev, line)

    def setSearchPattern(self, text):
        """Set search pattern [unicode]"""
        self._manifest_widget._fileview.searchbar.setPattern(text)

    def setSearchCaseInsensitive(self, ignorecase):
        """Set if search is case insensitive"""
        self._manifest_widget._fileview.searchbar.setCaseInsensitive(ignorecase)

    @pyqtSlot(unicode, dict)
    def _openSearchWidget(self, pattern, opts):
        opts = dict((str(k), str(v)) for k, v in opts.iteritems())
        from tortoisehg.hgqt import run
        run.grep(self._repo.ui, hglib.fromunicode(pattern), **opts)

    @pyqtSlot(unicode, object, int)
    def _openInEditor(self, path, rev, line):
        """Open editor to show the specified file"""
        _openineditor(self._repo, path, rev, line,
                      pattern=self._fileview.searchbar.pattern(), parent=self)

class ManifestWidget(QWidget, qtlib.TaskWidget):
    """Display file tree and contents at the specified revision"""

    revChanged = pyqtSignal(object)
    """Emitted (rev) when the current revision changed"""

    pathChanged = pyqtSignal(unicode)
    """Emitted (path) when the current file path changed"""

    showMessage = pyqtSignal(unicode)
    """Emitted when to show revision summary as a hint"""

    grepRequested = pyqtSignal(unicode, dict)
    """Emitted (pattern, opts) when user request to search changelog"""

    linkActivated = pyqtSignal(QString)
    """Emitted (path) when user clicks on link"""

    filecontextmenu = None
    subrepocontextmenu = None

    def canswitch(self):
        return False

    def __init__(self, repo, rev=None, parent=None):
        super(ManifestWidget, self).__init__(parent)
        self._repo = repo
        self._rev = rev
        self._selectedrev = rev
        self._diff_dialogs = {}
        self._nav_dialogs = {}

        self._initwidget()
        self._initactions()
        self._setupmodel()
        self._treeview.setCurrentIndex(self._treemodel.index(0, 0))

        self.setRev(self._rev)

    def _initwidget(self):
        self.setLayout(QVBoxLayout())
        self._splitter = QSplitter()
        self.layout().addWidget(self._splitter)
        self.layout().setContentsMargins(2, 2, 2, 2)

        navlayout = QVBoxLayout(spacing=0)
        navlayout.setContentsMargins(0, 0, 0, 0)
        self._toolbar = QToolBar()
        self._toolbar.setIconSize(QSize(16,16))
        self._toolbar.setStyleSheet(qtlib.tbstylesheet)
        self._treeview = QTreeView(self, headerHidden=True, dragEnabled=True)
        self._treeview.setContextMenuPolicy(Qt.CustomContextMenu)
        self._treeview.customContextMenuRequested.connect(self.menuRequest)
        self._treeview.doubleClicked.connect(self.onDoubleClick)
        navlayout.addWidget(self._toolbar)
        navlayout.addWidget(self._treeview)
        navlayoutw = QWidget()
        navlayoutw.setLayout(navlayout)

        self._splitter.addWidget(navlayoutw)
        self._splitter.setStretchFactor(0, 1)

        vbox = QVBoxLayout(spacing=0)
        vbox.setMargin(0)
        self.revpanel = revpanel.RevPanelWidget(self._repo)
        self.revpanel.linkActivated.connect(self.linkActivated)
        vbox.addWidget(self.revpanel, 0)
        self._fileview = fileview.HgFileView(self._repo, self)
        vbox.addWidget(self._fileview, 0)
        w = QWidget()
        w.setLayout(vbox)
        self._splitter.addWidget(w)

        self._splitter.setStretchFactor(1, 3)
        self._fileview.revisionSelected.connect(self.setRev)
        self._fileview.linkActivated.connect(self.linkActivated)
        for name in ('showMessage', 'grepRequested'):
            getattr(self._fileview, name).connect(getattr(self, name))

    def loadSettings(self, qs, prefix):
        prefix += '/manifest'
        self._fileview.loadSettings(qs, prefix+'/fileview')
        self._splitter.restoreState(qs.value(prefix+'/splitter').toByteArray())
        expanded = qs.value(prefix+'/revpanel.expanded', False).toBool()
        self.revpanel.set_expanded(expanded)

    def saveSettings(self, qs, prefix):
        prefix += '/manifest'
        self._fileview.saveSettings(qs, prefix+'/fileview')
        qs.setValue(prefix+'/splitter', self._splitter.saveState())
        qs.setValue(prefix+'/revpanel.expanded', self.revpanel.is_expanded())

    def _initactions(self):
        self._statusfilter = status.StatusFilterButton(
          statustext='MASC', text=_('Status'))
        self._toolbar.addWidget(self._statusfilter)

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
            ('ledit', _('Edit Local'), 'edit-file', 'Shift+Ctrl+E',
              _('Edit current file in working copy'), self.editlocal),
            ('revert', _('Revert to Revision'), 'hg-revert', 'Alt+Ctrl+T',
              _('Revert file(s) to contents at this revision'),
              self.revertfile),
            ('opensubrepo', _('Open subrepository'), 'thg-repository-open',
              'Alt+Ctrl+O', _('Open the selected subrepository'),
              self.opensubrepo),
            ('explore', _('Explore subrepository'), 'system-file-manager',
              'Alt+Ctrl+E',
              _('Open the selected subrepository in a file browser'),
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

    def navigate(self, filename=None):
        self._navigate(filename, FileLogDialog, self._nav_dialogs)

    def diffNavigate(self, filename=None):
        self._navigate(filename, FileDiffDialog, self._diff_dialogs)

    def vdiff(self):
        if self.path is None:
            return
        pats = [hglib.fromunicode(self.path)]
        opts = {'change':self.rev}
        dlg = visdiff.visualdiff(self._repo.ui, self._repo, pats, opts)
        if dlg:
            dlg.exec_()

    def vdifflocal(self):
        if self.path is None:
            return
        pats = [hglib.fromunicode(self.path)]
        assert type(self.rev) is int
        opts = {'rev':['rev(%d)' % self.rev]}
        dlg = visdiff.visualdiff(self._repo.ui, self._repo, pats, opts)
        if dlg:
            dlg.exec_()

    def editfile(self):
        if self.path is None:
            return
        if self.rev is None:
            qtlib.editfiles(self._repo, [hglib.fromunicode(self.path)],
                            parent=self)
        else:
            base, _ = visdiff.snapshot(self._repo,
                                       [hglib.fromunicode(self.path)],
                                       self._repo[self.rev])
            files = [os.path.join(base, hglib.fromunicode(self.path))]
            qtlib.editfiles(self._repo, files, parent=self)

    def editlocal(self):
        if self.path is None:
            return
        qtlib.editfiles(self._repo, [hglib.fromunicode(self.path)],
                        parent=self)

    def revertfile(self):
        if self.path is None:
            return
        rev = self.rev
        if rev is None:
            rev = self._repo['.'].rev()
        dlg = revert.RevertDialog(self._repo, [hglib.fromunicode(self.path)],
                                  rev, self)
        dlg.exec_()

    def _navigate(self, filename, dlgclass, dlgdict):
        if not filename:
            filename = hglib.fromunicode(self.path)
        if filename not in dlgdict:
            repoviewer = self.window()
            if not isinstance(repoviewer, workbench.Workbench):
                repoviewer = None
            dlg = dlgclass(self._repo, filename, repoviewer)
            dlgdict[filename] = dlg
            ufname = hglib.tounicode(filename)
            dlg.setWindowTitle(_('Hg file log viewer - %s') % ufname)
        dlg = dlgdict[filename]
        dlg.goto(self.rev)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def opensubrepo(self):
        path = self._repo.wjoin(hglib.fromunicode(self.path))
        if os.path.isdir(path):
            self.linkActivated.emit(u'subrepo:'+hglib.tounicode(path))
        else:
            QMessageBox.warning(self,
                _("Cannot open subrepository"),
                _("The selected subrepository does not exist on the working directory"))

    def explore(self):
        root = self._repo.wjoin(hglib.fromunicode(self.path))
        if os.path.isdir(root):
            QDesktopServices.openUrl(QUrl.fromLocalFile(hglib.tounicode(root)))

    def terminal(self):
        root = self._repo.wjoin(hglib.fromunicode(self.path))
        if os.path.isdir(root):
            qtlib.openshell(root, hglib.fromunicode(self.path))

    def showEvent(self, event):
        QWidget.showEvent(self, event)
        if self._selectedrev != self._rev:
            # If the selected revision is not the same as the current revision
            # we must "reload" the manifest contents with the selected revision
            self.setRev(self._selectedrev)

    #@pyqtSlot(QModelIndex)
    def onDoubleClick(self, index):
        itemissubrepo = (self._treemodel.fileStatus(index) == 'S')
        if itemissubrepo:
            self.opensubrepo()
        else:
            self.vdiff()

    def menuRequest(self, point):
        selmodel = self._treeview.selectionModel()
        if not selmodel.selectedRows():
            return
        point = self._treeview.viewport().mapToGlobal(point)

        currentindex = self._treeview.currentIndex()
        itemissubrepo = (self._treemodel.fileStatus(currentindex) == 'S')

        # Subrepos and regular items have different context menus
        if itemissubrepo:
            contextmenu = self.subrepocontextmenu
            actionlist = ['opensubrepo', 'explore', 'terminal']
        else:
            contextmenu = self.filecontextmenu
            actionlist = ['diff', 'ldiff', 'edit', 'ledit', 'revert',
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

        if actionlist:
            contextmenu.exec_(point)

    @property
    def toolbar(self):
        """Return toolbar for manifest widget"""
        return self._toolbar

    @pyqtSlot(unicode, bool, bool, bool)
    def find(self, pattern, icase=False, wrap=False, forward=True):
        return self._fileview.find(pattern, icase, wrap, forward)

    @pyqtSlot(unicode, bool)
    def highlightText(self, pattern, icase=False):
        self._fileview.highlightText(pattern, icase)

    def _setupmodel(self):
        self._treemodel = ManifestModel(self._repo, self._rev,
                                        statusfilter=self._statusfilter.status(),
                                        parent=self)
        oldmodel = self._treeview.model()
        oldselmodel = self._treeview.selectionModel()
        self._treeview.setModel(self._treemodel)
        if oldmodel:
            oldmodel.deleteLater()
        if oldselmodel:
            oldselmodel.deleteLater()

        selmodel = self._treeview.selectionModel()
        selmodel.currentChanged.connect(self._updatecontent)
        selmodel.currentChanged.connect(self._emitPathChanged)

        self._statusfilter.statusChanged.connect(self._treemodel.setStatusFilter)
        self._statusfilter.statusChanged.connect(self._autoexpandtree)
        self._autoexpandtree()

    @pyqtSlot()
    def _autoexpandtree(self):
        """expand file tree if the number of the items isn't large"""
        if 'C' not in self._statusfilter.status():
            self._treeview.expandAll()

    def reload(self):
        # TODO
        pass

    def setRepo(self, repo):
        self._repo = repo
        #self._fileview.setRepo(repo)
        self._fileview.repo = repo
        if len(repo) <= self._rev:
            self._rev = len(repo)-1
        self._setupmodel()

    @property
    def rev(self):
        """Return current revision"""
        return self._rev

    def selectRev(self, rev):
        """
        Select the revision that must be set when the dialog is shown again
        """
        self._selectedrev = rev

    @pyqtSlot(int)
    @pyqtSlot(object)
    def setRev(self, rev):
        """Change revision to show"""
        self._selectedrev = rev
        self.revpanel.set_revision(rev)
        self.revpanel.update(repo = self._repo)
        if rev == self._rev:
            return
        self._rev = rev
        path = self.path
        self.revChanged.emit(rev)
        self._setupmodel()
        ctx = self._repo[rev]
        if path and hglib.fromunicode(path) in ctx:
            # recover file selection after reloading the model
            self.setPath(path)
            self._fileview.setContext(ctx)
            self._fileview.displayFile(self.path, self.status)
        # update sensitivity of actions
        real = type(rev) is int
        self._actions['ldiff'].setEnabled(real)
        for act in ['diff', 'edit']:
            self._actions[act].setEnabled(real or rev is None)
        self._actions['revert'].setEnabled(real)

    @pyqtSlot(unicode, object)
    @pyqtSlot(unicode, object, int)
    def setSource(self, path, rev, line=None):
        """Change path and revision to show at once"""
        if self._rev != rev:
            self._rev = rev
            self._setupmodel()
            self.revChanged.emit(rev)
        if path != self.path:
            self.setPath(path)
            ctx = self._repo[rev]
            if hglib.fromunicode(self.path) in ctx:
                self._fileview.displayFile(path, self.status)
                if line:
                    self._fileview.showLine(int(line) - 1)
            else:
                self._fileview.clearDisplay()

    @property
    def path(self):
        """Return currently selected path [unicode]"""
        return self._treemodel.filePath(self._treeview.currentIndex())

    @property
    def status(self):
        """Return currently selected path"""
        return self._treemodel.fileStatus(self._treeview.currentIndex())

    @pyqtSlot(unicode)
    def setPath(self, path):
        """Change path to show"""
        self._treeview.setCurrentIndex(self._treemodel.indexFromPath(path))

    def displayFile(self):
        ctx, path = self._treemodel.fileSubrepoCtxFromPath(self.path)
        if ctx is None:
            ctx = self._repo[self._rev]
        else:
            ctx._repo.tabwidth = self._repo.tabwidth
            ctx._repo.maxdiff = self._repo.maxdiff
        self._fileview.setContext(ctx)
        self._fileview.displayFile(path, self.status)

    @pyqtSlot()
    def _updatecontent(self):
        self.displayFile()

    @pyqtSlot()
    def _emitPathChanged(self):
        self.pathChanged.emit(self.path)

def connectsearchbar(manifestwidget, searchbar):
    """Connect searchbar to manifest widget"""
    searchbar.conditionChanged.connect(manifestwidget.highlightText)
    searchbar.searchRequested.connect(manifestwidget.find)

def _openineditor(repo, path, rev, line=None, pattern=None, parent=None):
    """Open editor to show the specified file [unicode]"""
    path = hglib.fromunicode(path)
    pattern = hglib.fromunicode(pattern)
    base = visdiff.snapshot(repo, [path], repo[rev])[0]
    files = [os.path.join(base, path)]
    qtlib.editfiles(repo, files, line, pattern, parent=self)


def run(ui, *pats, **opts):
    repo = opts.get('repo') or thgrepo.repository(ui, paths.find_root())
    try:
        # ManifestWidget expects integer revision
        rev = repo[opts.get('rev')].rev()
    except error.RepoLookupError, e:
        qtlib.ErrorMsgBox(_('Failed to open Manifest dialog'),
                          hglib.tounicode(e.message))
        return
    dlg = ManifestDialog(repo, rev)

    # set initial state after dialog visible
    def init():
        try:
            if pats:
                path = hglib.canonpaths(pats)[0]
            elif 'canonpath' in opts:
                path = opts['canonpath']
            else:
                return
            line = opts.get('line') and int(opts['line']) or None
            dlg.setSource(path, rev, line)
            if opts.get('pattern'):
                dlg.setSearchPattern(opts['pattern'])
            if dlg._manifest_widget._fileview.actionAnnMode.isEnabled():
                dlg._manifest_widget._fileview.actionAnnMode.trigger()
            if 'ignorecase' in opts:
                dlg.setSearchCaseInsensitive(opts['ignorecase'])
        except IndexError:
            pass
        dlg.setSearchPattern(hglib.tounicode(opts.get('pattern')) or '')
    QTimer.singleShot(0, init)

    return dlg
