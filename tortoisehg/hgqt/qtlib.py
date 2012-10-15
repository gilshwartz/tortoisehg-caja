# qtlib.py - Qt utility code
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os
import sys
import atexit
import shutil
import stat
import subprocess
import tempfile
import re
import weakref

from mercurial import commands, extensions, error, util

from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _
from hgext.color import _styles

from PyQt4.QtCore import *
from PyQt4.QtGui import *

if PYQT_VERSION_STR.split('.') < ['4', '7'] or \
   QT_VERSION_STR.split('.') < ['4', '6']:
    sys.stderr.write('TortoiseHg requires Qt 4.6 and PyQt 4.7\n')
    sys.stderr.write('You have Qt %s and PyQt %s\n' %
                     (QT_VERSION_STR, PYQT_VERSION_STR))
    sys.exit()

try:
    import win32con
    openflags = win32con.CREATE_NO_WINDOW
except ImportError:
    openflags = 0

tmproot = None
def gettempdir():
    global tmproot
    def cleanup():
        def writeable(arg, dirname, names):
            for name in names:
                fullname = os.path.join(dirname, name)
                os.chmod(fullname, os.stat(fullname).st_mode | stat.S_IWUSR)
        try:
            os.path.walk(tmproot, writeable, None)
            shutil.rmtree(tmproot)
        except:
            pass
    if not tmproot:
        tmproot = tempfile.mkdtemp(prefix='thg.')
        atexit.register(cleanup)
    return tmproot

def openhelpcontents(url):
    'Open online help, use local CHM file if available'
    if not url.startswith('http'):
        fullurl = 'http://tortoisehg.org/manual/2.4/' + url
        # Use local CHM file if it can be found
        if os.name == 'nt' and paths.bin_path:
            chm = os.path.join(paths.bin_path, 'doc', 'TortoiseHg.chm')
            if os.path.exists(chm):
                fullurl = (r'mk:@MSITStore:%s::/' % chm) + url
                openlocalurl(fullurl)
                return
        QDesktopServices.openUrl(QUrl(fullurl))

def openlocalurl(path):
    '''open the given path with the default application

    takes str, unicode or QString as argument
    returns True if open was successfull
    '''

    if isinstance(path, str):
        path = QString(hglib.tounicode(path))
    elif isinstance(path, unicode):
        path = QString(path)
    if os.name == 'nt' and path.startsWith('\\\\'):
        # network share, special handling because of qt bug 13359
        # see http://bugreports.qt.nokia.com/browse/QTBUG-13359
        qurl = QUrl()
        qurl.setUrl(QDir.toNativeSeparators(path))
    else:
        qurl = QUrl.fromLocalFile(path)
    return QDesktopServices.openUrl(qurl)

def openfiles(repo, files, parent=None):
    for filename in files:
        openlocalurl(repo.wjoin(filename))

def editfiles(repo, files, lineno=None, search=None, parent=None, editor=None):
    if len(files) == 1:
        filename = files[0].strip()
        if not filename:
            return
        files = [filename]
        path = repo.wjoin(filename)
        cwd = os.path.dirname(path)
        files = [os.path.basename(path)]
    else:
        cwd = repo.root
    files = [util.shellquote(util.localpath(f)) for f in files]
    editor = repo.ui.config('tortoisehg', 'editor')
    assert len(files) == 1 or lineno == None
    if not editor:
        editor = repo.ui.config('tortoisehg', 'editor')
    if editor:
        try:
            regexp = re.compile('\[([^\]]*)\]')
            expanded = []
            pos = 0
            for m in regexp.finditer(editor):
                expanded.append(editor[pos:m.start()-1])
                phrase = editor[m.start()+1:m.end()-1]
                pos = m.end()+1
                if '$LINENUM' in phrase:
                    if lineno is None:
                        # throw away phrase
                        continue
                    phrase = phrase.replace('$LINENUM', str(lineno))
                elif '$SEARCH' in phrase:
                    if search is None:
                        # throw away phrase
                        continue
                    phrase = phrase.replace('$SEARCH', search)
                if '$FILE' in phrase:
                    phrase = phrase.replace('$FILE', files[0])
                    files = []
                expanded.append(phrase)
            expanded.append(editor[pos:])
            cmdline = ' '.join(expanded + files)
        except ValueError, e:
            # '[' or ']' not found
            cmdline = ' '.join([editor] + files)
        except TypeError, e:
            # variable expansion failed
            cmdline = ' '.join([editor] + files)
    else:
        editor = os.environ.get('HPLUMAOR') or repo.ui.config('ui', 'editor') \
                 or os.environ.get('EDITOR', 'vi')
        cmdline = ' '.join([editor] + files)
    if os.path.basename(editor) in ('vi', 'vim', 'hplumaor'):
        res = QMessageBox.critical(parent,
                    _('No visual editor configured'),
                    _('Please configure a visual editor.'))
        from tortoisehg.hgqt.settings import SettingsDialog
        dlg = SettingsDialog(False, focus='tortoisehg.editor')
        dlg.exec_()
        return

    cmdline = util.quotecommand(cmdline)
    shell = not (len(cwd) >= 2 and cwd[0:2] == r'\\')
    try:
        subprocess.Popen(cmdline, shell=shell, creationflags=openflags,
                         stderr=None, stdout=None, stdin=None, cwd=cwd)
    except (OSError, EnvironmentError), e:
        QMessageBox.warning(parent,
                _('Editor launch failure'),
                u'%s : %s' % (hglib.tounicode(cmdline),
                              hglib.tounicode(str(e))))
    return False

