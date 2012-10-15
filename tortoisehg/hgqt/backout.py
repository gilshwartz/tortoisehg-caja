# backout.py - Backout dialog for TortoiseHg
#
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from mercurial import error, hg, merge as mergemod

from tortoisehg.util import hglib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, csinfo, i18n, cmdui, status, resolve
from tortoisehg.hgqt import qscilib, thgrepo, messageentry

from PyQt4.QtCore import *
from PyQt4.QtGui import *

class BackoutDialog(QWizard):

    def __init__(self, rev, repo, parent):
        super(BackoutDialog, self).__init__(parent)
        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)

        self.backoutrev = rev
        self.parentbackout = False
        self.backoutmergeparentrev = None

        self.setWindowTitle(_('Backout - %s') % repo.displayname)
        self.setWindowIcon(qtlib.geticon('hg-revert'))
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.NoBackButtonOnLastPage, True)
        self.setOption(QWizard.IndependentPages, True)

        self.addPage(SummaryPage(repo, self))
        self.addPage(BackoutPage(repo, self))
        self.addPage(CommitPage(repo, self))
        self.addPage(ResultPage(repo, self))
        self.currentIdChanged.connect(self.pageChanged)

        self.resize(QSize(700, 489).expandedTo(self.minimumSizeHint()))

        repo.repositoryChanged.connect(self.repositoryChanged)
        repo.configChanged.connect(self.configChanged)

    def repositoryChanged(self):
        self.currentPage().repositoryChanged()

    def configChanged(self):
        self.currentPage().configChanged()

    def pageChanged(self, id):
        if id != -1:
            self.currentPage().currentPage()

    def reject(self):
        if self.currentPage().canExit():
            super(BackoutDialog, self).reject()


class BasePage(QWizardPage):
    def __init__(self, repo, parent):
        super(BasePage, self).__init__(parent)
        self.repo = repo

    def validatePage(self):
        'user pressed NEXT button, can we proceed?'
        return True

    def isComplete(self):
        'should NEXT button be sensitive?'
        return True

    def repositoryChanged(self):
        'repository has detected a change to changelog or parents'
        pass

    def configChanged(self):
        'repository has detected a change to config files'
        pass

    def currentPage(self):
        pass

    def canExit(self):
        return True


