# hglib.py - Mercurial API wrappers for TortoiseHg
#
# Copyright 2007 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import sys
import shlex
import time
import urllib

from mercurial import ui, util, extensions, match, bundlerepo, cmdutil
from mercurial import encoding, templatefilters, filemerge, error, scmutil
from mercurial import dispatch as hgdispatch

_encoding = encoding.encoding
_encodingmode = encoding.encodingmode
_fallbackencoding = encoding.fallbackencoding

# extensions which can cause problem with TortoiseHg
_extensions_blacklist = ('color', 'pager', 'progress')

from tortoisehg.util import paths
from tortoisehg.util.hgversion import hgversion
from tortoisehg.util.i18n import _, ngettext

def tounicode(s):
    """
    Convert the encoding of string from MBCS to Unicode.

    Based on mercurial.util.tolocal().
    Return 'unicode' type string.
    """
    if s is None:
        return None
    if isinstance(s, unicode):
        return s
    if isinstance(s, encoding.localstr):
        return s._utf8.decode('utf-8')
    for e in ('utf-8', _encoding):
        try:
            return s.decode(e, 'strict')
        except UnicodeDecodeError:
            pass
    return s.decode(_fallbackencoding, 'replace')

def fromunicode(s, errors='strict'):
    """
    Convert the encoding of string from Unicode to MBCS.

    Return 'str' type string.

    If you don't want an exception for conversion failure,
    specify errors='replace'.
    """
    if s is None:
        return None
    s = unicode(s)  # s can be QtCore.QString
    for enc in (_encoding, _fallbackencoding):
        try:
            l = s.encode(enc)
            if s == l.decode(enc):
                return l  # non-lossy encoding
            return encoding.localstr(s.encode('utf-8'), l)
        except UnicodeEncodeError:
            pass

    l = s.encode(_encoding, errors)  # last ditch
    return encoding.localstr(s.encode('utf-8'), l)

def toutf(s):
    """
    Convert the encoding of string from MBCS to UTF-8.

    Return 'str' type string.
    """
    if s is None:
        return None
    if isinstance(s, encoding.localstr):
        return s._utf8
    return tounicode(s).encode('utf-8').replace('\0','')

def fromutf(s):
    """
    Convert the encoding of string from UTF-8 to MBCS

    Return 'str' type string.
    """
    if s is None:
        return None
    try:
        return fromunicode(s.decode('utf-8'), 'replace')
    except UnicodeDecodeError:
        # can't round-trip
        return str(fromunicode(s.decode('utf-8', 'replace'), 'replace'))

_tabwidth = None
def gettabwidth(ui):
    global _tabwidth
    if _tabwidth is not None:
        return _tabwidth
    tabwidth = ui.config('tortoisehg', 'tabwidth')
    try:
        tabwidth = int(tabwidth)
        if tabwidth < 1 or tabwidth > 16:
            tabwidth = 0
    except (ValueError, TypeError):
        tabwidth = 0
    _tabwidth = tabwidth
    return tabwidth

_maxdiff = None
def getmaxdiffsize(ui):
    global _maxdiff
    if _maxdiff is not None:
        return _maxdiff
    maxdiff = ui.config('tortoisehg', 'maxdiff')
    try:
        maxdiff = int(maxdiff)
        if maxdiff < 1:
            maxdiff = sys.maxint
    except (ValueError, TypeError):
        maxdiff = 1024 # 1MB by default
    _maxdiff = maxdiff * 1024
    return _maxdiff

_deadbranch = None
def getdeadbranch(ui):
    '''return a list of dead branch names in UTF-8'''
    global _deadbranch
    if _deadbranch is None:
        db = toutf(ui.config('tortoisehg', 'deadbranch', ''))
        dblist = [b.strip() for b in db.split(',')]
        _deadbranch = dblist
    return _deadbranch

def getlivebranch(repo):
    '''return a list of live branch names in UTF-8'''
    lives = []
    deads = getdeadbranch(repo.ui)
    cl = repo.changelog
    for branch, heads in repo.branchmap().iteritems():
        # branch encoded in UTF-8
        if branch in deads:
            # ignore branch names in tortoisehg.deadbranch
            continue
        bheads = [h for h in heads if ('close' not in cl.read(h)[5])]
        if not bheads:
            # ignore branches with all heads closed
            continue
        lives.append(branch.replace('\0', ''))
    return lives

