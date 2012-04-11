# grep.py - Working copy and history search
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import re

from mercurial import ui, hg, error, commands, match, util, subrepo

from tortoisehg.hgqt import htmlui, visdiff, qtlib, htmldelegate, thgrepo, cmdui
from tortoisehg.util import paths, hglib, thread2
from tortoisehg.hgqt.i18n import _

from PyQt4.QtCore import *
from PyQt4.QtGui import *

# This widget can be embedded in any application that would like to
# provide search features

class SearchWidget(QWidget, qtlib.TaskWidget):
    '''Working copy and repository search widget'''
    showMessage = pyqtSignal(QString)
    progress = pyqtSignal(QString, object, QString, QString, object)
    revisionSelected = pyqtSignal(int)

    def __init__(self, upats, repo, parent=None, **opts):
        QWidget.__init__(self, parent)

        self.thread = None
        self.setWindowIcon(qtlib.geticon('view-filter'))

        mainvbox = QVBoxLayout()
        mainvbox.setSpacing(6)

        hbox = QHBoxLayout()
        hbox.setMargin(2)
        le = QLineEdit()
        if hasattr(le, 'setPlaceholderText'): # Qt >= 4.7
            le.setPlaceholderText(_('### regular expression search pattern ###'))
        else:
            lbl = QLabel(_('Regexp:'))
            lbl.setBuddy(le)
            hbox.addWidget(lbl)
        chk = QCheckBox(_('Ignore case'))
        bt = QPushButton(_('Search'))
        bt.setDefault(True)
        f = bt.font()
        f.setWeight(QFont.Bold)
        bt.setFont(f)
        cbt = QPushButton(_('Stop'))
        cbt.setEnabled(False)
        cbt.clicked.connect(self.stopClicked)
        hbox.addWidget(le, 1)
        hbox.addWidget(chk)
        hbox.addWidget(bt)
        hbox.addWidget(cbt)

        incle = QLineEdit()
        excle = QLineEdit()
        working = QRadioButton(_('Working Copy'))
        revision = QRadioButton(_('Revision'))
        history = QRadioButton(_('All History'))
        singlematch = QCheckBox(_('Report only the first match per file'))
        follow = QCheckBox(_('Follow copies and renames'))
        recurse = QCheckBox(_('Recurse into subrepositories'))
        revle = QLineEdit()
        grid = QGridLayout()
        grid.addWidget(working, 0, 0)
        grid.addWidget(recurse, 0, 1)
        grid.addWidget(history, 1, 0)
        grid.addWidget(revision, 2, 0)
        grid.addWidget(revle, 2, 1)
        grid.addWidget(singlematch, 0, 3)
        grid.addWidget(follow, 0, 4)
        ilabel = QLabel(_('Includes:'))
        ilabel.setBuddy(incle)
        elabel = QLabel(_('Excludes:'))
        elabel.setBuddy(excle)
        ehelpstr = _('Comma separated list of exclusion file patterns. '
                     'Exclusion patterns are applied after inclusion patterns.')
        ihelpstr = _('Comma separated list of inclusion file patterns. '
                     'By default, the entire repository is searched.')
        if hasattr(incle, 'setPlaceholderText'): # Qt >= 4.7
            incle.setPlaceholderText(u' '.join([u'###', ihelpstr, u'###']))
        else:
            incle.setToolTip(ihelpstr)
        if hasattr(excle, 'setPlaceholderText'): # Qt >= 4.7
            excle.setPlaceholderText(u' '.join([u'###', ehelpstr, u'###']))
        else:
            excle.setToolTip(ehelpstr)
        grid.addWidget(ilabel, 1, 2)
        grid.addWidget(incle, 1, 3, 1, 2)
        grid.addWidget(elabel, 2, 2)
        grid.addWidget(excle, 2, 3, 1, 2)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(1, 0)
        frame = QFrame()
        frame.setFrameStyle(QFrame.StyledPanel)
        def revisiontoggled(checked):
            revle.setEnabled(checked)
            if checked:
                revle.selectAll()
                QTimer.singleShot(0, lambda:revle.setFocus())
        revision.toggled.connect(revisiontoggled)
        history.toggled.connect(singlematch.setDisabled)
        revle.setEnabled(False)
        revle.returnPressed.connect(self.searchActivated)
        excle.returnPressed.connect(self.searchActivated)
        incle.returnPressed.connect(self.searchActivated)
        bt.clicked.connect(self.searchActivated)

        def updateRecurse(checked):
            try:
                wctx = repo[None]
                if '.hgsubstate' in wctx:
                    recurse.setEnabled(checked)
                else:
                    recurse.setEnabled(False)
                    recurse.setChecked(False)
            except Exception:
                recurse.setEnabled(False)
                recurse.setChecked(False)
        working.toggled.connect(updateRecurse)
        recurse.setChecked(True)
        working.setChecked(True)

        def updatefollow():
            slowpath = bool(incle.text() or excle.text())
            follow.setEnabled(history.isChecked() and not slowpath)
            if slowpath:
                follow.setChecked(False)
        history.toggled.connect(updatefollow)
        incle.textChanged.connect(updatefollow)
        excle.textChanged.connect(updatefollow)
        updatefollow()

        mainvbox.addLayout(hbox)
        frame.setLayout(grid)
        mainvbox.addWidget(frame)

        tv = MatchTree(repo, self)
        tv.revisionSelected.connect(self.revisionSelected)
        tv.setColumnHidden(COL_REVISION, True)
        tv.setColumnHidden(COL_USER, True)
        mainvbox.addWidget(tv)
        le.returnPressed.connect(self.searchActivated)

        self.repo = repo
        self.tv, self.regexple, self.chk, self.recurse = tv, le, chk, recurse
        self.incle, self.excle, self.revle = incle, excle, revle
        self.wctxradio, self.ctxradio, self.aradio = working, revision, history
        self.singlematch, self.follow, self.eframe = singlematch, follow, frame
        self.searchbutton, self.cancelbutton = bt, cbt
        self.regexple.setFocus()

        if 'rev' in opts or 'all' in opts:
            self.setSearch(upats[0], **opts)
        elif len(upats) >= 1:
            le.setText(upats[0])
        if len(upats) > 1:
            incle.setText(','.join(upats[1:]))
        chk.setChecked(opts.get('ignorecase', False))

        repoid = str(repo[0])
        s = QSettings()
        sh = list(s.value('grep/search-'+repoid).toStringList())
        ph = list(s.value('grep/paths-'+repoid).toStringList())
        self.pathshistory = [p for p in ph if p]
        self.searchhistory = [s for s in sh if s]
        self.setCompleters()

        if parent:
            self.closeonesc = False
            mainvbox.setContentsMargins(0, 0, 0, 0)
            self.setLayout(mainvbox)
        else:
            self.setWindowTitle(_('TortoiseHg Search'))
            self.resize(800, 550)
            self.closeonesc = True
            self.stbar = cmdui.ThgStatusBar()
            mainvbox.setContentsMargins(5, 5, 5, 5)
            outervbox = QVBoxLayout()
            outervbox.addLayout(mainvbox)
            outervbox.addWidget(self.stbar)
            outervbox.setContentsMargins(0, 0, 0, 0)
            self.setLayout(outervbox)
            self.showMessage.connect(self.stbar.showMessage)
            self.progress.connect(self.stbar.progress)

    def setCompleters(self):
        comp = QCompleter(self.searchhistory, self)
        QShortcut(QKeySequence('CTRL+D'), comp.popup(),
                  self.onSearchCompleterDelete)
        self.regexple.setCompleter(comp)

        comp = QCompleter(self.pathshistory, self)
        QShortcut(QKeySequence('CTRL+D'), comp.popup(),
                  self.onPathCompleterDelete)
        self.incle.setCompleter(comp)
        self.excle.setCompleter(comp)

    def onSearchCompleterDelete(self):
        'CTRL+D pressed in search completer popup window'
        text = self.regexple.completer().currentCompletion()
        if text and text in self.searchhistory:
            self.searchhistory.remove(text)
            self.setCompleters()
            self.showMessage.emit(_('"%s" removed from search history') % text)

    def onPathCompleterDelete(self):
        'CTRL+D pressed in path completer popup window'
        text = self.incle.completer().currentCompletion()
        if text and text in self.pathshistory:
            self.pathshistory.remove(text)
            self.setCompleters()
            self.showMessage.emit(_('"%s" removed from path history') % text)

    def addHistory(self, search, incpaths, excpaths):
        if search:
            usearch = hglib.tounicode(search)
            if usearch in self.searchhistory:
                self.searchhistory.remove(usearch)
            self.searchhistory = [usearch] + self.searchhistory[:9]
        for p in incpaths + excpaths:
            up = hglib.tounicode(p)
            if up in self.pathshistory:
                self.pathshistory.remove(up)
            self.pathshistory = [up] + self.pathshistory[:9]
        self.setCompleters()

    def setRevision(self, rev):
        'Repowidget is forwarding a selected revision'
        if isinstance(rev, int):
            self.revle.setText(str(rev))

    def setSearch(self, upattern, **opts):
        self.regexple.setText(upattern)
        if opts.get('all'):
            self.aradio.setChecked(True)
        elif opts.get('rev'):
            self.ctxradio.setChecked(True)
            self.revle.setText(opts['rev'])

    def stopClicked(self):
        if self.thread and self.thread.isRunning():
            self.thread.cancel()
            self.thread.wait(2000)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.thread and self.thread.isRunning():
                self.stopClicked()
            elif self.closeonesc:
                self.close()
        else:
            return super(SearchWidget, self).keyPressEvent(event)

    def canExit(self):
        'Repowidget is closing, can we quit?'
        if self.thread and self.thread.isRunning():
            return False
        return True

    def saveSettings(self, s):
        repoid = str(self.repo[0])
        s.setValue('grep/search-'+repoid, self.searchhistory)
        s.setValue('grep/paths-'+repoid, self.pathshistory)

    def closeEvent(self, event):
        self.saveSettings(QSettings())

    def searchActivated(self):
        'User pressed [Return] in QLineEdit'
        if self.thread and self.thread.isRunning():
            return

        model = self.tv.model()
        model.reset()
        pattern = hglib.fromunicode(self.regexple.text())
        if not pattern:
            return
        try:
            icase = self.chk.isChecked()
            regexp = re.compile(pattern, icase and re.I or 0)
        except Exception, inst:
            msg = _('grep: invalid match pattern: %s\n') % \
                    hglib.tounicode(str(inst))
            self.showMessage.emit(msg)
            return

        self.tv.setSortingEnabled(False)
        self.tv.pattern = pattern
        self.tv.icase = icase
        self.regexple.selectAll()
        inc = hglib.fromunicode(self.incle.text())
        if inc: inc = inc.split(', ')
        exc = hglib.fromunicode(self.excle.text())
        if exc: exc = exc.split(', ')
        rev = hglib.fromunicode(self.revle.text()).strip()

        self.addHistory(pattern, inc or [], exc or [])
        if self.wctxradio.isChecked():
            self.tv.setColumnHidden(COL_REVISION, True)
            self.tv.setColumnHidden(COL_USER, True)
            ctx = self.repo[None]
            self.thread = CtxSearchThread(self.repo, regexp, ctx, inc, exc,
                                          self.singlematch.isChecked(),
                                          self.recurse.isChecked())
        elif self.ctxradio.isChecked():
            self.tv.setColumnHidden(COL_REVISION, True)
            self.tv.setColumnHidden(COL_USER, True)
            try:
                ctx = self.repo[rev or '.']
            except error.RepoError, e:
                msg = _('grep: %s\n') % hglib.tounicode(str(e))
                self.showMessage.emit(msg)
                return
            self.thread = CtxSearchThread(self.repo, regexp, ctx, inc, exc,
                                          self.singlematch.isChecked(),
                                          False)
        else:
            assert self.aradio.isChecked()
            self.tv.setColumnHidden(COL_REVISION, False)
            self.tv.setColumnHidden(COL_USER, False)
            self.thread = HistorySearchThread(self.repo, pattern, icase,
                                              inc, exc,
                                              follow=self.follow.isChecked())

        self.showMessage.emit('')
        self.regexple.setEnabled(False)
        self.searchbutton.setEnabled(False)
        self.cancelbutton.setEnabled(True)
        self.thread.finished.connect(self.searchfinished)
        self.thread.showMessage.connect(self.showMessage)
        self.thread.progress.connect(self.progress)
        self.thread.matchedRow.connect(
                     lambda wrapper: model.appendRow(*wrapper.data))
        self.thread.start()

    def reload(self):
        # TODO
        pass

    def searchfinished(self):
        self.cancelbutton.setEnabled(False)
        self.searchbutton.setEnabled(True)
        self.regexple.setEnabled(True)
        self.regexple.setFocus()
        count = self.tv.model().rowCount(None)
        if count:
            for col in xrange(COL_TEXT):
                self.tv.resizeColumnToContents(col)
            self.tv.setSortingEnabled(True)
        if self.thread.completed == False:
            # do not overwrite error message on failure
            pass
        elif count:
            self.showMessage.emit(_('%d matches found') % count)
        else:
            self.showMessage.emit(_('No matches found'))