def savefiles(repo, files, rev, parent=None):
    for curfile in files:
        wfile = util.localpath(curfile)
        wfile, ext = os.path.splitext(os.path.basename(wfile))
        if wfile:
            filename = "%s@%d%s" % (wfile, rev, ext)
        else:
            filename = "%s@%d" % (ext, rev)
        result = QFileDialog.getSaveFileName(
            parent=parent, caption=_("Save file to"),
            directory=hglib.tounicode(filename))
        if not result:
            continue
        cwd = os.getcwd()
        try:
            os.chdir(repo.root)
            try:
                commands.cat(repo.ui, repo, curfile, rev=rev,
                             output=hglib.fromunicode(result))
            except (util.Abort, IOError), e:
                QMessageBox.critical(self, _('Unable to save file'),
                                     hglib.tounicode(str(e)))
        finally:
            os.chdir(cwd)

_user_shell = None
def openshell(root, reponame):
    if not os.path.exists(root):
        WarningMsgBox(
            _('Failed to open path in terminal'),
            _('"%s" is not a valid directory') % hglib.tounicode(root))
        return
    if _user_shell:
        cwd = os.getcwd()
        try:
            shellcmd = _user_shell % {'reponame': reponame}
            os.chdir(root)
            started = QProcess.startDetached(shellcmd)
        finally:
            os.chdir(cwd)
        if not started:
            ErrorMsgBox(_('Failed to open path in terminal'),
                        _('Unable to start the following command:'), shellcmd)
    else:
        InfoMsgBox(_('No shell configured'),
                   _('A terminal shell must be configured'))

def configureshell(ui):
    global _user_shell
    _user_shell = ui.config('tortoisehg', 'shell')
    if _user_shell:
        return
    if sys.platform == 'darwin':
        return # Terminal.App does not support open-to-folder
    elif os.name == 'nt':
        _user_shell = 'cmd.exe /K title %(reponame)s'
    else:
        _user_shell = 'xterm -T "%(reponame)s"'

# _styles maps from ui labels to effects
# _effects maps an effect to font style properties.  We define a limited
# set of _effects, since we convert color effect names to font style
# effect programatically.

_effects = {
    'bold': 'font-weight: bold',
    'italic': 'font-style: italic',
    'underline': 'text-decoration: underline',
}

_thgstyles = {
   # Styles defined by TortoiseHg
   'log.branch': 'black #aaffaa_background',
   'log.patch': 'black #aaddff_background',
   'log.unapplied_patch': 'black #dddddd_background',
   'log.tag': 'black #ffffaa_background',
   'log.bookmark': 'blue #ffffaa_background',
   'log.curbookmark': 'black #ffdd77_background',
   'log.modified': 'black #ffddaa_background',
   'log.added': 'black #aaffaa_background',
   'log.removed': 'black #ffcccc_background',
   'status.deleted': 'red bold',
   'ui.error': 'red bold #ffcccc_background',
   'control': 'black bold #dddddd_background',
}

thgstylesheet = '* { white-space: pre; font-family: monospace;' \
                ' font-size: 9pt; }'
tbstylesheet = 'QToolBar { border: 0px }'

def configstyles(ui):
    configureshell(ui)

    # extensions may provide more labels and default effects
    for name, ext in extensions.extensions():
        _styles.update(getattr(ext, 'colortable', {}))

    # tortoisehg defines a few labels and default effects
    _styles.update(_thgstyles)

    # allow the user to override
    for status, cfgeffects in ui.configitems('color'):
        if '.' not in status:
            continue
        cfgeffects = ui.configlist('color', status)
        _styles[status] = ' '.join(cfgeffects)

    for status, cfgeffects in ui.configitems('thg-color'):
        if '.' not in status:
            continue
        cfgeffects = ui.configlist('thg-color', status)
        _styles[status] = ' '.join(cfgeffects)