def getlivebheads(repo):
    '''return a list of revs of live branch heads'''
    bheads = []
    for b, ls in repo.branchmap().iteritems():
        bheads += [repo[x] for x in ls]
    heads = [x.rev() for x in bheads if not x.extra().get('close')]
    heads.sort()
    heads.reverse()
    return heads

_hidetags = None
def gethidetags(ui):
    global _hidetags
    if _hidetags is None:
        tags = toutf(ui.config('tortoisehg', 'hidetags', ''))
        taglist = [t.strip() for t in tags.split()]
        _hidetags = taglist
    return _hidetags

def getfilteredtags(repo):
    filtered = []
    hides = gethidetags(repo.ui)
    for tag in list(repo.tags()):
        if tag not in hides:
            filtered.append(tag)
    return filtered

def getrawctxtags(changectx):
    '''Returns the tags for changectx, converted to UTF-8 but
    unfiltered for hidden tags'''
    value = [toutf(tag) for tag in changectx.tags()]
    if len(value) == 0:
        return None
    return value

def getctxtags(changectx):
    '''Returns all unhidden tags for changectx, converted to UTF-8'''
    value = getrawctxtags(changectx)
    if value:
        htlist = gethidetags(changectx._repo.ui)
        tags = [tag for tag in value if tag not in htlist]
        if len(tags) == 0:
            return None
        return tags
    return None

def getmqpatchtags(repo):
    '''Returns all tag names used by MQ patches, or []'''
    if hasattr(repo, 'mq'):
        repo.mq.parse_series()
        return repo.mq.series[:]
    else:
        return []

def getcurrentqqueue(repo):
    """Return the name of the current patch queue."""
    if not hasattr(repo, 'mq'):
        return None
    cur = os.path.basename(repo.mq.path)
    if cur.startswith('patches-'):
        cur = cur[8:]
    return cur

def diffexpand(line):
    'Expand tabs in a line of diff/patch text'
    if _tabwidth is None:
        gettabwidth(ui.ui())
    if not _tabwidth or len(line) < 2:
        return line
    return line[0] + line[1:].expandtabs(_tabwidth)

_fontconfig = None
def getfontconfig(_ui=None):
    global _fontconfig
    if _fontconfig is None:
        if _ui is None:
            _ui = ui.ui()
        # defaults
        _fontconfig = {'fontcomment': 'monospace 10',
                       'fontdiff': 'monospace 10',
                       'fontlist': 'sans 9',
                       'fontlog': 'monospace 10'}
        # overwrite defaults with configured values
        for name, val in _ui.configitems('gtools'):
            if val and name.startswith('font'):
                _fontconfig[name] = val
    return _fontconfig

def invalidaterepo(repo):
    repo.dirstate.invalidate()
    for attr in ('_bookmarks', '_bookmarkcurrent'):
        if attr in repo.__dict__:
            delattr(repo, attr)
    if isinstance(repo, bundlerepo.bundlerepository):
        # Work around a bug in hg-1.3.  repo.invalidate() breaks
        # overlay bundlerepos
        return
    repo.invalidate()
    if 'mq' in repo.__dict__: #do not create if it does not exist
        repo.mq.invalidate()

def enabledextensions():
    """Return the {name: shortdesc} dict of enabled extensions

    shortdesc is in local encoding.
    """
    ret = extensions.enabled()
    if type(ret) is tuple:
        # hg <= 1.8
        return ret[0]
    else:
        # hg <= 1.9
        return ret

def disabledextensions():
    ret = extensions.disabled()
    if type(ret) is tuple:
        # hg <= 1.8
        return ret[0] or {}
    else:
        # hg <= 1.9
        return ret or {}

def allextensions():
    """Return the {name: shortdesc} dict of known extensions

    shortdesc is in local encoding.
    """
    enabledexts = enabledextensions()
    disabledexts = disabledextensions()
    exts = (disabledexts or {}).copy()
    exts.update(enabledexts)
    return exts

