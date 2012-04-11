# commit.py - TortoiseHg's commit widget and standalone dialog
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from mercurial import ui, util, error

from tortoisehg.util import hglib, shlib, wconfig, bugtraq

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt.messageentry import MessageEntry
from tortoisehg.hgqt import qtlib, qscilib, status, cmdui, branchop, revpanel
from tortoisehg.hgqt import hgrcutil, mq

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.Qsci import QsciAPIs


# Technical Debt for CommitWidget
#  disable commit button while no message is entered or no files are selected
#  qtlib decode failure dialog (ask for retry locale, suggest HGENCODING)
#  spell check / tab completion
#  in-memory patching / committing chunk selected files

class CommitWidget(QWidget, qtlib.TaskWidget):
    'A widget that encompasses a StatusWidget and commit extras'
    commitButtonEnable = pyqtSignal(bool)
    mqButtonEnable = pyqtSignal(bool)
    linkActivated = pyqtSignal(QString)
    showMessage = pyqtSignal(unicode)
    commitComplete = pyqtSignal()

    progress = pyqtSignal(QString, object, QString, QString, object)
    output = pyqtSignal(QString, QString)
    makeLogVisible = pyqtSignal(bool)
    beginSuppressPrompt = pyqtSignal()
    endSuppressPrompt = pyqtSignal()

    def __init__(self, repo, pats, opts, embedded=False, parent=None, rev=None):
        QWidget.__init__(self, parent=parent)

        repo.configChanged.connect(self.configChanged)
        repo.repositoryChanged.connect(self.repositoryChanged)
        repo.workingBranchChanged.connect(self.workingBranchChanged)
        self.repo = repo
        self._rev = rev
        self.lastAction = None
        self.lastCommitMsg = ''
        self.currentAction = None
        self.currentProgress = None

        opts['ciexclude'] = repo.ui.config('tortoisehg', 'ciexclude', '')
        opts['pushafter'] = repo.ui.config('tortoisehg', 'cipushafter', '')
        opts['autoinc'] = repo.ui.config('tortoisehg', 'autoinc', '')
        opts['bugtraqplugin'] = repo.ui.config('tortoisehg', 'issue.bugtraqplugin', None)
        opts['bugtraqparameters'] = repo.ui.config('tortoisehg', 'issue.bugtraqparameters', None)
        self.opts = opts # user, date

        self.stwidget = status.StatusWidget(repo, pats, opts, self)
        self.stwidget.showMessage.connect(self.showMessage)
        self.stwidget.progress.connect(self.progress)
        self.stwidget.linkActivated.connect(self.linkActivated)
        self.stwidget.fileDisplayed.connect(self.fileDisplayed)
        self.msghistory = []
        self.runner = cmdui.Runner(not embedded, self)
        self.runner.setTitle(_('Commit', 'window title'))
        self.runner.output.connect(self.output)
        self.runner.progress.connect(self.progress)
        self.runner.makeLogVisible.connect(self.makeLogVisible)
        self.runner.commandStarted.connect(self.beginSuppressPrompt)
        self.runner.commandFinished.connect(self.endSuppressPrompt)
        self.runner.commandFinished.connect(self.commandFinished)

        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        layout.addWidget(self.stwidget)
        self.setLayout(layout)

        vbox = QVBoxLayout()
        vbox.setMargin(0)
        vbox.setSpacing(0)
        vbox.setContentsMargins(*(0,)*4)

        hbox = QHBoxLayout()
        hbox.setMargin(0)
        hbox.setContentsMargins(*(0,)*4)
        tbar = QToolBar(_("Commit Dialog Toolbar"), self)
        tbar.setStyleSheet(qtlib.tbstylesheet)
        hbox.addWidget(tbar)

        self.branchbutton = tbar.addAction(_('Branch: '))
        font = self.branchbutton.font()
        font.setBold(True)
        self.branchbutton.setFont(font)
        self.branchbutton.triggered.connect(self.branchOp)
        self.branchop = None

        self.recentMessagesButton = QToolButton(
            text=_('Copy message'),
            popupMode=QToolButton.MenuButtonPopup,
            toolTip=_('Copy one of the recent commit messages'))
        self.recentMessagesButton.clicked.connect(self.recentMessagesButton.showMenu)
        tbar.addWidget(self.recentMessagesButton)
        self.updateRecentMessages()

        tbar.addAction(_('Options')).triggered.connect(self.details)
        tbar.setIconSize(QSize(16,16))

        if self.opts['bugtraqplugin'] != None:
            self.bugtraq = self.createBugTracker()
            try:
                parameters = self.opts['bugtraqparameters']
                linktext = self.bugtraq.get_link_text(parameters)
            except Exception, e:
                tracker = self.opts['bugtraqplugin'].split(' ', 1)[1]
                qtlib.ErrorMsgBox(_('Issue Tracker'),
                                  _('Failed to load issue tracker \'%s\': %s'
                                    % (tracker, e)),
                                  parent=self)
                self.bugtraq = None
            else:
                # connect UI because we have a valid bug tracker
                self.commitComplete.connect(self.bugTrackerPostCommit)
                tbar.addAction(linktext).triggered.connect(
                    self.getBugTrackerCommitMessage)

        self.stopAction = tbar.addAction(_('Stop'))
        self.stopAction.triggered.connect(self.stop)
        self.stopAction.setIcon(qtlib.geticon('process-stop'))
        self.stopAction.setEnabled(False)

        hbox.addStretch(1)

        vbox.addLayout(hbox, 0)
        self.buttonHBox = hbox

        if embedded and 'mq' in self.repo.extensions():
            self.hasmqbutton = True
            pnhbox = QHBoxLayout()
            self.pnlabel = QLabel()
            pnhbox.addWidget(self.pnlabel)
            self.pnedit = mq.getPatchNameLineEdit()
            self.pnedit.setMaximumWidth(250)
            pnhbox.addWidget(self.pnedit)
            pnhbox.addStretch()
            vbox.addLayout(pnhbox)
        else:
            self.hasmqbutton = False

        self.pcsinfo = revpanel.ParentWidget(repo)
        vbox.addWidget(self.pcsinfo, 0)

        msgte = MessageEntry(self, self.stwidget.getChecked)
        msgte.installEventFilter(qscilib.KeyPressInterceptor(self))
        vbox.addWidget(msgte, 1)
        upperframe = QFrame()

        SP = QSizePolicy
        sp = SP(SP.Expanding, SP.Expanding)
        sp.setHorizontalStretch(1)
        upperframe.setSizePolicy(sp)
        upperframe.setLayout(vbox)

        self.split = QSplitter(Qt.Vertical)
        sp = SP(SP.Expanding, SP.Expanding)
        sp.setHorizontalStretch(1)
        sp.setVerticalStretch(0)
        self.split.setSizePolicy(sp)
        # Add our widgets to the top of our splitter
        self.split.addWidget(upperframe)
        self.split.setCollapsible(0, False)
        # Add status widget document frame below our splitter
        # this reparents the docf from the status splitter
        self.split.addWidget(self.stwidget.docf)

        # add our splitter where the docf used to be
        self.stwidget.split.addWidget(self.split)
        self.msgte = msgte
        if not self.hasmqbutton:
            QShortcut(QKeySequence('Ctrl+Return'), self,
                      self.commit).setContext(Qt.WidgetWithChildrenShortcut)
            QShortcut(QKeySequence('Ctrl+Enter'), self,
                      self.commit).setContext(Qt.WidgetWithChildrenShortcut)

    @property
    def rev(self):
        """Return current revision"""
        return self._rev

    def selectRev(self, rev):
        """
        Select the revision that must be set when the dialog is shown again
        """
        self._rev = rev

    @pyqtSlot(int)
    @pyqtSlot(object)
    def setRev(self, rev):
        """Change revision to show"""
        self.selectRev(rev)
        if self.hasmqbutton:
            preferredActionName = self._getPreferredActionName()
            curractionName = self.mqgroup.checkedAction()._name
            if curractionName != preferredActionName:
                self.mqSetAction(refresh=True,
                    actionName=preferredActionName)

    def _getPreferredActionName(self):
        """Select the preferred action, depending on the selected revision"""
        if not self.hasmqbutton:
            return 'commit'
        else:
            pctx = self.repo.changectx('.')
            ispatch = 'qtip' in pctx.tags()
            if not ispatch:
                # Set the button to Commit
                return 'commit'
            elif self.rev is None:
                # Set the button to QNew
                return 'qnew'
            else:
                # Set the button to QRefresh
                return 'qref'

    def mqSetupButton(self):
        ispatch = lambda r: 'qtip' in r.changectx('.').tags()
        notpatch = lambda r: 'qtip' not in r.changectx('.').tags()
        acts = (
            ('commit', _('Commit changes'), _('Commit'), notpatch),
            ('qnew', _('Create a new patch'), _('QNew'), None),
            ('qref', _('Refresh current patch'), _('QRefresh'), ispatch),
        )

        class MQToolButton(QToolButton):
            def styleOption(self):
                opt = QStyleOptionToolButton()
                opt.initFrom(self)
                return opt
            def menuButtonWidth(self):
                style = self.style()
                opt = self.styleOption()
                opt.features = QStyleOptionToolButton.MenuButtonPopup
                rect = style.subControlRect(QStyle.CC_ToolButton, opt,
                                            QStyle.SC_ToolButtonMenu, self)
                return rect.width()
            def setBold(self):
                f = self.font()
                f.setWeight(QFont.Bold)
                self.setFont(f)
            def sizeHint(self):
                # Set the desired width to keep the button from resizing
                return QSize(self._width, QToolButton.sizeHint(self).height())

        self.mqtb = mqtb = MQToolButton(self)
        mqtb.setBold()
        mqtb.setPopupMode(QToolButton.MenuButtonPopup)
        fmk = lambda s: mqtb.fontMetrics().width(hglib.tounicode(s[2]))
        mqtb._width = max(map(fmk, acts)) + 4*mqtb.menuButtonWidth()

        class MQMenu(QMenu):
            def __init__(self, parent, repo):
                self.repo = repo
                return QMenu.__init__(self, parent)
            def getActionByName(self, act):
                return [a for a in self.actions() if a._name == act][0]
            def showEvent(self, event):
                for a in self.actions():
                    if a._enablefunc:
                        a.setEnabled(a._enablefunc(self.repo))
                return QMenu.showEvent(self, event)
        self.mqgroup = QActionGroup(self)
        mqmenu = MQMenu(mqtb, self.repo)
        menurefresh = lambda: self.mqSetAction(refresh=True)
        for a in acts:
            action = QAction(a[1], self.mqgroup)
            action._name = a[0]
            action._text = a[2]
            action._enablefunc = a[3]
            action.triggered.connect(menurefresh)
            action.setCheckable(True)
            mqmenu.addAction(action)
        mqtb.setMenu(mqmenu)
        mqtb.clicked.connect(self.mqPerformAction)
        self.mqButtonEnable.connect(mqtb.setEnabled)
        self.mqSetAction(actionName=self._getPreferredActionName())
        sc = QShortcut(QKeySequence('Ctrl+Return'), self, self.mqPerformAction)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc = QShortcut(QKeySequence('Ctrl+Enter'), self, self.mqPerformAction)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        return mqtb

    @pyqtSlot(bool)
    def mqSetAction(self, refresh=False, actionName=None):
        if actionName:
            selectedAction = \
                [act for act in self.mqgroup.actions() \
                    if act._name == actionName][0]
            selectedAction.setChecked(True)
        curraction = self.mqgroup.checkedAction()
        oldpctx = self.stwidget.pctx
        pctx = self.repo.changectx('.')
        if curraction._name == 'qnew':
            self.pnlabel.setVisible(True)
            self.pnedit.setVisible(True)
            self.pnedit.setFocus()
            self.pnedit.setText(mq.defaultNewPatchName(self.repo))
            self.pnedit.selectAll()
            self.stwidget.setPatchContext(None)
            refreshwctx = refresh and oldpctx is not None
        else:
            self.pnlabel.setVisible(False)
            self.pnedit.setVisible(False)
            ispatch = 'qtip' in pctx.tags()
            def switchAction(action, name):
                action.setChecked(False)
                action = self.mqtb.menu().getActionByName(name)
                action.setChecked(True)
                return action
            if curraction._name == 'qref' and not ispatch:
                curraction = switchAction(curraction, 'commit')
            elif curraction._name == 'commit' and ispatch:
                curraction = switchAction(curraction, 'qref')
            if curraction._name == 'qref':
                refreshwctx = refresh
                self.stwidget.setPatchContext(pctx)
            elif curraction._name == 'commit':
                refreshwctx = refresh and oldpctx is not None
                self.stwidget.setPatchContext(None)
        if curraction._name == 'qref':
            if self.lastAction != 'qref':
                self.lastCommitMsg = self.msgte.text()
            self.setMessage(hglib.tounicode(pctx.description()))
        else:
            if self.lastAction == 'qref':
                self.setMessage(self.lastCommitMsg)
        if refreshwctx:
            self.stwidget.refreshWctx()
        self.mqtb.setText(curraction._text)
        self.lastAction = curraction._name

    def getBranchCommandLine(self, branchName, repo):
        '''
        Create the command line to change or create the selected branch unless
        it is the selected branch

        Verify whether a branch exists on a repo. If it doesn't ask the user
        to confirm that it wants to create the branch. If it does and it is not
        the current branch as the user whether it wants to change to that branch.
        Depending on the user input, create the command line which will perform
        the selected action
        '''
        # This function is used both by commit() and mqPerformAction()
        commandlines = []
        newbranch = False
        branch = hglib.fromunicode(self.branchop)
        if branch in repo.branchtags():
            # response: 0=Yes, 1=No, 2=Cancel
            if branch in [p.branch() for p in repo.parents()]:
                resp = 0
            else:
                rev = repo[branch].rev()
                resp = qtlib.CustomPrompt(_('Confirm Branch Change'),
                    _('Named branch "%s" already exists, '
                      'last used in revision %d\n'
                      ) % (self.branchop, rev),
                    self,
                    (_('Restart &Branch'),
                     _('&Commit to current branch'),
                     _('Cancel')), 2, 2).run()
        else:
            resp = qtlib.CustomPrompt(_('Confirm New Branch'),
                _('Create new named branch "%s" with this commit?\n'
                  ) % self.branchop,
                self,
                (_('Create &Branch'),
                 _('&Commit to current branch'),
                 _('Cancel')), 2, 2).run()
        if resp == 0:
            newbranch = True
            commandlines.append(['branch', '--repository', repo.root,
                                 '--force', branch])
        elif resp == 2:
            return None, False
        return commandlines, newbranch

    @pyqtSlot()
    def mqPerformAction(self):
        curraction = self.mqgroup.checkedAction()
        if curraction._name == 'commit':
            return self.commit()

        # Check if we need to change branch first
        commandlines = []
        if self.branchop:
            commandlines, newbranch = self.getBranchCommandLine(self.branchop,
                                                                self.repo)
            if commandlines is None:
                return
        olist = ('user', 'date')
        cmdlines = commandlines + mq.mqNewRefreshCommand(self.repo,
                                          curraction._name == 'qnew',
                                          self.stwidget, self.pnedit,
                                          self.msgte.text(), self.opts, olist)
        self.repo.incrementBusyCount()
        self.currentAction = curraction._name
        self.currentProgress = _('MQ Action', 'start progress')
        self.progress.emit(*cmdui.startProgress(self.currentProgress, ''))
        self.commitButtonEnable.emit(False)
        self.mqButtonEnable.emit(False)
        self.runner.run(*cmdlines)

    @pyqtSlot(QString, QString)
    def fileDisplayed(self, wfile, contents):
        'Status widget is displaying a new file'
        if not (wfile and contents):
            return
        wfile = unicode(wfile)
        self._apis = QsciAPIs(self.msgte.lexer())
        tokens = set()
        for e in self.stwidget.getChecked():
            e = hglib.tounicode(e)
            tokens.add(e)
            tokens.add(os.path.basename(e))
        tokens.add(wfile)
        tokens.add(os.path.basename(wfile))
        try:
            from pygments.lexers import guess_lexer_for_filename
            from pygments.token import Token
            from pygments.util import ClassNotFound
            try:
                contents = unicode(contents)
                lexer = guess_lexer_for_filename(wfile, contents)
                for tokentype, value in lexer.get_tokens(contents):
                    if tokentype in Token.Name and len(value) > 4:
                        tokens.add(value)
            except ClassNotFound, TypeError:
                pass
        except ImportError:
            pass
        for n in sorted(list(tokens)):
            self._apis.add(n)
        self._apis.apiPreparationFinished.connect(self.apiPrepFinished)
        self._apis.prepare()

    def apiPrepFinished(self):
        'QsciAPIs has finished parsing displayed file'
        self.msgte.lexer().setAPIs(self._apis)

    def bugTrackerPostCommit(self):
        # commit already happened, get last message in history
        message = self.lastmessage
        error = self.bugtraq.on_commit_finished(message)
        if error != None and len(error) > 0:
            qtlib.ErrorMsgBox(_('Issue Tracker'), error, parent=self)
        # recreate bug tracker to get new COM object for next commit
        self.bugtraq = self.createBugTracker()

    def createBugTracker(self):
        bugtraqid = self.opts['bugtraqplugin'].split(' ', 1)[0]
        result = bugtraq.BugTraq(bugtraqid)
        return result

    def getBugTrackerCommitMessage(self):
        parameters = self.opts['bugtraqparameters']
        message = self.getMessage()
        newMessage = self.bugtraq.get_commit_message(parameters, message)
        self.setMessage(newMessage)

    def details(self):
        dlg = DetailsDialog(self.opts, self.userhist, self)
        dlg.finished.connect(dlg.deleteLater)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        if dlg.exec_() == QDialog.Accepted:
            self.opts.update(dlg.outopts)
            self.refresh()

    def workingBranchChanged(self):
        'Repository has detected a change in .hg/branch'
        self.refresh()

    def repositoryChanged(self):
        'Repository has detected a changelog / dirstate change'
        self.refresh()
        self.stwidget.refreshWctx() # Trigger reload of working context

    def configChanged(self):
        'Repository is reporting its config files have changed'
        self.refresh()

    @pyqtSlot()
    def reload(self):
        'User has requested a reload'
        self.repo.thginvalidate()
        self.refresh()
        self.stwidget.refreshWctx() # Trigger reload of working context

    def refresh(self):
        ispatch = self.repo.changectx('.').thgmqappliedpatch()
        self.commitButtonEnable.emit(not ispatch)
        self.msgte.refresh(self.repo)

        # Update branch operation button
        branchu = hglib.tounicode(self.repo[None].branch())
        if self.branchop is None:
            title = _('Branch: ') + branchu
        elif self.branchop == False:
            title = _('Close Branch: ') + branchu
        else:
            title = _('New Branch: ') + self.branchop
        self.branchbutton.setText(title)

        # Update parent csinfo widget
        self.pcsinfo.set_revision(None)
        self.pcsinfo.update()

        # This is ugly, but want pnlabel to have the same alignment/style/etc
        # as pcsinfo, so extract the needed parts of pcsinfo's markup.  Would
        # be nicer if csinfo exposed this information, or if csinfo could hold
        # widgets like pnlabel.
        if self.hasmqbutton:
            parent = hglib.fromunicode(_('Parent:'))
            patchname = hglib.fromunicode(_('Patch name:'))
            text = hglib.fromunicode(self.pcsinfo.revlabel.text())
            cellend = '</td>'
            firstidx = text.find(cellend) + len(cellend)
            secondidx = text[firstidx:].rfind('</tr>')
            if firstidx >= 0 and secondidx >= 0:
                start = text[0:firstidx].replace(parent, patchname)
                self.pnlabel.setText(start + text[firstidx+secondidx:])
            else:
                self.pnlabel.setText(patchname)
            self.mqSetAction()

    def branchOp(self):
        d = branchop.BranchOpDialog(self.repo, self.branchop, self)
        d.setWindowFlags(Qt.Sheet)
        d.setWindowModality(Qt.WindowModal)
        if d.exec_() == QDialog.Accepted:
            self.branchop = d.branchop
            self.refresh()

    def canUndo(self):
        'Returns undo description or None if not valid'
        if os.path.exists(self.repo.sjoin('undo')):
            try:
                args = self.repo.opener('undo.desc', 'r').read().splitlines()
                if args[1] != 'commit':
                    return None
                return _('Rollback commit to revision %d') % (int(args[0]) - 1)
            except (IOError, IndexError, ValueError):
                pass
        return None

    def rollback(self):
        msg = self.canUndo()
        if not msg:
            return
        d = QMessageBox.question(self, _('Confirm Undo'), msg,
                                 QMessageBox.Ok | QMessageBox.Cancel)
        if d != QMessageBox.Ok:
            return
        self.repo.incrementBusyCount()
        self.repo.rollback()
        self.repo.decrementBusyCount()
        self.reload()
        QTimer.singleShot(500, lambda: shlib.shell_notify([self.repo.root]))

    def updateRecentMessages(self):
        # Define a menu that lists recent messages
        m = QMenu()
        for s in self.msghistory:
            title = s.split('\n', 1)[0][:70]
            def overwriteMsg(newMsg): return lambda: self.msgSelected(newMsg)
            m.addAction(title).triggered.connect(overwriteMsg(s))
        self.recentMessagesButton.setMenu(m)

    def getMessage(self):
        text = self.msgte.text()
        try:
            text = hglib.fromunicode(text, 'strict')
        except UnicodeEncodeError:
            pass # TODO
        return text

    def msgSelected(self, message):
        if self.msgte.text() and self.msgte.isModified():
            d = QMessageBox.question(self, _('Confirm Discard Message'),
                        _('Discard current commit message?'),
                        QMessageBox.Ok | QMessageBox.Cancel)
            if d != QMessageBox.Ok:
                return
        self.setMessage(message)
        self.msgte.setFocus()

    def setMessage(self, msg):
        self.msgte.setText(msg)
        self.msgte.moveCursorToEnd()
        self.msgte.setModified(False)

    def canExit(self):
        if not self.stwidget.canExit():
            return False
        return not self.runner.core.running()

    def loadSettings(self, s, prefix):
        'Load history, etc, from QSettings instance'
        repoid = str(self.repo[0])
        lpref = prefix + '/commit/' # local settings (splitter, etc)
        gpref = 'commit/'           # global settings (history, etc)
        # message history is stored in unicode
        self.split.restoreState(s.value(lpref+'split').toByteArray())
        self.msgte.loadSettings(s, lpref+'msgte')
        self.stwidget.loadSettings(s, lpref+'status')
        self.msghistory = list(s.value(gpref+'history-'+repoid).toStringList())
        self.msghistory = [unicode(m) for m in self.msghistory if m]
        self.updateRecentMessages()
        self.userhist = s.value(gpref+'userhist').toStringList()
        self.userhist = [u for u in self.userhist if u]
        try:
            curmsg = self.repo.opener('cur-message.txt').read()
            self.setMessage(hglib.tounicode(curmsg))
        except EnvironmentError:
            pass
        try:
            curmsg = self.repo.opener('last-message.txt').read()
            if curmsg:
                self.addMessageToHistory(hglib.tounicode(curmsg))
        except EnvironmentError:
            pass

    def saveSettings(self, s, prefix):
        'Save history, etc, in QSettings instance'
        repoid = str(self.repo[0])
        lpref = prefix + '/commit/'
        gpref = 'commit/'
        s.setValue(lpref+'split', self.split.saveState())
        self.msgte.saveSettings(s, lpref+'msgte')
        self.stwidget.saveSettings(s, lpref+'status')
        s.setValue(gpref+'history-'+repoid, self.msghistory)
        s.setValue(gpref+'userhist', self.userhist)
        try:
            msg = self.getMessage()
            self.repo.opener('cur-message.txt', 'w').write(msg)
        except EnvironmentError:
            pass

    def addMessageToHistory(self, umsg):
        umsg = unicode(umsg)
        if umsg in self.msghistory:
            self.msghistory.remove(umsg)
        self.msghistory.insert(0, umsg)
        self.msghistory = self.msghistory[:10]
        self.updateRecentMessages()

    def addUsernameToHistory(self, user):
        user = hglib.tounicode(user)
        if user in self.userhist:
            self.userhist.remove(user)
        self.userhist.insert(0, user)
        self.userhist = self.userhist[:10]

    def commit(self):
        repo = self.repo
        msg = self.getMessage()
        if not msg:
            qtlib.WarningMsgBox(_('Nothing Commited'),
                                _('Please enter commit message'),
                                parent=self)
            self.msgte.setFocus()
            return

        commandlines = []

        brcmd = []
        newbranch = False
        if self.branchop is None:
            newbranch = repo[None].branch() != repo['.'].branch()
        elif self.branchop == False:
            brcmd = ['--close-branch']
        else:
            commandlines, newbranch = self.getBranchCommandLine(self.branchop,
                                                                self.repo)
            if commandlines is None:
                return
        self.files = self.stwidget.getChecked('MAR?!S')
        if not (self.files or brcmd or newbranch):
            qtlib.WarningMsgBox(_('No files checked'),
                                _('No modified files checkmarked for commit'),
                                parent=self)
            self.stwidget.tv.setFocus()
            return
        if len(repo.parents()) > 1:
            self.files = []

        user = qtlib.getCurrentUsername(self, self.repo, self.opts)
        if not user:
            return
        self.addUsernameToHistory(user)

        checkedUnknowns = self.stwidget.getChecked('?I')
        if checkedUnknowns:
            res = qtlib.CustomPrompt(
                    _('Confirm Add'),
                    _('Add selected untracked files?'), self,
                    (_('&Add'), _('Cancel')), 0, 1,
                    checkedUnknowns).run()
            if res == 0:
                cmd = ['add', '--repository', repo.root] + \
                      [repo.wjoin(f) for f in checkedUnknowns]
                commandlines.append(cmd)
            else:
                return
        checkedMissing = self.stwidget.getChecked('!')
        if checkedMissing:
            res = qtlib.CustomPrompt(
                    _('Confirm Remove'),
                    _('Remove selected deleted files?'), self,
                    (_('&Remove'), _('Cancel')), 0, 1,
                    checkedMissing).run()
            if res == 0:
                cmd = ['remove', '--repository', repo.root] + \
                      [repo.wjoin(f) for f in checkedMissing]
                commandlines.append(cmd)
            else:
                return
        try:
            date = self.opts.get('date')
            if date:
                util.parsedate(date)
                dcmd = ['--date', date]
            else:
                dcmd = []
        except error.Abort, e:
            if e.hint:
                err = _('%s (hint: %s)') % (hglib.tounicode(str(e)),
                                            hglib.tounicode(e.hint))
            else:
                err = hglib.tounicode(str(e))
            self.showMessage.emit(err)
            dcmd = []
        cmdline = ['commit', '--repository', repo.root, '--verbose',
                   '--user', user, '--message='+msg]
        cmdline += dcmd + brcmd + [repo.wjoin(f) for f in self.files]
        if len(repo.parents()) == 1:
            for fname in self.opts.get('autoinc', '').split(','):
                fname = fname.strip()
                if fname:
                    cmdline.extend(['--include', fname])

        commandlines.append(cmdline)

        if self.opts.get('pushafter'):
            cmd = ['push', '--repository', repo.root, self.opts['pushafter']]
            commandlines.append(cmd)

        repo.incrementBusyCount()
        self.currentAction = 'commit'
        self.currentProgress = _('Commit', 'start progress')
        self.progress.emit(*cmdui.startProgress(self.currentProgress, ''))
        self.commitButtonEnable.emit(False)
        self.mqButtonEnable.emit(False)
        self.runner.run(*commandlines)
        self.stopAction.setEnabled(True)

    def stop(self):
        self.runner.cancel()

    def commandFinished(self, ret):
        self.progress.emit(*cmdui.stopProgress(self.currentProgress))
        self.stopAction.setEnabled(False)
        self.commitButtonEnable.emit(True)
        self.mqButtonEnable.emit(True)
        self.repo.decrementBusyCount()
        if ret == 0:
            self.branchop = None
            umsg = self.msgte.text()
            if self.currentAction != 'qref':
                self.lastCommitMsg = ''
                if self.currentAction == 'commit':
                    # capture last message for BugTraq plugin
                    self.lastmessage = self.getMessage()
                if umsg:
                    self.addMessageToHistory(umsg)
                self.setMessage('')
                if self.currentAction == 'commit':
                    shlib.shell_notify(self.files)
                    self.commitComplete.emit()