# See http://doc.trolltech.com/4.2/richtext-html-subset.html
# and http://www.w3.org/TR/SVG/types.html#ColorKeywords

def geteffect(labels):
    'map labels like "log.date" to Qt font styles'
    labels = str(labels) # Could be QString
    effects = []
    # Multiple labels may be requested
    for l in labels.split():
        if not l:
            continue
        # Each label may request multiple effects
        es = _styles.get(l, '')
        for e in es.split():
            if e in _effects:
                effects.append(_effects[e])
            elif e.endswith('_background'):
                e = e[:-11]
                if e.startswith('#') or e in QColor.colorNames():
                    effects.append('background-color: ' + e)
            elif e.startswith('#') or e in QColor.colorNames():
                # Accept any valid QColor
                effects.append('color: ' + e)
    return ';'.join(effects)

def applyeffects(chars, effects):
    return '<span style="white-space: pre;%s">%s</span>' % (effects, chars)

def getbgcoloreffect(labels):
    """Map labels like "log.date" to background color if available

    Returns QColor object. You may need to check validity by isValid().
    """
    for l in str(labels).split():
        if not l:
            continue
        for e in _styles.get(l, '').split():
            if e.endswith('_background'):
                return QColor(e[:-11])
    return QColor()

NAME_MAP = {
    'fg': 'color', 'bg': 'background-color', 'family': 'font-family',
    'size': 'font-size', 'weight': 'font-weight', 'space': 'white-space',
    'style': 'font-style', 'decoration': 'text-decoration',
}

def markup(msg, **styles):
    style = {'white-space': 'pre'}
    for name, value in styles.items():
        if not value:
            continue
        if name in NAME_MAP:
            name = NAME_MAP[name]
        style[name] = value
    style = ';'.join(['%s: %s' % t for t in style.items()])
    msg = hglib.tounicode(msg)
    msg = Qt.escape(msg)
    msg = msg.replace('\n', '<br />')
    return u'<span style="%s">%s</span>' % (style, msg)

def descriptionhtmlizer(ui):
    """Return a function to mark up ctx.description() as an HTML

    >>> from mercurial import ui
    >>> u = ui.ui()
    >>> htmlize = descriptionhtmlizer(u)
    >>> htmlize('foo <bar> \\n& <baz>')
    u'foo &lt;bar&gt; \\n&amp; &lt;baz&gt;'

    changeset hash link:
    >>> htmlize('foo af50a62e9c20 bar')
    u'foo <a href="cset:af50a62e9c20">af50a62e9c20</a> bar'
    >>> htmlize('af50a62e9c2040dcdaf61ba6a6400bb45ab56410') # doctest: +ELLIPSIS
    u'<a href="cset:af...10">af...10</a>'

    http/https links:
    >>> s = htmlize('foo http://example.com:8000/foo?bar=baz&bax#blah')
    >>> (s[:63], s[63:]) # doctest: +NORMALIZE_WHITESPACE
    (u'foo <a href="http://example.com:8000/foo?bar=baz&amp;bax#blah">',
     u'http://example.com:8000/foo?bar=baz&amp;bax#blah</a>')
    >>> htmlize('https://example/')
    u'<a href="https://example/">https://example/</a>'

    issue links:
    >>> u.setconfig('tortoisehg', 'issue.regex', r'#(\\d+)\\b')
    >>> u.setconfig('tortoisehg', 'issue.link', 'http://example/issue/{1}/')
    >>> htmlize = descriptionhtmlizer(u)
    >>> htmlize('foo #123')
    u'foo <a href="http://example/issue/123/">#123</a>'

    missing issue.link setting:
    >>> u.setconfig('tortoisehg', 'issue.link', '')
    >>> htmlize = descriptionhtmlizer(u)
    >>> htmlize('foo #123')
    u'foo #123'

    too many replacements in issue.link:
    >>> u.setconfig('tortoisehg', 'issue.link', 'http://example/issue/{1}/{2}')
    >>> htmlize = descriptionhtmlizer(u)
    >>> htmlize('foo #123')
    u'foo #123'

    invalid regexp in issue.regex:
    >>> u.setconfig('tortoisehg', 'issue.regex', '(')
    >>> htmlize = descriptionhtmlizer(u)
    >>> htmlize('foo #123')
    u'foo #123'
    >>> htmlize('http://example/')
    u'<a href="http://example/">http://example/</a>'
    """
    csmatch = r'(\b[0-9a-f]{12}(?:[0-9a-f]{28})?\b)'
    httpmatch = r'(\b(http|https)://([-A-Za-z0-9+&@#/%?=~_()|!:,.;]*' \
                r'[-A-Za-z0-9+&@#/%=~_()|]))'
    regexp = r'%s|%s' % (csmatch, httpmatch)
    bodyre = re.compile(regexp)

    issuematch = ui.config('tortoisehg', 'issue.regex')
    issuerepl = ui.config('tortoisehg', 'issue.link')
    if issuematch and issuerepl:
        regexp += '|(%s)' % issuematch
        try:
            bodyre = re.compile(regexp)
        except re.error:
            pass

    def htmlize(desc):
        """Mark up ctx.description() [localstr] as an HTML [unicode]"""
        desc = unicode(Qt.escape(hglib.tounicode(desc)))

        buf = ''
        pos = 0
        for m in bodyre.finditer(desc):
            a, b = m.span()
            if a >= pos:
                buf += desc[pos:a]
                pos = b
            groups = m.groups()
            if groups[0]:
                cslink = groups[0]
                buf += '<a href="cset:%s">%s</a>' % (cslink, cslink)
            if groups[1]:
                urllink = groups[1]
                buf += '<a href="%s">%s</a>' % (urllink, urllink)
            if len(groups) > 4 and groups[4]:
                issue = groups[4]
                issueparams = groups[4:]
                try:
                    link = re.sub(r'\{(\d+)\}',
                                  lambda m: issueparams[int(m.group(1))],
                                  issuerepl)
                    buf += '<a href="%s">%s</a>' % (link, issue)
                except IndexError:
                    buf += issue

        if pos < len(desc):
            buf += desc[pos:]

        return buf

    return htmlize