def validateextensions(enabledexts):
    """Report extensions which should be disabled

    Returns the dict {name: message} of extensions expected to be disabled.
    message is 'utf-8'-encoded string.
    """
    exts = {}
    if os.name != 'posix':
        exts['inotify'] = _('inotify is not supported on this platform')
    if 'win32text' in enabledexts:
        exts['eol'] = _('eol is incompatible with win32text')
    if 'eol' in enabledexts:
        exts['win32text'] = _('win32text is incompatible with eol')
    if 'perfarce' in enabledexts:
        exts['hgsubversion'] = _('hgsubversion is incompatible with perfarce')
    if 'hgsubversion' in enabledexts:
        exts['perfarce'] = _('perfarce is incompatible with hgsubversion')
    return exts

def loadextension(ui, name):
    # Between Mercurial revisions 1.2 and 1.3, extensions.load() stopped
    # calling uisetup() after loading an extension.  This could do
    # unexpected things if you use an hg version < 1.3
    extensions.load(ui, name, None)
    mod = extensions.find(name)
    uisetup = getattr(mod, 'uisetup', None)
    if uisetup:
        uisetup(ui)

def _loadextensionwithblacklist(orig, ui, name, path):
    if name.startswith('hgext.') or name.startswith('hgext/'):
        shortname = name[6:]
    else:
        shortname = name
    if shortname in _extensions_blacklist and not path:  # only bundled ext
        return

    return orig(ui, name, path)

def wrapextensionsloader():
    """Wrap extensions.load(ui, name) for blacklist to take effect"""
    extensions.wrapfunction(extensions, 'load',
                            _loadextensionwithblacklist)

def canonpaths(list):
    'Get canonical paths (relative to root) for list of files'
    # This is a horrible hack.  Please remove this when HG acquires a
    # decent case-folding solution.
    canonpats = []
    cwd = os.getcwd()
    root = paths.find_root(cwd)
    for f in list:
        try:
            canonpats.append(scmutil.canonpath(root, cwd, f))
        except util.Abort:
            # Attempt to resolve case folding conflicts.
            fu = f.upper()
            cwdu = cwd.upper()
            if fu.startswith(cwdu):
                canonpats.append(scmutil.canonpath(root, cwd,
                                                   f[len(cwd+os.sep):]))
            else:
                # May already be canonical
                canonpats.append(f)
    return canonpats

def escapepath(path):
    'Before passing a file path to hg API, it may need escaping'
    p = path
    if '[' in p or '{' in p or '*' in p or '?' in p:
        return 'path:' + p
    else:
        return p

def normpats(pats):
    'Normalize file patterns'
    normpats = []
    for pat in pats:
        kind, p = match._patsplit(pat, None)
        if kind:
            normpats.append(pat)
        else:
            if '[' in p or '{' in p or '*' in p or '?' in p:
                normpats.append('glob:' + p)
            else:
                normpats.append('path:' + p)
    return normpats


def mergetools(ui, values=None):
    'returns the configured merge tools and the internal ones'
    if values == None:
        values = []
    seen = values[:]
    for key, value in ui.configitems('merge-tools'):
        t = key.split('.')[0]
        if t not in seen:
            seen.append(t)
            # Ensure the tool is installed
            if filemerge._findtool(ui, t):
                values.append(t)
    values.append('internal:merge')
    values.append('internal:prompt')
    values.append('internal:dump')
    values.append('internal:local')
    values.append('internal:other')
    values.append('internal:fail')
    return values


_difftools = None
def difftools(ui):
    global _difftools
    if _difftools:
        return _difftools

    def fixup_extdiff(diffopts):
        if '$child' not in diffopts:
            diffopts.append('$parent1')
            diffopts.append('$child')
        if '$parent2' in diffopts:
            mergeopts = diffopts[:]
            diffopts.remove('$parent2')
        else:
            mergeopts = []
        return diffopts, mergeopts

    tools = {}
    for cmd, path in ui.configitems('extdiff'):
        if cmd.startswith('cmd.'):
            cmd = cmd[4:]
            if not path:
                path = cmd
            diffopts = ui.config('extdiff', 'opts.' + cmd, '')
            diffopts = shlex.split(diffopts)
            diffopts, mergeopts = fixup_extdiff(diffopts)
            tools[cmd] = [path, diffopts, mergeopts]
        elif cmd.startswith('opts.'):
            continue
        else:
            # command = path opts
            if path:
                diffopts = shlex.split(path)
                path = diffopts.pop(0)
            else:
                path, diffopts = cmd, []
            diffopts, mergeopts = fixup_extdiff(diffopts)
            tools[cmd] = [path, diffopts, mergeopts]
    mt = []
    mergetools(ui, mt)
    for t in mt:
        if t.startswith('internal:'):
            continue
        dopts = ui.config('merge-tools', t + '.diffargs', '')
        mopts = ui.config('merge-tools', t + '.diff3args', '')
        dopts, mopts = shlex.split(dopts), shlex.split(mopts)
        tools[t] = [filemerge._findtool(ui, t), dopts, mopts]
    _difftools = tools
    return tools


