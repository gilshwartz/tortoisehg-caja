# prej.py - mpatch functionality hacked into TortoiseHg
#
# Copyright 2006 Brendan Cully <brendan@kublai.com>
# Copyright 2006 Chris Mason <chris.mason@oracle.com>
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms
# of the GNU General Public License, incorporated herein by reference.

# This file is an amalgam of two files from the mpatch tool source:
# mpatch/patch.py - which started life as Mercurial's patch.py
# cmd/mpatch      - mpatch's run script
#
# Where possible, it has been tied back into the current Mercurial
# sources.

from mercurial.i18n import _
from mercurial import demandimport
demandimport.disable()
from mercurial import base85, util, diffhelpers
from mercurial.patch import PatchError, copyfile
demandimport.enable()

import cStringIO, os, re, zlib
import bisect

# public functions

GP_PATCH  = 1 << 0  # we have to run patch
GP_FILTER = 1 << 1  # there's some copy/rename operation
GP_BINARY = 1 << 2  # there's a binary patch

def readgitpatch(fp, firstline):
    """extract git-style metadata about patches from <patchname>"""
    class gitpatch:
        "op is one of ADD, DELETE, RENAME, MODIFY or COPY"
        def __init__(self, path):
            self.path = path
            self.oldpath = None
            self.mode = None
            self.op = 'MODIFY'
            self.copymod = False
            self.lineno = 0
            self.binary = False

    def reader(fp, firstline):
        yield firstline
        for line in fp:
            yield line

    # Filter patch for git information
    gitre = re.compile('diff --git a/(.*) b/(.*)')
    gitpatches = []
    # Can have a git patch with only metadata, causing patch to complain
    dopatch = 0
    gp = None

    lineno = 0
    for line in reader(fp, firstline):
        lineno += 1
        if line.startswith('diff --git'):
            m = gitre.match(line)
            if m:
                if gp:
                    gitpatches.append(gp)
                src, dst = m.group(1, 2)
                gp = gitpatch(dst)
                gp.lineno = lineno
        elif gp:
            if line.startswith('--- '):
                if gp.op in ('COPY', 'RENAME'):
                    gp.copymod = True
                    dopatch |= GP_FILTER
                gitpatches.append(gp)
                gp = None
                dopatch |= GP_PATCH
                continue
            if line.startswith('rename from '):
                gp.op = 'RENAME'
                gp.oldpath = line[12:].rstrip()
            elif line.startswith('rename to '):
                gp.path = line[10:].rstrip()
            elif line.startswith('copy from '):
                gp.op = 'COPY'
                gp.oldpath = line[10:].rstrip()
            elif line.startswith('copy to '):
                gp.path = line[8:].rstrip()
            elif line.startswith('deleted file'):
                gp.op = 'DELETE'
            elif line.startswith('new file mode '):
                gp.op = 'ADD'
                gp.mode = int(line.rstrip()[-3:], 8)
            elif line.startswith('new mode '):
                gp.mode = int(line.rstrip()[-3:], 8)
            elif line.startswith('GIT binary patch'):
                dopatch |= GP_BINARY
                gp.binary = True
    if gp:
        gitpatches.append(gp)

    if not gitpatches:
        dopatch = GP_PATCH

    return (dopatch, gitpatches)

# @@ -start,len +start,len @@ or @@ -start +start @@ if len is 1
unidesc = re.compile('@@ -(\d+)(,(\d+))? \+(\d+)(,(\d+))? @@')
contextdesc = re.compile('(---|\*\*\*) (\d+)(,(\d+))? (---|\*\*\*)')

