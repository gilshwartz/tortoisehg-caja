# cmdui.py - A widget to execute Mercurial command for TortoiseHg
#
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os, sys, time

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.Qsci import QsciScintilla

from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _, localgettext
from tortoisehg.hgqt import qtlib, qscilib, thread

local = localgettext()

def startProgress(topic, status):
    topic, item, pos, total, unit = topic, '...', status, None, ''
    return (topic, pos, item, unit, total)

def stopProgress(topic):
    topic, item, pos, total, unit = topic, '', None, None, ''
    return (topic, pos, item, unit, total)

class ProgressMonitor(QWidget):
    'Progress bar for use in workbench status bar'
    def __init__(self, topic, parent):
        super(ProgressMonitor, self).__init__(parent=parent)

        hbox = QHBoxLayout()
        hbox.setContentsMargins(*(0,)*4)
        self.setLayout(hbox)
        self.idle = False

        self.pbar = QProgressBar()
        self.pbar.setTextVisible(False)
        self.pbar.setMinimum(0)
        hbox.addWidget(self.pbar)

        self.topic = QLabel(topic)
        hbox.addWidget(self.topic, 0)

        self.status = QLabel()
        hbox.addWidget(self.status, 1)

        self.pbar.setMaximum(100)
        self.pbar.reset()
        self.status.setText('')

    def clear(self):
        self.pbar.setMinimum(0)
        self.pbar.setMaximum(100)
        self.pbar.setValue(100)
        self.status.setText('')
        self.idle = True

    def setcounts(self, cur, max):
        self.pbar.setMaximum(max)
        self.pbar.setValue(cur)

    def unknown(self):
        self.pbar.setMinimum(0)
        self.pbar.setMaximum(0)


class ThgStatusBar(QStatusBar):
    linkActivated = pyqtSignal(QString)

    def __init__(self, parent=None):
        QStatusBar.__init__(self, parent=parent)
        self.topics = {}
        self.lbl = QLabel()
        self.lbl.linkActivated.connect(self.linkActivated)
        self.addWidget(self.lbl)
        self.setStyleSheet('QStatusBar::item { border: none }')

    @pyqtSlot(unicode)
    def showMessage(self, ustr, error=False):
        self.lbl.setText(ustr)
        if error:
            self.lbl.setStyleSheet('QLabel { color: red }')
        else:
            self.lbl.setStyleSheet('')

    def clear(self):
        keys = self.topics.keys()
        for key in keys:
            pm = self.topics[key]
            self.removeWidget(pm)
            del self.topics[key]

    @pyqtSlot(QString, object, QString, QString, object)
    def progress(self, topic, pos, item, unit, total, root=None):
        'Progress signal received from repowidget'
        # topic is current operation
        # pos is the current numeric position (revision, bytes)
        # item is a non-numeric marker of current position (current file)
        # unit is a string label
        # total is the highest expected pos
        #
        # All topics should be marked closed by setting pos to None
        if root:
            key = (root, topic)
        else:
            key = topic
        if pos is None or (not pos and not total):
            if key in self.topics:
                pm = self.topics[key]
                self.removeWidget(pm)
                del self.topics[key]
            return
        if key not in self.topics:
            pm = ProgressMonitor(topic, self)
            pm.setMaximumHeight(self.lbl.sizeHint().height())
            self.addWidget(pm)
            self.topics[key] = pm
        else:
            pm = self.topics[key]
        if total:
            fmt = '%s / %s ' % (unicode(pos), unicode(total))
            if unit:
                fmt += unit
            pm.status.setText(fmt)
            pm.setcounts(pos, total)
        else:
            if item:
                item = item[-30:]
            pm.status.setText('%s %s' % (unicode(pos), item))
            pm.unknown()


