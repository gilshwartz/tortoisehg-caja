# filectxactions.py - context menu actions for repository files
#
# Copyright 2010 Adrian Buehlmann <adrian@cadifra.com>
# Copyright 2010 Steve Borho <steve@borho.org>
# Copyright 2012 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import util

from tortoisehg.hgqt import qtlib, revert, thgrepo, visdiff
from tortoisehg.hgqt.filedialogs import FileLogDialog, FileDiffDialog
from tortoisehg.hgqt.i18n import _
from tortoisehg.util import hglib

_actionsbytype = {
    'subrepo': ['opensubrepo', 'explore', 'terminal', 'copypath', None,
                'revert'],
    'file': ['diff', 'ldiff', None, 'edit', 'save', None, 'ledit', 'lopen',
             'copypath', None, 'revert', None, 'navigate', 'diffnavigate'],
    'dir': ['diff', 'ldiff', None, 'revert', None, 'filter',
            None, 'explore', 'terminal', 'copypath'],
    }

class FilectxActions(QObject):
    """Container for repository file actions"""

    linkActivated = pyqtSignal(unicode)
    filterRequested = pyqtSignal(QString)
    """Ask the repowidget to change its revset filter"""


    def __init__(self, repo, parent=None, rev=None):
        super(FilectxActions, self).__init__(parent)
        if parent is not None and not isinstance(parent, QWidget):
            raise ValueError('parent must be a QWidget')

        self.repo = repo
        self.ctx = self.repo[rev]
        self._selectedfiles = []  # local encoding
        self._currentfile = None  # local encoding
        self._itemissubrepo = False
        self._itemisdir = False

        self._diff_dialogs = {}
        self._nav_dialogs = {}
        self._contextmenus = {}

        self._actions = {}
        for name, desc, icon, key, tip, cb in [
            ('navigate', _('File history'), 'hg-log', 'Shift+Return',
             _('Show the history of the selected file'), self.navigate),
            ('filter', _('Folder history'), 'hg-log', None,
             _('Show the history of the selected file'), self.filterfile),
            ('diffnavigate', _('Compare file revisions'), 'compare-files', None,
             _('Compare revisions of the selected file'), self.diffNavigate),
            ('diff', _('Diff to parent'), 'visualdiff', 'Ctrl+D',
             _('View file changes in external diff tool'), self.vdiff),
            ('ldiff', _('Diff to local'), 'ldiff', 'Shift+Ctrl+D',
             _('View changes to current in external diff tool'),
             self.vdifflocal),
            ('edit', _('View at Revision'), 'view-at-revision', 'Shift+Ctrl+E',
             _('View file as it appeared at this revision'), self.editfile),
            ('save', _('Save at Revision'), None, 'Shift+Ctrl+S',
             _('Save file as it appeared at this revision'), self.savefile),
            ('ledit', _('Edit Local'), 'edit-file', None,
             _('Edit current file in working copy'), self.editlocal),
            ('lopen', _('Open Local'), '', 'Shift+Ctrl+L',
             _('Edit current file in working copy'), self.openlocal),
            ('copypath', _('Copy Path'), '', 'Shift+Ctrl+C',
             _('Copy full path of file(s) to the clipboard'), self.copypath),
            ('revert', _('Revert to Revision'), 'hg-revert', 'Shift+Ctrl+R',
             _('Revert file(s) to contents at this revision'),
             self.revertfile),
            ('opensubrepo', _('Open subrepository'), 'thg-repository-open',
             'Shift+Ctrl+O', _('Open the selected subrepository'),
             self.opensubrepo),
            ('explore', _('Explore folder'), 'system-file-manager',
             None, _('Open the selected folder in the system file manager'),
             self.explore),
            ('terminal', _('Open terminal here'), 'utilities-terminal', None,
             _('Open a shell terminal in the selected folder'),
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

    def setRepo(self, repo):
        self.repo = repo

    def setRev(self, rev):
        self.ctx = self.repo[rev]
        real = type(rev) is int
        wd = rev is None
        for act in ['navigate', 'diffnavigate', 'ldiff', 'edit', 'save']:
            self._actions[act].setEnabled(real)
        for act in ['diff', 'revert']:
            self._actions[act].setEnabled(real or wd)

    def setPaths(self, selectedfiles, currentfile=None, itemissubrepo=False,
                 itemisdir=False):
        """Set selected files [unicode]"""
        self.setPaths_(map(hglib.fromunicode, selectedfiles),
                       hglib.fromunicode(currentfile), itemissubrepo, itemisdir)

    def setPaths_(self, selectedfiles, currentfile=None, itemissubrepo=False,
                  itemisdir=False):
        """Set selected files [local encoding]"""
        if not currentfile and selectedfiles:
            currentfile = selectedfiles[0]
        self._selectedfiles = list(selectedfiles)
        self._currentfile = currentfile
        self._itemissubrepo = itemissubrepo
        self._itemisdir = itemisdir

    def actions(self):
        """List of the actions; The owner widget should register them"""
        return self._actions.values()

    def menu(self):
        """Menu for the current selection if available; otherwise None"""
        # Subrepos and regular items have different context menus
        if self._itemissubrepo:
            contextmenu = self._cachedcontextmenu('subrepo')
        elif self._itemisdir:
            contextmenu = self._cachedcontextmenu('dir')
        else:
            contextmenu = self._cachedcontextmenu('file')

        ln = len(self._selectedfiles)
        if ln == 0:
            return
        if ln > 1 and not self._itemissubrepo:
            singlefileactions = False
        else:
            singlefileactions = True
        self._actions['navigate'].setEnabled(singlefileactions)
        self._actions['diffnavigate'].setEnabled(singlefileactions)
        return contextmenu

    def _cachedcontextmenu(self, key):
        contextmenu = self._contextmenus.get(key)
        if contextmenu:
            return contextmenu

        contextmenu = QMenu(self.parent())
        for act in _actionsbytype[key]:
            if act:
                contextmenu.addAction(self._actions[act])
            else:
                contextmenu.addSeparator()
        self._contextmenus[key] = contextmenu
        return contextmenu

    def navigate(self):
        self._navigate(FileLogDialog, self._nav_dialogs)

    def diffNavigate(self):
        self._navigate(FileDiffDialog, self._diff_dialogs)

    def filterfile(self):
        """Ask to only show the revisions in which files on that folder are
        present"""
        if not self._selectedfiles:
            return
        self.filterRequested.emit("file('%s/**')" % self._selectedfiles[0])

    def vdiff(self):
        repo, filenames, rev = self._findsub(self._selectedfiles)
        if not filenames:
            return
        if rev in repo.thgmqunappliedpatches:
            QMessageBox.warning(self.parent(),
                _("Cannot display visual diff"),
                _("Visual diffs are not supported for unapplied patches"))
            return
        opts = {'change': rev}
        dlg = visdiff.visualdiff(repo.ui, repo, filenames, opts)
        if dlg:
            dlg.exec_()

    def vdifflocal(self):
        repo, filenames, rev = self._findsub(self._selectedfiles)
        if not filenames:
            return
        assert type(rev) is int
        opts = {'rev': ['rev(%d)' % rev]}
        dlg = visdiff.visualdiff(repo.ui, repo, filenames, opts)
        if dlg:
            dlg.exec_()

    def editfile(self):
        repo, filenames, rev = self._findsub(self._selectedfiles)
        if not filenames:
            return
        if rev is None:
            qtlib.editfiles(repo, filenames, parent=self.parent())
        else:
            base, _ = visdiff.snapshot(repo, filenames, repo[rev])
            files = [os.path.join(base, filename)
                     for filename in filenames]
            qtlib.editfiles(repo, files, parent=self.parent())

    def savefile(self):
        repo, filenames, rev = self._findsub(self._selectedfiles)
        if not filenames:
            return
        qtlib.savefiles(repo, filenames, rev, parent=self.parent())

    def editlocal(self):
        repo, filenames, _rev = self._findsub(self._selectedfiles)
        if not filenames:
            return
        qtlib.editfiles(repo, filenames, parent=self.parent())

    def openlocal(self):
        repo, filenames, _rev = self._findsub(self._selectedfiles)
        if not filenames:
            return
        qtlib.openfiles(repo, filenames)

    def copypath(self):
        absfiles = [util.localpath(self.repo.wjoin(f))
                    for f in self._selectedfiles]
        QApplication.clipboard().setText(
            hglib.tounicode(os.linesep.join(absfiles)))

    def revertfile(self):
        repo, fileSelection, rev = self._findsub(self._selectedfiles)
        if not fileSelection:
            return
        if rev is None:
            rev = repo[rev].p1().rev()
        dlg = revert.RevertDialog(repo, fileSelection, rev,
                                  parent=self.parent())
        dlg.exec_()

    def _navigate(self, dlgclass, dlgdict):
        repo, filename, rev = self._findsubsingle(self._currentfile)
        if filename and len(repo.file(filename)) > 0:
            if self._currentfile not in dlgdict:
                # dirty hack to pass workbench only if available
                from tortoisehg.hgqt import workbench  # avoid cyclic dep
                repoviewer = None
                if self.parent() and isinstance(self.parent().window(),
                                                workbench.Workbench):
                    repoviewer = self.parent().window()
                dlg = dlgclass(repo, filename, repoviewer=repoviewer)
                dlgdict[self._currentfile] = dlg
                ufname = hglib.tounicode(filename)
                dlg.setWindowTitle(_('Hg file log viewer - %s') % ufname)
                dlg.setWindowIcon(qtlib.geticon('hg-log'))
            dlg = dlgdict[self._currentfile]
            dlg.goto(rev)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()

    def _findsub(self, paths):
        """Find the nearest (sub-)repository for the given paths

        All paths should be in the same repository. Otherwise, unmatched
        paths are silently omitted.
        """
        if not paths:
            return self.repo, [], self.ctx.rev()

        repopath, _relpath, ctx = hglib.getDeepestSubrepoContainingFile(
            paths[0], self.ctx)
        if not repopath:
            return self.repo, paths, self.ctx.rev()

        repo = thgrepo.repository(self.repo.ui, self.repo.wjoin(repopath))
        pfx = repopath + '/'
        relpaths = [e[len(pfx):] for e in paths if e.startswith(pfx)]
        return repo, relpaths, ctx.rev()

    def _findsubsingle(self, path):
        if not path:
            return self.repo, None, self.ctx.rev()
        repo, relpaths, rev = self._findsub([path])
        return repo, relpaths[0], rev

    def opensubrepo(self):
        path = os.path.join(self.repo.root, self._currentfile)
        if os.path.isdir(path):
            spath = path[len(self.repo.root)+1:]
            source, revid, stype = self.ctx.substate[spath]
            link = u'subrepo:' + hglib.tounicode(path)
            if stype == 'hg':
                link = u'%s?%s' % (link, revid)
            self.linkActivated.emit(link)
        else:
            QMessageBox.warning(self,
                _("Cannot open subrepository"),
                _("The selected subrepository does not exist on the working "
                  "directory"))

    def explore(self):
        root = self.repo.wjoin(self._currentfile)
        if os.path.isdir(root):
            qtlib.openlocalurl(root)

    def terminal(self):
        root = self.repo.wjoin(self._currentfile)
        if os.path.isdir(root):
            qtlib.openshell(root, self._currentfile)
