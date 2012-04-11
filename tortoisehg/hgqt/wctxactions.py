# wctxactions.py - menu and responses for working copy files
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import re

from mercurial import util, error, merge, commands
from tortoisehg.hgqt import qtlib, htmlui, visdiff
from tortoisehg.util import hglib, shlib
from tortoisehg.hgqt.i18n import _

from PyQt4.QtCore import Qt, QObject, QDir
from PyQt4.QtGui import *

class WctxActions(QObject):
    'container class for working context actions'

    def __init__(self, repo, parent):
        super(WctxActions, self).__init__(parent)

        self.menu = QMenu(parent)
        self.repo = repo
        allactions = []

        def make(text, func, types, icon=None, keys=None):
            action = QAction(text, parent)
            action._filetypes = types
            action._runfunc = func
            if icon:
                action.setIcon(qtlib.getmenuicon(icon))
            if keys:
                action.setShortcut(QKeySequence(keys))
            action.triggered.connect(self.runAction)
            parent.addAction(action)
            allactions.append(action)

        make(_('&Visual Diff'), vdiff, frozenset('MAR!'), 'visualdiff', 'CTRL+D')
        make(_('Copy patch'), copyPatch, frozenset('MAR!'), 'copy-patch')
        make(_('Edit'), edit, frozenset('MACI?'), 'edit-file', 'SHIFT+CTRL+E')
        make(_('Copy path'), copyPath, frozenset('MARC?!I'), '')
        make(_('View missing'), viewmissing, frozenset('R!'))
        allactions.append(None)
        make(_('&Revert...'), revert, frozenset('MAR!'), 'hg-revert')
        make(_('&Add'), add, frozenset('R'), 'fileadd')
        allactions.append(None)
        make(_('File History'), log, frozenset('MARC!'), 'hg-log')
        make(_('&Annotate'), annotate, frozenset('MARC!'), 'hg-annotate')
        allactions.append(None)
        make(_('&Forget'), forget, frozenset('MAC!'), 'filedelete')
        make(_('&Add'), add, frozenset('I?'), 'fileadd')
        make(_('&Detect Renames...'), guessRename, frozenset('A?!'),
             'detect_rename')
        make(_('&Ignore...'), ignore, frozenset('?'), 'ignore')
        make(_('Remove versioned'), remove, frozenset('C'), 'remove')
        make(_('&Delete unversioned...'), delete, frozenset('?I'), 'hg-purge')
        allactions.append(None)
        make(_('Mark unresolved'), unmark, frozenset('r'))
        make(_('Mark resolved'), mark, frozenset('u'))
        self.allactions = allactions

    def updateActionSensitivity(self, selrows):
        'Enable/Disable permanent actions based on current selection'
        self.selrows = selrows
        alltypes = set()
        for types, wfile in selrows:
            alltypes |= types
        for action in self.allactions:
            if action is not None:
                action.setEnabled(bool(action._filetypes & alltypes))

    def makeMenu(self, selrows):
        self.selrows = selrows
        repo, menu = self.repo, self.menu

        alltypes = set()
        for types, wfile in selrows:
            alltypes |= types

        menu.clear()
        addedActions = False
        for action in self.allactions:
            if action is None:
                if addedActions:
                    menu.addSeparator()
                    addedActions = False
            elif action._filetypes & alltypes:
                menu.addAction(action)
                addedActions = True

        def make(text, func, types, icon=None):
            if not types & alltypes:
                return
            action = menu.addAction(text)
            action._filetypes = types
            action._runfunc = func
            if icon:
                action.setIcon(qtlib.getmenuicon(icon))
            action.triggered.connect(self.runAction)

        if len(repo.parents()) > 1:
            make(_('View other'), viewother, frozenset('MA'))

        if len(selrows) == 1:
            menu.addSeparator()
            make(_('&Copy...'), copy, frozenset('MC'), 'edit-copy')
            make(_('Rename...'), rename, frozenset('MC'), 'hg-rename')

        # Add 'was renamed from' actions for unknown files
        t, path = selrows[0]
        wctx = self.repo[None]
        if t & frozenset('?') and wctx.deleted():
            rmenu = QMenu(_('Was renamed from'), self.parent())
            for d in wctx.deleted()[:15]:
                def mkaction(deleted):
                    a = rmenu.addAction(hglib.tounicode(deleted))
                    a.triggered.connect(lambda: renamefromto(repo, deleted, path))
                mkaction(d)
            menu.addSeparator()
            menu.addMenu(rmenu)

        # Add restart merge actions for resolved files
        if alltypes & frozenset('u'):
            f = make(_('Restart Merge...'), resolve, frozenset('u'))
            files = [f for t, f in selrows if 'u' in t]
            rmenu = QMenu(_('Restart merge with'), self.parent())
            for tool in hglib.mergetools(repo.ui):
                def mkaction(rtool):
                    a = rmenu.addAction(hglib.tounicode(rtool))
                    a.triggered.connect(lambda: resolve_with(rtool, repo, files))
                mkaction(tool)
            menu.addSeparator()
            menu.addMenu(rmenu)
        return menu

    def runAction(self):
        'run wrapper for all action methods'

        repo, action, parent = self.repo, self.sender(), self.parent()
        func = action._runfunc
        files = [wfile for t, wfile in self.selrows if t & action._filetypes]

        hu = htmlui.htmlui()
        name = hglib.tounicode(func.__name__.title())
        notify = False
        cwd = os.getcwd()
        try:
            os.chdir(repo.root)
            try:
                # All operations should quietly succeed.  Any error should
                # result in a message box
                notify = func(parent, hu, repo, files)
                o, e = hu.getdata()
                if e:
                    QMessageBox.warning(parent, name + _(' errors'), e)
                elif o:
                    QMessageBox.information(parent, name + _(' output'), o)
                elif notify:
                    wfiles = [repo.wjoin(x) for x in files]
                    shlib.shell_notify(wfiles)
            except (IOError, OSError), e:
                err = hglib.tounicode(str(e))
                QMessageBox.critical(parent, name + _(' Aborted'), err)
            except util.Abort, e:
                if e.hint:
                    err = _('%s (hint: %s)') % (hglib.tounicode(str(e)),
                                                hglib.tounicode(e.hint))
                else:
                    err = hglib.tounicode(str(e))
                QMessageBox.critical(parent, name + _(' Aborted'), err)
            except (error.LookupError), e:
                err = hglib.tounicode(str(e))
                QMessageBox.critical(parent, name + _(' Aborted'), err)
        finally:
            os.chdir(cwd)
        return notify