_iconcache = {}

def _findicon(name):
    # TODO: icons should be placed at single location before release
    if os.path.isabs(name):
        path = name
        if QFile.exists(path):
            return QIcon(path)
    else:
        for pfx in (':/icons', os.path.join(paths.get_icon_path(), 'svg'),
                    paths.get_icon_path()):
            for ext in ('svg', 'png', 'ico'):
                path = '%s/%s.%s' % (pfx, name, ext)
                if QFile.exists(path):
                    return QIcon(path)

    return None

# http://standards.freedesktop.org/icon-theme-spec/icon-theme-spec-latest.html
_SCALABLE_ICON_PATHS = [(QSize(), 'scalable/actions', '.svg'),
                        (QSize(), 'scalable/apps', '.svg'),
                        (QSize(), 'scalable/status', '.svg'),
                        (QSize(16, 16), '16x16/apps', '.png'),
                        (QSize(22, 22), '22x22/actions', '.png'),
                        (QSize(32, 32), '32x32/actions', '.png'),
                        (QSize(24, 24), '24x24/actions', '.png')]

def _findscalableicon(name):
    """Find icon from qrc by using freedesktop-like icon lookup"""
    o = QIcon()
    for size, subdir, sfx in _SCALABLE_ICON_PATHS:
        path = ':/icons/%s/%s%s' % (subdir, name, sfx)
        if QFile.exists(path):
            for mode in (QIcon.Normal, QIcon.Active):
                o.addFile(path, size, mode)
    if not o.isNull():
        return o

def geticon(name):
    """
    Return a QIcon for the specified name. (the given 'name' parameter
    must *not* provide the extension).

    This searches for the icon from theme, Qt resource or icons directory,
    named as 'name.(svg|png|ico)'.
    """
    if QIcon.hasThemeIcon(name):
        return QIcon.fromTheme(name)

    try:
        return _iconcache[name]
    except KeyError:
        _iconcache[name] = (_findscalableicon(name) or _findicon(name)
                            or QIcon(':/icons/fallback.svg'))
        return _iconcache[name]

if sys.platform == 'darwin':
    # On Mac OS X, we do not want icons on menus
    def getmenuicon(name):
        return QIcon()
else:
    getmenuicon = geticon


def getoverlaidicon(base, overlay):
    """Generate an overlaid icon"""
    pixmap = base.pixmap(16, 16)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.drawPixmap(0, 0, overlay.pixmap(16, 16))
    del painter
    return QIcon(pixmap)


_pixmapcache = {}

def getpixmap(name, width=16, height=16):
    key = '%s_%sx%s' % (name, width, height)
    try:
        return _pixmapcache[key]
    except KeyError:
        pixmap = geticon(name).pixmap(width, height)
    _pixmapcache[key] = pixmap
    return pixmap

class ThgFont(QObject):
    changed = pyqtSignal(QFont)
    def __init__(self, name):
        QObject.__init__(self)
        self.myfont = QFont()
        self.myfont.fromString(name)
    def font(self):
        return self.myfont
    def setFont(self, f):
        self.myfont = f
        self.changed.emit(f)

