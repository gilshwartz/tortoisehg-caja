# filedata.py - generate displayable file data
#
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os

from mercurial import error, match, patch, util, mdiff
from mercurial import ui as uimod

from tortoisehg.util import hglib, patchctx
from tortoisehg.hgqt.i18n import _

class FileData(object):
    def __init__(self, ctx, ctx2, wfile, status=None):
        self.contents = None
        self.ucontents = None
        self.error = None
        self.olddata = None
        self.diff = None
        self.flabel = u''
        self.elabel = u''
        try:
            self.readStatus(ctx, ctx2, wfile, status)
        except (EnvironmentError, error.LookupError), e:
            self.error = hglib.tounicode(str(e))

    def checkMaxDiff(self, ctx, wfile, maxdiff, status):
        p = _('File or diffs not displayed: ')
        try:
            fctx = ctx.filectx(wfile)
            if ctx.rev() is None:
                size = fctx.size()
            else:
                # fctx.size() can read all data into memory in rename cases so
                # we read the size directly from the filelog, this is deeper
                # under the API than I prefer to go, but seems necessary
                size = fctx._filelog.rawsize(fctx.filerev())
        except (EnvironmentError, error.LookupError), e:
            self.error = p + hglib.tounicode(str(e))
            return None
        if size > maxdiff:
            self.error = p + _('File is larger than the specified max size.\n'
                               'maxdiff = %s KB') % (maxdiff // 1024)
            return None
        try:
            data = fctx.data()
            if '\0' in data:
                self.error = p + _('File is binary')
                if status != 'A':
                    return None

                renamed = fctx.renamed()
                if renamed:
                    oldname, node = renamed
                    fr = hglib.tounicode(oldname)
                    self.flabel += _(' <i>(renamed from %s)</i>') % fr
                else:
                    self.flabel += _(' <i>(was added)</i>')

                return None
        except (EnvironmentError, util.Abort), e:
            self.error = p + hglib.tounicode(str(e))
            return None
        return fctx, data

    def isValid(self):
        return self.error is None

    def readStatus(self, ctx, ctx2, wfile, status):
        def getstatus(repo, n1, n2, wfile):
            m = match.exact(repo.root, repo.getcwd(), [wfile])
            modified, added, removed = repo.status(n1, n2, match=m)[:3]
            if wfile in modified:
                return 'M'
            if wfile in added:
                return 'A'
            if wfile in removed:
                return 'R'
            if wfile in ctx:
                return 'C'
            return None

        repo = ctx._repo
        self.flabel += u'<b>%s</b>' % hglib.tounicode(wfile)

        if isinstance(ctx, patchctx.patchctx):
            self.diff = ctx.thgmqpatchdata(wfile)
            flags = ctx.flags(wfile)
            if flags in ('x', '-'):
                lbl = _("exec mode has been <font color='red'>%s</font>")
                change = (flags == 'x') and _('set') or _('unset')
                self.elabel = lbl % change
            elif flags == 'l':
                self.flabel += _(' <i>(is a symlink)</i>')
            return

        if ctx2:
            # If a revision to compare to was provided, we must put it in
            # the context of the subrepo as well
            if ctx2._repo.root != ctx._repo.root:
                wsub2, wfileinsub2, sctx2 = \
                    hglib.getDeepestSubrepoContainingFile(wfile, ctx2)
                if wsub2:
                    ctx2 = sctx2

        absfile = repo.wjoin(wfile)
        if (wfile in ctx and 'l' in ctx.flags(wfile)) or \
           os.path.islink(absfile):
            if wfile in ctx:
                data = ctx[wfile].data()
            else:
                data = os.readlink(absfile)
            self.contents = data
            self.flabel += _(' <i>(is a symlink)</i>')
            return

        if status is None:
            status = getstatus(repo, ctx.p1().node(), ctx.node(), wfile)
        if ctx2 is None:
            ctx2 = ctx.p1()

        if status == 'S':
            try:
                from mercurial import subrepo, commands

                def genSubrepoRevChangedDescription(subrelpath, sfrom, sto, repo):
                    """Generate a subrepository revision change description"""
                    out = []
                    def getLog(_ui, srepo, opts):
                        _ui.pushbuffer()
                        try:
                            commands.log(_ui, srepo, **opts)
                            logOutput = _ui.popbuffer()
                        except error.ParseError, e:
                            # Some mercurial versions have a bug that results in
                            # saving a subrepo node id in the .hgsubstate file
                            # which ends with a "+" character. If that is the
                            # case, add a warning to the output, but try to
                            # get the revision information anyway
                            logOutput = ''
                            for n, rev in enumerate(opts['rev']):
                                if rev.endswith('+'):
                                    logOutput += _('[WARNING] Invalid subrepo '
                                        'revision ID:\n\t%s\n\n') % rev
                                    opts['rev'][n] = rev[:-1]
                            commands.log(_ui, srepo, **opts)
                            logOutput += _ui.popbuffer()
                        return logOutput

                    opts = {'date':None, 'user':None, 'rev':[sfrom]}
                    subabspath = os.path.join(repo.root, subrelpath)
                    missingsub = not os.path.isdir(subabspath)
                    incompletesub = False
                    sfromlog = ''
                    def isinitialrevision(rev):
                        return all([el == '0' for el in rev])
                    if isinitialrevision(sfrom):
                        sfrom = ''
                    if isinitialrevision(sto):
                        sto = ''
                    if not sfrom and not sto:
                        sstatedesc = 'new'
                        out.append(_('Subrepo created and set to initial revision.') + u'\n\n')
                        return out, sstatedesc
                    elif not sfrom:
                        sstatedesc = 'new'
                        out.append(_('Subrepo initialized to revision:') + u'\n\n')
                    elif not sto:
                        sstatedesc = 'removed'
                        out.append(_('Subrepo removed from repository.') + u'\n\n')
                        return out, sstatedesc
                    elif sfrom == sto:
                        sstatedesc = 'unchanged'
                        out.append(_('Subrepo was not changed.') + u'\n\n')
                        out.append(_('Subrepo state is:') + u'\n\n')
                        if missingsub:
                            out.append(_('changeset: %s') % sfrom + u'\n')
                        else:
                            out.append(hglib.tounicode(getLog(_ui, srepo, opts)))
                        return out, sstatedesc
                    else:
                        sstatedesc = 'changed'

                        out.append(_('Revision has changed to:') + u'\n\n')

                        if missingsub:
                            sfromlog = _('changeset: %s') % sfrom + u'\n\n'
                        else:
                            sfromlog = hglib.tounicode(getLog(_ui, srepo, opts))
                            if not sfromlog:
                                incompletesub = True
                                sfromlog = _('changeset: %s') % sfrom + u'\n\n'
                        sfromlog = _('From:') + u'\n' + sfromlog

                    if missingsub:
                        stolog = _('changeset: %s') % sto + '\n\n'
                        sfromlog += _('Subrepository not found in the working '
                            'directory.') + '\n'
                        sfromlog += _('Further subrepository revision '
                            'information cannot be retrieved.') + '\n'
                    elif incompletesub:
                        stolog = _('changeset: %s') % sto + '\n\n'
                        sfromlog += _('Subrepository is either damaged or '
                            'missing some revisions') + '\n'
                        sfromlog += _('Further subrepository revision '
                            'information cannot be retrieved.') + '\n'
                        sfromlog += _('You may need to open the missing '
                            'subrepository and manually\n'
                            'pull the missing revisions from its '
                            'source repository.') + '\n'
                    else:
                        opts['rev'] = [sto]
                        stolog = getLog(_ui, srepo, opts)

                    if not stolog:
                        stolog = _('Initial revision') + u'\n'
                    out.append(hglib.tounicode(stolog))

                    if sfromlog:
                        out.append(hglib.tounicode(sfromlog))

                    return out, sstatedesc

                srev = ctx.substate.get(wfile, subrepo.nullstate)[1]
                srepo = None
                try:
                    subabspath = os.path.join(ctx._repo.root, wfile)
                    if not os.path.isdir(subabspath):
                        sactual = ''
                    else:
                        sub = ctx.sub(wfile)
                        if isinstance(sub, subrepo.hgsubrepo):
                            srepo = sub._repo
                            sactual = srepo['.'].hex()
                        else:
                            self.error = _('Not a Mercurial subrepo, not previewable')
                            return
                except (util.Abort), e:
                    sactual = ''

                out = []
                _ui = uimod.ui()

                if srepo is None or ctx.rev() is not None:
                    data = []
                else:
                    _ui.pushbuffer()
                    commands.status(_ui, srepo)
                    data = _ui.popbuffer()
                    if data:
                        out.append(_('File Status:') + u'\n')
                        out.append(hglib.tounicode(data))
                        out.append(u'\n')

                sstatedesc = 'changed'
                if ctx.rev() is not None:
                    sparent = ctx.p1().substate.get(wfile, subrepo.nullstate)[1]
                    subrepochange, sstatedesc = \
                        genSubrepoRevChangedDescription(wfile,
                            sparent, srev, ctx._repo)
                    out += subrepochange
                else:
                    sstatedesc = 'dirty'
                    if srev != sactual:
                        subrepochange, sstatedesc = \
                            genSubrepoRevChangedDescription(wfile,
                                srev, sactual, ctx._repo)
                        out += subrepochange
                        if data:
                            sstatedesc += ' and dirty'
                    elif srev and not sactual:
                        sstatedesc = 'removed'
                self.ucontents = u''.join(out).strip()

                lbl = {
                    'changed':   _('(is a changed sub-repository)'),
                    'unchanged':   _('(is an unchanged sub-repository)'),
                    'dirty':   _('(is a dirty sub-repository)'),
                    'new':   _('(is a new sub-repository)'),
                    'removed':   _('(is a removed sub-repository)'),
                    'changed and dirty':   _('(is a changed and dirty sub-repository)'),
                    'new and dirty':   _('(is a new and dirty sub-repository)'),
                    'removed and dirty':   _('(is a removed sub-repository)')
                }[sstatedesc]
                self.flabel += ' <i>' + lbl + '</i>'
                if sactual:
                    lbl = _(' <a href="subrepo:%s">open...</a>')
                    self.flabel += lbl % hglib.tounicode(srepo.root)
            except (EnvironmentError, error.RepoError, util.Abort), e:
                self.error = _('Error previewing subrepo: %s') % \
                        hglib.tounicode(str(e))
            return

        # TODO: elif check if a subdirectory (for manifest tool)

        maxdiff = repo.maxdiff
        mde = _('File or diffs not displayed: '
                'File is larger than the specified max size.\n'
                'maxdiff = %s KB') % (maxdiff // 1024)

        if status in ('R', '!'):
            if wfile in ctx.p1():
                fctx = ctx.p1()[wfile]
                if fctx._filelog.rawsize(fctx.filerev()) > maxdiff:
                    self.error = mde
                else:
                    olddata = fctx.data()
                    if '\0' in olddata:
                        self.error = 'binary file'
                    else:
                        self.contents = olddata
                self.flabel += _(' <i>(was deleted)</i>')
            else:
                self.flabel += _(' <i>(was added, now missing)</i>')
            return

        if status in ('I', '?', 'C'):
            if ctx.rev() is None:
                if status in ('I', '?'):
                    self.flabel += _(' <i>(is unversioned)</i>')
                if os.path.getsize(absfile) > maxdiff:
                    self.error = mde
                    return
                else:
                    data = util.posixfile(absfile, 'r').read()
            else:
                data = ctx.filectx(wfile).data()
            if '\0' in data:
                self.error = 'binary file'
            else:
                self.contents = data
            return

        if status in ('M', 'A'):
            res = self.checkMaxDiff(ctx, wfile, maxdiff, status)
            if res is None:
                return
            fctx, newdata = res
            self.contents = newdata
            change = None
            for pfctx in fctx.parents():
                if 'x' in fctx.flags() and 'x' not in pfctx.flags():
                    change = _('set')
                elif 'x' not in fctx.flags() and 'x' in pfctx.flags():
                    change = _('unset')
            if change:
                lbl = _("exec mode has been <font color='red'>%s</font>")
                self.elabel = lbl % change

        if status == 'A':
            renamed = fctx.renamed()
            if not renamed:
                self.flabel += _(' <i>(was added)</i>')
                return

            oldname, node = renamed
            fr = hglib.tounicode(oldname)
            self.flabel += _(' <i>(renamed from %s)</i>') % fr
            olddata = repo.filectx(oldname, fileid=node).data()
        elif status == 'M':
            if wfile not in ctx2:
                # merge situation where file was added in other branch
                self.flabel += _(' <i>(was added)</i>')
                return
            oldname = wfile
            olddata = ctx2[wfile].data()
        else:
            return

        self.olddata = olddata
        newdate = util.datestr(ctx.date())
        olddate = util.datestr(ctx2.date())
        revs = [str(ctx), str(ctx2)]
        diffopts = patch.diffopts(repo.ui, {})
        diffopts.git = False
        self.diff = mdiff.unidiff(olddata, olddate, newdata, newdate,
                                  oldname, wfile, revs, diffopts)