class DataWrapper(object):
    def __init__(self, data):
        self.data = data

class HistorySearchThread(QThread):
    '''Background thread for searching repository history'''
    matchedRow = pyqtSignal(DataWrapper)
    showMessage = pyqtSignal(unicode)
    progress = pyqtSignal(QString, object, QString, QString, object)

    def __init__(self, repo, pattern, icase, inc, exc, follow):
        super(HistorySearchThread, self).__init__()
        self.repo = hg.repository(repo.ui, repo.root)
        self.pattern = pattern
        self.icase = icase
        self.inc = inc
        self.exc = exc
        self.follow = follow
        self.completed = False

    def cancel(self):
        if self.isRunning() and hasattr(self, 'thread_id'):
            try:
                thread2._async_raise(self.thread_id, KeyboardInterrupt)
            except ValueError:
                pass

    def run(self):
        self.thread_id = int(QThread.currentThreadId())

        def emitrow(row):
            w = DataWrapper(row)
            self.matchedRow.emit(w)
        def emitprog(topic, pos, item, unit, total):
            self.progress.emit(topic, pos, item, unit, total)
        class incrui(ui.ui):
            fullmsg = ''
            def write(self, msg, *args, **opts):
                self.fullmsg += msg
                if self.fullmsg.count('\0') >= 6:
                    try:
                        fname, line, rev, addremove, user, text, tail = \
                                self.fullmsg.split('\0', 6)
                        text = hglib.tounicode(text)
                        text = Qt.escape(text)
                        text = '<b>%s</b> <span>%s</span>' % (addremove, text)
                        row = [fname, rev, line, user, text]
                        emitrow(row)
                    except ValueError:
                        pass
                    self.fullmsg = tail
            def progress(topic, pos, item='', unit='', total=None):
                emitprog(topic, pos, item, unit, total)
        cwd = os.getcwd()
        os.chdir(self.repo.root)
        self.progress.emit(*cmdui.startProgress(_('Searching'), _('history')))
        try:
            # hg grep [-i] -afn regexp
            opts = {'all':True, 'user':True, 'follow':self.follow,
                    'rev':[], 'line_number':True, 'print0':True,
                    'ignore_case':self.icase, 'include':self.inc,
                    'exclude':self.exc}
            u = incrui()
            commands.grep(u, self.repo, self.pattern, **opts)
        except Exception, e:
            self.showMessage.emit(str(e))
        except KeyboardInterrupt:
            self.showMessage.emit(_('Interrupted'))
        self.progress.emit(*cmdui.stopProgress(_('Searching')))
        os.chdir(cwd)
        self.completed = True