tortoisehgtoollocations = {
    'workbench.custom-toolbar': 'Workbench custom toolbar',
    'workbench.revdetails.custom-menu': 'Revision details context menu',
}

def tortoisehgtools(uiorconfig, selectedlocation=None):
    """Parse 'tortoisehg-tools' section of ini file.

    >>> from pprint import pprint
    >>> from mercurial import config
    >>> class memui(ui.ui):
    ...     def readconfig(self, filename, root=None, trust=False,
    ...                    sections=None, remap=None):
    ...         pass  # avoid reading settings from file-system

    Changes:

    >>> hgrctext = '''
    ... [tortoisehg-tools]
    ... update_to_tip.icon = hg-update
    ... update_to_tip.command = hg update tip
    ... update_to_tip.tooltip = Update to tip
    ... '''
    >>> uiobj = memui()
    >>> uiobj._tcfg.parse('<hgrc>', hgrctext)

    into the following dictionary

    >>> tools, toollist = tortoisehgtools(uiobj)
    >>> pprint(tools) #doctest: +NORMALIZE_WHITESPACE
    {'update_to_tip': {'command': 'hg update tip',
                       'icon': 'hg-update',
                       'tooltip': 'Update to tip'}}
    >>> toollist
    ['update_to_tip']

    If selectedlocation is set, only return those tools that have been
    configured to be shown at the given "location".
    Tools are added to "locations" by adding them to one of the
    "extension lists", which are lists of tool names, which follow the same
    format as the workbench.task-toolbar setting, i.e. a list of tool names,
    separated by spaces or "|" to indicate separators.

    >>> hgrctext_full = hgrctext + '''
    ... update_to_null.icon = hg-update
    ... update_to_null.command = hg update null
    ... update_to_null.tooltip = Update to null
    ... explore_wd.command = explorer.exe /e,{ROOT}
    ... explore_wd.enable = iswd
    ... explore_wd.label = Open in explorer
    ... explore_wd.showoutput = True
    ...
    ... [tortoisehg]
    ... workbench.custom-toolbar = update_to_tip | explore_wd
    ... workbench.revdetails.custom-menu = update_to_tip update_to_null
    ... '''
    >>> uiobj = memui()
    >>> uiobj._tcfg.parse('<hgrc>', hgrctext_full)

    >>> tools, toollist = tortoisehgtools(
    ...     uiobj, selectedlocation='workbench.custom-toolbar')
    >>> sorted(tools.keys())
    ['explore_wd', 'update_to_tip']
    >>> toollist
    ['update_to_tip', '|', 'explore_wd']

    >>> tools, toollist = tortoisehgtools(
    ...     uiobj, selectedlocation='workbench.revdetails.custom-menu')
    >>> sorted(tools.keys())
    ['update_to_null', 'update_to_tip']
    >>> toollist
    ['update_to_tip', 'update_to_null']

    Valid "locations lists" are:
        - workbench.custom-toolbar
        - workbench.revdetails.custom-menu

    >>> tortoisehgtools(uiobj, selectedlocation='invalid.location')
    Traceback (most recent call last):
      ...
    ValueError: invalid location 'invalid.location'

    This function can take a ui object or a config object as its input.

    >>> cfg = config.config()
    >>> cfg.parse('<hgrc>', hgrctext)
    >>> tools, toollist = tortoisehgtools(cfg)
    >>> pprint(tools) #doctest: +NORMALIZE_WHITESPACE
    {'update_to_tip': {'command': 'hg update tip',
                       'icon': 'hg-update',
                       'tooltip': 'Update to tip'}}
    >>> toollist
    ['update_to_tip']

    >>> cfg = config.config()
    >>> cfg.parse('<hgrc>', hgrctext_full)
    >>> tools, toollist = tortoisehgtools(
    ...     cfg, selectedlocation='workbench.custom-toolbar')
    >>> sorted(tools.keys())
    ['explore_wd', 'update_to_tip']
    >>> toollist
    ['update_to_tip', '|', 'explore_wd']

    No error for empty config:

    >>> emptycfg = config.config()
    >>> tortoisehgtools(emptycfg)
    ({}, [])
    >>> tortoisehgtools(emptycfg, selectedlocation='workbench.custom-toolbar')
    ({}, [])
    """
    if isinstance(uiorconfig, ui.ui):
        configitems = uiorconfig.configitems
        configlist = uiorconfig.configlist
    else:
        configitems = uiorconfig.items
        def configlist(section, name):
            return uiorconfig.get(section, name, '').split()

    tools = {}
    for key, value in configitems('tortoisehg-tools'):
        toolname, field = key.split('.')
        if toolname not in tools:
            tools[toolname] = {}
        bvalue = util.parsebool(value)
        if bvalue is not None:
            value = bvalue
        tools[toolname][field] = value

    if selectedlocation is None:
        return tools, sorted(tools.keys())

    # Only return the tools that are linked to the selected location
    if selectedlocation not in tortoisehgtoollocations:
        raise ValueError('invalid location %r' % selectedlocation)

    guidef = configlist('tortoisehg', selectedlocation) or []
    toollist = []
    selectedtools = {}
    for name in guidef:
        if name != '|':
            info = tools.get(name, None)
            if info is None:
                continue
            selectedtools[name] = info
        toollist.append(name)
    return selectedtools, toollist