class patchfile:
    def __init__(self, ui, fname):
        self.fname = fname
        self.ui = ui
        try:
            fp = file(fname, 'rb')
            self.lines = fp.readlines()
            self.exists = True
        except IOError:
            dirname = os.path.dirname(fname)
            if dirname and not os.path.isdir(dirname):
                dirs = dirname.split(os.path.sep)
                d = ""
                for x in dirs:
                    d = os.path.join(d, x)
                    if not os.path.isdir(d):
                        os.mkdir(d)
            self.lines = []
            self.exists = False
            
        self.hash = {}
        self.dirty = 0
        self.offset = 0
        self.rej = []
        self.fileprinted = False
        self.printfile(False)
        self.hunks = 0

    def printfile(self, warn):
        if self.fileprinted:
            return
        if warn or self.ui.verbose:
            self.fileprinted = True
        s = _("patching file %s\n") % self.fname
        if warn:
            self.ui.warn(s)
        else:
            self.ui.note(s)


    def findlines(self, l, linenum):
        # looks through the hash and finds candidate lines.  The
        # result is a list of line numbers sorted based on distance
        # from linenum
        def sorter(a, b):
            vala = abs(a - linenum)
            valb = abs(b - linenum)
            return cmp(vala, valb)
            
        try:
            cand = self.hash[l]
        except:
            return []

        if len(cand) > 1:
            # resort our list of potentials forward then back.
            cand.sort(cmp=sorter)
        return cand

    def hashlines(self):
        self.hash = {}
        for x in xrange(len(self.lines)):
            s = self.lines[x]
            self.hash.setdefault(s, []).append(x)

    def write_rej(self):
        # our rejects are a little different from patch(1).  This always
        # creates rejects in the same form as the original patch.  A file
        # header is inserted so that you can run the reject through patch again
        # without having to type the filename.

        if not self.rej:
            return

        fname = self.fname + ".rej"
        self.ui.warn(
            _("%d out of %d hunks FAILED -- saving rejects to file %s\n") %
            (len(self.rej), self.hunks, fname))
        try: os.unlink(fname)
        except:
            pass
        fp = file(fname, 'wb')
        base = os.path.basename(self.fname)
        fp.write("--- %s\n+++ %s\n" % (base, base))
        for x in self.rej:
            for l in x.hunk:
                fp.write(l)
                if l[-1] != '\n':
                    fp.write("\n\ No newline at end of file\n")

    def write(self, dest=None):
        if self.dirty:
            if not dest:
                dest = self.fname
            st = None
            try:
                st = os.lstat(dest)
                if st.st_nlink > 1:
                    os.unlink(dest)
            except: pass
            fp = file(dest, 'wb')
            if st:
                os.chmod(dest, st.st_mode)
            fp.writelines(self.lines)
            fp.close()

    def close(self):
        self.write()
        self.write_rej()

    def apply(self, h, reverse):
        if not h.complete():
            raise PatchError(_("bad hunk #%d %s (%d %d %d %d)") %
                            (h.number, h.desc, len(h.a), h.lena, len(h.b),
                            h.lenb))

        self.hunks += 1
        if reverse:
            h.reverse()

        if self.exists and h.createfile():
            self.ui.warn(_("file %s already exists\n") % self.fname)
            self.rej.append(h)
            return -1

        if isinstance(h, binhunk):
            if h.rmfile():
                os.unlink(self.fname)
            else:
                self.lines[:] = h.new()
                self.offset += len(h.new())
                self.dirty = 1
            return 0

        # fast case first, no offsets, no fuzz
        old = h.old()
        # patch starts counting at 1 unless we are adding the file
        if h.starta == 0:
            start = 0
        else:
            start = h.starta + self.offset - 1
        orig_start = start
        if diffhelpers.testhunk(old, self.lines, start) == 0:
            if h.rmfile():
                os.unlink(self.fname)
            else:
                self.lines[start : start + h.lena] = h.new()
                self.offset += h.lenb - h.lena
                self.dirty = 1
            return 0

        # ok, we couldn't match the hunk.  Lets look for offsets and fuzz it
        self.hashlines()
        if h.hunk[-1][0] != ' ':
            # if the hunk tried to put something at the bottom of the file
            # override the start line and use eof here
            search_start = len(self.lines)
        else:
            search_start = orig_start

        for fuzzlen in xrange(3):
            for toponly in [ True, False ]:
                old = h.old(fuzzlen, toponly)

                cand = self.findlines(old[0][1:], search_start)
                for l in cand:
                    if diffhelpers.testhunk(old, self.lines, l) == 0:
                        newlines = h.new(fuzzlen, toponly)
                        self.lines[l : l + len(old)] = newlines
                        self.offset += len(newlines) - len(old)
                        self.dirty = 1
                        offset = l - orig_start - fuzzlen
                        if fuzzlen:
                            msg = _("Hunk #%d succeeded at %d "
                                    "with fuzz %d "
                                    "(offset %d lines).\n")
                            self.printfile(True)
                            self.ui.warn(msg %
                                (h.number, l + 1, fuzzlen, offset))
                        else:
                            msg = _("Hunk #%d succeeded at %d "
                                    "(offset %d lines).\n")
                            self.ui.note(msg % (h.number, l + 1, offset))
                        return fuzzlen
        self.printfile(True)
        self.ui.warn(_("Hunk #%d FAILED at %d\n") % (h.number, orig_start))
        self.rej.append(h)
        return -1

