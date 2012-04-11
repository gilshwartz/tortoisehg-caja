# resolve.py - TortoiseHg merge conflict resolve
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

import os

from mercurial import merge as mergemod

from tortoisehg.util import hglib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, cmdui, csinfo, visdiff, thgrepo

MARGINS = (8, 0, 0, 0)

class ResolveDialog(QDialog):
    def __init__(self, repo, parent=None):
        super(ResolveDialog, self).__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle(_('Resolve conflicts - %s') % repo.displayname)
        self.setWindowIcon(qtlib.geticon('hg-merge'))
        self.repo = repo

        self.setLayout(QVBoxLayout())
        self.layout().setSpacing(5)

        hbox = QHBoxLayout()
        self.layout().addLayout(hbox)

        self.refreshButton = tb = QToolButton(self)
        tb.setIcon(qtlib.geticon('view-refresh'))
        tb.setShortcut(QKeySequence.Refresh)
        tb.clicked.connect(self.refresh)
        self.stlabel = QLabel()
        hbox.addWidget(tb)
        hbox.addWidget(self.stlabel)

        def revisionInfoLayout(repo):
            """
            Return a layout containg the revision information (local and other)
            """
            hbox = QHBoxLayout()
            hbox.setSpacing(0)
            hbox.setContentsMargins(*MARGINS)

            vbox = QVBoxLayout()
            vbox.setContentsMargins(*MARGINS)
            hbox.addLayout(vbox)
            localrevtitle = qtlib.LabeledSeparator(_('Local revision information'))
            localrevinfo = csinfo.create(repo)
            localrevinfo.update(repo[None].p1())
            vbox.addWidget(localrevtitle)
            vbox.addWidget(localrevinfo)
            vbox.addStretch()

            vbox = QVBoxLayout()
            vbox.setContentsMargins(*MARGINS)
            hbox.addLayout(vbox)
            otherrevtitle = qtlib.LabeledSeparator(_('Other revision information'))
            otherrevinfo = csinfo.create(repo)
            otherrevinfo.update(repo[None].p2())

            vbox.addWidget(otherrevtitle)
            vbox.addWidget(otherrevinfo)
            vbox.addStretch()

            return hbox

        if len(self.repo[None].parents()) > 1:
            self.layout().addLayout(revisionInfoLayout(self.repo))

        unres = qtlib.LabeledSeparator(_('Unresolved conflicts'))
        self.layout().addWidget(unres)

        hbox = QHBoxLayout()
        hbox.setSpacing(0)
        hbox.setContentsMargins(*MARGINS)
        self.layout().addLayout(hbox)

        self.utree = PathsTree(self.repo, self)
        hbox.addWidget(self.utree)

        vbox = QVBoxLayout()
        vbox.setContentsMargins(*MARGINS)
        hbox.addLayout(vbox)
        auto = QPushButton(_('Mercurial Resolve'))
        auto.setToolTip(_('Attempt automatic (trivial) merge'))
        auto.clicked.connect(lambda: self.merge('internal:merge'))
        manual = QPushButton(_('Tool Resolve'))
        manual.setToolTip(_('Merge using selected merge tool'))
        manual.clicked.connect(self.merge)
        local = QPushButton(_('Take Local'))
        local.setToolTip(_('Accept the local file version (yours)'))
        local.clicked.connect(lambda: self.merge('internal:local'))
        other = QPushButton(_('Take Other'))
        other.setToolTip(_('Accept the other file version (theirs)'))
        other.clicked.connect(lambda: self.merge('internal:other'))
        res = QPushButton(_('Mark as Resolved'))
        res.setToolTip(_('Mark this file as resolved'))
        res.clicked.connect(self.markresolved)
        vbox.addWidget(auto)
        vbox.addWidget(manual)
        vbox.addWidget(local)
        vbox.addWidget(other)
        vbox.addWidget(res)
        vbox.addStretch(1)
        self.ubuttons = (auto, manual, local, other, res)

        res = qtlib.LabeledSeparator(_('Resolved conflicts'))
        self.layout().addWidget(res)

        hbox = QHBoxLayout()
        hbox.setContentsMargins(*MARGINS)
        hbox.setSpacing(0)
        self.layout().addLayout(hbox)

        self.rtree = PathsTree(self.repo, self)
        hbox.addWidget(self.rtree)

        vbox = QVBoxLayout()
        vbox.setContentsMargins(*MARGINS)
        hbox.addLayout(vbox)
        edit = QPushButton(_('Edit File'))
        edit.setToolTip(_('Edit resolved file'))
        edit.clicked.connect(self.edit)
        v3way = QPushButton(_('3-Way Diff'))
        v3way.setToolTip(_('Visual three-way diff'))
        v3way.clicked.connect(self.v3way)
        vp0 = QPushButton(_('Diff to Local'))
        vp0.setToolTip(_('Visual diff between resolved file and first parent'))
        vp0.clicked.connect(self.vp0)
        vp1 = QPushButton(_('Diff to Other'))
        vp1.setToolTip(_('Visual diff between resolved file and second parent'))
        vp1.clicked.connect(self.vp1)
        ures = QPushButton(_('Mark as Unresolved'))
        ures.setToolTip(_('Mark this file as unresolved'))
        ures.clicked.connect(self.markunresolved)
        vbox.addWidget(edit)
        vbox.addWidget(v3way)
        vbox.addWidget(vp0)
        vbox.addWidget(vp1)
        vbox.addWidget(ures)
        vbox.addStretch(1)
        self.rbuttons = (edit, vp0, ures)
        self.rmbuttons = (vp1, v3way)

        hbox = QHBoxLayout()
        hbox.setContentsMargins(*MARGINS)
        hbox.setSpacing(4)
        self.layout().addLayout(hbox)

        self.tcombo = ToolsCombo(self.repo, self)
        hbox.addWidget(QLabel(_('Detected merge/diff tools:')))
        hbox.addWidget(self.tcombo)
        hbox.addStretch(1)

        out = qtlib.LabeledSeparator(_('Command output'))
        self.layout().addWidget(out)
        self.cmd = cmdui.Widget(True, False, self)
        self.cmd.commandFinished.connect(self.refresh)
        self.cmd.setShowOutput(True)
        self.layout().addWidget(self.cmd)

        BB = QDialogButtonBox
        bbox = QDialogButtonBox(BB.Close)
        bbox.rejected.connect(self.reject)
        self.layout().addWidget(bbox)
        self.bbox = bbox

        s = QSettings()
        self.restoreGeometry(s.value('resolve/geom').toByteArray())

        self.refresh()
        self.utree.selectAll()
        self.utree.setFocus()
        repo.configChanged.connect(self.configChanged)
        repo.repositoryChanged.connect(self.repositoryChanged)

    def done(self, ret):
        self.repo.configChanged.disconnect(self.configChanged)
        self.repo.repositoryChanged.disconnect(self.repositoryChanged)
        super(ResolveDialog, self).done(ret)

    def repositoryChanged(self):
        self.refresh()

    def getSelectedPaths(self, tree):
        paths = []
        repo = self.repo
        if not tree.selectionModel():
            return paths
        for idx in tree.selectionModel().selectedRows():
            root, wfile = tree.model().getPathForIndex(idx)
            paths.append((root, wfile))
        return paths

    def runCommand(self, tree, cmdline):
        cmdlines = []
        selected = self.getSelectedPaths(tree)
        while selected:
            curroot = selected[0][0]
            cmd = cmdline + ['--repository', curroot, '--']
            for root, wfile in selected:
                if root == curroot:
                    cmd.append(os.path.join(root, wfile))
            cmdlines.append(cmd)
            selected = [(r, w) for r, w in selected if r != curroot]
        if cmdlines:
            self.cmd.run(*cmdlines)

    def merge(self, tool=False):
        if not tool:
            tool = self.tcombo.readValue()
        cmd = ['resolve']
        if tool:
            cmd += ['--tool='+tool]
        self.runCommand(self.utree, cmd)

    def markresolved(self):
        self.runCommand(self.utree, ['resolve', '--mark'])

    def markunresolved(self):
        self.runCommand(self.rtree, ['resolve', '--unmark'])

    def edit(self):
        paths = self.getSelectedPaths(self.rtree)
        if paths:
            abspaths = [os.path.join(r,w) for r,w in paths]
            qtlib.editfiles(self.repo, abspaths, parent=self)

    def getVdiffFiles(self, tree):
        paths = self.getSelectedPaths(self.rtree)
        if not paths:
            return []
        files, sub = [], False
        for root, wfile in paths:
            if root == self.repo.root:
                files.append(wfile)
            else:
                sub = True
        if sub:
            qtlib.InfoMsgBox(_('Unable to show subrepository files'),
                    _('Visual diffs are not supported for files in '
                      'subrepositories. They will not be shown.'))
        return files

    def v3way(self):
        paths = self.getVdiffFiles(self.rtree)
        if paths:
            opts = {}
            opts['rev'] = []
            opts['tool'] = self.tcombo.readValue()
            dlg = visdiff.visualdiff(self.repo.ui, self.repo, paths, opts)
            if dlg:
                dlg.exec_()

    def vp0(self):
        paths = self.getVdiffFiles(self.rtree)
        if paths:
            opts = {}
            opts['rev'] = ['p1()']
            opts['tool'] = self.tcombo.readValue()
            dlg = visdiff.visualdiff(self.repo.ui, self.repo, paths, opts)
            if dlg:
                dlg.exec_()

    def vp1(self):
        paths = self.getVdiffFiles(self.rtree)
        if paths:
            opts = {}
            opts['rev'] = ['p2()']
            opts['tool'] = self.tcombo.readValue()
            dlg = visdiff.visualdiff(self.repo.ui, self.repo, paths, opts)
            if dlg:
                dlg.exec_()

    def configChanged(self):
        'repository has detected a change to config files'
        self.tcombo.reset()

    def refresh(self):
        repo = self.repo

        u, r = [], []
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if status == 'u':
                u.append((root, path))
            else:
                r.append((root, path))
        paths = self.getSelectedPaths(self.utree)
        self.utree.setModel(PathsModel(u, self))
        self.utree.resizeColumnToContents(0)
        self.utree.resizeColumnToContents(1)

        model = self.utree.model()
        smodel = self.utree.selectionModel()
        sflags = QItemSelectionModel.Select | QItemSelectionModel.Columns
        for i, path in enumerate(u):
            if path in paths:
                smodel.select(model.index(i, 0), sflags)
                smodel.select(model.index(i, 1), sflags)
                smodel.select(model.index(i, 2), sflags)

        @pyqtSlot(QItemSelection, QItemSelection)
        def uchanged(selected, deselected):
            enable = self.utree.selectionModel().hasSelection()
            for b in self.ubuttons:
                b.setEnabled(enable)
        smodel.selectionChanged.connect(uchanged)
        uchanged(None, None)

        paths = self.getSelectedPaths(self.rtree)
        self.rtree.setModel(PathsModel(r, self))
        self.rtree.resizeColumnToContents(0)
        self.rtree.resizeColumnToContents(1)

        model = self.rtree.model()
        smodel = self.rtree.selectionModel()
        for i, path in enumerate(r):
            if path in paths:
                smodel.select(model.index(i, 0), sflags)
                smodel.select(model.index(i, 1), sflags)
                smodel.select(model.index(i, 2), sflags)

        @pyqtSlot(QItemSelection, QItemSelection)
        def rchanged(selected, deselected):
            enable = self.rtree.selectionModel().hasSelection()
            for b in self.rbuttons:
                b.setEnabled(enable)
            merge = len(self.repo.parents()) > 1
            for b in self.rmbuttons:
                b.setEnabled(enable and merge)
        smodel.selectionChanged.connect(rchanged)
        rchanged(None, None)

        if u:
            txt = _('There are merge <b>conflicts</b> to be resolved')
        elif r:
            txt = _('All conflicts are resolved.')
        else:
            txt = _('There are no conflicting file merges.')
        self.stlabel.setText(u'<h2>' + txt + u'</h2>')

    def reject(self):
        s = QSettings()
        s.setValue('resolve/geom', self.saveGeometry())
        if len(self.utree.model()):
            main = _('Exit without finishing resolve?')
            text = _('Unresolved conflicts remain. Are you sure?')
            labels = ((QMessageBox.Yes, _('E&xit')),
                      (QMessageBox.No, _('Cancel')))
            if not qtlib.QuestionMsgBox(_('Confirm Exit'), main, text,
                                labels=labels, parent=self):
                return
        super(ResolveDialog, self).reject()