def hmcmd_toq(q, label, args):
    '''
    Run an hg command in a background thread, pipe all output to a Queue
    object.  Assumes command is completely noninteractive.
    '''
    class Qui(ui.ui):
        def __init__(self, src=None):
            super(Qui, self).__init__(src)
            self.setconfig('ui', 'interactive', 'off')

        def write(self, *args, **opts):
            if self._buffers:
                self._buffers[-1].extend([str(a) for a in args])
            else:
                for a in args:
                    if label:
                        q.put((str(a), opts.get('label', '')))
                    else:
                        q.put(str(a))

        def plain(self):
            return True

    u = Qui()
    oldterm = os.environ.get('TERM')
    os.environ['TERM'] = 'dumb'
    ret = dispatch(u, list(args))
    if oldterm:
        os.environ['TERM'] = oldterm
    return ret

def get_reponame(repo):
    if repo.ui.config('tortoisehg', 'fullpath', False):
        name = repo.root
    elif repo.ui.config('web', 'name', False):
        name = repo.ui.config('web', 'name')
    else:
        name = os.path.basename(repo.root)
    return toutf(name)

def displaytime(date):
    return util.datestr(date, '%Y-%m-%d %H:%M:%S %1%2')

def utctime(date):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(date[0]))

agescales = [
    ((lambda n: ngettext("%d year", "%d years", n)), 3600 * 24 * 365),
    ((lambda n: ngettext("%d month", "%d months", n)), 3600 * 24 * 30),
    ((lambda n: ngettext("%d week", "%d weeks", n)), 3600 * 24 * 7),
    ((lambda n: ngettext("%d day", "%d days", n)), 3600 * 24),
    ((lambda n: ngettext("%d hour", "%d hours", n)), 3600),
    ((lambda n: ngettext("%d minute", "%d minutes", n)), 60),
    ((lambda n: ngettext("%d second", "%d seconds", n)), 1),
    ]

def age(date):
    '''turn a (timestamp, tzoff) tuple into an age string.'''
    # This is i18n-ed version of mercurial.templatefilters.age().

    now = time.time()
    then = date[0]
    if then > now:
        return _('in the future')

    delta = int(now - then)
    if delta == 0:
        return _('now')
    if delta > agescales[0][1] * 2:
        return util.shortdate(date)

    for t, s in agescales:
        n = delta // s
        if n >= 2 or s == 1:
            return t(n) % n

def username(user):
    author = templatefilters.person(user)
    if not author:
        author = util.shortuser(user)
    return author