class hunk:
    def __init__(self, desc, num, lr, context):
        self.number = num
        self.desc = desc
        self.hunk = [ desc ]
        self.a = []
        self.b = []
        if context:
            self.read_context_hunk(lr)
        else:
            self.read_unified_hunk(lr)

    def read_unified_hunk(self, lr):
        m = unidesc.match(self.desc)
        if not m:
            raise PatchError(_("bad hunk #%d") % self.number)
        self.starta, foo, self.lena, self.startb, foo2, self.lenb = m.groups()
        if self.lena == None:
            self.lena = 1
        else:
            self.lena = int(self.lena)
        if self.lenb == None:
            self.lenb = 1
        else:
            self.lenb = int(self.lenb)
        self.starta = int(self.starta)
        self.startb = int(self.startb)
        diffhelpers.addlines(lr.fp, self.hunk, self.lena, self.lenb, self.a, self.b)
        # if we hit eof before finishing out the hunk, the last line will
        # be zero length.  Lets try to fix it up.
        while len(self.hunk[-1]) == 0:
                del self.hunk[-1]
                del self.a[-1]
                del self.b[-1]
                self.lena -= 1
                self.lenb -= 1

    def read_context_hunk(self, lr):
        self.desc = lr.readline()
        m = contextdesc.match(self.desc)
        if not m:
            raise PatchError(_("bad hunk #%d") % self.number)
        foo, self.starta, foo2, aend, foo3 = m.groups()
        self.starta = int(self.starta)
        if aend == None:
            aend = self.starta
        self.lena = int(aend) - self.starta
        if self.starta:
            self.lena += 1
        for x in xrange(self.lena):
            l = lr.readline()
            if l.startswith('---'):
                lr.push(l)
                break
            s = l[2:]
            if l.startswith('- ') or l.startswith('! '):
                u = '-' + s
            elif l.startswith('  '):
                u = ' ' + s
            else:
                raise PatchError(_("bad hunk #%d old text line %d") %
                                 (self.number, x))
            self.a.append(u)
            self.hunk.append(u)

        l = lr.readline()
        if l.startswith('\ '):
            s = self.a[-1][:-1]
            self.a[-1] = s
            self.hunk[-1] = s
            l = lr.readline()
        m = contextdesc.match(l)
        if not m:
            raise PatchError(_("bad hunk #%d") % self.number)
        foo, self.startb, foo2, bend, foo3 = m.groups()
        self.startb = int(self.startb)
        if bend == None:
            bend = self.startb
        self.lenb = int(bend) - self.startb
        if self.startb:
            self.lenb += 1
        hunki = 1
        for x in xrange(self.lenb):
            l = lr.readline()
            if l.startswith('\ '):
                s = self.b[-1][:-1]
                self.b[-1] = s
                self.hunk[hunki-1] = s
                continue
            if not l:
                lr.push(l)
                break
            s = l[2:]
            if l.startswith('+ ') or l.startswith('! '):
                u = '+' + s
            elif l.startswith('  '):
                u = ' ' + s
            elif len(self.b) == 0:
                # this can happen when the hunk does not add any lines
                lr.push(l)
                break
            else:
                raise PatchError(_("bad hunk #%d old text line %d") %
                                 (self.number, x))
            self.b.append(s)
            while True:
                if hunki >= len(self.hunk):
                    h = ""
                else:
                    h = self.hunk[hunki]
                hunki += 1
                if h == u:
                    break
                elif h.startswith('-'):
                    continue
                else:
                    self.hunk.insert(hunki-1, u)
                    break

        if not self.a:
            # this happens when lines were only added to the hunk
            for x in self.hunk:
                if x.startswith('-') or x.startswith(' '):
                    self.a.append(x)
        if not self.b:
            # this happens when lines were only deleted from the hunk
            for x in self.hunk:
                if x.startswith('+') or x.startswith(' '):
                    self.b.append(x[1:])
        # @@ -start,len +start,len @@
        self.desc = "@@ -%d,%d +%d,%d @@\n" % (self.starta, self.lena,
                                             self.startb, self.lenb)
        self.hunk[0] = self.desc

    def reverse(self):
        origlena = self.lena
        origstarta = self.starta
        self.lena = self.lenb
        self.starta = self.startb
        self.lenb = origlena
        self.startb = origstarta
        self.a = []
        self.b = []
        # self.hunk[0] is the @@ description
        for x in xrange(1, len(self.hunk)):
            o = self.hunk[x]
            if o.startswith('-'):
                n = '+' + o[1:]
                self.b.append(o[1:])
            elif o.startswith('+'):
                n = '-' + o[1:]
                self.a.append(n)
            else:
                n = o
                self.b.append(o[1:])
                self.a.append(o)
            self.hunk[x] = o

    def fix_newline(self):
        diffhelpers.fix_newline(self.hunk, self.a, self.b)

    def complete(self):
        return len(self.a) == self.lena and len(self.b) == self.lenb

    def createfile(self):
        return self.starta == 0 and self.lena == 0

    def rmfile(self):
        return self.startb == 0 and self.lenb == 0

    def fuzzit(self, l, fuzz, toponly):
        # this removes context lines from the top and bottom of list 'l'.  It
        # checks the hunk to make sure only context lines are removed, and then
        # returns a new shortened list of lines.
        fuzz = min(fuzz, len(l)-1)
        if fuzz:
            top = 0
            bot = 0
            hlen = len(self.hunk)
            for x in xrange(hlen-1):
                # the hunk starts with the @@ line, so use x+1
                if self.hunk[x+1][0] == ' ':
                    top += 1
                else:
                    break
            if not toponly:
                for x in xrange(hlen-1):
                    if self.hunk[hlen-bot-1][0] == ' ':
                        bot += 1
                    else:
                        break

            # top and bot now count context in the hunk
            # adjust them if either one is short
            context = max(top, bot, 3)
            if bot < context:
                bot = max(0, fuzz - (context - bot))
            else:
                bot = min(fuzz, bot)
            if top < context:
                top = max(0, fuzz - (context - top))
            else:
                top = min(fuzz, top)

            return l[top:len(l)-bot]
        return l

    def old(self, fuzz=0, toponly=False):
        return self.fuzzit(self.a, fuzz, toponly)
        
    def newctrl(self):
        res = []
        for x in self.hunk:
            c = x[0]
            if c == ' ' or c == '+':
                res.append(x)
        return res

    def new(self, fuzz=0, toponly=False):
        return self.fuzzit(self.b, fuzz, toponly)

