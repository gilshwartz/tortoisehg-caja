# mq.py - TortoiseHg MQ widget
#
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os
import re
import time

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import hg, ui, url, util, error
from mercurial import merge as mergemod
from hgext import mq as mqmod

from tortoisehg.util import hglib, patchctx
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, cmdui, rejects, qscilib, thgrepo, status
from tortoisehg.hgqt import qqueue, qreorder, fileview, thgimport, messageentry
from tortoisehg.hgqt.qtlib import geticon

# TODO
# keep original file name in file list item
# more wctx functions

def defaultNewPatchName(repo):
    t = time.strftime('%Y-%m-%d_%H-%M-%S')
    return t + '_r%d+.diff' % repo['.'].rev()

def getPatchNameLineEdit():
    patchNameLE = QLineEdit()
    if hasattr(patchNameLE, 'setPlaceholderText'): # Qt >= 4.7
        patchNameLE.setPlaceholderText(_('### patch name ###'))
    return patchNameLE

def getUserOptions(opts, *optionlist):
    out = []
    for opt in optionlist:
        if opt not in opts:
            continue
        val = opts[opt]
        if val is False:
            continue
        elif val is True:
            out.append('--' + opt)
        else:
            out.append('--' + opt)
            out.append(val)
    return out

def mqNewRefreshCommand(repo, isnew, stwidget, pnwidget, message, opts, olist):
    if isnew:
        name = hglib.fromunicode(pnwidget.text())
        if not name:
            qtlib.ErrorMsgBox(_('Patch Name Required'),
                              _('You must enter a patch name'))
            pnwidget.setFocus()
            return
        cmdline = ['qnew', '--repository', repo.root, name]
    else:
        cmdline = ['qrefresh', '--repository', repo.root]
    if message:
        cmdline += ['--message=' + hglib.fromunicode(message)]
    cmdline += getUserOptions(opts, *olist)
    files = ['--'] + [repo.wjoin(x) for x in stwidget.getChecked()]
    addrem = [repo.wjoin(x) for x in stwidget.getChecked('!?')]
    if len(files) > 1:
        cmdline += files
    else:
        cmdline += ['--exclude', repo.root]
    if addrem:
        cmdlines = [ ['addremove', '-R', repo.root] + addrem, cmdline]
    else:
        cmdlines = [cmdline]
    return cmdlines

