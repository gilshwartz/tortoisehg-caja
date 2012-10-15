# Copyright (c) 2009-2010 LOGILAB S.A. (Paris, FRANCE).
# http://www.logilab.fr/ -- mailto:contact@logilab.fr
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import binascii, re

from mercurial import util, error
from mercurial.util import propertycache
from mercurial.context import workingctx

from tortoisehg.util import hglib
from tortoisehg.hgqt.graph import Graph
from tortoisehg.hgqt.graph import revision_grapher
from tortoisehg.hgqt import qtlib
from tortoisehg.hgqt.qreorder import writeSeries

from tortoisehg.hgqt.i18n import _

from PyQt4.QtCore import *
from PyQt4.QtGui import *

nullvariant = QVariant()

mqpatchmimetype = 'application/thg-mqunappliedpatch'

# TODO: Remove these two when we adopt GTK author color scheme
COLORS = [ "blue", "darkgreen", "red", "green", "darkblue", "purple",
           "dodgerblue", Qt.darkYellow, "magenta", "darkred", "darkmagenta",
           "darkcyan", "gray", ]
COLORS = [str(QColor(x).name()) for x in COLORS]

COLUMNHEADERS = (
    ('Graph', _('Graph', 'column header')),
    ('Rev', _('Rev', 'column header')),
    ('Branch', _('Branch', 'column header')),
    ('Description', _('Description', 'column header')),
    ('Author', _('Author', 'column header')),
    ('Tags', _('Tags', 'column header')),
    ('Node', _('Node', 'column header')),
    ('Age', _('Age', 'column header')),
    ('LocalTime', _('Local Time', 'column header')),
    ('UTCTime', _('UTC Time', 'column header')),
    ('Changes', _('Changes', 'column header')),
    ('Converted', _('Converted From', 'column header')),
    ('Phase', _('Phase', 'column header')),
    )

UNAPPLIED_PATCH_COLOR = '#999999'

def get_color(n, ignore=()):
    """
    Return a color at index 'n' rotating in the available
    colors. 'ignore' is a list of colors not to be chosen.
    """
    ignore = [str(QColor(x).name()) for x in ignore]
    colors = [x for x in COLORS if x not in ignore]
    if not colors: # ghh, no more available colors...
        colors = COLORS
    return colors[n % len(colors)]

def _parsebranchcolors(value):
    r"""Parse tortoisehg.branchcolors setting

    >>> _parsebranchcolors('foo:#123456  bar:#789abc ')
    [('foo', '#123456'), ('bar', '#789abc')]
    >>> _parsebranchcolors(r'foo\ bar:black foo\:bar:white')
    [('foo bar', 'black'), ('foo:bar', 'white')]

    >>> _parsebranchcolors(r'\u00c0:black')
    [('\xc0', 'black')]
    >>> _parsebranchcolors('\xc0:black')
    [('\xc0', 'black')]

    >>> _parsebranchcolors(None)
    []
    >>> _parsebranchcolors('ill:formed:value no-value')
    []
    >>> _parsebranchcolors(r'\ubad:unicode-repr')
    []
    """
    if not value:
        return []

    colors = []
    for e in re.split(r'(?:(?<=\\\\)|(?<!\\)) ', value):
        pair = re.split(r'(?:(?<=\\\\)|(?<!\\)):', e)
        if len(pair) != 2:
            continue # ignore ill-formed
        key, val = pair
        key = key.replace('\\:', ':').replace('\\ ', ' ')
        if r'\u' in key:
            # apply unicode_escape only if \u found, so that raw non-ascii
            # value isn't always mangled.
            try:
                key = hglib.fromunicode(key.decode('unicode_escape'))
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
        colors.append((key, val))
    return colors

