# merge.py - Merge dialog for TortoiseHg
#
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from mercurial import hg, error

from tortoisehg.util import hglib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, csinfo, i18n, cmdui, status, resolve
from tortoisehg.hgqt import qscilib, thgrepo, messageentry

from PyQt4.QtCore import *
from PyQt4.QtGui import *

MARGINS = (8, 0, 0, 0)

class MergeDialog(QWizard):

    def __init__(self, otherrev, repo, parent):
        super(MergeDialog, self).__init__(parent)
        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)

        self.otherrev = str(otherrev)
        self.localrev = str(repo['.'].rev())

        self.setWindowTitle(_('Merge - %s') % repo.displayname)
        self.setWindowIcon(qtlib.geticon('hg-merge'))
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.NoBackButtonOnLastPage, True)
        self.setOption(QWizard.IndependentPages, True)

        # set pages
        self.addPage(SummaryPage(repo, self))
        self.addPage(MergePage(repo, self))
        self.addPage(CommitPage(repo, self))
        self.addPage(ResultPage(repo, self))
        self.currentIdChanged.connect(self.pageChanged)

        self.resize(QSize(700, 489).expandedTo(self.minimumSizeHint()))

        repo.repositoryChanged.connect(self.repositoryChanged)
        repo.configChanged.connect(self.configChanged)
        self.repo = repo

    def repositoryChanged(self):
        self.currentPage().repositoryChanged()

    def configChanged(self):
        self.currentPage().configChanged()

    def pageChanged(self, id):
        if id != -1:
            self.currentPage().currentPage()

    def reject(self):
        if self.currentPage().canExit():
            super(MergeDialog, self).reject()

    def done(self, ret):
        self.repo.repositoryChanged.disconnect(self.repositoryChanged)
        self.repo.configChanged.disconnect(self.configChanged)
        super(MergeDialog, self).done(ret)


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
        if len(self.repo.parents()) == 2:
            main = _('Do you want to exit?')
            text = _('To finish merging, you need to commit '
                     'the working directory.')
            labels = ((QMessageBox.Yes, _('&Exit')),
                      (QMessageBox.No, _('Cancel')))
            if not qtlib.QuestionMsgBox(_('Confirm Exit'), main, text,
                                        labels=labels, parent=self):
                return False
        return True