class SummaryPage(BasePage):

    def __init__(self, repo, parent):
        super(SummaryPage, self).__init__(repo, parent)
        self.clean = False
        self.th = None

    def initializePage(self):
        if self.layout():
            return
        self.setTitle(_('Prepare to backout'))
        self.setSubTitle(_('Verify backout revision and ensure your working '
                           'directory is clean.'))
        self.setLayout(QVBoxLayout())

        self.groups = qtlib.WidgetGroups()

        repo = self.repo
        try:
            bctx = repo[self.wizard().backoutrev]
            pctx = repo['.']
        except error.RepoLookupError:
            qtlib.InfoMsgBox(_('Unable to backout'),
                             _('Backout revision not found'))
            QTimer.singleShot(0, self.wizard().close)
            return

        if pctx == bctx:
            lbl = _('Backing out a parent revision is a single step operation')
            self.layout().addWidget(QLabel(u'<b>%s</b>' % lbl))
            self.wizard().parentbackout = True

        op1, op2 = repo.dirstate.parents()
        if op1 is None:
            qtlib.InfoMsgBox(_('Unable to backout'),
                             _('Backout requires a parent revision'))
            QTimer.singleShot(0, self.wizard().close)
            return

        a = repo.changelog.ancestor(op1, bctx.node())
        if a != bctx.node():
            qtlib.InfoMsgBox(_('Unable to backout'),
                             _('Cannot backout change on a different branch'))
            QTimer.singleShot(0, self.wizard().close)

        ## backout revision
        style = csinfo.panelstyle(contents=csinfo.PANEL_DEFAULT)
        create = csinfo.factory(repo, None, style, withupdate=True)
        sep = qtlib.LabeledSeparator(_('Backout revision'))
        self.layout().addWidget(sep)
        backoutCsInfo = create(bctx.rev())
        self.layout().addWidget(backoutCsInfo)

        ## current revision
        contents = ('ishead',) + csinfo.PANEL_DEFAULT
        style = csinfo.panelstyle(contents=contents)
        def markup_func(widget, item, value):
            if item == 'ishead' and value is False:
                text = _('Not a head, backout will create a new head!')
                return qtlib.markup(text, fg='red', weight='bold')
            raise csinfo.UnknownItem(item)
        custom = csinfo.custom(markup=markup_func)
        create = csinfo.factory(repo, custom, style, withupdate=True)

        sep = qtlib.LabeledSeparator(_('Current local revision'))
        self.layout().addWidget(sep)
        localCsInfo = create(pctx.rev())
        self.layout().addWidget(localCsInfo)
        self.localCsInfo = localCsInfo

        ## Merge revision backout handling
        if len(bctx.parents()) > 1:
            # Show two radio buttons letting the user which merge revision
            # parent to backout to
            p1rev = bctx.p1().rev()
            p2rev = bctx.p2().rev()

            def setBackoutMergeParentRev(rev):
                self.wizard().backoutmergeparentrev = rev

            setBackoutMergeParentRev(p1rev)

            sep = qtlib.LabeledSeparator(_('Merge parent to backout to'))
            self.layout().addWidget(sep)
            self.layout().addWidget(QLabel(
                _('To backout a <b>merge</b> revision you must select which '
                'parent to backout to '
                '(i.e. whose changes will be <i>kept</i>)')))

            self.actionFirstParent = QRadioButton(
                _('First Parent: revision %s (%s)') \
                % (p1rev, str(bctx.p1())), self)
            self.actionFirstParent.setCheckable(True)
            self.actionFirstParent.setChecked(True)
            self.actionFirstParent.setShortcut('CTRL+1')
            self.actionFirstParent.setToolTip(
                _('Backout to the first parent of the merge revision'))
            self.actionFirstParent.clicked.connect(
                lambda: setBackoutMergeParentRev(p1rev))

            self.actionSecondParent = QRadioButton(
                _('Second Parent: revision %s (%s)')
                % (p2rev, str(bctx.p2())), self)
            self.actionSecondParent.setCheckable(True)
            self.actionSecondParent.setShortcut('CTRL+2')
            self.actionSecondParent.setToolTip(
                _('Backout to the second parent of the merge revision'))
            self.actionSecondParent.clicked.connect(
                lambda: setBackoutMergeParentRev(p2rev))

            self.layout().addWidget(self.actionFirstParent)
            self.layout().addWidget(self.actionSecondParent)

        ## working directory status
        sep = qtlib.LabeledSeparator(_('Working directory status'))
        self.layout().addWidget(sep)

        wdbox = QHBoxLayout()
        self.layout().addLayout(wdbox)
        self.wd_status = qtlib.StatusLabel()
        self.wd_status.set_status(_('Checking...'))
        wdbox.addWidget(self.wd_status)
        wd_prog = QProgressBar()
        wd_prog.setMaximum(0)
        wd_prog.setTextVisible(False)
        self.groups.add(wd_prog, 'prog')
        wdbox.addWidget(wd_prog, 1)

        text = _('Before backout, you must <a href="commit"><b>commit</b></a>, '
                 '<a href="shelve"><b>shelve</b></a> to patch, '
                 'or <a href="discard"><b>discard</b></a> changes.')
        wd_text = QLabel(text)
        wd_text.setWordWrap(True)
        wd_text.linkActivated.connect(self.onLinkActivated)
        self.wd_text = wd_text
        self.groups.add(wd_text, 'dirty')
        self.layout().addWidget(wd_text)

        ## auto-resolve
        autoresolve_chk = QCheckBox(_('Automatically resolve merge conflicts '
                                      'where possible'))
        autoresolve_chk.setChecked(
            repo.ui.configbool('tortoisehg', 'autoresolve', False))
        self.registerField('autoresolve', autoresolve_chk)
        self.layout().addWidget(autoresolve_chk)
        self.autoresolve_chk = autoresolve_chk
        self.groups.set_visible(False, 'dirty')

    def isComplete(self):
        'should Next button be sensitive?'
        return self.clean

    def repositoryChanged(self):
        'repository has detected a change to changelog or parents'
        pctx = self.repo['.']
        self.localCsInfo.update(pctx)
        self.wizard().localrev = str(pctx.rev())

    def canExit(self):
        'can backout tool be closed?'
        if self.th is not None and self.th.isRunning():
            self.th.cancel()
            self.th.wait()
        return True

    def currentPage(self):
        self.refresh()

    def refresh(self):
        if self.th is None:
            self.th = CheckThread(self.repo, self)
            self.th.finished.connect(self.threadFinished)
        if self.th.isRunning():
            return
        self.groups.set_visible(True, 'prog')
        self.th.start()

    def threadFinished(self):
        self.groups.set_visible(False, 'prog')
        if self.th.canceled:
            return
        dirty, parents = self.th.results
        self.clean = not dirty
        if dirty:
            self.groups.set_visible(True, 'dirty')
            self.wd_status.set_status(_('<b>Uncommitted local changes '
                                        'are detected</b>'), 'thg-warning')
        else:
            self.groups.set_visible(False, 'dirty')
            self.wd_status.set_status(_('Clean'), True)
        self.completeChanged.emit()

    @pyqtSlot(QString)
    def onLinkActivated(self, cmd):
        cmd = hglib.fromunicode(cmd)
        repo = self.repo
        if cmd == 'commit':
            from tortoisehg.hgqt import commit
            dlg = commit.CommitDialog(repo, [], {}, self.wizard())
            dlg.finished.connect(dlg.deleteLater)
            dlg.exec_()
            self.refresh()
        elif cmd == 'shelve':
            from tortoisehg.hgqt import shelve
            dlg = shelve.ShelveDialog(repo, self.wizard())
            dlg.finished.connect(dlg.deleteLater)
            dlg.exec_()
            self.refresh()
        elif cmd.startswith('discard'):
            if cmd != 'discard:noconfirm':
                labels = [(QMessageBox.Yes, _('&Discard')),
                          (QMessageBox.No, _('Cancel'))]
                if not qtlib.QuestionMsgBox(_('Confirm Discard'),
                         _('Discard outstanding changes to working directory?'),
                         labels=labels, parent=self):
                    return
            def finished(ret):
                repo.decrementBusyCount()
                self.refresh()
            cmdline = ['update', '--clean', '--repository', repo.root,
                       '--rev', '.']
            self.runner = cmdui.Runner(True, self)
            self.runner.commandFinished.connect(finished)
            repo.incrementBusyCount()
            self.runner.run(cmdline)
        elif cmd == 'view':
            dlg = status.StatusDialog(repo, [], {}, self)
            dlg.exec_()
            self.refresh()
        else:
            raise 'unknown command: %s' % cmd


