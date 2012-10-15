# about.py - About dialog for TortoiseHg
#
# Copyright 2007 TK Soh <teekaysoh@gmail.com>
# Copyright 2007 Steve Borho <steve@borho.org>
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
# Copyright 2010 Johan Samyn <johan.samyn@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.
"""
TortoiseHg About dialog - PyQt4 version
"""

import sys

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib
from tortoisehg.util import version, hglib, paths

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.QtNetwork import QNetworkAccessManager, QNetworkRequest

class AboutDialog(QDialog):
    """Dialog for showing info about TortoiseHg"""

    def __init__(self, parent=None):
        super(AboutDialog, self).__init__(parent)

        self.setWindowIcon(qtlib.geticon('thg_logo'))
        self.setWindowTitle(_('About'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.vbox = QVBoxLayout()
        self.vbox.setSpacing(8)

        self.logo_lbl = QLabel()
        self.logo_lbl.setMinimumSize(QSize(92, 50))
        self.logo_lbl.setScaledContents(False)
        self.logo_lbl.setAlignment(Qt.AlignCenter)
        thglogofile = paths.get_tortoise_icon('thg_logo_92x50.png')
        self.logo_lbl.setPixmap(QPixmap(thglogofile))
        self.vbox.addWidget(self.logo_lbl)

        self.name_version_libs_lbl = QLabel()
        self.name_version_libs_lbl.setText(' ')
        self.name_version_libs_lbl.setAlignment(Qt.AlignCenter)
        self.name_version_libs_lbl.setTextInteractionFlags(
                Qt.TextSelectableByMouse)
        self.vbox.addWidget(self.name_version_libs_lbl)
        self.getVersionInfo()

        self.copyright_lbl = QLabel()
        self.copyright_lbl.setAlignment(Qt.AlignCenter)
        self.copyright_lbl.setText('\n'
                + _('Copyright 2008-2012 Steve Borho and others'))
        self.vbox.addWidget(self.copyright_lbl)
        self.courtesy_lbl = QLabel()
        self.courtesy_lbl.setAlignment(Qt.AlignCenter)
        self.courtesy_lbl.setText(
              _('Several icons are courtesy of the TortoiseSVN project') + '\n')
        self.vbox.addWidget(self.courtesy_lbl)

        self.download_url_lbl = QLabel()
        self.download_url_lbl.setAlignment(Qt.AlignCenter)
        self.download_url_lbl.setMouseTracking(True)
        self.download_url_lbl.setAlignment(Qt.AlignCenter)
        self.download_url_lbl.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.download_url_lbl.setOpenExternalLinks(True)
        self.download_url_lbl.setText('<a href=%s>%s</a>' %
                ('http://tortoisehg.org', _('You can visit our site here')))
        self.vbox.addWidget(self.download_url_lbl)

        # Let's have some space between the url and the buttons.
        self.blancline_lbl = QLabel()
        self.vbox.addWidget(self.blancline_lbl)

        self.hbox = QHBoxLayout()
        self.license_btn = QPushButton()
        self.license_btn.setText(_('&License'))
        self.license_btn.setAutoDefault(False)
        self.license_btn.clicked.connect(self.showLicense)
        self.hspacer = QSpacerItem(40, 20,
                QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.close_btn = QPushButton()
        self.close_btn.setText(_('&Close'))
        self.close_btn.setDefault(True)
        self.close_btn.clicked.connect(self.close)
        self.hbox.addWidget(self.license_btn)
        self.hbox.addItem(self.hspacer)
        self.hbox.addWidget(self.close_btn)
        self.vbox.addLayout(self.hbox)

        self.setLayout(self.vbox)
        self.layout().setSizeConstraint(QLayout.SetFixedSize)
        self._readsettings()

        # Spawn it later, so that the dialog gets visible quickly.
        QTimer.singleShot(0, self.getUpdateInfo)
        self._newverreply = None

    def getVersionInfo(self):
        def make_version(tuple):
            vers = ".".join([str(x) for x in tuple])
            return vers
        thgv = (_('version %s') % version.version())
        libv = (_('with Mercurial-%s, Python-%s, PyQt-%s, Qt-%s') % \
              (hglib.hgversion, make_version(sys.version_info[0:3]),
              PYQT_VERSION_STR, QT_VERSION_STR))
        par = ('<p style=\" margin-top:0px; margin-bottom:6px;\">'
                '<span style=\"font-size:%spt; font-weight:600;\">'
                '%s</span></p>')
        name = (par % (14, 'TortoiseHg'))
        thgv = (par % (10, thgv))
        nvl = ''.join([name, thgv, libv])
        self.name_version_libs_lbl.setText(nvl)

    @pyqtSlot()
    def getUpdateInfo(self):
        verurl = 'http://tortoisehg.bitbucket.org/curversion.txt'
        # If we use QNetworkAcessManager elsewhere, it should be shared
        # through the application.
        self._netmanager = QNetworkAccessManager(self)
        self._newverreply = self._netmanager.get(QNetworkRequest(QUrl(verurl)))
        self._newverreply.finished.connect(self.uFinished)

    @pyqtSlot()
    def uFinished(self):
        newver = (0,0,0)
        try:
            f = self._newverreply.readAll().data().splitlines()
            self._newverreply.close()
            self._newverreply = None
            newver = tuple([int(p) for p in f[0].split('.')])
            upgradeurl = f[1] # generic download URL
            platform = sys.platform
            if platform == 'win32':
                from win32process import IsWow64Process as IsX64
                platform = IsX64() and 'x64' or 'x86'
            # linux2 for Linux, darwin for OSX
            for line in f[2:]:
                p, _url = line.split(':', 1)
                if platform == p:
                    upgradeurl = _url.strip()
                    break
        except (IndexError, ImportError, ValueError):
            pass
        try:
            thgv = version.version()
            if '+' in thgv:
                thgv = thgv[:thgv.index('+')]
            curver = tuple([int(p) for p in thgv.split('.')])
        except ValueError:
            curver = (0,0,0)
        if newver > curver:
            url_lbl = _('A new version of TortoiseHg is ready for download!')
            urldata = ('<a href=%s>%s</a>' % (upgradeurl, url_lbl))
            self.download_url_lbl.setText(urldata)

    def showLicense(self):
        from tortoisehg.hgqt import license
        ld = license.LicenseDialog(self)
        ld.show()

    def closeEvent(self, event):
        if self._newverreply:
            self._newverreply.abort()
        self._writesettings()
        super(AboutDialog, self).closeEvent(event)

    def _readsettings(self):
        s = QSettings()
        self.restoreGeometry(s.value('about/geom').toByteArray())

    def _writesettings(self):
        s = QSettings()
        s.setValue('about/geom', self.saveGeometry())

def run(ui, *pats, **opts):
    return AboutDialog()