def renamefromto(repo, deleted, unknown):
    repo[None].copy(deleted, unknown)
    repo[None].forget([deleted]) # !->R

def copyPatch(parent, ui, repo, files):
    ui.pushbuffer()
    try:
        commands.diff(ui, repo, *files)
    except Exception, e:
        ui.popbuffer()
        if 'THGDEBUG' in os.environ:
            import traceback
            traceback.print_exc()
        return
    output = ui.popbuffer()
    QApplication.clipboard().setText(hglib.tounicode(output))

def copyPath(parent, ui, repo, files):
    clip = QApplication.clipboard()
    absfiles = [hglib.fromunicode(QDir.toNativeSeparators(repo.wjoin(fname)))
         for fname in files]
    clip.setText(os.linesep.join(absfiles))

def vdiff(parent, ui, repo, files):
    dlg = visdiff.visualdiff(ui, repo, files, {})
    if dlg:
        dlg.exec_()

def edit(parent, ui, repo, files, lineno=None, search=None):
    qtlib.editfiles(repo, files, lineno, search, parent)

def viewmissing(parent, ui, repo, files):
    base, _ = visdiff.snapshot(repo, files, repo['.'])
    edit(parent, ui, repo, [os.path.join(base, f) for f in files])

def viewother(parent, ui, repo, files):
    wctx = repo[None]
    assert bool(wctx.p2())
    base, _ = visdiff.snapshot(repo, files, wctx.p2())
    edit(parent, ui, repo, [os.path.join(base, f) for f in files])