class DetailsDialog(QDialog):
    'Utility dialog for configuring uncommon settings'
    def __init__(self, opts, userhistory, parent):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('%s - commit options') % parent.repo.displayname)
        self.repo = parent.repo

        layout = QVBoxLayout()
        self.setLayout(layout)

        hbox = QHBoxLayout()
        self.usercb = QCheckBox(_('Set username:'))

        usercombo = QComboBox()
        usercombo.setEditable(True)
        usercombo.setEnabled(False)
        SP = QSizePolicy
        usercombo.setSizePolicy(SP(SP.Expanding, SP.Minimum))
        self.usercb.toggled.connect(usercombo.setEnabled)
        self.usercb.toggled.connect(lambda s: s and usercombo.setFocus())

        l = []
        if opts.get('user'):
            val = hglib.tounicode(opts['user'])
            self.usercb.setChecked(True)
            l.append(val)
        try:
            val = hglib.tounicode(self.repo.ui.username())
            l.append(val)
        except util.Abort:
            pass
        for name in userhistory:
            if name not in l:
                l.append(name)
        for name in l:
            usercombo.addItem(name)
        self.usercombo = usercombo

        usersaverepo = QPushButton(_('Save in Repo'))
        usersaverepo.clicked.connect(self.saveInRepo)
        usersaverepo.setEnabled(False)
        self.usercb.toggled.connect(usersaverepo.setEnabled)

        usersaveglobal = QPushButton(_('Save Global'))
        usersaveglobal.clicked.connect(self.saveGlobal)
        usersaveglobal.setEnabled(False)
        self.usercb.toggled.connect(usersaveglobal.setEnabled)

        hbox.addWidget(self.usercb)
        hbox.addWidget(self.usercombo)
        hbox.addWidget(usersaverepo)
        hbox.addWidget(usersaveglobal)
        layout.addLayout(hbox)

        hbox = QHBoxLayout()
        self.datecb = QCheckBox(_('Set Date:'))
        self.datele = QLineEdit()
        self.datele.setEnabled(False)
        self.datecb.toggled.connect(self.datele.setEnabled)
        curdate = QPushButton(_('Update'))
        curdate.setEnabled(False)
        self.datecb.toggled.connect(curdate.setEnabled)
        self.datecb.toggled.connect(lambda s: s and curdate.setFocus())
        curdate.clicked.connect( lambda: self.datele.setText(
                hglib.tounicode(hglib.displaytime(util.makedate()))))
        if opts.get('date'):
            self.datele.setText(opts['date'])
            self.datecb.setChecked(True)
        else:
            self.datecb.setChecked(False)
            curdate.clicked.emit(True)

        hbox.addWidget(self.datecb)
        hbox.addWidget(self.datele)
        hbox.addWidget(curdate)
        layout.addLayout(hbox)

        hbox = QHBoxLayout()
        self.pushaftercb = QCheckBox(_('Push After Commit:'))
        self.pushafterle = QLineEdit()
        self.pushafterle.setEnabled(False)
        self.pushaftercb.toggled.connect(self.pushafterle.setEnabled)
        self.pushaftercb.toggled.connect(lambda s:
                s and self.pushafterle.setFocus())

        pushaftersave = QPushButton(_('Save in Repo'))
        pushaftersave.clicked.connect(self.savePushAfter)
        pushaftersave.setEnabled(False)
        self.pushaftercb.toggled.connect(pushaftersave.setEnabled)

        if opts.get('pushafter'):
            val = hglib.tounicode(opts['pushafter'])
            self.pushafterle.setText(val)
            self.pushaftercb.setChecked(True)

        hbox.addWidget(self.pushaftercb)
        hbox.addWidget(self.pushafterle)
        hbox.addWidget(pushaftersave)
        layout.addLayout(hbox)

        hbox = QHBoxLayout()
        self.autoinccb = QCheckBox(_('Auto Includes:'))
        self.autoincle = QLineEdit()
        self.autoincle.setEnabled(False)
        self.autoinccb.toggled.connect(self.autoincle.setEnabled)
        self.autoinccb.toggled.connect(lambda s:
                s and self.autoincle.setFocus())

        autoincsave = QPushButton(_('Save in Repo'))
        autoincsave.clicked.connect(self.saveAutoInc)
        autoincsave.setEnabled(False)
        self.autoinccb.toggled.connect(autoincsave.setEnabled)

        if opts.get('autoinc'):
            val = hglib.tounicode(opts['autoinc'])
            self.autoincle.setText(val)
            self.autoinccb.setChecked(True)

        hbox.addWidget(self.autoinccb)
        hbox.addWidget(self.autoincle)
        hbox.addWidget(autoincsave)
        layout.addLayout(hbox)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.bb = bb
        layout.addWidget(bb)

    def saveInRepo(self):
        fn = os.path.join(self.repo.root, '.hg', 'hgrc')
        self.saveToPath([fn])

    def saveGlobal(self):
        self.saveToPath(hglib.user_rcpath())

    def saveToPath(self, path):
        fn, cfg = hgrcutil.loadIniFile(path, self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to save username'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return
        try:
            user = hglib.fromunicode(self.usercombo.currentText())
            if user:
                cfg.set('ui', 'username', user)
            else:
                try:
                    del cfg['ui']['username']
                except KeyError:
                    pass
            wconfig.writefile(cfg, fn)
        except IOError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(e), parent=self)

    def savePushAfter(self):
        path = os.path.join(self.repo.root, '.hg', 'hgrc')
        fn, cfg = hgrcutil.loadIniFile([path], self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to save after commit push'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return
        try:
            remote = hglib.fromunicode(self.pushafterle.text())
            if remote:
                cfg.set('tortoisehg', 'cipushafter', remote)
            else:
                try:
                    del cfg['tortoisehg']['cipushafter']
                except KeyError:
                    pass
            wconfig.writefile(cfg, fn)
        except IOError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(e), parent=self)

    def saveAutoInc(self):
        path = os.path.join(self.repo.root, '.hg', 'hgrc')
        fn, cfg = hgrcutil.loadIniFile([path], self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to save auto include list'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return
        try:
            list = hglib.fromunicode(self.autoincle.text())
            if list:
                cfg.set('tortoisehg', 'autoinc', list)
            else:
                try:
                    del cfg['tortoisehg']['autoinc']
                except KeyError:
                    pass
            wconfig.writefile(cfg, fn)
        except IOError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(e), parent=self)

    def accept(self):
        outopts = {}
        if self.datecb.isChecked():
            date = hglib.fromunicode(self.datele.text())
            try:
                util.parsedate(date)
            except error.Abort, e:
                if e.hint:
                    err = _('%s (hint: %s)') % (hglib.tounicode(str(e)),
                                                hglib.tounicode(e.hint))
                else:
                    err = hglib.tounicode(str(e))
                qtlib.WarningMsgBox(_('Invalid date format'), err, parent=self)
                return
            outopts['date'] = date
        else:
            outopts['date'] = ''

        if self.usercb.isChecked():
            user = hglib.fromunicode(self.usercombo.currentText())
        else:
            user = ''
        outopts['user'] = user
        if not user:
            try:
                self.repo.ui.username()
            except util.Abort, e:
                if e.hint:
                    err = _('%s (hint: %s)') % (hglib.tounicode(str(e)),
                                                hglib.tounicode(e.hint))
                else:
                    err = hglib.tounicode(str(e))
                qtlib.WarningMsgBox(_('No username configured'),
                                    err, parent=self)
                return

        if self.pushaftercb.isChecked():
            remote = hglib.fromunicode(self.pushafterle.text())
            outopts['pushafter'] = remote
        else:
            outopts['pushafter'] = ''

        self.outopts = outopts
        QDialog.accept(self)


