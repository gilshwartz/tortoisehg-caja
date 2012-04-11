# hgshelve.py - TortoiseHg dialog to initialize a repo
#
# Copyright 2007 Bryan O'Sullivan <bos@serpentine.com>
# Copyright 2007 TK Soh <teekaysoh@gmailcom>
# Copyright 2009 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

'''interactive change selection to set aside that may be restored later'''

import copy
import cStringIO
import errno
import operator
import os
import re
import tempfile

from mercurial import commands, cmdutil, hg, mdiff, patch, revlog
from mercurial import util, fancyopts

from tortoisehg.util.i18n import _
from tortoisehg.util import hglib

lines_re = re.compile(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@\s*(.*)')

def internalpatch(patchobj, ui, strip, cwd, files={}):
    """use builtin patch to apply <patchobj> to the working directory.
    returns whether patch was applied with fuzz factor.

    Adapted from patch.internalpatch() to support reverse patching.
    """
    try:
        fp = file(patchobj, 'rb')
    except TypeError:
        fp = patchobj
    if cwd:
        curdir = os.getcwd()
        os.chdir(cwd)
    eolmode = ui.config('patch', 'eol', 'strict')
    try:
        eol = {'strict': None,
               'auto': None,
               'crlf': '\r\n',
               'lf': '\n'}[eolmode.lower()]
    except KeyError:
        raise util.Abort(_('Unsupported line endings type: %s') % eolmode)
    try:
        if hasattr(patch, 'eolmodes'): # hg-1.5 hack
            ret = patch.applydiff(ui, fp, files, strip=strip, eolmode=eolmode)
        else:
            ret = patch.applydiff(ui, fp, files, strip=strip, eol=eol)
    finally:
        if cwd:
            os.chdir(curdir)
    if ret < 0:
        raise patch.PatchError
    return ret > 0

def scanpatch(fp):
    lr = patch.linereader(fp)

    def scanwhile(first, p):
        lines = [first]
        while True:
            line = lr.readline()
            if not line:
                break
            if p(line):
                lines.append(line)
            else:
                lr.push(line)
                break
        return lines

    while True:
        line = lr.readline()
        if not line:
            break
        if line.startswith('diff --git a/'):
            def notheader(line):
                s = line.split(None, 1)
                return not s or s[0] not in ('---', 'diff')
            header = scanwhile(line, notheader)
            fromfile = lr.readline()
            if fromfile.startswith('---'):
                tofile = lr.readline()
                header += [fromfile, tofile]
            else:
                lr.push(fromfile)
            yield 'file', header
        elif line[0] == ' ':
            yield 'context', scanwhile(line, lambda l: l[0] in ' \\')
        elif line[0] in '-+':
            yield 'hunk', scanwhile(line, lambda l: l[0] in '-+\\')
        else:
            m = lines_re.match(line)
            if m:
                yield 'range', m.groups()
            else:
                raise patch.PatchError(_('unknown patch content: %r') % line)

class header(object):
    diff_re = re.compile('diff --git a/(.*) b/(.*)$')
    allhunks_re = re.compile('(?:index|new file|deleted file) ')
    pretty_re = re.compile('(?:new file|deleted file) ')
    special_re = re.compile('(?:index|new file|deleted|copy|rename) ')

    def __init__(self, header):
        self.header = header
        self.hunks = []

    def binary(self):
        for h in self.header:
            if h.startswith('index '):
                return True

    def selpretty(self, selected):
        str = ''
        for h in self.header:
            if h.startswith('index '):
                str += _('this modifies a binary file (all or nothing)\n')
                break
            if self.pretty_re.match(h):
                str += hglib.toutf(h)
                if self.binary():
                    str += _('this is a binary file\n')
                break
            if h.startswith('---'):
                hunks = len(self.hunks)
                shunks, lines, slines = 0, 0, 0
                for i, h in enumerate(self.hunks):
                    lines += h.added + h.removed
                    if selected(i):
                        shunks += 1
                        slines += h.added + h.removed
                str += '<span foreground="blue">'
                str += _('total: %d hunks (%d changed lines); '
                        'selected: %d hunks (%d changed lines)') % (hunks,
                                lines, shunks, slines)
                str += '</span>'
                break
            str += hglib.toutf(h)
        return str

    def pretty(self, fp):
        for h in self.header:
            if h.startswith('index '):
                fp.write(_('this modifies a binary file (all or nothing)\n'))
                break
            if self.pretty_re.match(h):
                fp.write(h)
                if self.binary():
                    fp.write(_('this is a binary file\n'))
                break
            if h.startswith('---'):
                fp.write(_('%d hunks, %d lines changed\n') %
                         (len(self.hunks),
                          sum([h.added + h.removed for h in self.hunks])))
                break
            fp.write(h)

    def write(self, fp):
        fp.write(''.join(self.header))

    def allhunks(self):
        for h in self.header:
            if self.allhunks_re.match(h):
                return True

    def files(self):
        fromfile, tofile = self.diff_re.match(self.header[0]).groups()
        if fromfile == tofile:
            return [fromfile]
        return [fromfile, tofile]

    def filename(self):
        return self.files()[-1]

    def __repr__(self):
        return '<header %s>' % (' '.join(map(repr, self.files())))

    def special(self):
        for h in self.header:
            if self.special_re.match(h):
                return True

    def __cmp__(self, other):
        return cmp(repr(self), repr(other))

def countchanges(hunk):
    add = len([h for h in hunk if h[0] == '+'])
    rem = len([h for h in hunk if h[0] == '-'])
    return add, rem

class hunk(object):
    maxcontext = 3

    def __init__(self, header, fromline, toline, proc, before, hunk, after):
        def trimcontext(number, lines):
            delta = len(lines) - self.maxcontext
            if False and delta > 0:
                return number + delta, lines[:self.maxcontext]
            return number, lines

        self.header = header
        self.fromline, self.before = trimcontext(fromline, before)
        self.toline, self.after = trimcontext(toline, after)
        self.proc = proc
        self.hunk = hunk
        self.added, self.removed = countchanges(self.hunk)

    def write(self, fp):
        delta = len(self.before) + len(self.after)
        if self.after and self.after[-1] == '\\ No newline at end of file\n':
            delta -= 1
        fromlen = delta + self.removed
        tolen = delta + self.added
        fp.write('@@ -%d,%d +%d,%d @@%s\n' %
                 (self.fromline, fromlen, self.toline, tolen,
                  self.proc and (' ' + self.proc)))
        fp.write(''.join(self.before + self.hunk + self.after))

    pretty = write

    def filename(self):
        return self.header.filename()

    def __repr__(self):
        return '<hunk %r@%d>' % (self.filename(), self.fromline)

    def __cmp__(self, other):
        return cmp(repr(self), repr(other))

def parsepatch(fp):
    class parser(object):
        def __init__(self):
            self.fromline = 0
            self.toline = 0
            self.proc = ''
            self.header = None
            self.context = []
            self.before = []
            self.hunk = []
            self.stream = []

        def addrange(self, (fromstart, fromend, tostart, toend, proc)):
            self.fromline = int(fromstart)
            self.toline = int(tostart)
            self.proc = proc

        def addcontext(self, context):
            if self.hunk:
                h = hunk(self.header, self.fromline, self.toline, self.proc,
                         self.before, self.hunk, context)
                self.header.hunks.append(h)
                self.stream.append(h)
                self.fromline += len(self.before) + h.removed
                self.toline += len(self.before) + h.added
                self.before = []
                self.hunk = []
                self.proc = ''
            self.context = context

        def addhunk(self, hunk):
            if self.context:
                self.before = self.context
                self.context = []
            self.hunk = hunk

        def newfile(self, hdr):
            self.addcontext([])
            h = header(hdr)
            self.stream.append(h)
            self.header = h

        def finished(self):
            self.addcontext([])
            return self.stream

        transitions = {
            'file': {'context': addcontext,
                     'file': newfile,
                     'hunk': addhunk,
                     'range': addrange},
            'context': {'file': newfile,
                        'hunk': addhunk,
                        'range': addrange},
            'hunk': {'context': addcontext,
                     'file': newfile,
                     'range': addrange},
            'range': {'context': addcontext,
                      'hunk': addhunk},
            }

    p = parser()

    state = 'context'
    for newstate, data in scanpatch(fp):
        try:
            p.transitions[state][newstate](p, data)
        except KeyError:
            raise patch.PatchError(_('unhandled transition: %s -> %s') %
                                   (state, newstate))
        state = newstate
    return p.finished()

def filterpatch(ui, chunks):
    chunks = list(chunks)
    chunks.reverse()
    seen = {}
    def consumefile():
        consumed = []
        while chunks:
            if isinstance(chunks[-1], header):
                break
            else:
                consumed.append(chunks.pop())
        return consumed
    resp_all = [None]
    resp_file = [None]
    applied = {}
    def prompt(query):
        if resp_all[0] is not None:
            return resp_all[0]
        if resp_file[0] is not None:
            return resp_file[0]
        while True:
            r = (ui.prompt(query + _(' [Ynsfdaq?] '), '(?i)[Ynsfdaq?]?$')
                 or 'y').lower()
            if r == '?':
                c = shelve.__doc__.find('y - shelve this change')
                for l in shelve.__doc__[c:].splitlines():
                    if l: ui.write(_(l.strip()), '\n')
                continue
            elif r == 's':
                r = resp_file[0] = 'n'
            elif r == 'f':
                r = resp_file[0] = 'y'
            elif r == 'd':
                r = resp_all[0] = 'n'
            elif r == 'a':
                r = resp_all[0] = 'y'
            elif r == 'q':
                raise util.Abort(_('user quit'))
            return r
    while chunks:
        chunk = chunks.pop()
        if isinstance(chunk, header):
            resp_file = [None]
            fixoffset = 0
            hdr = ''.join(chunk.header)
            if hdr in seen:
                consumefile()
                continue
            seen[hdr] = True
            if resp_all[0] is None:
                chunk.pretty(ui)
            r = prompt(_('shelve changes to %s?') %
                       _(' and ').join(map(repr, chunk.files())))
            if r == 'y':
                applied[chunk.filename()] = [chunk]
                if chunk.allhunks():
                    applied[chunk.filename()] += consumefile()
            else:
                consumefile()
        else:
            if resp_file[0] is None and resp_all[0] is None:
                chunk.pretty(ui)
            r = prompt(_('shelve this change to %r?') %
                       chunk.filename())
            if r == 'y':
                if fixoffset:
                    chunk = copy.copy(chunk)
                    chunk.toline += fixoffset
                applied[chunk.filename()].append(chunk)
            else:
                fixoffset += chunk.removed - chunk.added
    return reduce(operator.add, [h for h in applied.itervalues()
                                 if h[0].special() or len(h) > 1], [])

def refilterpatch(allchunk, selected):
    ''' return unshelved chunks of files to be shelved '''
    l = []
    fil = []
    for c in allchunk:
        if isinstance(c, header):
            if len(l) > 1 and l[0] in selected:
                fil += l
            l = [c]
        elif c not in selected:
            l.append(c)
    if len(l) > 1 and l[0] in selected:
        fil += l
    return fil

def makebackup(ui, repo, dir, files):
    try:
        os.mkdir(dir)
    except OSError, err:
        if err.errno != errno.EEXIST:
            raise

    backups = {}
    for f in files:
        fd, tmpname = tempfile.mkstemp(prefix=f.replace('/', '_')+'.',
                                       dir=dir)
        os.close(fd)
        ui.debug(_('backup %r as %r\n') % (f, tmpname))
        try:
            util.copyfile(repo.wjoin(f), tmpname)
        except:
            ui.warn(_('file copy of %s failed\n') % f)
            raise
        backups[f] = tmpname

    return backups


def delete_backup(ui, repo, backupdir):
    """remove the shelve backup files and directory"""

    backupdir = os.path.normpath(repo.join(backupdir))

    # Do a sanity check to ensure that unrelated files aren't destroyed.
    # All shelve file and directory paths must start with "shelve" under
    # the .hg directory.
    if backupdir.startswith(repo.join('shelve')):
        try:
            backups = os.listdir(backupdir)
            for filename in backups:
                ui.debug(_('removing backup file : %r\n') % filename)
                os.unlink(os.path.join(backupdir, filename))
            os.rmdir(backupdir)
        except OSError:
            ui.warn(_('delete of shelve backup failed'))
            pass
    else:
        ui.warn(_('bad shelve backup directory name'))


def get_shelve_filename(repo):
    return repo.join('shelve')

def shelve(ui, repo, *pats, **opts):
    '''interactively select changes to set aside

    If a list of files is omitted, all changes reported by "hg status"
    will be candidates for shelveing.

    You will be prompted for whether to shelve changes to each
    modified file, and for files with multiple changes, for each
    change to use.  For each query, the following responses are
    possible:

    y - shelve this change
    n - skip this change

    s - skip remaining changes to this file
    f - shelve remaining changes to this file

    d - done, skip remaining changes and files
    a - shelve all changes to all remaining files
    q - quit, shelveing no changes

    ? - display help'''

    if not ui.interactive():
        raise util.Abort(_('shelve can only be run interactively'))

    forced = opts['force'] or opts['append']
    if os.path.exists(repo.join('shelve')) and not forced:
        raise util.Abort(_('shelve data already exists'))

    def shelvefunc(ui, repo, message, match, opts):
        # If an MQ patch is applied, consider all qdiff changes
        if hasattr(repo, 'mq') and repo.mq.applied and repo['.'] == repo['qtip']:
            qtip = repo['.']
            basenode = qtip.parents()[0].node()
        else:
            basenode = repo.dirstate.parents()[0]

        changes = repo.status(node1=basenode, match=match)[:5]
        modified, added, removed = changes[:3]
        files = modified + added + removed
        diffopts = mdiff.diffopts(git=True, nodates=True)
        patch_diff = ''.join(patch.diff(repo, basenode, match=match,
                             changes=changes, opts=diffopts))

        fp = cStringIO.StringIO(patch_diff)
        ac = parsepatch(fp)
        fp.close()
        chunks = filterpatch(ui, ac)
        rc = refilterpatch(ac, chunks)

        contenders = {}
        for h in chunks:
            try: contenders.update(dict.fromkeys(h.files()))
            except AttributeError: pass

        newfiles = [f for f in files if f in contenders]

        if not newfiles:
            ui.status(_('no changes to shelve\n'))
            return 0

        modified = dict.fromkeys(changes[0])

        backupdir = repo.join('shelve-backups')

        try:
            bkfiles = [f for f in newfiles if f in modified]
            backups = makebackup(ui, repo, backupdir, bkfiles)

            # patch to shelve
            sp = cStringIO.StringIO()
            for c in chunks:
                if c.filename() in backups:
                    c.write(sp)
            doshelve = sp.tell()
            sp.seek(0)

            # patch to apply to shelved files
            fp = cStringIO.StringIO()
            for c in rc:
                if c.filename() in backups:
                    c.write(fp)
            dopatch = fp.tell()
            fp.seek(0)

            try:
                # 3a. apply filtered patch to clean repo (clean)
                if backups:
                    hg.revert(repo, basenode, backups.has_key)

                # 3b. apply filtered patch to clean repo (apply)
                if dopatch:
                    ui.debug(_('applying patch\n'))
                    ui.debug(fp.getvalue())
                    patch.internalpatch(fp, ui, 1, repo.root, eolmode=None)
                del fp

                # 3c. apply filtered patch to clean repo (shelve)
                if doshelve:
                    ui.debug(_('saving patch to shelve\n'))
                    if opts['append']:
                        f = repo.opener('shelve', "a")
                    else:
                        f = repo.opener('shelve', "w")
                    f.write(sp.getvalue())
                    del f
                del sp
            except:
                try:
                    for realname, tmpname in backups.iteritems():
                        ui.debug(_('restoring %r to %r\n') % (tmpname, realname))
                        util.copyfile(tmpname, repo.wjoin(realname))
                    ui.debug(_('removing shelve file\n'))
                    os.unlink(repo.join('shelve'))
                except (IOError, OSError), e:
                    ui.warn(_('abort: backup restore failed, %s\n') % str(e))

            return 0
        finally:
            delete_backup(ui, repo, backupdir)

    fancyopts.fancyopts([], commands.commitopts, opts)
    return cmdutil.commit(ui, repo, shelvefunc, pats, opts)


def unshelve(ui, repo, *pats, **opts):
    '''restore shelved changes'''

    try:
        fp = cStringIO.StringIO()
        fp.write(repo.opener('shelve').read())
    except:
        ui.warn(_('nothing to unshelve\n'))
    else:
        if opts['inspect']:
            ui.status(fp.getvalue())
        else:
            files = []
            fp.seek(0)
            for chunk in parsepatch(fp):
                if isinstance(chunk, header):
                    files += chunk.files()
            backupdir = repo.join('shelve-backups')
            try:
                backups = makebackup(ui, repo, backupdir, set(files))
            except:
                ui.warn(_('unshelve backup aborted\n'))
                delete_backup(ui, repo, backupdir)
                raise

            ui.debug(_('applying shelved patch\n'))
            patchdone = 0
            try:
                try:
                    fp.seek(0)
                    pfiles = {}
                    internalpatch(fp, ui, 1, repo.root, files=pfiles)
                    cmdutil.updatedir(ui, repo, pfiles)
                    patchdone = 1
                except:
                    if opts['force']:
                        patchdone = 1
                    else:
                        ui.status(_('restoring backup files\n'))
                        for realname, tmpname in backups.iteritems():
                            ui.debug(_('restoring %r to %r\n') %
                                     (tmpname, realname))
                            util.copyfile(tmpname, repo.wjoin(realname))
            finally:
                delete_backup(ui, repo, backupdir)

            if patchdone:
                ui.debug(_('removing shelved patches\n'))
                os.unlink(repo.join('shelve'))
                ui.status(_('unshelve completed\n'))
            else:
                raise patch.PatchError


def abandon(ui, repo):
    '''abandon shelved changes'''
    try:
        if os.path.exists(repo.join('shelve')):
            ui.debug(_('abandoning shelved file\n'))
            os.unlink(repo.join('shelve'))
            ui.status(_('shelved file abandoned\n'))
        else:
            ui.warn(_('nothing to abandon\n'))
    except IOError:
        ui.warn(_('abandon failed\n'))


cmdtable = {
    "shelve":
        (shelve,
         [('A', 'addremove', None,
           _('mark new/missing files as added/removed before shelving')),
          ('f', 'force', None,
           _('overwrite existing shelve data')),
          ('a', 'append', None,
           _('append to existing shelve data')),
         ] + commands.walkopts,
         _('hg shelve [OPTION]... [FILE]...')),
    "unshelve":
        (unshelve,
         [('i', 'inspect', None, _('inspect shelved changes only')),
          ('f', 'force', None,
           _('proceed even if patches do not unshelve cleanly')),
         ],
         _('hg unshelve [OPTION]... [FILE]...')),
}