class BackoutPage(BasePage):
    def __init__(self, repo, parent):
        super(BackoutPage, self).__init__(repo, parent)
        self.backoutcomplete = False

        self.setTitle(_('Backing out, then merging...'))
        self.setSubTitle(_('All conflicting files will be marked unresolved.'))
        self.setLayout(QVBoxLayout())

        self.cmd = cmdui.Widget(True, False, self)
        self.cmd.commandFinished.connect(self.onCommandFinished)
        self.cmd.setShowOutput(True)
        self.layout().addWidget(self.cmd)

        self.reslabel = QLabel()
        self.reslabel.linkActivated.connect(self.onLinkActivated)
        self.reslabel.setWordWrap(True)
        self.layout().addWidget(self.reslabel)

        self.autonext = QCheckBox(_('Automatically advance to next page '
                                    'when backout and merge are complete.'))
        checked = QSettings().value('backout/autoadvance', False).toBool()
        self.autonext.setChecked(checked)
        self.autonext.toggled.connect(self.tryAutoAdvance)
        self.layout().addWidget(self.autonext)

    def currentPage(self):
        if self.wizard().parentbackout:
            self.wizard().next()
            return
        cmdline = ['--repository', self.repo.root, 'backout']
        tool = self.field('autoresolve').toBool() and 'merge' or 'fail'
        cmdline += ['--tool=internal:' + tool]
        cmdline += ['--rev', str(self.wizard().backoutrev)]
        if self.wizard().backoutmergeparentrev:
            cmdline += ['--parent', str(self.wizard().backoutmergeparentrev)]
        self.repo.incrementBusyCount()
        self.cmd.core.clearOutput()
        self.cmd.run(cmdline)

    def isComplete(self):
        'should Next button be sensitive?'
        if not self.backoutcomplete:
            return False
        count = 0
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if status == 'u':
                count += 1
        if count:
            # if autoresolve is enabled, we know these were real conflicts
            self.reslabel.setText(_('%d files have <b>merge conflicts</b> '
                                    'that must be <a href="resolve">'
                                    '<b>resolved</b></a>') % count)
            return False
        else:
            self.reslabel.setText(_('No merge conflicts, ready to commit'))
            return True

    def tryAutoAdvance(self, checked):
        if checked and self.isComplete():
            self.wizard().next()

    def cleanupPage(self):
        QSettings().setValue('backout/autoadvance', self.autonext.isChecked())

    def onCommandFinished(self, ret):
        self.repo.decrementBusyCount()
        if ret in (0, 1):
            self.backoutcomplete = True
            if self.autonext.isChecked():
                self.tryAutoAdvance(True)
            self.completeChanged.emit()

    @pyqtSlot(QString)
    def onLinkActivated(self, cmd):
        if cmd == 'resolve':
            dlg = resolve.ResolveDialog(self.repo, self)
            dlg.finished.connect(dlg.deleteLater)
            dlg.exec_()
            if self.autonext.isChecked():
                self.tryAutoAdvance(True)
            self.completeChanged.emit()