class binhunk:
    'A binary patch file. Only understands literals so far.'
    def __init__(self, gitpatch):
        self.gitpatch = gitpatch
        self.text = None
        self.hunk = ['GIT binary patch\n']

    def createfile(self):
        return self.gitpatch.op in ('ADD', 'RENAME', 'COPY')

    def rmfile(self):
        return self.gitpatch.op == 'DELETE'

    def complete(self):
        return self.text is not None

    def new(self):
        return [self.text]

    def extract(self, fp):
        line = fp.readline()
        self.hunk.append(line)
        while line and not line.startswith('literal '):
            line = fp.readline()
            self.hunk.append(line)
        if not line:
            raise PatchError(_('could not extract binary patch'))
        size = int(line[8:].rstrip())
        dec = []
        line = fp.readline()
        self.hunk.append(line)
        while len(line) > 1:
            l = line[0]
            if l <= 'Z' and l >= 'A':
                l = ord(l) - ord('A') + 1
            else:
                l = ord(l) - ord('a') + 27
            dec.append(base85.b85decode(line[1:-1])[:l])
            line = fp.readline()
            self.hunk.append(line)
        text = zlib.decompress(''.join(dec))
        if len(text) != size:
            raise PatchError(_('binary patch is %d bytes, not %d') %
                             len(text), size)
        self.text = text

