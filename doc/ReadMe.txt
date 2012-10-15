TortoiseHg Documentation

To build this documentation you need Sphinx installed.  On Ubuntu this
is the python-sphinx package.   On Windows your best bet is easy_install
or pip.  To build without warnings, you need Sphinx 0.6 or later.

To build PDF files you need LaTeX packages.  On Ubuntu these are
texlive-latex-extra, texlive-fonts-recommended and all of their
dependencies.  On Windows the best choice is MiKTeX.

Once all of the prerequisites are in place, you can use the makefile to
build targets: 'make html htmlhelp latex'.

Once 'latex' is built, you have to cd into that output directory and run
'make all-pdf' to build the actual PDF file.

Once 'htmlhelp' is built, you have to run the actual HTML Help Compiler on a
Windows machine.

On Windows, if you have no make tool you can use build.bat. If the HTML Help 
Compiler and MiKTeX are installed you can directly generate the CHM file 
('build chm') and PDF file ('build pdf').

Hacking the source
==================

Please follow this rules when hacking the doc source files.

- As suggested by Sphinx (see http://sphinx.pocoo.org/rest.html#sections)
  use:

  *************
  Chapter title
  *************

  Section title
  =============

  Subsection title
  ----------------

  Subsubsection title
  ^^^^^^^^^^^^^^^^^^^

- To indicate a key or a combination of keys use :kbd:, for example:

  :kbd:`Ctrl-A`

- To indicate a label, button or anything that appears in user interfaces
  use :guilabel:, for example:

  :guilabel:`Commit`

- To indicate a menu choice use :menuselection: and -->, for example:

  :menuselection:`File --> Settings...`

- To indicate a file use :file:, for example:

  :file:`.hg/hgrc`

- To indicate a command to enter into command window use :command:, for example:

  :command:`thg log`

- To indicate a text to enter into a text input field in the GUI use ``, for example:

  ``myproxy:8000``