_fontdefaults = {
    'fontcomment': 'monospace,10',
    'fontdiff': 'monospace,10',
    'fontlist': 'sans,9',
    'fontlog': 'monospace,10',
    'fontoutputlog': 'sans,8'
}
if sys.platform == 'darwin':
    _fontdefaults['fontoutputlog'] = 'sans,10'
_fontcache = {}

def initfontcache(ui):
    for name in _fontdefaults:
        fname = ui.config('tortoisehg', name, _fontdefaults[name])
        _fontcache[name] = ThgFont(fname)

def getfont(name):
    assert name in _fontdefaults
    return _fontcache[name]

def gettranslationpath():
    """Return path to Qt's translation file (.qm)"""
    if getattr(sys, 'frozen', False):
        return ':/translations'
    else:
        return QLibraryInfo.location(QLibraryInfo.TranslationsPath)

def CommonMsgBox(icon, title, main, text='', buttons=QMessageBox.Ok,
                 labels=[], parent=None, defaultbutton=None):
    msg = QMessageBox(parent)
    msg.setIcon(icon)
    msg.setWindowTitle(title)
    msg.setStandardButtons(buttons)
    for button_id, label in labels:
        msg.setButtonText(button_id, label)
    if defaultbutton:
        msg.setDefaultButton(defaultbutton)
    msg.setText('<b>%s</b>' % main)
    info = ''
    for line in text.split('\n'):
        info += '<nobr>%s</nobr><br />' % line
    msg.setInformativeText(info)
    return msg.exec_()

def InfoMsgBox(*args, **kargs):
    return CommonMsgBox(QMessageBox.Information, *args, **kargs)

def WarningMsgBox(*args, **kargs):
    return CommonMsgBox(QMessageBox.Warning, *args, **kargs)

def ErrorMsgBox(*args, **kargs):
    return CommonMsgBox(QMessageBox.Critical, *args, **kargs)

def QuestionMsgBox(*args, **kargs):
    btn = QMessageBox.Yes | QMessageBox.No
    res = CommonMsgBox(QMessageBox.Question, buttons=btn, *args, **kargs)
    return res == QMessageBox.Yes

class CustomPrompt(QMessageBox):
    def __init__(self, title, message, parent, choices, default=None,
                 esc=None, files=None):
        QMessageBox.__init__(self, parent)

        self.setWindowTitle(hglib.tounicode(title))
        self.setText(hglib.tounicode(message))
        if files:
            self.setDetailedText(hglib.tounicode('\n'.join(files)))
        self.hotkeys = {}
        for i, s in enumerate(choices):
            btn = self.addButton(s, QMessageBox.AcceptRole)
            try:
                char = s[s.index('&')+1].lower()
                self.hotkeys[char] = btn
            except (ValueError, IndexError):
                pass
            if default == i:
                self.setDefaultButton(btn)
            if esc == i:
                self.setEscapeButton(btn)

    def run(self):
        return self.exec_()

    def keyPressEvent(self, event):
        for k, btn in self.hotkeys.iteritems():
            if event.text() == k:
                btn.clicked.emit(False)
        super(CustomPrompt, self).keyPressEvent(event)

class ChoicePrompt(QDialog):
    def __init__(self, title, message, parent, choices, default=None,
                 esc=None, files=None):
        QDialog.__init__(self, parent)

        self.setWindowIcon(geticon('thg_logo'))
        self.setWindowTitle(hglib.tounicode(title))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.box = QHBoxLayout()
        self.vbox = QVBoxLayout()
        self.vbox.setSpacing(8)

        self.message_lbl = QLabel()
        self.message_lbl.setText(message)
        self.vbox.addWidget(self.message_lbl)

        self.choice_combo = combo = QComboBox()
        self.choices = choices
        combo.addItems([hglib.tounicode(item) for item in choices])
        if default:
            try:
                combo.setCurrentIndex(choices.index(default))
            except:
                # Ignore a missing default value
                pass
        self.vbox.addWidget(combo)
        self.box.addLayout(self.vbox)
        vbox = QVBoxLayout()
        self.ok = QPushButton('&OK')
        self.ok.clicked.connect(self.accept)
        vbox.addWidget(self.ok)
        self.cancel = QPushButton('&Cancel')
        self.cancel.clicked.connect(self.reject)
        vbox.addWidget(self.cancel)
        vbox.addStretch()
        self.box.addLayout(vbox)
        self.setLayout(self.box)

    def run(self):
        if self.exec_():
            return self.choices[self.choice_combo.currentIndex()]
        return None

def setup_font_substitutions():
    QFont.insertSubstitutions('monospace', ['monaco', 'courier new'])