def user(ctx):
    '''
    Get the username of the change context. Does not abort and just returns
    an empty string if ctx is a working context and no username has been set
    in mercurial's config.
    '''
    try:
        user = ctx.user()
    except error.Abort:
        if ctx._rev is not None:
            raise
        # ctx is a working context and probably no username has
        # been configured in mercurial's config
        user = ''
    return user

def get_revision_desc(fctx, curpath=None):
    """return the revision description as a string"""
    author = tounicode(username(fctx.user()))
    rev = fctx.linkrev()
    # If the source path matches the current path, don't bother including it.
    if curpath and curpath == fctx.path():
        source = u''
    else:
        source = u'(%s)' % tounicode(fctx.path())
    date = tounicode(age(fctx.date()))
    l = tounicode(fctx.description()).splitlines()
    summary = l and l[0] or ''
    return u'%s@%s%s:%s "%s"' % (author, rev, source, date, summary)

def validate_synch_path(path, repo):
    '''
    Validate the path that must be used to sync operations (pull,
    push, outgoing and incoming)
    '''
    return_path = path
    for alias, path_aux in repo.ui.configitems('paths'):
        if path == alias:
            return_path = path_aux
        elif path == util.hidepassword(path_aux):
            return_path = path_aux
    return return_path

def is_rev_current(repo, rev):
    '''
    Returns True if the revision indicated by 'rev' is the current
    working directory parent.

    If rev is '' or None, it is assumed to mean 'tip'.
    '''
    if rev in ('', None):
        rev = 'tip'
    rev = repo.lookup(rev)
    parents = repo.parents()

    if len(parents) > 1:
        return False

    return rev == parents[0].node()

def export(repo, revs, template='hg-%h.patch', fp=None, switch_parent=False,
           opts=None):
    '''
    export changesets as hg patches.

    Mercurial moved patch.export to cmdutil.export after version 1.5
    (change e764f24a45ee in mercurial).
    '''

    try:
        return cmdutil.export(repo, revs, template, fp, switch_parent, opts)
    except AttributeError:
        from mercurial import patch
        return patch.export(repo, revs, template, fp, switch_parent, opts)

def getDeepestSubrepoContainingFile(wfile, ctx):
    """
    Given a filename and context, get the deepest subrepo that contains the file

    Also return the corresponding subrepo context and the filename relative to
    its containing subrepo
    """
    if wfile in ctx:
        return '', wfile, ctx
    for wsub in ctx.substate:
        if wfile.startswith(wsub):
            srev = ctx.substate[wsub][1]
            stype = ctx.substate[wsub][2]
            if stype != 'hg':
                continue
            if not os.path.exists(ctx._repo.wjoin(wsub)):
                # Maybe the repository does not exist in the working copy?
                continue
            try:
                sctx = ctx.sub(wsub)._repo[srev]
            except:
                # The selected revision does not exist in the working copy
                continue
            wfileinsub =  wfile[len(wsub)+1:]
            if wfileinsub in sctx.substate or wfileinsub in sctx:
                return wsub, wfileinsub, sctx
            else:
                wsubsub, wfileinsub, sctx = \
                    getDeepestSubrepoContainingFile(wfileinsub, sctx)
                if wsubsub is None:
                    return None, wfile, ctx
                else:
                    return os.path.join(wsub, wsubsub), wfileinsub, sctx
    return None, wfile, ctx

def netlocsplit(netloc):
    '''split [user[:passwd]@]host[:port] into 4-tuple.'''

    a = netloc.find('@')
    if a == -1:
        user, passwd = None, None
    else:
        userpass, netloc = netloc[:a], netloc[a + 1:]
        c = userpass.find(':')
        if c == -1:
            user, passwd = urllib.unquote(userpass), None
        else:
            user = urllib.unquote(userpass[:c])
            passwd = urllib.unquote(userpass[c + 1:])
    c = netloc.find(':')
    if c == -1:
        host, port = netloc, None
    else:
        host, port = netloc[:c], netloc[c + 1:]
    return host, port, user, passwd

def getLineSeparator(line):
    """Get the line separator used on a given line"""
    # By default assume the default OS line separator 
    linesep = os.linesep
    lineseptypes = ['\r\n', '\n', '\r']
    for sep in lineseptypes:
        if line.endswith(sep):
            linesep = sep
            break
    return linesep

def dispatch(ui, args):
    req = hgdispatch.request(args, ui)
    return hgdispatch._dispatch(req)