def parsefilename(str, git=False):
    # --- filename \t|space stuff
    if git:
        return s
    s = str[4:]
    i = s.find('\t')
    if i < 0:
        i = s.find(' ')
        if i < 0:
            return s
    return s[:i]

def selectfile(afile_orig, bfile_orig, hunk, strip, reverse):
    def pathstrip(path, count=1):
        pathlen = len(path)
        i = 0
        if count == 0:
            return path.rstrip()
        while count > 0:
            i = path.find('/', i)
            if i == -1:
                raise PatchError(_("unable to strip away %d dirs from %s") %
                                 (count, path))
            i += 1
            # consume '//' in the path
            while i < pathlen - 1 and path[i] == '/':
                i += 1
            count -= 1
        return path[i:].rstrip()

    nulla = afile_orig == "/dev/null"
    nullb = bfile_orig == "/dev/null"
    afile = pathstrip(afile_orig, strip)
    gooda = os.path.exists(afile) and not nulla
    bfile = pathstrip(bfile_orig, strip)
    if afile == bfile:
        goodb = gooda
    else:
        goodb = os.path.exists(bfile) and not nullb
    createfunc = hunk.createfile
    if reverse:
        createfunc = hunk.rmfile
    if not goodb and not gooda and not createfunc():
        raise PatchError(_("unable to find %s or %s for patching") %
                         (afile, bfile))
    if gooda and goodb:
        fname = bfile
        if afile in bfile:
            fname = afile
    elif gooda:
        fname = afile
    elif not nullb:
        fname = bfile
        if afile in bfile:
            fname = afile
    elif not nulla:
        fname = afile
    return fname

class linereader:
    # simple class to allow pushing lines back into the input stream
    def __init__(self, fp):
        self.fp = fp
        self.buf = []

    def push(self, line):
        self.buf.append(line)

    def readline(self):
        if self.buf:
            l = self.buf[0]
            del self.buf[0]
            return l
        return self.fp.readline()