class CommitPage(BasePage):

    def __init__(self, repo, parent):
        super(CommitPage, self).__init__(repo, parent)
        self.commitComplete = False

        self.setTitle(_('Commit backout and merge results'))
        self.setSubTitle(' ')
        self.setLayout(QVBoxLayout())
        self.setCommitPage(True)

        # csinfo
        def label_func(widget, item, ctx):
            if item == 'rev':
                return _('Revision:')
            elif item == 'parents':
                return _('Parents')
            raise csinfo.UnknownItem()
        def data_func(widget, item, ctx):
            if item == 'rev':
                return _('Working Directory'), str(ctx)
            elif item == 'parents':
                parents = []
                cbranch = ctx.branch()
                for pctx in ctx.parents():
                    branch = None
                    if hasattr(pctx, 'branch') and pctx.branch() != cbranch:
                        branch = pctx.branch()
                    parents.append((str(pctx.rev()), str(pctx), branch, pctx))
                return parents
            raise csinfo.UnknownItem()
        def markup_func(widget, item, value):
            if item == 'rev':
                text, rev = value
                if self.wizard() and self.wizard().parentbackout:
                    return '%s (%s)' % (text, rev)
                else:
                    return '<a href="view">%s</a> (%s)' % (text, rev)
            elif item == 'parents':
                def branch_markup(branch):
                    opts = dict(fg='black', bg='#aaffaa')
                    return qtlib.markup(' %s ' % branch, **opts)
                csets = []
                for rnum, rid, branch, pctx in value:
                    line = '%s (%s)' % (rnum, rid)
                    if branch:
                        line = '%s %s' % (line, branch_markup(branch))
                    msg = widget.info.get_data('summary', widget,
                                               pctx, widget.custom)
                    if msg:
                        line = '%s %s' % (line, msg)
                    csets.append(line)
                return csets
            raise csinfo.UnknownItem()
        custom = csinfo.custom(label=label_func, data=data_func,
                               markup=markup_func)
        contents = ('rev', 'user', 'dateage', 'branch', 'parents')
        style = csinfo.panelstyle(contents=contents, margin=6)

        # merged files
        rev_sep = qtlib.LabeledSeparator(_('Working Directory (merged)'))
        self.layout().addWidget(rev_sep)
        bkCsInfo = csinfo.create(repo, None, style, custom=custom,
                                 withupdate=True)
        bkCsInfo.linkActivated.connect(self.onLinkActivated)
        self.layout().addWidget(bkCsInfo)

        # commit message area
        msg_sep = qtlib.LabeledSeparator(_('Commit message'))
        self.layout().addWidget(msg_sep)
        msgEntry = messageentry.MessageEntry(self)
        msgEntry.installEventFilter(qscilib.KeyPressInterceptor(self))
        msgEntry.refresh(repo)
        msgEntry.loadSettings(QSettings(), 'backout/message')

        msgEntry.textChanged.connect(self.completeChanged)
        self.layout().addWidget(msgEntry)
        self.msgEntry = msgEntry

        self.cmd = cmdui.Widget(True, False, self)
        self.cmd.commandFinished.connect(self.onCommandFinished)
        self.cmd.setShowOutput(False)
        self.layout().addWidget(self.cmd)

        def tryperform():
            if self.isComplete():
                self.wizard().next()
        actionEnter = QAction('alt-enter', self)
        actionEnter.setShortcuts([Qt.CTRL+Qt.Key_Return, Qt.CTRL+Qt.Key_Enter])
        actionEnter.triggered.connect(tryperform)
        self.addAction(actionEnter)

        self.skiplast = QCheckBox(_('Skip final confirmation page, '
                                    'close after commit.'))
        checked = QSettings().value('backout/skiplast', False).toBool()
        self.skiplast.setChecked(checked)
        self.layout().addWidget(self.skiplast)

        def eng_toggled(checked):
            if self.isComplete():
                oldmsg = self.msgEntry.text()
                if self.wizard().backoutmergeparentrev:
                    msgset = i18n.keepgettext()._(
                        'Backed out merge changeset: ')
                else:
                    msgset = i18n.keepgettext()._('Backed out changeset: ')
                msg = checked and msgset['id'] or msgset['str']
                if oldmsg and oldmsg != msg:
                    if not qtlib.QuestionMsgBox(_('Confirm Discard Message'),
                         _('Discard current backout message?'), parent=self):
                        self.engChk.blockSignals(True)
                        self.engChk.setChecked(not checked)
                        self.engChk.blockSignals(False)
                        return
                self.msgEntry.setText(msg
                                     + str(self.repo[self.wizard().backoutrev]))
                self.msgEntry.moveCursorToEnd()

        self.engChk = QCheckBox(_('Use English backout message'))
        self.engChk.toggled.connect(eng_toggled)
        engmsg = self.repo.ui.configbool('tortoisehg', 'engmsg', False)
        self.engChk.setChecked(engmsg)
        self.layout().addWidget(self.engChk)

    def refresh(self):
        pass

    def cleanupPage(self):
        s = QSettings()
        s.setValue('backout/skiplast', self.skiplast.isChecked())
        self.msgEntry.saveSettings(s, 'backout/message')

    def currentPage(self):
        engmsg = self.repo.ui.configbool('tortoisehg', 'engmsg', False)
        mergeparentrev = self.wizard().backoutmergeparentrev
        if mergeparentrev:
            msgset = i18n.keepgettext()._(
                'Backed out merge changeset: ')
        else:
            msgset = i18n.keepgettext()._('Backed out changeset: ')
        msg = engmsg and msgset['id'] or msgset['str']
        msg += str(self.repo[self.wizard().backoutrev])
        if mergeparentrev:
            msg += '\n\n'
            bctx = self.repo[self.wizard().backoutrev]
            isp1 = (bctx.p1().rev() == mergeparentrev)
            if isp1:
                msg += _('Backed out merge revision '
                    'to its first parent (%s)') % str(bctx.p1())
            else:
                msg += _('Backed out merge revision '
                    'to its second parent (%s)') % str(bctx.p2())
        self.msgEntry.setText(msg)
        self.msgEntry.moveCursorToEnd()

    @pyqtSlot(QString)
    def onLinkActivated(self, cmd):
        if cmd == 'view':
            dlg = status.StatusDialog(self.repo, [], {}, self)
            dlg.exec_()
            self.refresh()

    def isComplete(self):
        return len(self.msgEntry.text()) > 0

    def validatePage(self):
        if self.commitComplete:
            # commit succeeded, repositoryChanged() called wizard().next()
            if self.skiplast.isChecked():
                self.wizard().close()
            return True
        if self.cmd.core.running():
            return False

        user = qtlib.getCurrentUsername(self, self.repo)
        if not user:
            return False

        if self.wizard().parentbackout:
            self.setTitle(_('Backing out and committing...'))
            self.setSubTitle(_('Please wait while making backout.'))
            message = hglib.fromunicode(self.msgEntry.text())
            cmdline = ['backout', '--verbose', '--message', message, '--rev',
                       str(self.wizard().backoutrev), '--user', user,
                       '--repository', self.repo.root]
            if self.wizard().backoutmergeparentrev:
                cmdline += ['--parent', str(self.wizard().backoutmergeparentrev)]
        else:
            self.setTitle(_('Committing...'))
            self.setSubTitle(_('Please wait while committing merged files.'))
            message = hglib.fromunicode(self.msgEntry.text())
            cmdline = ['commit', '--verbose', '--message', message,
                       '--repository', self.repo.root, '--user', user]
        commandlines = [cmdline]
        pushafter = self.repo.ui.config('tortoisehg', 'cipushafter')
        if pushafter:
            cmd = ['push', '--repository', self.repo.root, pushafter]
            commandlines.append(cmd)

        self.repo.incrementBusyCount()
        self.cmd.setShowOutput(True)
        self.cmd.run(*commandlines)
        return False

    def onCommandFinished(self, ret):
        self.repo.decrementBusyCount()
        if ret == 0:
            self.commitComplete = True
            self.wizard().next()