class HgRepoListModel(QAbstractTableModel):
    """
    Model used for displaying the revisions of a Hg *local* repository
    """
    showMessage = pyqtSignal(unicode)
    filled = pyqtSignal()
    loaded = pyqtSignal()

    _allcolumns = tuple(h[0] for h in COLUMNHEADERS)
    _allcolnames = dict(COLUMNHEADERS)

    _columns = ('Graph', 'Rev', 'Branch', 'Description', 'Author', 'Age', 'Tags', 'Phase',)
    _stretchs = {'Description': 1, }
    _mqtags = ('qbase', 'qtip', 'qparent')

    def __init__(self, repo, cfgname, branch, revset, rfilter, parent):
        """
        repo is a hg repo instance
        """
        QAbstractTableModel.__init__(self, parent)
        self._cache = []
        self.graph = None
        self.timerHandle = None
        self.dotradius = 8
        self.rowheight = 20
        self.rowcount = 0
        self.repo = repo
        self.revset = revset
        self.filterbyrevset = rfilter
        self.unicodestar = True
        self.unicodexinabox = True
        self.cfgname = cfgname

        # To be deleted
        self._user_colors = {}
        self._branch_colors = {}

        if repo:
            self.initBranchColors()
            self.reloadConfig()
            self.updateColumns()
            self.setBranch(branch)

    def initBranchColors(self):
        # Set all the branch colors once on a fixed order,
        # which should make the branch colors more stable

        # Always assign the first color to the default branch
        self.namedbranch_color('default')

        # Set the colors specified in the tortoisehg.brachcolors config key
        self._branch_colors.update(_parsebranchcolors(
            self.repo.ui.config('tortoisehg', 'branchcolors')))

        # Then assign colors to all branches in alphabetical order
        # Note that re-assigning the color to the default branch
        # is not expensive
        for branch in sorted(self.repo.branchtags().keys()):
            self.namedbranch_color(branch)

    def setBranch(self, branch=None, allparents=False):
        self.filterbranch = branch  # unicode
        self.invalidateCache()
        if self.revset and self.filterbyrevset:
            grapher = revision_grapher(self.repo,
                                       branch=hglib.fromunicode(branch),
                                       revset=self.revset)
            self.graph = Graph(self.repo, grapher, include_mq=False)
        else:
            grapher = revision_grapher(self.repo,
                                       branch=hglib.fromunicode(branch),
                                       allparents=allparents)
            self.graph = Graph(self.repo, grapher, include_mq=True)
        self.rowcount = 0
        self.layoutChanged.emit()
        self.ensureBuilt(row=0)
        self.showMessage.emit('')
        QTimer.singleShot(0, lambda: self.filled.emit())

    def reloadConfig(self):
        _ui = self.repo.ui
        self.fill_step = int(_ui.config('tortoisehg', 'graphlimit', 500))
        self.authorcolor = _ui.configbool('tortoisehg', 'authorcolor')

    def updateColumns(self):
        s = QSettings()
        cols = s.value(self.cfgname + '/columns').toStringList()
        cols = [str(col) for col in cols]
        # Fixup older names for columns
        if 'Log' in cols:
            cols[cols.index('Log')] = 'Description'
            s.setValue(self.cfgname + '/columns', cols)
        if 'ID' in cols:
            cols[cols.index('ID')] = 'Rev'
            s.setValue(self.cfgname + '/columns', cols)
        validcols = [col for col in cols if col in self._allcolumns]
        if validcols:
            self._columns = tuple(validcols)
            self.invalidateCache()
            self.layoutChanged.emit()

    def invalidate(self):
        self.reloadConfig()
        self.invalidateCache()
        self.layoutChanged.emit()

    def branch(self):
        return self.filterbranch

    def ensureBuilt(self, rev=None, row=None):
        """
        Make sure rev data is available (graph element created).

        """
        if self.graph.isfilled():
            return
        required = 0
        buildrev = rev
        n = len(self.graph)
        if rev is not None:
            if n and self.graph[-1].rev <= rev:
                buildrev = None
            else:
                required = self.fill_step/2
        elif row is not None and row > (n - self.fill_step / 2):
            required = row - n + self.fill_step
        if required or buildrev:
            self.graph.build_nodes(nnodes=required, rev=buildrev)
            self.updateRowCount()

        if self.rowcount >= len(self.graph):
            return  # no need to update row count
        if row and row > self.rowcount:
            # asked row was already built, but views where not aware of this
            self.updateRowCount()
        elif rev is not None and rev <= self.graph[self.rowcount].rev:
            # asked rev was already built, but views where not aware of this
            self.updateRowCount()

    def loadall(self):
        self.timerHandle = self.startTimer(1)

    def timerEvent(self, event):
        if event.timerId() == self.timerHandle:
            self.showMessage.emit(_('filling (%d)')%(len(self.graph)))
            if self.graph.isfilled():
                self.killTimer(self.timerHandle)
                self.timerHandle = None
                self.showMessage.emit('')
                self.loaded.emit()
            # we only fill the graph data structures without telling
            # views until the model is loaded, to keep maximal GUI
            # reactivity
            elif not self.graph.build_nodes():
                self.killTimer(self.timerHandle)
                self.timerHandle = None
                self.updateRowCount()
                self.showMessage.emit('')
                self.loaded.emit()

    def updateRowCount(self):
        currentlen = self.rowcount
        newlen = len(self.graph)

        if newlen > self.rowcount:
            self.beginInsertRows(QModelIndex(), currentlen, newlen-1)
            self.rowcount = newlen
            self.endInsertRows()

    def rowCount(self, parent):
        if parent.isValid():
            return 0
        return self.rowcount

    def columnCount(self, parent):
        if parent.isValid():
            return 0
        return len(self._columns)

    def maxWidthValueForColumn(self, col):
        if self.graph is None:
            return 'XXXX'
        column = self._columns[col]
        if column == 'Rev':
            return '8' * len(str(len(self.repo))) + '+'
        if column == 'Node':
            return '8' * 12 + '+'
        if column in ('LocalTime', 'UTCTime'):
            return hglib.displaytime(util.makedate())
        if column == 'Tags':
            try:
                return sorted(self.repo.tags().keys(), key=lambda x: len(x))[-1][:10]
            except IndexError:
                pass
        if column == 'Branch':
            try:
                return sorted(self.repo.branchtags().keys(), key=lambda x: len(x))[-1]
            except IndexError:
                pass
        if column == 'Filename':
            return self.filename
        if column == 'Graph':
            res = self.col2x(self.graph.max_cols)
            return min(res, 150)
        if column == 'Changes':
            return 'Changes'
        # Fall through for Description
        return None

    def user_color(self, user):
        'deprecated, please replace with hgtk color scheme'
        if user not in self._user_colors:
            self._user_colors[user] = get_color(len(self._user_colors),
                                                self._user_colors.values())
        return self._user_colors[user]

    def namedbranch_color(self, branch):
        'deprecated, please replace with hgtk color scheme'
        if branch not in self._branch_colors:
            self._branch_colors[branch] = get_color(len(self._branch_colors))
        return self._branch_colors[branch]

    def col2x(self, col):
        return 2 * self.dotradius * col + self.dotradius/2 + 8

    def graphctx(self, ctx, gnode):
        w = self.col2x(gnode.cols) + 10
        h = self.rowheight

        pix = QPixmap(w, h)
        pix.fill(QColor(0,0,0,0))
        painter = QPainter(pix)
        try:
            self._drawgraphctx(painter, pix, ctx, gnode)
        finally:
            painter.end()
        return QVariant(pix)

    def _drawgraphctx(self, painter, pix, ctx, gnode):
        h = pix.height()
        dot_y = h / 2

        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen(Qt.blue)
        pen.setWidth(2)
        painter.setPen(pen)

        lpen = QPen(pen)
        lpen.setColor(Qt.black)
        painter.setPen(lpen)
        for y1, y4, lines in ((dot_y, dot_y + h, gnode.bottomlines),
                              (dot_y - h, dot_y, gnode.toplines)):
            y2 = y1 + 1 * (y4 - y1)/4
            ymid = (y1 + y4)/2
            y3 = y1 + 3 * (y4 - y1)/4

            for start, end, color in lines:
                lpen = QPen(pen)
                lpen.setColor(QColor(get_color(color)))
                lpen.setWidth(2)
                painter.setPen(lpen)
                x1 = self.col2x(start)
                x2 = self.col2x(end)
                path = QPainterPath()
                path.moveTo(x1, y1)
                path.cubicTo(x1, y2,
                             x1, y2,
                             (x1 + x2)/2, ymid)
                path.cubicTo(x2, y3,
                             x2, y3,
                             x2, y4)
                painter.drawPath(path)

        # Draw node
        dot_color = QColor(self.namedbranch_color(ctx.branch()))
        dotcolor = dot_color.lighter()
        pencolor = dot_color.darker()
        white = QColor("white")
        fillcolor = gnode.rev is None and white or dotcolor

        pen = QPen(pencolor)
        pen.setWidthF(1.5)
        painter.setPen(pen)

        radius = self.dotradius
        centre_x = self.col2x(gnode.x)
        centre_y = h/2

        def circle(r):
            rect = QRectF(centre_x - r,
                          centre_y - r,
                          2 * r, 2 * r)
            painter.drawEllipse(rect)

        def closesymbol(s):
            rect_ = QRectF(centre_x - 1.5 * s, centre_y - 0.5 * s, 3 * s, s)
            painter.drawRect(rect_)

        def diamond(r):
            poly = QPolygonF([QPointF(centre_x - r, centre_y),
                              QPointF(centre_x, centre_y - r),
                              QPointF(centre_x + r, centre_y),
                              QPointF(centre_x, centre_y + r),
                              QPointF(centre_x - r, centre_y),])
            painter.drawPolygon(poly)

        if ctx.thgmqappliedpatch():  # diamonds for patches
            if ctx.thgwdparent():
                painter.setBrush(white)
                diamond(2 * 0.9 * radius / 1.5)
            painter.setBrush(fillcolor)
            diamond(radius / 1.5)
        elif ctx.thgmqunappliedpatch():
            patchcolor = QColor('#dddddd')
            painter.setBrush(patchcolor)
            painter.setPen(patchcolor)
            diamond(radius / 1.5)
        elif ctx.extra().get('close'):
            painter.setBrush(fillcolor)
            closesymbol(0.5 * radius)
        else:  # circles for normal revisions
            if ctx.thgwdparent():
                painter.setBrush(white)
                circle(0.9 * radius)
            painter.setBrush(fillcolor)
            circle(0.5 * radius)

    def invalidateCache(self):
        self._cache = []
        for a in ('_roleoffsets',):
            if hasattr(self, a):
                delattr(self, a)

    @propertycache
    def _roleoffsets(self):
        return {Qt.DisplayRole : 0,
                Qt.ForegroundRole : len(self._columns),
                Qt.DecorationRole : len(self._columns) * 2}

    def data(self, index, role):
        if not index.isValid():
            return nullvariant
        if role not in self._roleoffsets:
            return nullvariant
        try:
            return self.safedata(index, role)
        except Exception, e:
            if role == Qt.DisplayRole:
                return QVariant(hglib.tounicode(str(e)))
            else:
                return nullvariant

    def safedata(self, index, role):
        row = index.row()
        self.ensureBuilt(row=row)
        graphlen = len(self.graph)
        cachelen = len(self._cache)
        if graphlen > cachelen:
            self._cache.extend([None,] * (graphlen-cachelen))
        data = self._cache[row]
        if data is None:
            data = [None,] * (self._roleoffsets[Qt.DecorationRole]+1)
        column = self._columns[index.column()]
        offset = self._roleoffsets[role]
        if role == Qt.DecorationRole:
            if column != 'Graph':
                return nullvariant
            if data[offset] is None:
                gnode = self.graph[row]
                ctx = self.repo.changectx(gnode.rev)
                data[offset] = self.graphctx(ctx, gnode)
                self._cache[row] = data
            return data[offset]
        else:
            idx = index.column() + offset
            if data[idx] is None:
                try:
                    result = self.rawdata(row, column, role)
                except util.Abort:
                    result = nullvariant
                data[idx] = result
                self._cache[row] = data
            return data[idx]

    def rawdata(self, row, column, role):
        gnode = self.graph[row]
        ctx = self.repo.changectx(gnode.rev)

        if role == Qt.DisplayRole:
            text = self._columnmap[column](self, ctx, gnode)
            if not isinstance(text, (QString, unicode)):
                text = hglib.tounicode(text)
            return QVariant(text)
        elif role == Qt.ForegroundRole:
            if ctx.thgmqunappliedpatch():
                return QColor(UNAPPLIED_PATCH_COLOR)
            if column == 'Author':
                if self.authorcolor:
                    return QVariant(QColor(self.user_color(ctx.user())))
                return nullvariant
            if column == 'Branch':
                return QVariant(QColor(self.namedbranch_color(ctx.branch())))
        return nullvariant

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlags(0)
        row = index.row()
        self.ensureBuilt(row=row)
        if row >= len(self.graph):
            return Qt.ItemFlags(0)
        gnode = self.graph[row]
        ctx = self.repo.changectx(gnode.rev)

        dragflags = Qt.ItemFlags(0)
        if ctx.thgmqunappliedpatch():
            dragflags = Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        if isinstance(ctx, workingctx):
            dragflags |= Qt.ItemIsDropEnabled
        if not self.revset:
            return Qt.ItemIsSelectable | Qt.ItemIsEnabled | dragflags
        if ctx.rev() not in self.revset:
            return Qt.ItemFlags(0)
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled | dragflags

    def mimeTypes(self):
        return QStringList([mqpatchmimetype])

    def supportedDropActions(self):
        return Qt.MoveAction

    def mimeData(self, indexes):
        data = set()
        for index in indexes:
            row = str(index.row())
            if row not in data:
                data.add(row)
        qmd = QMimeData()
        bytearray = QByteArray(','.join(sorted(data, reverse=True)))
        qmd.setData(mqpatchmimetype, bytearray)
        return qmd

    def dropMimeData(self, data, action, row, column, parent):
        if mqpatchmimetype not in data.formats():
            return False
        dragrows = [int(r) for r in str(data.data(mqpatchmimetype)).split(',')]
        destrow = parent.row() - len([r for r in dragrows if r < parent.row()])
        if destrow < 0:
            return False
        unapplied = self.repo.thgmqunappliedpatches[::-1]
        applied = [p.name for p in self.repo.mq.applied[::-1]]
        if max(dragrows) >= len(unapplied):
            return False
        dragpatches = [unapplied[d] for d in dragrows]
        for i in dragrows:
            unapplied.pop(i)
        for p in dragpatches:
            unapplied.insert(destrow, p)
        writeSeries(self.repo, applied, unapplied)
        return True

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return QVariant(self._allcolnames[self._columns[section]])
            if role == Qt.TextAlignmentRole:
                return QVariant(Qt.AlignLeft)
        return nullvariant

    def rowFromRev(self, rev):
        row = self.graph.index(rev)
        if row == -1:
            row = None
        return row

    def indexFromRev(self, rev):
        if self.graph is None:
            return None
        self.ensureBuilt(rev=rev)
        row = self.rowFromRev(rev)
        if row is not None:
            return self.index(row, 0)
        return None

    def clear(self):
        'empty the list'
        self.graph = None
        self.datacache = {}
        self.layoutChanged.emit()

    def getbranch(self, ctx, gnode):
        b = hglib.tounicode(ctx.branch())
        if ctx.extra().get('close'):
            if self.unicodexinabox:
                b += u' \u2327'
            else:
                b += u'--'
        return b

    def gettags(self, ctx, gnode):
        if ctx.rev() is None:
            return ''
        tags = [t for t in ctx.tags() if t not in self._mqtags]
        return hglib.tounicode(','.join(tags))

    def getrev(self, ctx, gnode):
        rev = ctx.rev()
        if type(rev) is int:
            return str(rev)
        elif rev is None:
            return u'%d+' % ctx.p1().rev()
        else:
            return ''

    def getauthor(self, ctx, gnode):
        try:
            return hglib.username(ctx.user())
        except error.Abort:
            return _('Mercurial User')

    def getlog(self, ctx, gnode):
        if ctx.rev() is None:
            msg = None
            if self.unicodestar:
                # The Unicode symbol is a black star:
                msg = u'\u2605 ' + _('Working Directory') + u' \u2605'
            else:
                msg = '*** ' + _('Working Directory') + ' ***'

            for pctx in ctx.parents():
                if self.repo._branchheads and pctx.node() not in self.repo._branchheads:
                    text = _('Not a head revision!')
                    msg += " " + qtlib.markup(text, fg='red', weight='bold')

            return msg

        msg = ctx.longsummary()

        if ctx.thgmqunappliedpatch():
            effects = qtlib.geteffect('log.unapplied_patch')
            text = qtlib.applyeffects(' %s ' % ctx._patchname, effects)
            # qtlib.markup(msg, fg=UNAPPLIED_PATCH_COLOR)
            msg = qtlib.markup(msg)
            return hglib.tounicode(text + ' ') + msg

        parts = []
        if ctx.thgbranchhead():
            branchu = hglib.tounicode(ctx.branch())
            effects = qtlib.geteffect('log.branch')
            parts.append(qtlib.applyeffects(u' %s ' % branchu, effects))

        for mark in ctx.bookmarks():
            style = 'log.bookmark'
            if mark == self.repo._bookmarkcurrent:
                bn = self.repo._bookmarks[self.repo._bookmarkcurrent]
                if bn in self.repo.dirstate.parents():
                    style = 'log.curbookmark'
            marku = hglib.tounicode(mark)
            effects = qtlib.geteffect(style)
            parts.append(qtlib.applyeffects(u' %s ' % marku, effects))

        for tag in ctx.thgtags():
            if self.repo.thgmqtag(tag):
                style = 'log.patch'
            else:
                style = 'log.tag'
            tagu = hglib.tounicode(tag)
            effects = qtlib.geteffect(style)
            parts.append(qtlib.applyeffects(u' %s ' % tagu, effects))

        if msg:
            if ctx.thgwdparent():
                msg = qtlib.markup(msg, weight='bold')
            else:
                msg = qtlib.markup(msg)
            parts.append(hglib.tounicode(msg))

        return ' '.join(parts)

    def getchanges(self, ctx, gnode):
        """Return the MAR status for the given ctx."""
        changes = []
        M, A, R = ctx.changesToParent(0)
        def addtotal(files, style):
            effects = qtlib.geteffect(style)
            text = qtlib.applyeffects(' %s ' % len(files), effects)
            changes.append(text)
        if A:
            addtotal(A, 'log.added')
        if M:
            addtotal(M, 'log.modified')
        if R:
            addtotal(R, 'log.removed')
        return ''.join(changes)

    def getconv(self, ctx, gnode):
        if ctx.rev() is not None:
            extra = ctx.extra()
            cvt = extra.get('convert_revision', '')
            if cvt:
                if cvt.startswith('svn:'):
                    return cvt.split('@')[-1]
                if len(cvt) == 40:
                    try:
                        binascii.unhexlify(cvt)
                        return cvt[:12]
                    except TypeError:
                        pass
            cvt = extra.get('p4', '')
            if cvt:
                return cvt
        return ''

    def getphase(self, ctx, gnode):
        if ctx.rev() is None:
            return ''
        try:
            return ctx.phasestr()
        except:
            return 'draft'

    _columnmap = {
        'Rev':      getrev,
        'Node':     lambda self, ctx, gnode: str(ctx),
        'Graph':    lambda self, ctx, gnode: "",
        'Description': getlog,
        'Author':   getauthor,
        'Tags':     gettags,
        'Branch':   getbranch,
        'Filename': lambda self, ctx, gnode: gnode.extra[0],
        'Age':      lambda self, ctx, gnode: hglib.age(ctx.date()).decode('utf-8'),
        'LocalTime':lambda self, ctx, gnode: hglib.displaytime(ctx.date()),
        'UTCTime':  lambda self, ctx, gnode: hglib.utctime(ctx.date()),
        'Changes':  getchanges,
        'Converted': getconv,
        'Phase':    getphase,
    }