def applydiff(ui, fp, changed, strip=1, sourcefile=None, reverse=False,
              updatedir=None):
    """reads a patch from fp and tries to apply it.  The dict 'changed' is
       filled in with all of the filenames changed by the patch.  Returns 0
       for a clean patch, -1 if any rejects were found and 1 if there was
       any fuzz.""" 

    def scangitpatch(fp, firstline, cwd=None):
        '''git patches can modify a file, then copy that file to
        a new file, but expect the source to be the unmodified form.
        So we scan the patch looking for that case so we can do
        the copies ahead of time.'''

        pos = 0
        try:
            pos = fp.tell()
        except IOError:
            fp = cStringIO.StringIO(fp.read())

        (dopatch, gitpatches) = readgitpatch(fp, firstline)
        for gp in gitpatches:
            if gp.copymod:
                copyfile(gp.oldpath, gp.path, basedir=cwd)

        fp.seek(pos)

        return fp, dopatch, gitpatches

    current_hunk = None
    current_file = None
    afile = ""
    bfile = ""
    state = None
    hunknum = 0
    rejects = 0

    git = False
    gitre = re.compile('diff --git (a/.*) (b/.*)')

    # our states
    BFILE = 1
    err = 0
    context = None
    lr = linereader(fp)
    dopatch = True
    gitworkdone = False

    while True:
        newfile = False
        x = lr.readline()
        if not x:
            break
        if current_hunk:
            if x.startswith('\ '):
                current_hunk.fix_newline()
            ret = current_file.apply(current_hunk, reverse)
            if ret > 0:
                err = 1
            current_hunk = None
            gitworkdone = False
        if ((sourcefile or state == BFILE) and ((not context and x[0] == '@') or
            ((context or context == None) and x.startswith('***************')))):
            try:
                if context == None and x.startswith('***************'):
                    context = True
                current_hunk = hunk(x, hunknum + 1, lr, context)
            except PatchError:
                current_hunk = None
                continue
            hunknum += 1
            if not current_file:
                if sourcefile:
                    current_file = patchfile(ui, sourcefile)
                else:
                    current_file = selectfile(afile, bfile, current_hunk,
                                              strip, reverse)
                    current_file = patchfile(ui, current_file)
                changed.setdefault(current_file.fname, (None, None))
        elif state == BFILE and x.startswith('GIT binary patch'):
            current_hunk = binhunk(changed[bfile[2:]][1])
            if not current_file:
                if sourcefile:
                    current_file = patchfile(ui, sourcefile)
                else:
                    current_file = selectfile(afile, bfile, current_hunk,
                                              strip, reverse)
                    current_file = patchfile(ui, current_file)
            hunknum += 1
            current_hunk.extract(fp)
        elif x.startswith('diff --git'):
            # check for git diff, scanning the whole patch file if needed
            m = gitre.match(x)
            if m:
                afile, bfile = m.group(1, 2)
                if not git:
                    git = True
                    fp, dopatch, gitpatches = scangitpatch(fp, x)
                    for gp in gitpatches:
                        changed[gp.path] = (gp.op, gp)
                # else error?
                # copy/rename + modify should modify target, not source
                if changed.get(bfile[2:], (None, None))[0] in ('COPY',
                                                               'RENAME'):
                    afile = bfile
                    gitworkdone = True
            newfile = True
        elif x.startswith('---'):
            # check for a unified diff
            l2 = lr.readline()
            if not l2.startswith('+++'):
                lr.push(l2)
                continue
            newfile = True
            context = False
            afile = parsefilename(x, git)
            bfile = parsefilename(l2, git)
        elif x.startswith('***'):
            # check for a context diff
            l2 = lr.readline()
            if not l2.startswith('---'):
                lr.push(l2)
                continue
            l3 = lr.readline()
            lr.push(l3)
            if not l3.startswith("***************"):
                lr.push(l2)
                continue
            newfile = True
            context = True
            afile = parsefilename(x, git)
            bfile = parsefilename(l2, git)

        if newfile:
            if current_file:
                current_file.close()
                rejmerge(current_file)
                rejects += len(current_file.rej)
            state = BFILE
            current_file = None
            hunknum = 0
    if current_hunk:
        if current_hunk.complete():
            ret = current_file.apply(current_hunk, reverse)
            if ret > 0:
                err = 1
        else:
            fname = current_file and current_file.fname or None
            raise PatchError(_("malformed patch %s %s") % (fname,
                             current_hunk.desc))
    if current_file:
        current_file.close()
        rejmerge(current_file)
        rejects += len(current_file.rej)
    if updatedir and git:
        updatedir(gitpatches)
    if rejects:
        return -1
    if hunknum == 0 and dopatch and not gitworkdone:
        raise PatchError(_("No valid hunks found"))
    return err


# This portion of the code came from the mpatch script

global_conflicts = 0
global_rejects = 0

wsre = re.compile('[ \r\t\n]+')

