TortoiseHg Documentation

Pro vytvoření dokumentace ve formátu HTML je potřebná instalace sphinx. V Ubuntu je sphinx balíčkem Pythonu. Ve Windows je zřejmě nejlepší easy_install. Sphinx musí být novější než 0.6.

Pro vytvoření souborů PDF jsou potřebné balíčky latex. V Ubuntu to jsou 'texlive-latex-extra' a všechny jeho dependence. Ve Windows je nejlepší miktex. 

Jsou-li všechny potřebné rekvizity k disposici, lze použít makefile pro vytvoření cílů: html htmlhelp latex.

Máme-li latex vybudován, nacédujeme se do jeho výstupního adresáře a spuštěním make all-pdf vytvoříme vlastní soubor PDF.

Máme-li vybudován htmlhelp, musíme ve Windows použít jejich  vlastní help compiler. 

Pokud ve Window nemáme žádný nástroj 'make', můžeme použít build.bat. Je-li nainstalován HTML compiler a miktex, můžeme formáty chm (build chm) a pdf (build pdf) generovat přímo.


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

- To indicate a menu choise use :menuselection: and -->, for example:

  :menuselection:`TortoiseHg... --> About`
  
- To indicate a file use :file:, for example:

  :file:`.hg/hgrc`
 
- To indicate a command to enter into command window use :command:, for example:

  :command:`hgtk log`

- To indicate a text to enter into a text input field in the GUI use ``, for example:

  ``myproxy:8000``