class SummaryPage(BasePage):

    def __init__(self, repo, parent):
        super(SummaryPage, self).__init__(repo, parent)
        self.clean = None
        self.th = None

    ### Override Methods ###

    def initializePage(self):
        if self.layout():
            return
        self.setTitle(_('Prepare to merge'))
        self.setSubTitle(_('Verify merge targets and ensure your working '
                           'directory is clean.'))
        self.setLayout(QVBoxLayout())

        repo = self.repo
        contents = ('ishead',) + csinfo.PANEL_DEFAULT
        style = csinfo.panelstyle(contents=contents)
        def markup_func(widget, item, value):
            if item == 'ishead' and value is False:
                text = _('Not a head revision!')
                return qtlib.markup(text, fg='red', weight='bold')
            raise csinfo.UnknownItem(item)
        custom = csinfo.custom(markup=markup_func)
        create = csinfo.factory(repo, custom, style, withupdate=True)

        ## merge target
        other_sep = qtlib.LabeledSeparator(_('Merge from (other revision)'))
        self.layout().addWidget(other_sep)
        try:
            otherCsInfo = create(self.wizard().otherrev)
        except error.RepoLookupError:
            qtlib.InfoMsgBox(_('Unable to merge'),
                             _('Merge revision not specified or not found'))
            QTimer.singleShot(0, self.wizard().close)
        self.layout().addWidget(otherCsInfo)
        self.otherCsInfo = otherCsInfo

        ## current revision
        local_sep = qtlib.LabeledSeparator(_('Merge to (working directory)'))
        self.layout().addWidget(local_sep)
        localCsInfo = create(self.wizard().localrev)
        self.layout().addWidget(localCsInfo)
        self.localCsInfo = localCsInfo

        ## working directory status
        wd_sep = qtlib.LabeledSeparator(_('Working directory status'))
        self.layout().addWidget(wd_sep)

        self.groups = qtlib.WidgetGroups()

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

        wd_merged = QLabel(_('The working directory is already <b>merged</b>. '
                             '<a href="skip"><b>Continue</b></a> or '
                             '<a href="discard"><b>discard</b></a> existing '
                             'merge.'))
        wd_merged.linkActivated.connect(self.onLinkActivated)
        wd_merged.setWordWrap(True)
        self.groups.add(wd_merged, 'merged')
        self.layout().addWidget(wd_merged)

        text = _('Before merging, you must <a href="commit"><b>commit</b></a>, '
                 '<a href="shelve"><b>shelve</b></a> to patch, '
                 'or <a href="discard"><b>discard</b></a> changes.')
        wd_text = QLabel(text)
        wd_text.setWordWrap(True)
        wd_text.linkActivated.connect(self.onLinkActivated)
        self.wd_text = wd_text
        self.groups.add(wd_text, 'dirty')
        self.layout().addWidget(wd_text)

        wdbox = QHBoxLayout()
        self.layout().addLayout(wdbox)
        wd_alt = QLabel(_('Or use:'))
        self.groups.add(wd_alt, 'dirty')
        wdbox.addWidget(wd_alt)
        force_chk = QCheckBox(_('Force a merge with outstanding changes '
                                '(-f/--force)'))
        force_chk.toggled.connect(lambda c: self.completeChanged.emit())
        self.registerField('force', force_chk)
        self.groups.add(force_chk, 'dirty')
        wdbox.addWidget(force_chk)

        ### options
        expander = qtlib.ExpanderLabel(_('Options'), False)
        expander.expanded.connect(self.toggleShowOptions)
        self.layout().addWidget(expander)
        self.expander = expander

        ### discard option
        discard_chk = QCheckBox(_('Discard all changes from merge target '
                                  '(other) revision'))
        self.registerField('discard', discard_chk)
        self.layout().addWidget(discard_chk)
        self.discard_chk = discard_chk

        ## auto-resolve
        autoresolve_chk = QCheckBox(_('Automatically resolve merge conflicts '
                                      'where possible'))
        autoresolve_chk.setChecked(
            repo.ui.configbool('tortoisehg', 'autoresolve', False))
        self.registerField('autoresolve', autoresolve_chk)
        self.layout().addWidget(autoresolve_chk)
        self.autoresolve_chk = autoresolve_chk

        self.groups.set_visible(False, 'dirty')
        self.groups.set_visible(False, 'merged')
        self.toggleShowOptions(self.expander.is_expanded())

    def isComplete(self):
        'should Next button be sensitive?'
        return self.clean or self.field('force').toBool()

    def validatePage(self):
        'validate that we can continue with the merge'
        if self.field('discard').toBool():
            labels = [(QMessageBox.Yes, _('&Discard')),
                      (QMessageBox.No, _('Cancel'))]
            if not qtlib.QuestionMsgBox(_('Confirm Discard Changes'),
                _('The changes from revision %s and all unmerged parents '
                  'will be discarded.\n\n'
                  'Are you sure this is what you want to do?')
                      % (self.otherCsInfo.get_data('revid')),
                         labels=labels, parent=self):
                return False
        return super(SummaryPage, self).validatePage();

    ## custom methods ##

    def toggleShowOptions(self, visible):
        self.discard_chk.setShown(visible)
        self.autoresolve_chk.setShown(visible)

    def repositoryChanged(self):
        'repository has detected a change to changelog or parents'
        pctx = self.repo['.']
        self.localCsInfo.update(pctx)
        self.wizard().localrev = str(pctx.rev())

    def canExit(self):
        'can merge tool be closed?'
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
            self.groups.set_visible(parents == 2, 'merged')
            self.groups.set_visible(parents == 1, 'dirty')
            self.wd_status.set_status(_('<b>Uncommitted local changes '
                                        'are detected</b>'), 'thg-warning')
        else:
            self.groups.set_visible(False, 'dirty')
            self.groups.set_visible(False, 'merged')
            self.wd_status.set_status(_('Clean', 'working dir state'), True)
        self.completeChanged.emit()

    @pyqtSlot(QString)
    def onLinkActivated(self, cmd):
        cmd = hglib.fromunicode(cmd)
        repo = self.repo
        if cmd == 'commit':
            from tortoisehg.hgqt import commit
            dlg = commit.CommitDialog(repo, [], {}, self)
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
        elif cmd == 'skip':
            self.wizard().next()
        else:
            raise 'unknown command: %s' % cmd