class Core(QObject):
    """Core functionality for running Mercurial command.
    Do not attempt to instantiate and use this directly.
    """

    commandStarted = pyqtSignal()
    commandFinished = pyqtSignal(int)
    commandCanceling = pyqtSignal()

    output = pyqtSignal(QString, QString)
    progress = pyqtSignal(QString, object, QString, QString, object)

    def __init__(self, logWindow, parent):
        super(Core, self).__init__(parent)

        self.thread = None
        self.extproc = None
        self.stbar = None
        self.queue = []
        self.rawoutlines = []
        self.display = None
        self.useproc = False
        if logWindow:
            self.outputLog = LogWidget()
            self.outputLog.installEventFilter(qscilib.KeyPressInterceptor(self))
            self.output.connect(self.outputLog.appendLog)

    ### Public Methods ###

    def run(self, cmdline, *cmdlines, **opts):
        '''Execute or queue Mercurial command'''
        self.display = opts.get('display')
        self.useproc = opts.get('useproc', False)
        self.queue.append(cmdline)
        if len(cmdlines):
            self.queue.extend(cmdlines)
        if self.useproc:
            self.runproc()
        elif not self.running():
            self.runNext()

    def cancel(self):
        '''Cancel running Mercurial command'''
        if self.running():
            try:
                if self.extproc:
                    self.extproc.close()
                elif self.thread:
                    self.thread.abort()
            except AttributeError:
                pass
            self.commandCanceling.emit()

    def setStbar(self, stbar):
        self.stbar = stbar

    def running(self):
        try:
            if self.extproc:
                return self.extproc.state() != QProcess.NotRunning
            elif self.thread:
                return self.thread.isRunning()
        except AttributeError:
            pass
        return False

    def rawoutput(self):
        return ''.join(self.rawoutlines)

    ### Private Method ###

    def runproc(self):
        'Run mercurial command in separate process'

        exepath = None
        if hasattr(sys, 'frozen'):
            progdir = paths.get_prog_root()
            exe = os.path.join(progdir, 'hg.exe')
            if os.path.exists(exe):
                exepath = exe
        if not exepath:
            exepath = paths.find_in_path('hg')

        def start(cmdline, display):
            self.rawoutlines = []
            if display:
                cmd = '%% hg %s\n' % display
            else:
                cmd = '%% hg %s\n' % ' '.join(cmdline)
            self.output.emit(cmd, 'control')
            proc.start(exepath, cmdline, QIODevice.ReadOnly)

        @pyqtSlot(int)
        def finished(ret):
            if ret:
                msg = _('[command returned code %d %%s]') % int(ret)
            else:
                msg = _('[command completed successfully %s]')
            msg = msg % time.asctime() + '\n'
            self.output.emit(msg, 'control')
            if ret == 0 and self.queue:
                start(self.queue.pop(0), '')
            else:
                self.queue = []
                self.extproc = None
                self.commandFinished.emit(ret)

        def handleerror(error):
            if error == QProcess.FailedToStart:
                self.output.emit(_('failed to start command\n'),
                                 'ui.error')
                finished(-1)
            elif error != QProcess.Crashed:
                self.output.emit(_('error while running command\n'),
                                 'ui.error')

        def stdout():
            data = proc.readAllStandardOutput().data()
            self.rawoutlines.append(data)
            self.output.emit(hglib.tounicode(data), '')

        def stderr():
            data = proc.readAllStandardError().data()
            self.output.emit(hglib.tounicode(data), 'ui.error')

        self.extproc = proc = QProcess(self)
        proc.started.connect(self.onCommandStarted)
        proc.finished.connect(finished)
        proc.readyReadStandardOutput.connect(stdout)
        proc.readyReadStandardError.connect(stderr)
        proc.error.connect(handleerror)
        start(self.queue.pop(0), self.display)


    def runNext(self):
        if not self.queue:
            return False

        cmdline = self.queue.pop(0)

        self.thread = thread.CmdThread(cmdline, self.display, self.parent())
        self.thread.started.connect(self.onCommandStarted)
        self.thread.commandFinished.connect(self.onThreadFinished)

        self.thread.outputReceived.connect(self.output)
        self.thread.progressReceived.connect(self.progress)
        if self.stbar:
            self.thread.progressReceived.connect(self.stbar.progress)

        self.thread.start()
        return True

    def clearOutput(self):
        if hasattr(self, 'outputLog'):
            self.outputLog.clear()

    ### Signal Handlers ###

    @pyqtSlot()
    def onCommandStarted(self):
        if self.stbar:
            self.stbar.showMessage(_('Running...'))

        self.commandStarted.emit()

    @pyqtSlot(int)
    def onThreadFinished(self, ret):
        if self.stbar:
            error = False
            if ret is None:
                self.stbar.clear()
                if self.thread.abortbyuser:
                    status = _('Terminated by user')
                else:
                    status = _('Terminated')
            elif ret == 0:
                status = _('Finished')
            else:
                status = _('Failed!')
                error = True
            self.stbar.showMessage(status, error)

        self.display = None
        if ret == 0 and self.runNext():
            return # run next command
        else:
            self.queue = []
            text = self.thread.rawoutput.join('')
            self.rawoutlines = [hglib.fromunicode(text, 'replace')]

        self.commandFinished.emit(ret)