def fix_application_font():
    if os.name != 'nt':
        return
    try:
        import win32gui, win32con
    except ImportError:
        return

    # use configurable font like GTK, Mozilla XUL or Eclipse SWT
    ncm = win32gui.SystemParametersInfo(win32con.SPI_GETNONCLIENTMETRICS)
    lf = ncm['lfMessageFont']
    f = QFont(hglib.tounicode(lf.lfFaceName))
    f.setItalic(lf.lfItalic)
    if lf.lfWeight != win32con.FW_DONTCARE:
        weights = [(0, QFont.Light), (400, QFont.Normal), (600, QFont.DemiBold),
                   (700, QFont.Bold), (800, QFont.Black)]
        n, w = filter(lambda e: e[0] <= lf.lfWeight, weights)[-1]
        f.setWeight(w)
    f.setPixelSize(abs(lf.lfHeight))
    QApplication.setFont(f, 'QWidget')

class PMButton(QPushButton):
    """Toggle button with plus/minus icon images"""

    def __init__(self, expanded=True, parent=None):
        QPushButton.__init__(self, parent)

        size = QSize(11, 11)
        self.setIconSize(size)
        self.setMaximumSize(size)
        self.setFlat(True)
        self.setAutoDefault(False)

        self.plus = geticon('expander-open')
        self.minus = geticon('expander-close')
        icon = expanded and self.minus or self.plus
        self.setIcon(icon)

        def clicked():
            icon = self.is_expanded() and self.plus or self.minus
            self.setIcon(icon)
        self.clicked.connect(clicked)

    def set_expanded(self, state=True):
        icon = state and self.minus or self.plus
        self.setIcon(icon)

    def set_collapsed(self, state=True):
        icon = state and self.plus or self.minus
        self.setIcon(icon)

    def is_expanded(self):
        return self.icon().serialNumber() == self.minus.serialNumber()

    def is_collapsed(self):
        return not self.is_expanded()

class ClickableLabel(QLabel):

    clicked = pyqtSignal()

    def __init__(self, label, parent=None):
        QLabel.__init__(self, parent)

        self.setText(label)

    def mouseReleaseEvent(self, event):
        self.clicked.emit()

class ExpanderLabel(QWidget):

    expanded = pyqtSignal(bool)

    def __init__(self, label, expanded=True, stretch=True, parent=None):
        QWidget.__init__(self, parent)

        box = QHBoxLayout()
        box.setSpacing(4)
        box.setContentsMargins(*(0,)*4)
        self.button = PMButton(expanded, self)
        self.button.clicked.connect(self.pm_clicked)
        box.addWidget(self.button)
        self.label = ClickableLabel(label, self)
        self.label.clicked.connect(lambda: self.button.click())
        box.addWidget(self.label)
        if not stretch:
            box.addStretch(0)

        self.setLayout(box)

    def pm_clicked(self):
        self.expanded.emit(self.button.is_expanded())

    def set_expanded(self, state=True):
        if not self.button.is_expanded() == state:
            self.button.set_expanded(state)
            self.expanded.emit(state)

    def is_expanded(self):
        return self.button.is_expanded()

class StatusLabel(QWidget):

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)

        box = QHBoxLayout()
        box.setContentsMargins(*(0,)*4)
        self.status_icon = QLabel()
        self.status_icon.setMaximumSize(16, 16)
        self.status_icon.setAlignment(Qt.AlignCenter)
        box.addWidget(self.status_icon)
        self.status_text = QLabel()
        self.status_text.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        box.addWidget(self.status_text)
        box.addStretch(0)

        self.setLayout(box)

    def set_status(self, text, icon=None):
        self.set_text(text)
        self.set_icon(icon)

    def clear_status(self):
        self.clear_text()
        self.clear_icon()

    def set_text(self, text=''):
        if text is None:
            text = ''
        self.status_text.setText(text)

    def clear_text(self):
        self.set_text()

    def set_icon(self, icon=None):
        if icon is None:
            self.clear_icon()
        else:
            if isinstance(icon, bool):
                icon = geticon(icon and 'thg-success' or 'thg-error')
            elif isinstance(icon, basestring):
                icon = geticon(icon)
            elif not isinstance(icon, QIcon):
                raise TypeError, '%s: bool, str or QIcon' % type(icon)
            self.status_icon.setShown(True)
            self.status_icon.setPixmap(icon.pixmap(16, 16))

    def clear_icon(self):
        self.status_icon.setHidden(True)

