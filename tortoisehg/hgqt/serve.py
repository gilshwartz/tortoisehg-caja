# serve.py - TortoiseHg dialog to start web server
#
# Copyright 2010 Yuya Nishihara <yuya@tcha.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import sys, os, httplib, socket, tempfile
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from mercurial import extensions, hgweb, util, error, subrepo
from mercurial.hgweb import server  # workaround for demandimport
from tortoisehg.util import paths, wconfig, hglib
from tortoisehg.hgqt import cmdui, qtlib, thgrepo
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt.serve_ui import Ui_ServeDialog
from tortoisehg.hgqt.webconf import WebconfForm

class ServeDialog(QDialog):
    """Dialog for serving repositories via web"""
    def __init__(self, webconf, parent=None):
        super(ServeDialog, self).__init__(parent)
        self.setWindowFlags((self.windowFlags() | Qt.WindowMinimizeButtonHint)
                            & ~Qt.WindowContextHelpButtonHint)
        # TODO: choose appropriate icon
        self.setWindowIcon(qtlib.geticon('proxy'))

        self._qui = Ui_ServeDialog()
        self._qui.setupUi(self)

        self._initwebconf(webconf)
        self._initcmd()
        self._initactions()
        self._updateform()

    def _initcmd(self):
        self._cmd = cmdui.Widget(True, False, self)
        # TODO: forget old logs?
        self._log_edit = self._cmd.core.outputLog
        self._qui.details_tabs.addTab(self._log_edit, _('Log'))
        self._cmd.hide()
        self._cmd.commandStarted.connect(self._updateform)
        self._cmd.commandFinished.connect(self._updateform)

    def _initwebconf(self, webconf):
        self._webconf_form = WebconfForm(webconf=webconf, parent=self)
        self._qui.details_tabs.addTab(self._webconf_form, _('Repositories'))

    def _initactions(self):
        self._qui.start_button.clicked.connect(self.start)
        self._qui.stop_button.clicked.connect(self.stop)

    @pyqtSlot()
    def _updateform(self):
        """update form availability and status text"""
        self._updatestatus()
        self._qui.start_button.setEnabled(not self.isstarted())
        self._qui.stop_button.setEnabled(self.isstarted())
        self._qui.settings_button.setEnabled(not self.isstarted())
        self._qui.port_edit.setEnabled(not self.isstarted())
        self._webconf_form.setEnabled(not self.isstarted())

    def _updatestatus(self):
        def statustext():
            if self.isstarted():
                # TODO: escape special chars
                link = '<a href="%s">%s</a>' % (self.rooturl, self.rooturl)
                return _('Running at %s') % link
            else:
                return _('Stopped')

        self._qui.status_edit.setText(statustext())

    @pyqtSlot()
    def start(self):
        """Start web server"""
        if self.isstarted():
            return

        _setupwrapper()
        self._cmd.run(self._cmdargs())

    def _cmdargs(self):
        """Build command args to run server"""
        a = ['serve', '--port', str(self.port), '--debug']
        if self._singlerepo:
            a += ['-R', self._singlerepo]
        else:
            a += ['--web-conf', self._tempwebconf()]
        return a

    def _tempwebconf(self):
        """Save current webconf to temporary file; return its path"""
        if not hasattr(self._webconf, 'write'):
            return self._webconf.path

        fd, fname = tempfile.mkstemp(prefix='webconf_', dir=qtlib.gettempdir())
        f = os.fdopen(fd, 'w')
        try:
            self._webconf.write(f)
            return fname
        finally:
            f.close()

    @property
    def _webconf(self):
        """Selected webconf object"""
        return self._webconf_form.webconf

    @property
    def _singlerepo(self):
        """Return repository path if serving single repository"""
        # NOTE: we cannot use web-conf to serve single repository at '/' path
        if len(self._webconf['paths']) != 1:
            return
        path = self._webconf.get('paths', '/')
        if path and '*' not in path:  # exactly a single repo (no wildcard)
            return path

    @pyqtSlot()
    def stop(self):
        """Stop web server"""
        if not self.isstarted():
            return

        self._cmd.cancel()
        self._fake_request()

    def _fake_request(self):
        """Send fake request for server to run python code"""
        TIMEOUT = 0.5  # [sec]
        conn = httplib.HTTPConnection('localhost:%d' % self.port)
        origtimeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(TIMEOUT)
        try:
            try:
                conn.request('GET', '/')
                res = conn.getresponse()
                res.read()
            except (socket.error, httplib.HTTPException):
                pass
        finally:
            socket.setdefaulttimeout(origtimeout)
            conn.close()

    def reject(self):
        self.stop()
        super(ServeDialog, self).reject()

    def isstarted(self):
        """Is the web server running?"""
        return self._cmd.core.running()

    @property
    def rooturl(self):
        """Returns the root URL of the web server"""
        # TODO: scheme, hostname ?
        return 'http://localhost:%d' % self.port

    @property
    def port(self):
        """Port number of the web server"""
        return int(self._qui.port_edit.value())

    def setport(self, port):
        self._qui.port_edit.setValue(port)

    def keyPressEvent(self, event):
        if self.isstarted() and event.key() == Qt.Key_Escape:
            self.stop()
            return

        return super(ServeDialog, self).keyPressEvent(event)

    def closeEvent(self, event):
        if self.isstarted():
            self._minimizetotray()
            event.ignore()
            return

        return super(ServeDialog, self).closeEvent(event)

    @util.propertycache
    def _trayicon(self):
        icon = QSystemTrayIcon(self.windowIcon(), parent=self)
        icon.activated.connect(self._restorefromtray)
        icon.setToolTip(self.windowTitle())
        # TODO: context menu
        return icon

    # TODO: minimize to tray by minimize button

    @pyqtSlot()
    def _minimizetotray(self):
        self._trayicon.show()
        self.hide()

    @pyqtSlot()
    def _restorefromtray(self):
        self._trayicon.hide()
        self.show()

    @pyqtSlot()
    def on_settings_button_clicked(self):
        from tortoisehg.hgqt import settings
        settings.SettingsDialog(parent=self, focus='web.name').exec_()