class CtxSearchThread(QThread):
    '''Background thread for searching a changectx'''
    matchedRow = pyqtSignal(object)
    showMessage = pyqtSignal(unicode)
    progress = pyqtSignal(QString, object, QString, QString, object)

    def __init__(self, repo, regexp, ctx, inc, exc, once, recurse):
        super(CtxSearchThread, self).__init__()
        self.repo = hg.repository(repo.ui, repo.root)
        self.regexp = regexp
        self.ctx = ctx
        self.inc = inc
        self.exc = exc
        self.once = once
        self.recurse = recurse
        self.canceled = False
        self.completed = False

    def cancel(self):
        self.canceled = True

    def run(self):
        def badfn(f, msg):
            e = hglib.tounicode("%s: %s" % (matchfn.rel(f), msg))
            self.showMessage.emit(e)
        self.hu = htmlui.htmlui()
        try:
            # generate match function relative to repo root
            matchfn = match.match(self.repo.root, '', [], self.inc, self.exc)
            matchfn.bad = badfn
            self.searchRepo(self.ctx, '', matchfn)
            self.completed = True
        except Exception, e:
            self.showMessage.emit(hglib.tounicode(str(e)))

    def searchRepo(self, ctx, prefix, matchfn):
        topic = _('Searching')
        unit = _('files')
        total = len(ctx.manifest())
        count = 0
        for wfile in ctx:                # walk manifest
            if self.canceled:
                break
            self.progress.emit(topic, count, wfile, unit, total)
            count += 1
            if not matchfn(wfile):
                continue
            try:
                data = ctx[wfile].data()     # load file data
            except EnvironmentError:
                self.showMessage.emit(_('Skipping %s, unable to read') %
                                      hglib.tounicode(wfile))
                continue
            if util.binary(data):
                continue
            for i, line in enumerate(data.splitlines()):
                pos = 0
                for m in self.regexp.finditer(line): # perform regexp
                    self.hu.write(line[pos:m.start()], label='ui.status')
                    self.hu.write(line[m.start():m.end()], label='grep.match')
                    pos = m.end()
                if pos:
                    self.hu.write(line[pos:], label='ui.status')
                    path = os.path.join(prefix, wfile)
                    row = [path, i + 1, ctx.rev(), None,
                           hglib.tounicode(self.hu.getdata()[0])]
                    w = DataWrapper(row)
                    self.matchedRow.emit(w)
                    if self.once:
                        break
        self.progress.emit(topic, None, '', '', None)

        if ctx.rev() is None and self.recurse:
            for s in ctx.substate:
                if not matchfn(s):
                    continue
                sub = ctx.sub(s)
                if isinstance(sub, subrepo.hgsubrepo):
                    newprefix = os.path.join(prefix, s)
                    self.searchRepo(sub._repo[None], newprefix, lambda x: True)