class LabeledSeparator(QWidget):

    def __init__(self, label=None, parent=None):
        QWidget.__init__(self, parent)

        box = QHBoxLayout()
        box.setContentsMargins(*(0,)*4)

        if label:
            if isinstance(label, basestring):
                label = QLabel(label)
            box.addWidget(label)

        sep = QFrame()
        sep.setFrameShadow(QFrame.Sunken)
        sep.setFrameShape(QFrame.HLine)
        box.addWidget(sep, 1, Qt.AlignVCenter)

        self.setLayout(box)

class InfoBar(QFrame):
    """Non-modal confirmation/alert (like web flash or Chrome's InfoBar)

    You shouldn't reuse InfoBar object after close(). It is automatically
    deleted.

    Layout::

        |widgets ...                |right widgets ...|x|
    """
    linkActivated = pyqtSignal(unicode)

    # type of InfoBar (the number denotes its priority)
    INFO = 1
    ERROR = 2
    CONFIRM = 3

    infobartype = INFO

    _colormap = {
        INFO: '#e7f9e0',
        ERROR: '#f9d8d8',
        CONFIRM: '#fae9b3',
        }

    def __init__(self, parent=None):
        super(InfoBar, self).__init__(parent, frameShape=QFrame.StyledPanel,
                                      frameShadow=QFrame.Plain)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(QPalette.Window, QColor(self._colormap[self.infobartype]))
        p.setColor(QPalette.WindowText, QColor("black"))
        self.setPalette(p)

        self.setLayout(QHBoxLayout())
        self.layout().setContentsMargins(2, 2, 2, 2)

        self.layout().addStretch()
        self._closebutton = QPushButton(self, flat=True, autoDefault=False,
            icon=self.style().standardIcon(QStyle.SP_DockWidgetCloseButton))
        self._closebutton.clicked.connect(self.close)
        self.layout().addWidget(self._closebutton)

    def addWidget(self, w, stretch=0):
        self.layout().insertWidget(self.layout().count() - 2, w, stretch)

    def addRightWidget(self, w):
        self.layout().insertWidget(self.layout().count() - 1, w)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        super(InfoBar, self).keyPressEvent(event)

class StatusInfoBar(InfoBar):
    """Show status message"""
    def __init__(self, message, parent=None):
        super(StatusInfoBar, self).__init__(parent)
        self._msglabel = QLabel(message, self, wordWrap=True,
                                textInteractionFlags=Qt.TextSelectableByMouse \
                                | Qt.LinksAccessibleByMouse)
        self._msglabel.linkActivated.connect(self.linkActivated)
        self.addWidget(self._msglabel, stretch=1)

class CommandErrorInfoBar(InfoBar):
    """Show command execution failure (with link to open log window)"""
    infobartype = InfoBar.ERROR

    def __init__(self, message, parent=None):
        super(CommandErrorInfoBar, self).__init__(parent)

        self._msglabel = QLabel(message, self, wordWrap=True,
                                textInteractionFlags=Qt.TextSelectableByMouse \
                                | Qt.LinksAccessibleByMouse)
        self._msglabel.linkActivated.connect(self.linkActivated)
        self.addWidget(self._msglabel, stretch=1)

        self._loglabel = QLabel('<a href="log:">%s</a>' % _('Show Log'))
        self._loglabel.linkActivated.connect(self.linkActivated)
        self.addRightWidget(self._loglabel)

class ConfirmInfoBar(InfoBar):
    """Show confirmation message with accept/reject buttons"""
    accepted = pyqtSignal()
    rejected = pyqtSignal()
    infobartype = InfoBar.CONFIRM

    def __init__(self, message, parent=None):
        super(ConfirmInfoBar, self).__init__(parent)

        # no wordWrap=True and stretch=1, which inserts unwanted space
        # between _msglabel and _buttons.
        self._msglabel = QLabel(message, self,
                                textInteractionFlags=Qt.TextSelectableByMouse \
                                | Qt.LinksAccessibleByMouse)
        self._msglabel.linkActivated.connect(self.linkActivated)
        self.addWidget(self._msglabel)

        self._buttons = QDialogButtonBox(self)
        self._buttons.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.acceptButton = self._buttons.addButton(QDialogButtonBox.Ok)
        self.rejectButton = self._buttons.addButton(QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self._accept)
        self._buttons.rejected.connect(self._reject)
        self.addWidget(self._buttons)

        # so that acceptButton gets focus by default
        self.setFocusProxy(self._buttons)

    def closeEvent(self, event):
        if self.isVisible():
            self.rejected.emit()
        super(ConfirmInfoBar, self).closeEvent(event)

    @pyqtSlot()
    def _accept(self):
        self.accepted.emit()
        self.hide()
        self.close()

    @pyqtSlot()
    def _reject(self):
        self.rejected.emit()
        self.hide()
        self.close()