class rejhunk:
    def __init__(self, h, f):
        self.hunk = h
        self.match = []
        self.score = 0
        self.start = 0
        self.conficts = 0
        self.file = f
        self.direction = False

    def findline(self, l, min):
        # look for line l in the file's hash.  min is the minimum line number
        # to return
        try:
            res = self.file.hash[l]
        except KeyError:
            return None
        i = bisect.bisect_right(res, min)
        if i < len(res):
            return res[i]
        return None
        
    def findforward(self):
        # search for the new text of the hunk already in the file.
        # the file should already be hashed
        hlines = self.hunk.newctrl()
        orig_start = self.hunk.startb
        if len(hlines) < 6:
            # only guess about applied hunks when there is some context.
            return False
        for fuzzlen in xrange(3):
            lines = self.hunk.fuzzit(hlines, fuzzlen, False)
            cand = self.file.findlines(lines[0][1:], orig_start)
            for l in cand:
                if diffhelpers.testhunk(lines, self.file.lines, l) == 0:
                    self.file.ui.warn(
                             _("hunk %d already applied at line %d (fuzz %d)\n"
                             % (self.hunk.number, l+1, fuzzlen)))
                    return True
        return False

    def search(self):
        # search through the file for a good place to put our hunk.
        # on return the rejhunk is setup for a call to apply.  We will
        # either have found a suitable location or have given up and
        # set things up to put the hunk at the start of the file.
        self.file.hashlines()
        if self.findforward():
            # this hunk was already applied
            self.score = -2
            return

        scan = ((False, self.hunk.old(), self.hunk.starta),
                 (True, self.hunk.newctrl(), self.hunk.startb))
        last = (-1, -1, 0, [], None)
        for direction, hlines, hstart in scan:
            maxlines = min(len(hlines)/2+1, 15)
            # don't look forward if we already have a conflict free
            # match of the old text
            if direction and last[1] > 3 and last[2] == 0:
                break
            for i in xrange(maxlines):
                try:
                    res = self.file.hash[hlines[i][1:]]
                except KeyError:
                    continue
                for s in res:
                    start, score, conflicts, match = self.align(s-1, i, hlines)
                    
                    # new text matches are more likely to have false positives.
                    # use a higher bar for them.
                    if direction and score < 7:
                        score = -1

                    if score > last[1]:
                        update = True
                        # more special checks for replacing an match of the
                        # old text with the new.  Check for conflicts
                        # and the size of the total match.
                        if direction and last[4] == False:
                            dist = len(match) - len(hlines)
                            if conflicts and dist > ((len(hlines) * 3) / 2):
                                update = False
                        if update:
                            last = (start, score, conflicts, match, direction)
                    elif score == last[1]:
                        distold = abs(last[0] - hstart)
                        distnew = abs(start - hstart)
                        if direction == False or last[4] == True:
                            # we prefer to match the old text, so if
                            # we don't replace a match of the old text
                            # with a match of the new
                            if distnew < distold:
                                last = (start, score, conflicts, match,
                                        direction)
        if last[1] > 3:
            (self.start, self.score, self.conflicts,
             self.match, self.direction) = last
        else:
            # no good locations found, lets just put it at the start of the
            # file.
            self.conflicts = 1
            
    def scoreline(self, l):
        ws = wsre.sub('', l)
        if len(ws) == 0:
            return .25
        return 1

    def apply(self):
        # after calling search, call apply to merge the hunk into the file.
        # on return the file is dirtied but not written
        if self.direction:
            # when merging into already applied data, the match array
            # has it all
            new = []
        else:
            new = self.hunk.newctrl()
        newi = 0
        filei = self.start
        lines = []
        i = 0
        while i < len(self.match) or newi < len(new):
            # the order is a little strange.
            # ctrl of '|' means the file had lines the hunk did not.  These
            # need to go before any '+' lines from the new hunk
            if i < len(self.match):
                l = self.match[i]
                ctrl = l[0]
                if ctrl == '|':
                    lines.append(l[1:])
                    filei += 1
                    i += 1
                    continue

            # find lines added by the hunk
            if newi < len(new):
                l = new[newi]
                if l[0] == '+':
                    lines.append(l[1:])
                    newi += 1
                    continue
                elif i >= len(self.match):
                    # if we've gone through the whole match array,
                    # the new hunk may have context that didn't exist
                    # in the file.  Just skip past it.
                    newi += 1
                    continue

            l = self.match[i]
            i += 1
            ctrl = l[0]
            if ctrl == '-':
                # deleted by the hunk, skip over it in the file
                filei += 1
                pass
            elif ctrl == '^':
                # in the hunk but missing from the file.  skip over it in
                # the hunk
                newi += 1
            elif ctrl == '<':
                # deleted by the hunk but missing from the file.  Let the
                # user know by inserting the deletion marker
                lines.append(l)
            elif ctrl == '+':
                # only happens when self.direction == True
                lines.append(l[1:])
                continue
            elif ctrl == ' ':
                # context from the hunk found in the file.  Add it
                lines.append(l[1:])
                newi += 1
                filei += 1
            else:
                raise PatchError("unknown control char %s" % l)

        self.file.lines[self.start:filei] = lines
        self.file.dirty = 1

    def align(self, fstart, hstart, hlines):
        hcur = hstart
        fcur = fstart
        flines = self.file.lines
        retstart = None
        match = []
        score = 0
        conflicts = 0

        # add deletion markers for any lines removed by the parts of the
        # hunk we could not find (between 0 and hstart)
        for i in xrange(hstart):
            if hlines[i][0] == '-':
                match.append('<<<<del ' + hlines[i][1:])
            elif hlines[i][0] == '+':
                match.append(hlines[i])
        consec = False
        last_append = None
        while hcur < len(hlines):
            if hcur > len(hlines)/2 and score <= 0:
                return (-1, -1, 1, [])
            fnext = self.findline(hlines[hcur][1:], fcur)
            ctrl = hlines[hcur][0]
            if fnext == None or (fcur >=0 and fnext - fcur > 20):
                consec = False
                fnext = None
                if ctrl == '-':
                    # we've failed to find a line the patch wanted to delete.
                    # record it as a conflict.
                    match.append('<<<<del ' + hlines[hcur][1:])
                    conflicts += 1
                elif ctrl == '+':
                    match.append(hlines[hcur])
                    conflicts += 1
                else:
                    match.append('^' + hlines[hcur][1:])
            else:
                if fcur >= 0 and retstart:
                    # any lines between fcur and fnext were in the file but
                    # not the hunk.
                    # decrement our score for a big block of missing lines
                    dist = fnext - fcur
                    while dist > 5:
                        score -= 1
                        dist -= 5
                    for x in xrange(fcur+1, fnext):
                        match.append('|' + flines[x])
                if retstart == None:
                    retstart = fnext
                # plus one just for finding a match
                # plus one more if it was a consecutive match
                # plus one more if it was a match on a line we're deleting
                # or adding.  But, only do it for non-ws lines and for
                # lines relatlively close to the last match
                inc = self.scoreline(hlines[hcur][1:])
                score += inc
                if consec and fnext == fcur + 1:
                    score += inc
                if ctrl == '-' or ctrl == '+':
                    ws = hlines[hcur].rstrip()
                    if len(ws) > 1 and fnext - fcur < 5:
                        score += inc
                consec = True
                # record the line from the hunk we did find
                if ctrl == '+':
                    # we matched a line added by the hunk.  The code that
                    # merges needs to know to inc the file line number to
                    # include this line, so instead of adding a + ctrl
                    # use |
                    match.append('|' + hlines[hcur][1:])
                else:
                    match.append(hlines[hcur])

            hcur += 1
            if fnext != None:
                fcur = fnext
        return (retstart, score, conflicts, match)