COL_PATH     = 0
COL_LINE     = 1
COL_REVISION = 2  # Hidden if ctx
COL_USER     = 3  # Hidden if ctx
COL_TEXT     = 4

class MatchTree(QTableView):
    revisionSelected = pyqtSignal(int)
    contextmenu = None

    def __init__(self, repo, parent):
        QTableView.__init__(self, parent)

        self.repo = repo
        self.pattern = None
        self.icase = False
        self.embedded = parent.parent() is not None
        self.selectedRows = ()

        self.delegate = htmldelegate.HTMLDelegate(self)
        self.setItemDelegateForColumn(COL_TEXT, self.delegate)
        self.setSelectionMode(QTableView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setShowGrid(False)
        vh = self.verticalHeader()
        vh.hide()
        vh.setDefaultSectionSize(20)
        self.horizontalHeader().setStretchLastSection(True)

        self.actions = {}
        self.contextmenu = QMenu(self)
        for key, name, func, shortcut in (
            ('edit',  _('View file'),      self.onViewFile,      'CTRL+E'),
            ('ctx',   _('View Changeset'), self.onViewChangeset, 'CTRL+V'),
            ('vdiff', _('Visual Diff'),    self.onVisualDiff,    'CTRL+D'),
            ('ann',   _('Annotate file'),  self.onAnnotateFile,  'CTRL+F')):
            action = QAction(name, self)
            action.triggered.connect(func)
            action.setShortcut(QKeySequence(shortcut))
            self.actions[key] = action
            self.addAction(action)
            self.contextmenu.addAction(action)
        self.activated.connect(self.onRowActivated)
        self.customContextMenuRequested.connect(self.menuRequest)

        self.setModel(MatchModel(self))
        self.selectionModel().selectionChanged.connect(self.onSelectionChanged)

    def dragObject(self):
        snapshots = {}
        for index in self.selectionModel().selectedRows():
            path, line, rev, user, text = self.model().getRow(index)
            if rev not in snapshots:
                snapshots[rev] = [path]
            else:
                snapshots[rev].append(path)
        urls = []
        for rev, paths in snapshots.iteritems():
            if rev is not None:
                base, _ = visdiff.snapshot(self.repo, paths, self.repo[rev])
            else:
                base = self.repo.root
            for p in paths:
                urls.append(QUrl.fromLocalFile(os.path.join(base, path)))
        if urls:
            d = QDrag(self)
            m = QMimeData()
            m.setUrls(urls)
            d.setMimeData(m)
            d.start(Qt.CopyAction)

    def mousePressEvent(self, event):
        self.pressPos = event.pos()
        self.pressTime = QTime.currentTime()
        return QTableView.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        d = event.pos() - self.pressPos
        if d.manhattanLength() < QApplication.startDragDistance():
            return QTableView.mouseMoveEvent(self, event)
        elapsed = self.pressTime.msecsTo(QTime.currentTime())
        if elapsed < QApplication.startDragTime():
            return QTableView.mouseMoveEvent(self, event)
        self.dragObject()
        return QTableView.mouseMoveEvent(self, event)

    def menuRequest(self, point):
        if not self.selectionModel().selectedRows():
            return
        point = self.viewport().mapToGlobal(point)
        self.contextmenu.exec_(point)

    def onSelectionChanged(self, selected, deselected):
        selrows = []
        wctxonly = True
        allhistory = False
        for index in self.selectionModel().selectedRows():
            path, line, rev, user, text = self.model().getRow(index)
            if rev is not None:
                wctxonly = False
            if user is not None:
                allhistory = True
            selrows.append((rev, path, line))
        self.selectedRows = selrows
        self.actions['ctx'].setEnabled(not wctxonly and self.embedded)
        self.actions['vdiff'].setEnabled(allhistory)

    def onRowActivated(self, index):
        saved = self.selectedRows
        path, line, rev, user, text = self.model().getRow(index)
        self.selectedRows = [(rev, path, line)]
        self.onAnnotateFile()
        self.selectedRows = saved

    def onAnnotateFile(self):
        from tortoisehg.hgqt.manifestdialog import run
        from tortoisehg.hgqt.run import qtrun
        repo, ui, pattern, icase = self.repo, self.repo.ui, self.pattern, self.icase
        seen = set()
        for rev, path, line in self.selectedRows:
            # Only open one annotate instance per file
            if path in seen:
                continue
            else:
                seen.add(path)
            if rev is None and path not in repo[None]:
                abs = repo.wjoin(path)
                root = paths.find_root(abs)
                if root and abs.startswith(root):
                    path = abs[len(root)+1:]
                    if rev is None:
                        rev = repo['.'].rev()
                    srepo = thgrepo.repository(None, root)
                    opts = {'repo': srepo, 'canonpath' : path, 'rev' : rev,
                            'line': line, 'pattern': pattern, 'ignorecase': icase}
                    qtrun(run, ui, **opts)
                else:
                    continue
            else:
                if rev is None:
                    rev = repo['.'].rev()
                opts = {'repo': repo, 'canonpath' : path, 'rev' : rev,
                        'line': line, 'pattern': pattern, 'ignorecase': icase}
                qtrun(run, ui, **opts)

    def onViewChangeset(self):
        for rev, path, line in self.selectedRows:
            self.revisionSelected.emit(int(rev))
            return

    def onViewFile(self):
        repo, ui, pattern = self.repo, self.repo.ui, self.pattern
        seen = set()
        for rev, path, line in self.selectedRows:
            # Only open one editor instance per file
            if path in seen:
                continue
            else:
                seen.add(path)
            if rev is None:
                qtlib.editfiles(repo, [path], line, pattern, self)
            else:
                base, _ = visdiff.snapshot(repo, [path], repo[rev])
                files = [os.path.join(base, path)]
                qtlib.editfiles(repo, files, line, pattern, self)

    def onVisualDiff(self):
        rows = self.selectedRows[:]
        repo, ui = self.repo, self.repo.ui
        while rows:
            defer = []
            crev = rows[0][0]
            files = set([rows[0][1]])
            for rev, path, line in rows[1:]:
                if rev == crev:
                    files.add(path)
                else:
                    defer.append([rev, path, line])
            if crev is not None:
                dlg = visdiff.visualdiff(ui, repo, list(files), {'change':crev})
                if dlg:
                    dlg.exec_()
            rows = defer


class MatchModel(QAbstractTableModel):
    def __init__(self, parent):
        QAbstractTableModel.__init__(self, parent)
        self.rows = []
        self.headers = (_('File'), _('Line'), _('Rev'), _('User'),
                        _('Match Text'))

    def rowCount(self, parent):
        return len(self.rows)

    def columnCount(self, parent):
        return len(self.headers)

    def data(self, index, role):
        if not index.isValid():
            return QVariant()
        if role == Qt.DisplayRole:
            return QVariant(self.rows[index.row()][index.column()])
        return QVariant()

    def headerData(self, col, orientation, role):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return QVariant()
        else:
            return QVariant(self.headers[col])

    def flags(self, index):
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled
        return flags

    def sort(self, col, order):
        self.layoutAboutToBeChanged.emit()
        self.rows.sort(key=lambda x: x[col],
                       reverse=(order == Qt.DescendingOrder))
        self.layoutChanged.emit()

    ## Custom methods

    def appendRow(self, *args):
        l = len(self.rows)
        self.beginInsertRows(QModelIndex(), l, l)
        self.rows.append(args)
        self.endInsertRows()
        self.layoutChanged.emit()

    def reset(self):
        self.beginRemoveRows(QModelIndex(), 0, len(self.rows)-1)
        self.rows = []
        self.endRemoveRows()
        self.layoutChanged.emit()

    def getRow(self, index):
        assert index.isValid()
        return self.rows[index.row()]

def run(ui, *pats, **opts):
    repo = thgrepo.repository(ui, path=paths.find_root())
    upats = [hglib.tounicode(p) for p in pats]
    return SearchWidget(upats, repo, **opts)