class WidgetGroups(object):
    """ Support for bulk-updating properties of Qt widgets """

    def __init__(self):
        object.__init__(self)

        self.clear(all=True)

    ### Public Methods ###

    def add(self, widget, group='default'):
        if group not in self.groups:
            self.groups[group] = []
        widgets = self.groups[group]
        if widget not in widgets:
            widgets.append(widget)

    def remove(self, widget, group='default'):
        if group not in self.groups:
            return
        widgets = self.groups[group]
        if widget in widgets:
            widgets.remove(widget)

    def clear(self, group='default', all=True):
        if all:
            self.groups = {}
        else:
            del self.groups[group]

    def set_prop(self, prop, value, group='default', cond=None):
        if group not in self.groups:
            return
        widgets = self.groups[group]
        if callable(cond):
            widgets = [w for w in widgets if cond(w)]
        for widget in widgets:
            getattr(widget, prop)(value)

    def set_visible(self, *args, **kargs):
        self.set_prop('setVisible', *args, **kargs)

    def set_enable(self, *args, **kargs):
        self.set_prop('setEnabled', *args, **kargs)

class TaskWidget(object):
    def canswitch(self):
        """Return True if the widget allows to switch away from it"""
        return True

    def canExit(self):
        return True

class DemandWidget(QWidget):
    'Create a widget the first time it is shown'

    def __init__(self, createfuncname, createinst, parent=None):
        super(DemandWidget, self).__init__(parent)
        # We store a reference to the create function name to avoid having a
        # hard reference to the bound function, which prevents it being
        # disposed. Weak references to bound functions don't work.
        self._createfuncname = createfuncname
        self._createinst = weakref.ref(createinst)
        self._widget = None
        vbox = QVBoxLayout()
        vbox.setContentsMargins(*(0,)*4)
        self.setLayout(vbox)

    def showEvent(self, event):
        """create the widget if necessary"""
        self.get()
        super(DemandWidget, self).showEvent(event)

    def forward(self, funcname, *args, **opts):
        if self._widget:
            return getattr(self._widget, funcname)(*args, **opts)
        return None

    def get(self):
        """Returns the stored widget"""
        if self._widget is None:
            func = getattr(self._createinst(), self._createfuncname, None)
            self._widget = func()
            self.layout().addWidget(self._widget)
        return self._widget

    def canswitch(self):
        """Return True if the widget allows to switch away from it"""
        if self._widget is None:
            return True
        return self._widget.canswitch()

    def canExit(self):
        if self._widget is None:
            return True
        return self._widget.canExit()

    def __getattr__(self, name):
        return getattr(self._widget, name)

class Spacer(QWidget):
    """Spacer to separate controls in a toolbar"""

    def __init__(self, width, height, parent=None):
        QWidget.__init__(self, parent)
        self.width = width
        self.height = height

    def sizeHint(self):
        return QSize(self.width, self.height)

def getCurrentUsername(widget, repo, opts=None):
    if opts:
        # 1. Override has highest priority
        user = opts.get('user')
        if user:
            return user

    # 2. Read from repository
    try:
        return repo.ui.username()
    except error.Abort:
        pass

    # 3. Get a username from the user
    QMessageBox.information(widget, _('Please enter a username'),
                _('You must identify yourself to Mercurial'),
                QMessageBox.Ok)
    from tortoisehg.hgqt.settings import SettingsDialog
    dlg = SettingsDialog(False, focus='ui.username')
    dlg.exec_()
    repo.invalidateui()
    try:
        return repo.ui.username()
    except error.Abort:
        return None

def getTextInput(parent, title, label, mode=QLineEdit.Normal, text='',
  flags=Qt.WindowFlags()):
    # the flags argument is supported under Qt 4.6, but probably with
    # a different name (see issue 252), so we simply call everything
    # positionally
    return QInputDialog.getText(parent, title, label, mode, text,
      Qt.CustomizeWindowHint | Qt.WindowTitleHint |
      Qt.WindowCloseButtonHint | flags)

def keysequence(o):
    """Create QKeySequence from string or QKeySequence"""
    if isinstance(o, (QKeySequence, QKeySequence.StandardKey)):
        return o
    try:
        return getattr(QKeySequence, str(o))  # standard key
    except AttributeError:
        return QKeySequence(o)

def modifiedkeysequence(o, modifier):
    """Create QKeySequence of modifier key prepended"""
    origseq = QKeySequence(keysequence(o))
    return QKeySequence('%s+%s' % (modifier, origseq.toString()))

def newshortcutsforstdkey(key, *args, **kwargs):
    """Create [QShortcut,...] for all key bindings of the given StandardKey"""
    return [QShortcut(keyseq, *args, **kwargs)
            for keyseq in QKeySequence.keyBindings(key)]