class ResultPage(BasePage):
    def __init__(self, repo, parent):
        super(ResultPage, self).__init__(repo, parent)
        self.setTitle(_('Finished'))
        self.setSubTitle(' ')
        self.setFinalPage(True)

        self.setLayout(QVBoxLayout())
        sep = qtlib.LabeledSeparator(_('Backout changeset'))
        self.layout().addWidget(sep)
        bkCsInfo = csinfo.create(self.repo, 'tip', withupdate=True)
        self.layout().addWidget(bkCsInfo)
        self.bkCsInfo = bkCsInfo
        self.layout().addStretch(1)

    def currentPage(self):
        self.bkCsInfo.update(self.repo['tip'])
        self.wizard().setOption(QWizard.NoCancelButton, True)


class CheckThread(QThread):
    def __init__(self, repo, parent):
        QThread.__init__(self, parent)
        self.repo = hg.repository(repo.ui, repo.root)
        self.results = (False, 1)
        self.canceled = False

    def run(self):
        self.repo.dirstate.invalidate()
        unresolved = False
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if self.canceled:
                return
            if status == 'u':
                unresolved = True
                break
        wctx = self.repo[None]
        dirty = bool(wctx.dirty()) or unresolved
        self.results = (dirty, len(wctx.parents()))

    def cancel(self):
        self.canceled = True


def run(ui, *pats, **opts):
    from tortoisehg.util import paths
    repo = thgrepo.repository(ui, path=paths.find_root())
    if opts.get('rev'):
        rev = opts.get('rev')
    elif len(pats) == 1:
        rev = pats[0]
    else:
        rev = 'tip'
    return BackoutDialog(rev, repo, None)