def rejmerge(pfile):
    def backup(orig):
        fname = orig + ".mergebackup"
        try: os.unlink(fname)
        except: pass
        old = file(orig)
        new = file(fname, 'w')
        for x in old:
            new.write(x)
        return fname

    rej = pfile.rej
    if not rej:
        return
    backupf = None
    badrej = []
    for h in rej:
        r = rejhunk(h, pfile)
        r.search()
        if r.score >= 0:
            if not backupf:
                backupf = backup(pfile.fname)
            global global_conflicts
            global global_rejects
            if r.direction:
                s = "warning file %s hunk %d: merging " % (
                     pfile.fname, h.number)
                pfile.ui.warn(s + "with changes already applied\n")
            r.apply()
            if r.conflicts > 0:
                global_conflicts += 1
            global_rejects += 1
    if backupf:
        global merge_func
        pfile.rej = badrej
        pfile.write()
        merge_func(pfile.ui, pfile.fname, backupf)
        try:
            os.unlink(backupf)
        except:
            pass

def updatedir(patches):
    l = patches.keys()
    l.sort()
    for f in l:
        ctype, gp = patches[f]
        if gp.mode != None:
            x = gp.mode & 0100 != 0
            util.set_exec(gp.path, x)

global merge_func
def run(ui, rejfile, sourcefile, mergefunc):
    '''
    Attempt to apply the patch hunks in rejfile,  When patch fails,
    run merge_func to launch user's preferred visual diff tool to
    resolve conflicts.
    '''
    global merge_func
    merge_func = mergefunc
    diffp = file(rejfile)
    changed = {}
    try:
        ret = applydiff(ui, diffp, changed, strip=1,
                          sourcefile=sourcefile,
                          updatedir=updatedir,
                          reverse=False)
    except PatchError, inst:
        sys.stderr.write("Error: %s\n" % inst)
