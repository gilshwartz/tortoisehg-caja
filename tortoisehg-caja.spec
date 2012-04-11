%{!?python_sitelib: %global python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
# Pure python package
%define debug_package %{nil}

Name:           tortoisehg-caja
Version:        2.1.4
Release:        3%{?dist}
Summary:        Mercurial GUI command line tool thg
Group:          Development/Tools
License:        GPLv2
# - few files are however under the more permissive GPLv2+
URL:            http://tortoisehg.bitbucket.org/
Source0:        http://bitbucket.org/tortoisehg/targz/downloads/%{name}-%{version}.tar.gz
# This package _is_ noarch, but that isn't possible because the caja
# subpackage has to be arch-specific:
# BuildArch:    noarch
BuildRequires:  python-devel, gettext, python-sphinx, PyQt4-devel, desktop-file-utils
#Requires:       python-iniparse, mercurial >= 1.9, mercurial < 2.0
# gconf needed at util/shlib.py for browse_url(url).
#Requires:       mate-python2-mateconf
#Requires:       PyQt4 >= 4.6, qscintilla-python, python-pygments

#%description
#This package contains the thg command line tool, which provides a graphical
#user interface to the Mercurial distributed revision control system.

Requires:       tortoisehg = %{version}, python-caja
Obsoletes:		mate-tortoisehg
Obsoletes:		mate-tortoisehg-caja
Provides:		tortoisehg-caja

%description
This package contains the TortoiseHg Mate/Caja extension, which makes the
Mercurial distributed revision control system available in the file manager
with a graphical interface.

Note that the caja extension has been deprecated upstream.

%prep
%setup -q

# Fedora Caja python extensions lives in lib64 on x86_64 (https://bugzilla.redhat.com/show_bug.cgi?id=509633) ...
%{__sed} -i "s,lib/caja,%{_lib}/caja,g" setup.py

cat > tortoisehg/util/config.py << EOT
bin_path     = "%{_bindir}"
license_path = "%{_docdir}/%{name}-%{version}/COPYING.txt"
locale_path  = "%{_datadir}/locale"
icon_path    = "%{_datadir}/pixmaps/tortoisehg/icons"
nofork       = True
EOT

%build
%{__python} setup.py build

(cd doc && make html)
rm doc/build/html/.buildinfo

%install
rm -rf $RPM_BUILD_ROOT

%{__python} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT

mkdir -p $RPM_BUILD_ROOT/%{_sysconfdir}/mercurial/hgrc.d
install contrib/mergetools.rc $RPM_BUILD_ROOT%{_sysconfdir}/mercurial/hgrc.d/thgmergetools.rc

ln -s tortoisehg/icons/svg/thg_logo.svg $RPM_BUILD_ROOT%{_datadir}/pixmaps/%{name}_logo.svg
desktop-file-install --dir=$RPM_BUILD_ROOT%{_datadir}/applications contrib/tortoisehg.desktop
#mv -f $RPM_BUILD_ROOT%{_datadir}/applications/tortoisehg.desktop $RPM_BUILD_ROOT%{_datadir}/applications/mate-tortoisehg.desktop
rm -rf $RPM_BUILD_ROOT%{_datadir}/pixmaps
rm -rf $RPM_BUILD_ROOT%{_bindir}/thg
rm -rf $RPM_BUILD_ROOT%{_sysconfdir}/mercurial
rm -rf $RPM_BUILD_ROOT%{python_sitelib}
rm -rf $RPM_BUILD_ROOT%{_datadir}/applications
rm -rf $RPM_BUILD_ROOT%{_datadir}/locale

#%find_lang tortoisehg

%clean
rm -rf $RPM_BUILD_ROOT

#%files -f tortoisehg.lang

#%defattr(-,root,root,-)
#%doc COPYING.txt doc/build/html/
#%{_bindir}/thg
#%{python_sitelib}/tortoisehg/
#%{python_sitelib}/tortoisehg-*.egg-info
#%{_datadir}/pixmaps/mate/tortoisehg/
#%{_datadir}/pixmaps/%{name}_logo.svg
#%{_datadir}/applications/%{name}.desktop

#%config(noreplace) %attr(644,root,root) %{_sysconfdir}/mate/mercurial/hgrc.d/thgmergetools.rc

%files
%defattr(-,root,root,-)
%{_libdir}/caja/extensions-2.0/python/caja-thg.py*

%changelog
* Tue Apr 10 2012 Wolfgang Ulbrich <info@raveit.de> - 2.1.4-3
- switch to python-caja instead of caja-python

* Sat Feb 18 2012 Wolfgang Ulbrich <info@raveit.de> - 2.1.4-2
- remove the mate-tortoisehg package because tortoisehg is already in fedora
- rename mate-tortoisehg-caja to tortoisehg-caja

* Tue Feb 07 2012 Wolfgang Ulbrich <info@raveit.de> - 2.1.4-1
- mate-tortoisehg.spec based on tortoisehg-2.1.4-2.fc16 spec

* Fri Oct 07 2011 Mads Kiilerich <mads@kiilerich.com> - 2.1.4-2
- the real tortoisehg-2.1.4, not just a stupid proxy

* Thu Oct 06 2011 Mads Kiilerich <mads@kiilerich.com> - 2.1.4-1
- tortoisehg-2.1.4

* Sun Aug 28 2011 Mads Kiilerich <mads@kiilerich.com> - 2.1.3-1
- tortoisehg-2.1.3

* Wed Aug 03 2011 Mads Kiilerich <mads@kiilerich.com> - 2.1.2-1
- tortoisehg-2.1.2

* Mon Jul 11 2011 Mads Kiilerich <mads@kiilerich.com> - 2.1.1-1
- tortoisehg-2.1.1
- clarify in requirements that this is intended to work with Mercurial 1.9.x only

* Sun Jul 03 2011 Mads Kiilerich <mads@kiilerich.com> - 2.1-1
- tortoisehg-2.1

* Thu Jun 02 2011 Mads Kiilerich <mads@kiilerich.com> - 2.0.5-1
- tortoisehg-2.0.5

* Mon May 02 2011 Mads Kiilerich <mads@kiilerich.com> - 2.0.4-1
- tortoisehg-2.0.4

* Sat Apr 02 2011 Mads Kiilerich <mads@kiilerich.com> - 2.0.3-1
- tortoisehg-2.0.3

* Thu Mar 10 2011 Mads Kiilerich <mads@kiilerich.com> - 2.0.2-1
- tortoisehg-2.0.2

* Thu Mar 10 2011 Mads Kiilerich <mads@kiilerich.com> - 2.0.1-1
- tortoisehg-2.0.1
- require Mercurial 1.8 or later

* Thu Mar 03 2011 Mads Kiilerich <mads@kiilerich.com> - 2.0-1
- tortoisehg-2.0

* Wed Feb 09 2011 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.9.2.4-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_15_Mass_Rebuild

* Mon Feb 07 2011 Mads Kiilerich <mads@kiilerich.com> - 1.9.2.4-1
- tortoisehg-1.9.2+4-cff31955a6fa
- preparing for the qt based TortoiseHg 2.0 in Fedora 15

* Thu Feb 03 2011 Mads Kiilerich <mads@kiilerich.com> - 1.1.9.1-1
- tortoisehg-1.1.9.1

* Wed Feb 02 2011 Mads Kiilerich <mads@kiilerich.com> - 1.1.9-1
- tortoisehg-1.1.9

* Sun Jan 02 2011 Mads Kiilerich <mads@kiilerich.com> - 1.1.8-1
- tortoisehg-1.1.8

* Thu Dec 02 2010 Mads Kiilerich <mads@kiilerich.com> - 1.1.7-1
- tortoisehg-1.1.7

* Tue Nov 16 2010 Mads Kiilerich <mads@kiilerich.com> - 1.1.6.1-1
- tortoisehg-1.1.6.1

* Tue Nov 16 2010 Mads Kiilerich <mads@kiilerich.com> - 1.1.6-1
- tortoisehg-1.1.6

* Sun Nov 07 2010 Mads Kiilerich <mads@kiilerich.com> - 1.1.5-1
- tortoisehg-1.1.5

* Fri Aug 27 2010 Mads Kiilerich <mads@kiilerich.com> - 1.1.3-1
- tortoisehg-1.1.3

* Sun Aug  8 2010 Mads Kiilerich <mads@kiilerich.com> - 1.1.2-1
- tortoisehg-1.1.2

* Thu Jul 22 2010 David Malcolm <dmalcolm@redhat.com> - 1.1.1-2
- Rebuilt for https://fedoraproject.org/wiki/Features/Python_2.7/MassRebuild

* Tue Jul 13 2010 Mads Kiilerich <mads@kiilerich.com> - 1.1.1-1
- tortoisehg-1.1.1 with minor bugfixes
- requires mercurial-1.6

* Fri Jul 02 2010 Mads Kiilerich <mads@kiilerich.com> - 1.1-1
- tortoisehg-1.1
- Still requires Mercurial 1.5 but also works with 1.6

* Wed Jun  2 2010 Mads Kiilerich <mads@kiilerich.com> - 1.0.4-1
- New upstream bugfix release 1.0.4

* Sun May 16 2010 Mads Kiilerich <mads@kiilerich.com> - 1.0.3-1
- New upstream bugfix release 1.0.3
- Drop unused dependency gnome-python2-gtksourceview

* Fri Apr  2 2010 Mads Kiilerich <mads@kiilerich.com> - 1.0.1-1
- New upstream bugfix release 1.0.1

* Sat Mar  6 2010 Mads Kiilerich <mads@kiilerich.com> - 1.0-1
- New upstream release 1.0

* Tue Feb  2 2010 Mads Kiilerich <mads@kiilerich.com> - 0.9.3-1
- New upstream minor release 0.9.3

* Sat Jan  2 2010 Mads Kiilerich <mads@kiilerich.com> - 0.9.2-1
- New upstream bugfix release 0.9.2

* Thu Dec  3 2009 Mads Kiilerich <mads@kiilerich.com> - 0.9.1.1-1
- tortoisehg-0.9.1.1 - a brown paperbag release

* Thu Dec  3 2009 Mads Kiilerich <mads@kiilerich.com> - 0.9.1-1
- tortoisehg-0.9.1

* Wed Nov 18 2009 Mads Kiilerich <mads@kiilerich.com> - 0.9-1
- Update to tortoisehg-0.9

* Mon Nov 16 2009 Mads Kiilerich <mads@kiilerich.com> - 0.9-0.2.hg2525801b8b8d
- New upstream snapshot, pretty close to 0.9
- First koji upload

* Tue Oct 20 2009 Mads Kiilerich <mads@kiilerich.com> - 0.9-0.1.hgdc0d0231f39a
- Address review comments from Mamoru Tasaka
- Rebase to new non-forking upstream version from unreleased stable branch

* Fri Oct 16 2009 Mads Kiilerich <mads@kiilerich.com> 0.9-0.0.hg7d91c4a48d37
- Rebase to snapshot of upstream and adopt new package structure

* Fri Jul 24 2009 Mads Kiilerich <mads@kiilerich.com> 0.8.1-1
- New upstream release where minor fixes has been applied
- Remove workarounds no longer needed

* Mon Jul 20 2009 Mads Kiilerich <mads@kiilerich.com> 0.8-4.6da01818c9ea
- Rebase to snapshot of upstream with
  - Clarified that license is GPLv2
  - .mo files build with gettext
  - Local copy of python-iniparse replaced with dependency

* Mon Jul 6 2009 Mads Kiilerich <mads@kiilerich.com> 0.8-3
- Initial package of tortoisehg 0.8