class CommitDialog(QDialog):
    'Standalone commit tool, a wrapper for CommitWidget'

    def __init__(self, repo, pats, opts, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowIcon(qtlib.geticon('hg-commit'))
        self.pats = pats
        self.opts = opts

        layout = QVBoxLayout()
        layout.setMargin(0)
        self.setLayout(layout)

        toplayout = QVBoxLayout()
        toplayout.setContentsMargins(5, 5, 5, 0)
        layout.addLayout(toplayout)
        
        commit = CommitWidget(repo, pats, opts, False, self)
        toplayout.addWidget(commit, 1)

        self.statusbar = cmdui.ThgStatusBar(self)
        commit.showMessage.connect(self.statusbar.showMessage)
        commit.progress.connect(self.statusbar.progress)
        commit.linkActivated.connect(self.linkActivated)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Close|BB.Discard)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(BB.Discard).setText('Undo')
        bb.button(BB.Discard).clicked.connect(commit.rollback)
        bb.button(BB.Close).setDefault(False)
        bb.button(BB.Discard).setDefault(False)
        bb.button(BB.Ok).setDefault(True)
        self.commitButton = bb.button(BB.Ok)
        self.commitButton.setText(_('Commit', 'action button'))
        self.bb = bb

        toplayout.addWidget(self.bb)
        layout.addWidget(self.statusbar)

        s = QSettings()
        self.restoreGeometry(s.value('commit/geom').toByteArray())
        commit.loadSettings(s, 'committool')
        repo.repositoryChanged.connect(self.updateUndo)
        commit.commitComplete.connect(self.postcommit)
        commit.commitButtonEnable.connect(self.commitButton.setEnabled)

        self.setWindowTitle(_('%s - commit') % repo.displayname)
        self.commit = commit
        self.commit.reload()
        self.updateUndo()
        self.commit.msgte.setFocus()
        QShortcut(QKeySequence.Refresh, self, self.refresh)

    def done(self, ret):
        self.commit.repo.configChanged.disconnect(self.commit.configChanged)
        self.commit.repo.repositoryChanged.disconnect(self.commit.repositoryChanged)
        self.commit.repo.workingBranchChanged.disconnect(self.commit.workingBranchChanged)
        self.commit.repo.repositoryChanged.disconnect(self.updateUndo)
        super(CommitDialog, self).done(ret)

    def linkActivated(self, link):
        link = hglib.fromunicode(link)
        if link.startswith('subrepo:'):
            from tortoisehg.hgqt.run import qtrun
            qtrun(run, ui.ui(), root=link[8:])
        if link.startswith('shelve:'):
            repo = self.commit.repo
            from tortoisehg.hgqt import shelve
            dlg = shelve.ShelveDialog(repo, self)
            dlg.finished.connect(dlg.deleteLater)
            dlg.exec_()
            self.refresh()

    def updateUndo(self):
        BB = QDialogButtonBox
        undomsg = self.commit.canUndo()
        if undomsg:
            self.bb.button(BB.Discard).setEnabled(True)
            self.bb.button(BB.Discard).setToolTip(undomsg)
        else:
            self.bb.button(BB.Discard).setEnabled(False)
            self.bb.button(BB.Discard).setToolTip('')

    def refresh(self):
        self.updateUndo()
        self.commit.reload()

    def postcommit(self):
        repo = self.commit.stwidget.repo
        if repo.ui.configbool('tortoisehg', 'closeci'):
            if self.commit.canExit():
                self.reject()
            else:
                self.commit.stwidget.refthread.wait()
                QTimer.singleShot(0, self.reject)

    def accept(self):
        self.commit.commit()

    def reject(self):
        if self.commit.canExit():
            s = QSettings()
            s.setValue('commit/geom', self.saveGeometry())
            self.commit.saveSettings(s, 'committool')
            QDialog.reject(self)

def run(ui, *pats, **opts):
    from tortoisehg.util import paths
    from tortoisehg.hgqt import thgrepo
    root = opts.get('root', paths.find_root())
    repo = thgrepo.repository(ui, path=root)
    pats = hglib.canonpaths(pats)
    os.chdir(repo.root)
    return CommitDialog(repo, pats, opts)