class LogWidget(QsciScintilla):
    """Output log viewer"""

    def __init__(self, parent=None):
        super(LogWidget, self).__init__(parent)
        self.setReadOnly(True)
        self.setUtf8(True)
        self.setMarginWidth(1, 0)
        self.setWrapMode(QsciScintilla.WrapCharacter)
        self._initfont()
        self._initmarkers()

    def _initfont(self):
        tf = qtlib.getfont('fontoutputlog')
        tf.changed.connect(self.forwardFont)
        self.setFont(tf.font())

    @pyqtSlot(QFont)
    def forwardFont(self, font):
        self.setFont(font)

    def _initmarkers(self):
        self._markers = {}
        for l in ('ui.error', 'control'):
            self._markers[l] = m = self.markerDefine(QsciScintilla.Background)
            c = QColor(qtlib.getbgcoloreffect(l))
            if c.isValid():
                self.setMarkerBackgroundColor(c, m)
            # NOTE: self.setMarkerForegroundColor() doesn't take effect,
            # because it's a *Background* marker.

    @pyqtSlot(unicode, str)
    def appendLog(self, msg, label):
        """Append log text to the last line; scrolls down to there"""
        self.append(msg)
        self._setmarker(xrange(self.lines() - unicode(msg).count('\n') - 1,
                               self.lines() - 1), label)
        self.setCursorPosition(self.lines() - 1, 0)

    def _setmarker(self, lines, label):
        for m in self._markersforlabel(label):
            for i in lines:
                self.markerAdd(i, m)

    def _markersforlabel(self, label):
        return iter(self._markers[l] for l in str(label).split()
                    if l in self._markers)


class Widget(QWidget):
    """An embeddable widget for running Mercurial command"""

    commandStarted = pyqtSignal()
    commandFinished = pyqtSignal(int)
    commandCanceling = pyqtSignal()

    output = pyqtSignal(QString, QString)
    progress = pyqtSignal(QString, object, QString, QString, object)
    makeLogVisible = pyqtSignal(bool)

    def __init__(self, logWindow, statusBar, parent):
        super(Widget, self).__init__(parent)

        self.core = Core(logWindow, self)
        self.core.commandStarted.connect(self.commandStarted)
        self.core.commandFinished.connect(self.onCommandFinished)
        self.core.commandCanceling.connect(self.commandCanceling)
        self.core.output.connect(self.output)
        self.core.progress.connect(self.progress)
        if not logWindow:
            return

        vbox = QVBoxLayout()
        vbox.setSpacing(4)
        vbox.setContentsMargins(*(1,)*4)
        self.setLayout(vbox)

        # command output area
        self.core.outputLog.setHidden(True)
        self.layout().addWidget(self.core.outputLog, 1)

        if statusBar:
            ## status and progress labels
            self.stbar = ThgStatusBar()
            self.stbar.setSizeGripEnabled(False)
            self.core.setStbar(self.stbar)
            self.layout().addWidget(self.stbar)

    ### Public Methods ###

    def run(self, cmdline, *args, **opts):
        self.core.run(cmdline, *args, **opts)

    def cancel(self):
        self.core.cancel()

    def setShowOutput(self, visible):
        if hasattr(self.core, 'outputLog'):
            self.core.outputLog.setShown(visible)

    def outputShown(self):
        if hasattr(self.core, 'outputLog'):
            return self.core.outputLog.isVisible()
        else:
            return False

    ### Signal Handler ###

    @pyqtSlot(int)
    def onCommandFinished(self, ret):
        if ret == -1:
            self.makeLogVisible.emit(True)
            self.setShowOutput(True)
        self.commandFinished.emit(ret)