class MergePage(BasePage):
    def __init__(self, repo, parent):
        super(MergePage, self).__init__(repo, parent)
        self.mergecomplete = False

        self.setTitle(_('Merging...'))
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
                                    'when merge is complete.'))
        checked = QSettings().value('merge/autoadvance', False).toBool()
        self.autonext.setChecked(checked)
        self.autonext.toggled.connect(self.tryAutoAdvance)
        self.layout().addWidget(self.autonext)

    def currentPage(self):
        if self.field('discard').toBool():
            # '.' is safer than self.localrev, in case the user has
            # pulled a fast one on us and updated from the CLI
            cmdline = ['--repository', self.repo.root, 'debugsetparents',
                       '.', self.wizard().otherrev]
        else:
            cmdline = ['--repository', self.repo.root, 'merge', '--verbose']
            if self.field('force').toBool():
                cmdline.append('--force')
            tool = self.field('autoresolve').toBool() and 'merge' or 'fail'
            cmdline += ['--tool=internal:' + tool]
            cmdline.append(self.wizard().otherrev)

        if len(self.repo.parents()) == 1:
            self.repo.incrementBusyCount()
            self.cmd.core.clearOutput()
            self.cmd.run(cmdline)
        else:
            self.mergecomplete = True
            self.completeChanged.emit()

    def isComplete(self):
        'should Next button be sensitive?'
        if not self.mergecomplete:
            return False
        count = 0
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if status == 'u':
                count += 1
        if count:
            if self.field('autoresolve').toBool():
                # if autoresolve is enabled, we know these were real conflicts
                self.reslabel.setText(_('%d files have <b>merge conflicts</b> '
                                        'that must be <a href="resolve">'
                                        '<b>resolved</b></a>') % count)
            else:
                # else give a calmer indication of conflicts
                self.reslabel.setText(_('%d files were modified on both '
                                        'branches and must be <a href="resolve">'
                                        '<b>resolved</b></a>') % count)
            return False
        else:
            self.reslabel.setText(_('No merge conflicts, ready to commit'))
        return True

    def tryAutoAdvance(self, checked):
        if checked and self.isComplete():
            self.wizard().next()

    def cleanupPage(self):
        QSettings().setValue('merge/autoadvance', self.autonext.isChecked())

    def onCommandFinished(self, ret):
        self.repo.decrementBusyCount()
        if ret in (0, 1):
            self.mergecomplete = True
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

        self.setTitle(_('Commit merge results'))
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
        mergeCsInfo = csinfo.create(repo, None, style, custom=custom,
                                    withupdate=True)
        mergeCsInfo.linkActivated.connect(self.onLinkActivated)
        self.layout().addWidget(mergeCsInfo)

        # commit message area
        msg_sep = qtlib.LabeledSeparator(_('Commit message'))
        self.layout().addWidget(msg_sep)
        msgEntry = messageentry.MessageEntry(self)
        msgEntry.installEventFilter(qscilib.KeyPressInterceptor(self))
        msgEntry.refresh(repo)
        msgEntry.loadSettings(QSettings(), 'merge/message')

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
        checked = QSettings().value('merge/skiplast', False).toBool()
        self.skiplast.setChecked(checked)
        self.layout().addWidget(self.skiplast)

    def refresh(self):
        pass

    def cleanupPage(self):
        s = QSettings()
        s.setValue('merge/skiplast', self.skiplast.isChecked())
        self.msgEntry.saveSettings(s, 'merge/message')

    def currentPage(self):
        engmsg = self.repo.ui.configbool('tortoisehg', 'engmsg', False)
        wctx = self.repo[None]
        if wctx.p1().branch() == wctx.p2().branch():
            msgset = i18n.keepgettext()._('Merge')
            text = engmsg and msgset['id'] or msgset['str']
            text = unicode(text)
        else:
            msgset = i18n.keepgettext()._('Merge with %s')
            text = engmsg and msgset['id'] or msgset['str']
            text = unicode(text) % hglib.tounicode(wctx.p2().branch())
        self.msgEntry.setText(text)
        self.msgEntry.moveCursorToEnd()

    @pyqtSlot(QString)
    def onLinkActivated(self, cmd):
        if cmd == 'view':
            dlg = status.StatusDialog(self.repo, [], {}, self)
            dlg.exec_()
            self.refresh()

    def isComplete(self):
        return len(self.repo.parents()) == 2 and len(self.msgEntry.text()) > 0

    def validatePage(self):
        if len(self.repo.parents()) == 1:
            # commit succeeded, repositoryChanged() called wizard().next()
            if self.skiplast.isChecked():
                self.wizard().close()
            return True
        if self.cmd.core.running():
            return False

        user = qtlib.getCurrentUsername(self, self.repo)
        if not user:
            return False

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

    def repositoryChanged(self):
        'repository has detected a change to changelog or parents'
        if len(self.repo.parents()) == 1:
            self.wizard().next()

    def onCommandFinished(self, ret):
        self.repo.decrementBusyCount()
        self.completeChanged.emit()


class ResultPage(BasePage):
    def __init__(self, repo, parent):
        super(ResultPage, self).__init__(repo, parent)
        self.setTitle(_('Finished'))
        self.setSubTitle(' ')
        self.setFinalPage(True)

        self.setLayout(QVBoxLayout())
        merge_sep = qtlib.LabeledSeparator(_('Merge changeset'))
        self.layout().addWidget(merge_sep)
        mergeCsInfo = csinfo.create(self.repo, 'tip', withupdate=True)
        self.layout().addWidget(mergeCsInfo)
        self.mergeCsInfo = mergeCsInfo
        self.layout().addStretch(1)

    def currentPage(self):
        self.mergeCsInfo.update(self.repo['tip'])
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
    rev = opts.get('rev') or None
    if not rev and len(pats):
        rev = pats[0]
    if not rev:
        import sys
        qtlib.InfoMsgBox(_('Unable to merge'),
                         _('Merge revision not specified or not found'))
        sys.exit()
    repo = thgrepo.repository(ui, path=paths.find_root())
    return MergeDialog(rev, repo, None)