def _create_server(orig, ui, app):
    """wrapper for hgweb.server.create_server to be interruptable"""
    server = orig(ui, app)
    server.accesslog = ui
    server.errorlog = ui  # TODO: ui.warn
    server._serving = False

    def serve_forever(orig):
        server._serving = True
        try:
            while server._serving:
                server.handle_request()
        except KeyboardInterrupt:
            # raised outside try-block around process_request().
            # see SocketServer.BaseServer
            pass
        finally:
            server._serving = False
            server.server_close()

    def handle_error(orig, request, client_address):
        type, value, _traceback = sys.exc_info()
        if issubclass(type, KeyboardInterrupt):
            server._serving = False
        else:
            ui.write_err('%s\n' % value)

    extensions.wrapfunction(server, 'serve_forever', serve_forever)
    extensions.wrapfunction(server, 'handle_error', handle_error)
    return server

_setupwrapper_done = False
def _setupwrapper():
    """Wrap hgweb.server.create_server to get along with thg"""
    global _setupwrapper_done
    if not _setupwrapper_done:
        extensions.wrapfunction(hgweb.server, 'create_server',
                                _create_server)
        _setupwrapper_done = True

def run(ui, *pats, **opts):
    repopath = opts.get('root') or paths.find_root()
    webconfpath = opts.get('web_conf') or opts.get('webdir_conf')
    dlg = ServeDialog(webconf=_newwebconf(repopath, webconfpath))

    lui = ui.copy()
    if webconfpath:
        lui.readconfig(webconfpath)
    elif repopath:
        lui.readconfig(os.path.join(repopath, '.hg', 'hgrc'), repopath)
    try:
        dlg.setport(int(lui.config('web', 'port', '8000')))
    except ValueError:
        pass

    if repopath or webconfpath:
        dlg.start()
    return dlg

def recursiveRepoSearch(repo):
    yield repo.root
    try:
        wctx = repo[None]
        for s in wctx.substate:
            sub = wctx.sub(s)
            if isinstance(sub, subrepo.hgsubrepo):
                for root in recursiveRepoSearch(sub._repo):
                    yield root
    except (EnvironmentError, error.Abort, error.RepoError):
        pass

def _newwebconf(repopath, webconfpath):
    """create config obj for hgweb"""
    if webconfpath:
        # TODO: handle file not found
        c = wconfig.readfile(webconfpath)
        c.path = os.path.abspath(webconfpath)
        return c
    elif repopath:  # imitate webconf for single repo
        c = wconfig.config()
        try:
            repo = thgrepo.repository(None, repopath)
            roots = [root for root in recursiveRepoSearch(repo)]
            if len(roots) == 1:
                c.set('paths', '/', repopath)
            else:
                base = hglib.fromunicode(repo.shortname)
                c.set('paths', base, repopath)
                for root in roots[1:]:
                    c.set('paths', base + root[len(repopath):], root)
        except (EnvironmentError, error.Abort, error.RepoError):
            c.set('paths', '/', repopath)
        return c