def revert(parent, ui, repo, files):
    revertopts = {'date': None, 'rev': '.'}

    if len(repo.parents()) > 1:
        res = qtlib.CustomPrompt(
                _('Uncommited merge - please select a parent revision'),
                _('Revert files to local or other parent?'), parent,
                (_('&Local'), _('&Other'), _('Cancel')), 0, 2, files).run()
        if res == 0:
            revertopts['rev'] = repo[None].p1().rev()
        elif res == 1:
            revertopts['rev'] = repo[None].p2().rev()
        else:
            return
        commands.revert(ui, repo, *files, **revertopts)
    else:
        res = qtlib.CustomPrompt(
                _('Confirm Revert'),
                _('Revert local file changes?'), parent,
                (_('&Revert with backup'), _('&Discard changes'),
                _('Cancel')), 2, 2, files).run()
        if res == 2:
            return False
        if res == 1:
            revertopts['no_backup'] = True
        commands.revert(ui, repo, *files, **revertopts)
        return True

def log(parent, ui, repo, files):
    from tortoisehg.hgqt.workbench import run
    from tortoisehg.hgqt.run import qtrun
    opts = {'root': repo.root}
    qtrun(run, repo.ui, *files, **opts)
    return False

def annotate(parent, ui, repo, files):
    from tortoisehg.hgqt.manifestdialog import run
    from tortoisehg.hgqt.run import qtrun
    opts = {'repo': repo, 'canonpath' : files[0], 'rev' : repo['.'].rev()}
    qtrun(run, repo.ui, **opts)
    return False

def forget(parent, ui, repo, files):
    commands.forget(ui, repo, *files)
    return True

def add(parent, ui, repo, files):
    commands.add(ui, repo, *files)
    return True

def guessRename(parent, ui, repo, files):
    from tortoisehg.hgqt.guess import DetectRenameDialog
    dlg = DetectRenameDialog(repo, parent, *files)
    def matched():
        ret[0] = True
    ret = [False]
    dlg.matchAccepted.connect(matched)
    dlg.finished.connect(dlg.deleteLater)
    dlg.exec_()
    return ret[0]

def ignore(parent, ui, repo, files):
    from tortoisehg.hgqt.hgignore import HgignoreDialog
    dlg = HgignoreDialog(repo, parent, *files)
    dlg.finished.connect(dlg.deleteLater)
    return dlg.exec_() == QDialog.Accepted

def remove(parent, ui, repo, files):
    commands.remove(ui, repo, *files)
    return True

def delete(parent, ui, repo, files):
    res = qtlib.CustomPrompt(
            _('Confirm Delete Unversioned'),
            _('Delete the following unversioned files?'),
            parent, (_('&Delete'), _('Cancel')), 1, 1, files).run()
    if res == 1:
        return
    for wfile in files:
        os.unlink(wfile)
    return True

def copy(parent, ui, repo, files):
    assert len(files) == 1
    wfile = repo.wjoin(files[0])
    fd = QFileDialog(parent)
    fname = fd.getSaveFileName(parent, _('Copy file to'), wfile)
    if not fname:
        return
    fname = hglib.fromunicode(fname)
    wfiles = [wfile, fname]
    commands.copy(ui, repo, *wfiles)
    return True

def rename(parent, ui, repo, files):
    from tortoisehg.hgqt.rename import RenameDialog
    assert len(files) == 1
    dlg = RenameDialog(ui, files, parent)
    dlg.finished.connect(dlg.deleteLater)
    dlg.exec_()
    return True

def unmark(parent, ui, repo, files):
    ms = merge.mergestate(repo)
    for wfile in files:
        ms.mark(wfile, 'u')
    ms.commit()
    return True

def mark(parent, ui, repo, files):
    ms = merge.mergestate(repo)
    for wfile in files:
        ms.mark(wfile, 'r')
    ms.commit()
    return True

def resolve(parent, ui, repo, files):
    commands.resolve(ui, repo, *files)
    return True

def resolve_with(tool, repo, files):
    opts = {'tool': tool}
    paths = [repo.wjoin(f) for f in files]
    commands.resolve(repo.ui, repo, *paths, **opts)
    return True