class MQPatchesWidget(QDockWidget):
    showMessage = pyqtSignal(unicode)
    output = pyqtSignal(QString, QString)
    progress = pyqtSignal(QString, object, QString, QString, object)
    makeLogVisible = pyqtSignal(bool)

    def __init__(self, parent, **opts):
        QDockWidget.__init__(self, parent)
        self.repo = None
        self.opts = opts
        self.refreshing = False
        self.finishfunc = None

        self.setFeatures(QDockWidget.DockWidgetClosable |
                         QDockWidget.DockWidgetMovable  |
                         QDockWidget.DockWidgetFloatable)
        self.setWindowTitle(_('Patch Queue'))

        w = QWidget()
        mainlayout = QVBoxLayout()
        mainlayout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(mainlayout)
        self.setWidget(w)

        # top toolbar
        w = QWidget()
        tbarhbox = QHBoxLayout()
        tbarhbox.setContentsMargins(0, 0, 0, 0)
        w.setLayout(tbarhbox)
        mainlayout.addWidget(w)

        self.qpushAllAct = a = QAction(
            geticon('hg-qpush-all'), _('Push all', 'MQ QPush'), self)
        a.setToolTip(_('Apply all patches'))
        self.qpushAct = a = QAction(
            geticon('hg-qpush'), _('Push', 'MQ QPush'), self)
        a.setToolTip(_('Apply one patch'))
        self.setGuardsAct = a = QAction(
            geticon('hg-qguard'), _('Guards'), self)
        a.setToolTip(_('Configure guards for selected patch'))
        self.qreorderAct = a = QAction(
            geticon('hg-qreorder'), _('Reorder patches'), self)
        a.setToolTip(_('Reorder patches'))
        self.qdeleteAct = a = QAction(
            geticon('hg-qdelete'), _('Delete'), self)
        a.setToolTip(_('Delete selected patches'))
        self.qpopAct = a = QAction(
            geticon('hg-qpop'), _('Pop'), self)
        a.setToolTip(_('Unapply one patch'))
        self.qpopAllAct = a = QAction(
            geticon('hg-qpop-all'), _('Pop all'), self)
        a.setToolTip(_('Unapply all patches'))
        self.qtbar = tbar = QToolBar(_('Patch Queue Actions Toolbar'))
        tbar.setIconSize(QSize(18, 18))
        tbarhbox.addWidget(tbar)
        tbar.addAction(self.qpushAct)
        tbar.addAction(self.qpushAllAct)
        tbar.addSeparator()
        tbar.addAction(self.qpopAct)
        tbar.addAction(self.qpopAllAct)
        tbar.addSeparator()
        tbar.addAction(self.qreorderAct)
        tbar.addSeparator()
        tbar.addAction(self.qdeleteAct)
        tbar.addSeparator()
        tbar.addAction(self.setGuardsAct)

        self.queueFrame = w = QFrame()
        mainlayout.addWidget(w)

        # Patch Queue Frame
        layout = QVBoxLayout()
        layout.setSpacing(5)
        layout.setContentsMargins(0, 0, 0, 0)
        self.queueFrame.setLayout(layout)

        self.queueListWidget = QListWidget(self)
        layout.addWidget(self.queueListWidget, 1)

        bbarhbox = QHBoxLayout()
        bbarhbox.setSpacing(5)
        layout.addLayout(bbarhbox)
        self.guardSelBtn = QPushButton()
        bbarhbox.addWidget(self.guardSelBtn)

        # Command runner and connections...
        self.cmd = cmdui.Runner(not parent, self)
        self.cmd.output.connect(self.output)
        self.cmd.makeLogVisible.connect(self.makeLogVisible)
        self.cmd.progress.connect(self.progress)
        self.cmd.commandFinished.connect(self.onCommandFinished)

        self.queueListWidget.currentRowChanged.connect(self.onPatchSelected)
        self.queueListWidget.itemActivated.connect(self.onGotoPatch)
        self.queueListWidget.itemChanged.connect(self.onRenamePatch)

        self.qpushAllAct.triggered.connect(self.onPushAll)
        self.qpushAct.triggered.connect(self.onPush)
        self.qreorderAct.triggered.connect(self.onQreorder)
        self.qpopAllAct.triggered.connect(self.onPopAll)
        self.qpopAct.triggered.connect(self.onPop)
        self.setGuardsAct.triggered.connect(self.onGuardConfigure)
        self.qdeleteAct.triggered.connect(self.onDelete)

        self.setAcceptDrops(True)

        self.layout().setContentsMargins(2, 2, 2, 2)

        self.loadConfigs()
        QTimer.singleShot(0, self.reload)

    def setrepo(self, repo):
        if self.repo:
            self.repo.configChanged.disconnect(self.onConfigChanged)
            self.repo.repositoryChanged.disconnect(self.onRepositoryChanged)
        self.repo = None
        if repo and 'mq' in repo.extensions():
            self.repo = repo
            self.repo.configChanged.connect(self.onConfigChanged)
            self.repo.repositoryChanged.connect(self.onRepositoryChanged)
        QTimer.singleShot(0, self.reload)

    def getUserOptions(self, *optionlist):
        out = []
        for opt in optionlist:
            if opt not in self.opts:
                continue
            val = self.opts[opt]
            if val is False:
                continue
            elif val is True:
                out.append('--' + opt)
            else:
                out.append('--' + opt)
                out.append(val)
        return out

    @pyqtSlot()
    def onConfigChanged(self):
        'Repository is reporting its config files have changed'
        pass

    @pyqtSlot()
    def onRepositoryChanged(self):
        'Repository is reporting its changelog has changed'
        self.reload()

    @pyqtSlot(int)
    def onCommandFinished(self, ret):
        self.qtbar.setEnabled(True)
        self.repo.decrementBusyCount()
        if self.finishfunc:
            self.finishfunc(ret)
            self.finishfunc = None

    def checkForRejects(self, ret):
        if ret is 0:
            self.refreshStatus()
            return
        rejre = re.compile('saving rejects to file (.*).rej')
        for m in rejre.finditer(self.cmd.core.rawoutput()):
            wfile = m.groups()[0]
            if not os.path.exists(self.repo.wjoin(wfile)):
                continue
            ufile = hglib.tounicode(wfile)
            if qtlib.QuestionMsgBox(_('Manually resolve rejected chunks?'),
                                    _('%s had rejected chunks, edit patched '
                                      'file together with rejects?') % ufile,
                                    parent=self):
                dlg = rejects.RejectsDialog(self.repo.wjoin(wfile), self)
                dlg.exec_()
        self.refreshStatus()

    @pyqtSlot(QString)
    def qqueueActivate(self, uqueue):
        if self.refreshing:
            return
        queue = hglib.fromunicode(uqueue)
        if queue == self.repo.thgactivemqname:
            return
        self.repo.incrementBusyCount()
        self.qtbar.setEnabled(False)
        cmdline = ['qqueue', '-R', self.repo.root, queue]
        def finished(ret):
            if ret:
                for i in xrange(self.queueCombo.count()):
                    if (hglib.fromunicode(self.queueCombo.itemText(i))
                            == self.repo.thgactivemqname):
                        self.queueCombo.setCurrentIndex(i)
                        break
        self.finishfunc = finished
        self.cmd.run(cmdline)

    @pyqtSlot()
    def onPushAll(self):
        if self.cmd.running():
            return
        self.repo.incrementBusyCount()
        cmdline = ['qpush', '-R', self.repo.root, '--all']
        cmdline += self.getUserOptions('force', 'exact')
        self.qtbar.setEnabled(False)
        self.finishfunc = self.checkForRejects
        self.cmd.run(cmdline)

    @pyqtSlot()
    def onPush(self):
        if self.cmd.running():
            return
        self.repo.incrementBusyCount()
        cmdline = ['qpush', '-R', self.repo.root]
        cmdline += self.getUserOptions('force', 'exact')
        self.qtbar.setEnabled(False)
        self.finishfunc = self.checkForRejects
        self.cmd.run(cmdline)

    @pyqtSlot()
    def onPopAll(self):
        if self.cmd.running():
            return
        self.repo.incrementBusyCount()
        cmdline = ['qpop', '-R', self.repo.root, '--all']
        cmdline += self.getUserOptions('force')
        self.qtbar.setEnabled(False)
        self.cmd.run(cmdline)

    @pyqtSlot()
    def onPop(self):
        if self.cmd.running():
            return
        self.repo.incrementBusyCount()
        cmdline = ['qpop', '-R', self.repo.root]
        cmdline += self.getUserOptions('force')
        self.qtbar.setEnabled(False)
        self.cmd.run(cmdline)

    @pyqtSlot()
    def onPushMove(self):
        if self.cmd.running():
            return
        patch = self.queueListWidget.currentItem()._thgpatch
        cmdline = ['qpush', '-R', self.repo.root]
        cmdline += self.getUserOptions('force')
        cmdline += ['--move', '--', patch]
        self.repo.incrementBusyCount()
        self.qtbar.setEnabled(False)
        self.finishfunc = self.checkForRejects
        self.cmd.run(cmdline)

    def onQreorder(self):
        if self.cmd.running():
            return
        def checkGuardsOrComments():
            cont = True
            for p in self.repo.mq.fullseries:
                if '#' in p:
                    cont = qtlib.QuestionMsgBox('Confirm qreorder',
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

    @pyqtSlot()
    def onGuardConfigure(self):
        item = self.queueListWidget.currentItem()
        patch = item._thgpatch
        if item._thgguards:
            uguards = hglib.tounicode(' '.join(item._thgguards))
        else:
            uguards = ''
        new, ok = QInputDialog.getText(self,
                      _('Configure guards'),
                      _('Input new guards for %s:') % hglib.tounicode(patch),
                      text=uguards)
        if not ok or new == uguards:
            return
        guards = []
        for guard in hglib.fromunicode(new).split(' '):
            guard = guard.strip()
            if not guard:
                continue
            if not (guard[0] == '+' or guard[0] == '-'):
                self.showMessage.emit(_('Guards must begin with "+" or "-"'))
                continue
            guards.append(guard)
        cmdline = ['qguard', '-R', self.repo.root, '--', patch]
        if guards:
            cmdline += guards
        else:
            cmdline.insert(3, '--none')
        if self.cmd.running():
            return
        self.repo.incrementBusyCount()
        self.qtbar.setEnabled(False)
        self.cmd.run(cmdline)

    @pyqtSlot()
    def onDelete(self):
        from tortoisehg.hgqt import qdelete
        patch = self.queueListWidget.currentItem()._thgpatch
        dlg = qdelete.QDeleteDialog(self.repo, [patch], self)
        dlg.finished.connect(dlg.deleteLater)
        if dlg.exec_() == QDialog.Accepted:
            self.reload()

    def qgotoRevision(self, rev):
        if self.cmd.running():
            return
        cmdline = ['qgoto', '-R', self.repo.root]
        cmdline += self.getUserOptions('force')
        cmdline += ['--', str(rev)]
        self.repo.incrementBusyCount()
        self.qtbar.setEnabled(False)
        self.finishfunc = self.checkForRejects
        self.cmd.run(cmdline)

    #@pyqtSlot(QListWidgetItem)
    def onGotoPatch(self, item):
        'Patch has been activated (return), issue qgoto'
        if self.cmd.running():
            return
        cmdline = ['qgoto', '-R', self.repo.root]
        cmdline += self.getUserOptions('force')
        cmdline += ['--', item._thgpatch]
        self.repo.incrementBusyCount()
        self.qtbar.setEnabled(False)
        self.finishfunc = self.checkForRejects
        self.cmd.run(cmdline)

    #@pyqtSlot(QListWidgetItem)
    def onRenamePatch(self, item):
        'Patch has been renamed, issue qrename'
        if self.cmd.running():
            return
        from tortoisehg.hgqt import qrename
        newpatchname = hglib.fromunicode(item.text())
        if newpatchname == item._thgpatch:
            return
        else:
            res = qrename.checkPatchname(self.repo.root,
                        self.repo.thgactivemqname, newpatchname, self)
            if not res:
                item.setText(item._thgpatch)
                return
        self.repo.incrementBusyCount()
        self.qtbar.setEnabled(False)
        self.cmd.run(['qrename', '-R', self.repo.root, '--',
                      item._thgpatch, newpatchname])

    @pyqtSlot(int)
    def onPatchSelected(self, row):
        'Patch has been selected, update buttons'
        if self.refreshing:
            return
        if row >= 0:
            patch = self.queueListWidget.item(row)._thgpatch
            applied = set([p.name for p in self.repo.mq.applied])
            self.qdeleteAct.setEnabled(patch not in applied)
            self.setGuardsAct.setEnabled(True)
        else:
            self.qdeleteAct.setEnabled(False)
            self.setGuardsAct.setEnabled(False)

    def refreshStatus(self):
        self.refreshing = False

    def reload(self):
        self.refreshing = True
        self.reselectPatchItem = None
        try:
            try:
                self._reload()
            except Exception, e:
                self.showMessage.emit(hglib.tounicode(str(e)))
                if 'THGDEBUG' in os.environ:
                    import traceback
                    traceback.print_exc()
        finally:
            self.refreshing = False
        if self.reselectPatchItem:
            self.queueListWidget.setCurrentItem(self.reselectPatchItem)
        self.refreshStatus()

    def _reload(self):
        item = self.queueListWidget.currentItem()
        if item:
            wasselected = item._thgpatch
        else:
            wasselected = None
        self.queueListWidget.clear()

        if self.repo is None:
            self.qpushAllAct.setEnabled(False)
            self.qpushAct.setEnabled(False)
            self.qdeleteAct.setEnabled(False)
            self.setGuardsAct.setEnabled(False)
            self.qpopAct.setEnabled(False)
            self.qpopAllAct.setEnabled(False)
            self.qreorderAct.setEnabled(False)
            return

        ui, repo = self.repo.ui.copy(), self.repo

        applied = set([p.name for p in repo.mq.applied])
        self.allguards = set()
        items = []
        for idx, patch in enumerate(repo.mq.series):
            ctx = repo.changectx(patch)
            desc = ctx.longsummary()
            item = QListWidgetItem(hglib.tounicode(patch))
            if patch in applied: # applied
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            elif not repo.mq.pushable(idx)[0]: # guarded
                f = item.font()
                f.setItalic(True)
                item.setFont(f)
            patchguards = repo.mq.seriesguards[idx]
            if patchguards:
                for guard in patchguards:
                    self.allguards.add(guard[1:])
                uguards = hglib.tounicode(', '.join(patchguards))
            else:
                uguards = _('no guards')
            uname = hglib.tounicode(patch)
            item._thgpatch = patch
            item._thgguards = patchguards
            item.setToolTip(u'%s: %s\n%s' % (uname, uguards, desc))
            item.setFlags(Qt.ItemIsSelectable |
                          Qt.ItemIsEditable |
                          Qt.ItemIsEnabled)
            items.append(item)

        for item in reversed(items):
            self.queueListWidget.addItem(item)
            if item._thgpatch == wasselected:
                self.reselectPatchItem = item

        for guard in repo.mq.active():
            self.allguards.add(guard)
        self.refreshSelectedGuards()

        self.qpushAllAct.setEnabled(bool(repo.thgmqunappliedpatches))
        self.qpushAct.setEnabled(bool(repo.thgmqunappliedpatches))
        self.qdeleteAct.setEnabled(False)
        self.setGuardsAct.setEnabled(False)
        self.qpopAct.setEnabled(bool(applied))
        self.qpopAllAct.setEnabled(bool(applied))

    def refreshSelectedGuards(self):
        total = len(self.allguards)
        count = len(self.repo.mq.active())
        oldmenu = self.guardSelBtn.menu()
        if oldmenu:
            oldmenu.setParent(None)
        menu = QMenu(self)
        for guard in self.allguards:
            a = menu.addAction(hglib.tounicode(guard))
            a.setCheckable(True)
            a.setChecked(guard in self.repo.mq.active())
            a.triggered.connect(self.onGuardSelectionChange)
        self.guardSelBtn.setMenu(menu)
        self.guardSelBtn.setText(_('Guards: %d/%d') % (count, total))
        self.guardSelBtn.setEnabled(bool(total))

    def onGuardSelectionChange(self, isChecked):
        guard = hglib.fromunicode(self.sender().text())
        newguards = self.repo.mq.active()[:]
        if isChecked:
            newguards.append(guard)
        elif guard in newguards:
            newguards.remove(guard)
        cmdline = ['qselect', '-R', self.repo.root]
        cmdline += newguards or ['--none']
        self.repo.incrementBusyCount()
        self.qtbar.setEnabled(False)
        self.cmd.run(cmdline)

    def loadConfigs(self):
        'Load history, etc, from QSettings instance'
        pass

    def storeConfigs(self):
        'Save history, etc, in QSettings instance'
        pass

    def canExit(self):
        self.storeConfigs()
        return not self.cmd.core.running()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.cmd.core.running():
                self.cmd.cancel()
            elif not self.parent() and self.canExit():
                self.close()
        else:
            return super(MQPatchesWidget, self).keyPressEvent(event)


class MQWidget(QWidget, qtlib.TaskWidget):
    showMessage = pyqtSignal(unicode)
    output = pyqtSignal(QString, QString)
    progress = pyqtSignal(QString, object, QString, QString, object)
    makeLogVisible = pyqtSignal(bool)

    def __init__(self, repo, parent, **opts):
        QWidget.__init__(self, parent)

        self.repo = repo
        self.opts = opts
        self.refreshing = False
        self.finishfunc = None

        layout = QVBoxLayout()
        layout.setSpacing(4)
        self.setLayout(layout)

        b = QPushButton(_('QRefresh'))
        f = b.font()
        f.setWeight(QFont.Bold)
        b.setFont(f)
        self.qnewOrRefreshBtn = b

        self.qqueueBtn = QPushButton(_('Queues'))

        # top toolbar
        tbarhbox = QHBoxLayout()
        tbarhbox.setSpacing(5)
        self.layout().addLayout(tbarhbox, 0)

        self.revisionOrCommitBtn = QPushButton()

        self.queueCombo = QComboBox()
        self.queueCombo.activated['QString'].connect(self.qqueueActivate)
        self.optionsBtn = QPushButton(_('Options'))
        self.msgSelectCombo = PatchMessageCombo(self)
        tbarhbox.addWidget(self.revisionOrCommitBtn)
        tbarhbox.addWidget(self.queueCombo)
        tbarhbox.addWidget(self.optionsBtn)
        tbarhbox.addWidget(self.qqueueBtn)
        tbarhbox.addWidget(self.msgSelectCombo, 1)
        tbarhbox.addWidget(self.qnewOrRefreshBtn)

        # main area consists of a two-way horizontal splitter
        self.splitter = splitter = QSplitter()
        self.layout().addWidget(splitter, 1)
        splitter.setOrientation(Qt.Horizontal)
        splitter.setChildrenCollapsible(True)
        splitter.setObjectName('splitter')

        self.filesFrame = QFrame(splitter)

        # Files Frame
        layout = QVBoxLayout()
        layout.setSpacing(5)
        layout.setContentsMargins(0, 0, 0, 0)
        self.filesFrame.setLayout(layout)

        mtbarhbox = QHBoxLayout()
        mtbarhbox.setSpacing(8)
        layout.addLayout(mtbarhbox, 0)
        mtbarhbox.setContentsMargins(0, 0, 0, 0)
        self.newCheckBox = QCheckBox(_('New Patch'))
        self.patchNameLE = getPatchNameLineEdit()
        mtbarhbox.addWidget(self.newCheckBox)
        mtbarhbox.addWidget(self.patchNameLE, 1)

        self.messageEditor = messageentry.MessageEntry(self)
        self.messageEditor.installEventFilter(qscilib.KeyPressInterceptor(self))
        self.messageEditor.refresh(repo)

        self.stwidget = status.StatusWidget(repo, None, opts, self)

        self.fileview = self.stwidget.fileview
        self.fileview.showMessage.connect(self.showMessage)
        self.fileview.setContext(repo[None])
        self.fileview.shelveToolExited.connect(self.reload)
        layout.addWidget(self.stwidget)

        # Message and diff
        vb2 = QVBoxLayout()
        vb2.setSpacing(0)
        vb2.setContentsMargins(0, 0, 0, 0)
        w = QWidget()
        w.setLayout(vb2)
        splitter.addWidget(w)
        self.vsplitter = vsplitter = QSplitter()
        vsplitter.setOrientation(Qt.Vertical)
        vb2.addWidget(vsplitter)
        vsplitter.addWidget(self.messageEditor)
        vsplitter.addWidget(self.stwidget.docf)

        # Command runner and connections...
        self.cmd = cmdui.Runner(not parent, self)
        self.cmd.output.connect(self.output)
        self.cmd.makeLogVisible.connect(self.makeLogVisible)
        self.cmd.progress.connect(self.progress)
        self.cmd.commandFinished.connect(self.onCommandFinished)

        self.qqueueBtn.clicked.connect(self.launchQQueueTool)
        self.optionsBtn.clicked.connect(self.launchOptionsDialog)
        self.revisionOrCommitBtn.clicked.connect(self.qinitOrCommit)
        self.msgSelectCombo.activated.connect(self.onMessageSelected)
        self.newCheckBox.toggled.connect(self.onNewModeToggled)
        self.qnewOrRefreshBtn.clicked.connect(self.onQNewOrQRefresh)
        QShortcut(QKeySequence('Ctrl+Return'), self, self.onQNewOrQRefresh)
        QShortcut(QKeySequence('Ctrl+Enter'), self, self.onQNewOrQRefresh)

        self.repo.configChanged.connect(self.onConfigChanged)
        self.repo.repositoryChanged.connect(self.onRepositoryChanged)
        self.setAcceptDrops(True)

        if parent:
            self.layout().setContentsMargins(2, 2, 2, 2)
        else:
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.setWindowTitle(_('TortoiseHg Patch Queue'))
            self.statusbar = cmdui.ThgStatusBar(self)
            self.layout().addWidget(self.statusbar)
            self.progress.connect(self.statusbar.progress)
            self.showMessage.connect(self.statusbar.showMessage)
            QShortcut(QKeySequence.Refresh, self, self.reload)
            self.resize(850, 550)

        self.loadConfigs()
        QTimer.singleShot(0, self.reload)

    def closeEvent(self, event):
        self.repo.configChanged.disconnect(self.onConfigChanged)
        self.repo.repositoryChanged.disconnect(self.onRepositoryChanged)
        super(MQWidget, self).closeEvent(event)

    def getUserOptions(self, *optionlist):
        return getUserOptions(self.opts, *optionlist)

    @pyqtSlot()
    def onConfigChanged(self):
        'Repository is reporting its config files have changed'
        self.messageEditor.refresh(self.repo)

    @pyqtSlot()
    def onRepositoryChanged(self):
        'Repository is reporting its changelog has changed'
        self.reload()

    @pyqtSlot(int)
    def onCommandFinished(self, ret):
        self.repo.decrementBusyCount()
        if self.finishfunc:
            self.finishfunc(ret)
            self.finishfunc = None

    def checkForRejects(self, ret):
        if ret is 0:
            self.refreshStatus()
            return
        rejre = re.compile('saving rejects to file (.*).rej')
        for m in rejre.finditer(self.cmd.core.rawoutput()):
            wfile = m.groups()[0]
            if not os.path.exists(self.repo.wjoin(wfile)):
                continue
            ufile = hglib.tounicode(wfile)
            if qtlib.QuestionMsgBox(_('Manually resolve rejected chunks?'),
                                    _('%s had rejected chunks, edit patched '
                                      'file together with rejects?') % ufile,
                                    parent=self):
                dlg = rejects.RejectsDialog(self.repo.wjoin(wfile), self)
                dlg.exec_()
        self.refreshStatus()

    @pyqtSlot(QString)
    def qqueueActivate(self, uqueue):
        if self.refreshing:
            return
        queue = hglib.fromunicode(uqueue)
        if queue == self.repo.thgactivemqname:
            return
        self.repo.incrementBusyCount()
        cmdline = ['qqueue', '-R', self.repo.root, queue]
        def finished(ret):
            if ret:
                for i in xrange(self.queueCombo.count()):
                    if (hglib.fromunicode(self.queueCombo.itemText(i))
                            == self.repo.thgactivemqname):
                        self.queueCombo.setCurrentIndex(i)
                        break
        self.finishfunc = finished
        self.cmd.run(cmdline)

    def onQreorder(self):
        if self.cmd.running():
            return
        def checkGuardsOrComments():
            cont = True
            for p in self.repo.mq.fullseries:
                if '#' in p:
                    cont = qtlib.QuestionMsgBox('Confirm qreorder',
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

    def qgotoRevision(self, rev):
        if self.cmd.running():
            return
        cmdline = ['qgoto', '-R', self.repo.root]
        cmdline += self.getUserOptions('force')
        cmdline += ['--', str(rev)]
        self.repo.incrementBusyCount()
        self.finishfunc = self.checkForRejects
        self.cmd.run(cmdline)

    #@pyqtSlot(QListWidgetItem)
    def onGotoPatch(self, item):
        'Patch has been activated (return), issue qgoto'
        if self.cmd.running():
            return
        cmdline = ['qgoto', '-R', self.repo.root]
        cmdline += self.getUserOptions('force')
        cmdline += ['--', item._thgpatch]
        self.repo.incrementBusyCount()
        self.finishfunc = self.checkForRejects
        self.cmd.run(cmdline)

    @pyqtSlot(int)
    def onMessageSelected(self, row):
        if self.messageEditor.text() and self.messageEditor.isModified():
            d = QMessageBox.question(self, _('Confirm Discard Message'),
                        _('Discard current commit message?'),
                        QMessageBox.Ok | QMessageBox.Cancel)
            if d != QMessageBox.Ok:
                return
        self.setMessage(self.messages[row][1])
        self.messageEditor.setFocus()

    def setMessage(self, message):
        self.messageEditor.setText(message)  # message: unicode
        lines = self.messageEditor.lines()
        if lines:
            lines -= 1
            pos = self.messageEditor.lineLength(lines)
            self.messageEditor.setCursorPosition(lines, pos)
            self.messageEditor.ensureLineVisible(lines)
            hs = self.messageEditor.horizontalScrollBar()
            hs.setSliderPosition(0)
        self.messageEditor.setModified(False)

    @pyqtSlot()
    def onQNewOrQRefresh(self):
        if self.newCheckBox.isChecked():
            self.finishfunc = lambda ret: self.newCheckBox.setChecked(False)
        optionlist = ('user', 'currentuser', 'git', 'date', 'currentdate')
        cmdlines = mqNewRefreshCommand(self.repo, self.newCheckBox.isChecked(),
                                       self.stwidget, self.patchNameLE,
                                       self.messageEditor.text(), self.opts,
                                       optionlist)
        self.repo.incrementBusyCount()
        self.cmd.run(*cmdlines)

    @pyqtSlot()
    def qinitOrCommit(self):
        if os.path.isdir(self.repo.mq.join('.hg')):
            from tortoisehg.hgqt import commit
            mqrepo = thgrepo.repository(None, self.repo.mq.path)
            dlg = commit.CommitDialog(mqrepo, [], {}, self)
            dlg.finished.connect(dlg.deleteLater)
            dlg.exec_()
            self.reload()
        else:
            self.repo.incrementBusyCount()
            self.cmd.run(['qinit', '-c', '-R', self.repo.root])

    @pyqtSlot()
    def launchQQueueTool(self):
        dlg = qqueue.QQueueDialog(self.repo, True, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.output.connect(self.output)
        dlg.makeLogVisible.connect(self.makeLogVisible)
        dlg.exec_()
        self.reload()

    @pyqtSlot()
    def launchOptionsDialog(self):
        dlg = OptionsDialog(self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        if dlg.exec_() == QDialog.Accepted:
            self.opts.update(dlg.outopts)

    def refreshStatus(self):
        self.refreshing = True
        pctx = self.repo.changectx('.')

        # Refresh the wctx in synchronous (blocking) mode, since MQ can fire
        # multiple refresh requests in rapid succession (e.g. when QNew is
        # pressed).  The first would launch the background status thread but
        # the last request (with pctx.tags and newCheckBox set up properly)
        # would return immediately from stwidget.refreshWctx because refthread
        # was still running, so the final status display after QNew would not
        # correctly show the status of the new patch.
        #
        # This could be tuned for better performance; the current synchronous
        # approach is the closest equivalent to the pre-StatusWidget behavior.
        if 'qtip' in pctx.tags() and not self.newCheckBox.isChecked():
            # qrefresh (qdiff) diffs
            self.stwidget.setPatchContext(pctx)
            self.stwidget.refreshWctx(synchronous=True)
        elif self.newCheckBox.isChecked():
            # qnew (working) diffs
            self.stwidget.setPatchContext(None)
            self.stwidget.refreshWctx(synchronous=True)
        self.refreshing = False

    def reload(self):
        self.refreshing = True
        try:
            try:
                self._reload()
            except Exception, e:
                self.showMessage.emit(hglib.tounicode(str(e)))
                if 'THGDEBUG' in os.environ:
                    import traceback
                    traceback.print_exc()
        finally:
            self.refreshing = False
        self.refreshStatus()

    def _reload(self):
        ui, repo = self.repo.ui.copy(), self.repo

        self.queueCombo.clear()

        ui.quiet = True  # don't append "(active)"
        ui.pushbuffer()
        mqmod.qqueue(ui, repo, list=True)
        out = ui.popbuffer()
        for i, qname in enumerate(out.splitlines()):
            if qname == repo.thgactivemqname:
                current = i
            self.queueCombo.addItem(hglib.tounicode(qname))
        self.queueCombo.setCurrentIndex(current)
        self.queueCombo.setEnabled(self.queueCombo.count() > 1)

        self.messages = []
        for patch in repo.mq.series:
            ctx = repo.changectx(patch)
            msg = hglib.tounicode(ctx.description())
            if msg:
                self.messages.append((patch, msg))
        self.msgSelectCombo.reset(self.messages)

        if os.path.isdir(repo.mq.join('.hg')):
            self.revisionOrCommitBtn.setText(_('QCommit'))
        else:
            self.revisionOrCommitBtn.setText(_('Create MQ repo'))

        pctx = repo.changectx('.')
        newmode = self.newCheckBox.isChecked()
        if 'qtip' in pctx.tags():
            self.stwidget.tv.setEnabled(True)
            self.messageEditor.setEnabled(True)
            self.msgSelectCombo.setEnabled(True)
            self.qnewOrRefreshBtn.setEnabled(True)
            if not newmode:
                self.setMessage(hglib.tounicode(pctx.description()))
                name = repo.mq.applied[-1].name
                self.patchNameLE.setText(hglib.tounicode(name))
        else:
            self.stwidget.tv.setEnabled(newmode)
            self.messageEditor.setEnabled(newmode)
            self.msgSelectCombo.setEnabled(newmode)
            self.qnewOrRefreshBtn.setEnabled(newmode)
            if not newmode:
                self.setMessage('')
                self.patchNameLE.setText('')
        self.patchNameLE.setEnabled(newmode)

    def onNewModeToggled(self, isChecked):
        if isChecked:
            self.stwidget.tv.setEnabled(True)
            self.qnewOrRefreshBtn.setText(_('QNew'))
            self.qnewOrRefreshBtn.setEnabled(True)
            self.messageEditor.setEnabled(True)
            self.patchNameLE.setEnabled(True)
            self.patchNameLE.setFocus()
            self.patchNameLE.setText(defaultNewPatchName(self.repo))
            self.patchNameLE.selectAll()
            self.setMessage('')
        else:
            self.qnewOrRefreshBtn.setText(_('QRefresh'))
            pctx = self.repo.changectx('.')
            if 'qtip' in pctx.tags():
                self.messageEditor.setEnabled(True)
                self.setMessage(hglib.tounicode(pctx.description()))
                name = self.repo.mq.applied[-1].name
                self.patchNameLE.setText(hglib.tounicode(name))
                self.qnewOrRefreshBtn.setEnabled(True)
                self.stwidget.tv.setEnabled(True)
            else:
                self.messageEditor.setEnabled(False)
                self.qnewOrRefreshBtn.setEnabled(False)
                self.stwidget.tv.setEnabled(False)
                self.patchNameLE.setText('')
                self.setMessage('')
            self.patchNameLE.setEnabled(False)
        self.refreshStatus()

    def refreshSelectedGuards(self):
        total = len(self.allguards)
        count = len(self.repo.mq.active())
        oldmenu = self.guardSelBtn.menu()
        if oldmenu:
            oldmenu.setParent(None)
        menu = QMenu(self)
        for guard in self.allguards:
            a = menu.addAction(hglib.tounicode(guard))
            a.setCheckable(True)
            a.setChecked(guard in self.repo.mq.active())
            a.triggered.connect(self.onGuardSelectionChange)
        self.guardSelBtn.setMenu(menu)
        self.guardSelBtn.setText(_('Guards: %d/%d') % (count, total))
        self.guardSelBtn.setEnabled(bool(total))

    def onGuardSelectionChange(self, isChecked):
        guard = hglib.fromunicode(self.sender().text())
        newguards = self.repo.mq.active()[:]
        if isChecked:
            newguards.append(guard)
        elif guard in newguards:
            newguards.remove(guard)
        cmdline = ['qselect', '-R', self.repo.root]
        cmdline += newguards or ['--none']
        self.repo.incrementBusyCount()
        self.cmd.run(cmdline)

    # Capture drop events, try to import into current patch queue

    def detectPatches(self, paths):
        filepaths = []
        for p in paths:
            if not os.path.isfile(p):
                continue
            try:
                pf = open(p, 'rb')
                filename, message, user, date, branch, node, p1, p2 = \
                        patch.extract(self.repo.ui, pf)
                if filename:
                    filepaths.append(p)
                    os.unlink(filename)
            except Exception, e:
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
        if patches:
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            super(MQWidget, self).dropEvent(event)
            return
        dlg = thgimport.ImportDialog(self.repo, self, mq=True)
        dlg.finished.connect(dlg.deleteLater)
        dlg.setfilepaths(patches)
        dlg.exec_()

    # End drop events

    def loadConfigs(self):
        'Load history, etc, from QSettings instance'
        s = QSettings()
        self.splitter.restoreState(s.value('mq/splitter').toByteArray())
        self.vsplitter.restoreState(s.value('mq/vsplitter').toByteArray())
        userhist = s.value('commit/userhist').toStringList()
        self.opts['userhist'] = [hglib.fromunicode(u) for u in userhist if u]
        self.messageEditor.loadSettings(s, 'mq/editor')
        self.fileview.loadSettings(s, 'mq/fileview')
        if not self.parent():
            self.restoreGeometry(s.value('mq/geom').toByteArray())

    def storeConfigs(self):
        'Save history, etc, in QSettings instance'
        s = QSettings()
        s.setValue('mq/splitter', self.splitter.saveState())
        s.setValue('mq/vsplitter', self.vsplitter.saveState())
        self.messageEditor.saveSettings(s, 'mq/editor')
        self.fileview.saveSettings(s, 'mq/fileview')
        if not self.parent():
            s.setValue('mq/geom', self.saveGeometry())

    def canExit(self):
        self.storeConfigs()
        return not self.cmd.core.running()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.cmd.core.running():
                self.cmd.cancel()
            elif not self.parent() and self.canExit():
                self.close()
        else:
            return super(MQWidget, self).keyPressEvent(event)



class PatchMessageCombo(QComboBox):
    def __init__(self, parent):
        super(PatchMessageCombo, self).__init__(parent)
        self.reset([])

    def reset(self, msglist):
        self.clear()
        self.addItem(_('Patch commit messages...'))
        self.loaded = False
        self.msglist = msglist

    def showPopup(self):
        if not self.loaded and self.msglist:
            self.clear()
            for patch, message in self.msglist:
                sum = message.split('\n', 1)[0][:70]
                self.addItem(hglib.tounicode('%s: %s' % (patch, sum)))
            self.loaded = True
        if self.loaded:
            super(PatchMessageCombo, self).showPopup()



class OptionsDialog(QDialog):
    'Utility dialog for configuring uncommon options'
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('MQ options'))

        layout = QFormLayout()
        self.setLayout(layout)

        self.gitcb = QCheckBox(
            _('Force use of git extended diff format (--git)'))
        layout.addRow(self.gitcb, None)

        self.forcecb = QCheckBox(
            _('Force push or pop (--force)'))
        layout.addRow(self.forcecb, None)

        self.exactcb = QCheckBox(
            _('Apply patch to its recorded parent (--exact)'))
        layout.addRow(self.exactcb, None)

        self.currentdatecb = QCheckBox(
            _('Update date field with current date (--currentdate)'))
        layout.addRow(self.currentdatecb, None)

        self.datele = QLineEdit()
        layout.addRow(QLabel(_('Specify an explicit date:')), self.datele)

        self.currentusercb = QCheckBox(
            _('Update author field with current user (--currentuser)'))
        layout.addRow(self.currentusercb, None)

        self.userle = QLineEdit()
        layout.addRow(QLabel(_('Specify an explicit author:')), self.userle)

        self.currentdatecb.toggled.connect(self.datele.setDisabled)
        self.currentusercb.toggled.connect(self.userle.setDisabled)

        self.gitcb.setChecked(parent.opts.get('git', False))
        self.forcecb.setChecked(parent.opts.get('force', False))
        self.exactcb.setChecked(parent.opts.get('exact', False))
        self.currentdatecb.setChecked(parent.opts.get('currentdate', False))
        self.currentusercb.setChecked(parent.opts.get('currentuser', False))
        self.datele.setText(hglib.tounicode(parent.opts.get('date', '')))
        self.userle.setText(hglib.tounicode(parent.opts.get('user', '')))

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.bb = bb
        layout.addWidget(bb)

    def accept(self):
        outopts = {}
        outopts['git'] = self.gitcb.isChecked()
        outopts['force'] = self.forcecb.isChecked()
        outopts['exact'] = self.exactcb.isChecked()
        outopts['currentdate'] = self.currentdatecb.isChecked()
        outopts['currentuser'] = self.currentusercb.isChecked()
        if self.currentdatecb.isChecked():
            outopts['date'] = ''
        else:
            outopts['date'] = hglib.fromunicode(self.datele.text())
        if self.currentusercb.isChecked():
            outopts['user'] = ''
        else:
            outopts['user'] = hglib.fromunicode(self.userle.text())

        self.outopts = outopts
        QDialog.accept(self)



def run(ui, *pats, **opts):
    from tortoisehg.util import paths
    repo = thgrepo.repository(ui, path=paths.find_root())
    return MQWidget(repo, None, **opts)