class PathsTree(QTreeView):
    def __init__(self, repo, parent):
        QTreeView.__init__(self, parent)
        self.repo = repo
        self.setSelectionMode(QTreeView.ExtendedSelection)
        self.setSortingEnabled(True)

    def dragObject(self):
        urls = []
        for index in self.selectionModel().selectedRows():
            root, path = self.model().getPathForIndex(index)
            urls.append(QUrl.fromLocalFile(os.path.join(root, path)))
        if urls:
            d = QDrag(self)
            m = QMimeData()
            m.setUrls(urls)
            d.setMimeData(m)
            d.start(Qt.CopyAction)

    def mousePressEvent(self, event):
        self.pressPos = event.pos()
        self.pressTime = QTime.currentTime()
        return QTreeView.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        d = event.pos() - self.pressPos
        if d.manhattanLength() < QApplication.startDragDistance():
            return QTreeView.mouseMoveEvent(self, event)
        elapsed = self.pressTime.msecsTo(QTime.currentTime())
        if elapsed < QApplication.startDragTime():
            return QTreeView.mouseMoveEvent(self, event)
        self.dragObject()
        return QTreeView.mouseMoveEvent(self, event)

class PathsModel(QAbstractTableModel):
    def __init__(self, pathlist, parent):
        QAbstractTableModel.__init__(self, parent)
        self.headers = (_('Path'), _('Ext'), _('Repository'))
        self.rows = []
        for root, path in pathlist:
            name, ext = os.path.splitext(path)
            self.rows.append([path, ext, root])

    def __len__(self):
        return len(self.rows)

    def rowCount(self, parent):
        if parent.isValid():
            return 0 # no child
        return len(self.rows)

    def columnCount(self, parent):
        if parent.isValid():
            return 0 # no child
        return len(self.headers)

    def data(self, index, role):
        if not index.isValid():
            return QVariant()
        if role == Qt.DisplayRole:
            data = self.rows[index.row()][index.column()]
            return QVariant(hglib.tounicode(data))
        return QVariant()

    def headerData(self, col, orientation, role):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return QVariant()
        else:
            return QVariant(self.headers[col])

    def getPathForIndex(self, index):
        'return root, wfile for the given row'
        row = index.row()
        return self.rows[row][2], self.rows[row][0]

class ToolsCombo(QComboBox):
    def __init__(self, repo, parent):
        QComboBox.__init__(self, parent)
        self.setEditable(False)
        self.loaded = False
        self.default = _('<default>')
        self.addItem(self.default)
        self.repo = repo

    def reset(self):
        self.loaded = False
        self.clear()
        self.addItem(self.default)

    def showPopup(self):
        if not self.loaded:
            self.loaded = True
            self.clear()
            self.addItem(self.default)
            for t in self.repo.mergetools:
                self.addItem(hglib.tounicode(t))
        QComboBox.showPopup(self)

    def readValue(self):
        if self.loaded:
            text = self.currentText()
            if text != self.default:
                return hglib.fromunicode(text)
        else:
            return None

def run(ui, *pats, **opts):
    from tortoisehg.util import paths
    repo = thgrepo.repository(ui, path=paths.find_root())
    return ResolveDialog(repo, None)