class Dialog(QDialog):
    """A dialog for running random Mercurial command"""

    def __init__(self, cmdline, parent=None):
        super(Dialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.core = Core(True, self)
        self.core.commandFinished.connect(self.onCommandFinished)

        vbox = QVBoxLayout()
        vbox.setSpacing(4)
        vbox.setContentsMargins(5, 5, 5, 5)

        # command output area
        vbox.addWidget(self.core.outputLog, 1)

        ## status and progress labels
        self.stbar = ThgStatusBar()
        self.stbar.setSizeGripEnabled(False)
        self.core.setStbar(self.stbar)
        vbox.addWidget(self.stbar)

        # bottom buttons
        buttons = QDialogButtonBox()
        self.cancelBtn = buttons.addButton(QDialogButtonBox.Cancel)
        self.cancelBtn.clicked.connect(self.core.cancel)
        self.core.commandCanceling.connect(self.commandCanceling)

        self.closeBtn = buttons.addButton(QDialogButtonBox.Close)
        self.closeBtn.setHidden(True)
        self.closeBtn.clicked.connect(self.reject)

        self.detailBtn = buttons.addButton(_('Detail'),
                                            QDialogButtonBox.ResetRole)
        self.detailBtn.setAutoDefault(False)
        self.detailBtn.setCheckable(True)
        self.detailBtn.setChecked(True)
        self.detailBtn.toggled.connect(self.setShowOutput)
        vbox.addWidget(buttons)

        self.setLayout(vbox)
        self.setWindowTitle(_('TortoiseHg Command Dialog'))
        self.resize(540, 420)

        # start command
        self.core.run(cmdline)

    def setShowOutput(self, visible):
        """show/hide command output"""
        self.core.outputLog.setVisible(visible)
        self.detailBtn.setChecked(visible)

        # workaround to adjust only window height
        self.setMinimumWidth(self.width())
        self.adjustSize()
        self.setMinimumWidth(0)

    ### Private Method ###

    def reject(self):
        if self.core.running():
            ret = QMessageBox.question(self, _('Confirm Exit'),
                        _('Mercurial command is still running.\n'
                          'Are you sure you want to terminate?'),
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No)
            if ret == QMessageBox.Yes:
                self.core.cancel()
            # don't close dialog
            return

        # close dialog
        if self.returnCode == 0:
            self.accept()  # means command successfully finished
        else:
            super(Dialog, self).reject()

    @pyqtSlot()
    def commandCanceling(self):
        self.cancelBtn.setDisabled(True)

    @pyqtSlot(int)
    def onCommandFinished(self, ret):
        self.returnCode = ret
        self.cancelBtn.setHidden(True)
        self.closeBtn.setShown(True)
        self.closeBtn.setFocus()

class Runner(QObject):
    """A component for running Mercurial command without UI

    This command runner doesn't show any UI element unless it gets a warning
    or an error while the command is running.  Once an error or a warning is
    received, it pops-up a small dialog which contains the command log.
    """

    commandStarted = pyqtSignal()
    commandFinished = pyqtSignal(int)
    commandCanceling = pyqtSignal()

    output = pyqtSignal(QString, QString)
    progress = pyqtSignal(QString, object, QString, QString, object)
    makeLogVisible = pyqtSignal(bool)

    def __init__(self, logWindow, parent):
        super(Runner, self).__init__(parent)
        self.title = _('TortoiseHg')
        self.core = Core(logWindow, parent)
        self.core.commandStarted.connect(self.commandStarted)
        self.core.commandFinished.connect(self.onCommandFinished)
        self.core.commandCanceling.connect(self.commandCanceling)
        self.core.output.connect(self.output)
        self.core.progress.connect(self.progress)

    ### Public Methods ###

    def setTitle(self, title):
        self.title = title

    def run(self, cmdline, *args, **opts):
        self.core.run(cmdline, *args, **opts)

    def running(self):
        return self.core.running()

    def cancel(self):
        self.core.cancel()

    def outputShown(self):
        if hasattr(self, 'dlg'):
            return self.dlg.isVisible()
        else:
            return False

    def setShowOutput(self, visible=True):
        if not hasattr(self.core, 'outputLog'):
            return
        if not hasattr(self, 'dlg'):
            self.dlg = dlg = QDialog(self.parent())
            dlg.setWindowTitle(self.title)
            dlg.setWindowFlags(Qt.Dialog)
            dlg.setLayout(QVBoxLayout())
            dlg.layout().addWidget(self.core.outputLog)
            self.core.outputLog.setMinimumSize(460, 320)
        self.dlg.setVisible(visible)

    ### Signal Handler ###

    @pyqtSlot(int)
    def onCommandFinished(self, ret):
        if ret != 0:
            self.makeLogVisible.emit(True)
            self.setShowOutput(True)
        self.commandFinished.emit(ret)
