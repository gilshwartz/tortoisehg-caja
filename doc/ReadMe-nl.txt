TortoiseHg Documentatie

Om deze documentatie aan te maken moet Sphinx geïnstalleerd zijn.  Voor Ubuntu
is dit het python-sphinx pakket.  Voor Windows maakt u de beste kans met
easy_install of pip.  Om een build te doen zonder waarschuwingen heeft u
Sphinx 0.6 of later nodig.

Om PDF bestanden te maken heeft u LaTeX pakketten nodig.  Voor Ubuntu zijn dat
texlive-latex-extra, texlive-fonts-recommended en al hun afhankelijkheden.  Voor
Windows is de beste keuze MiKTeX.

Eens alle voorwaarden voldaan zijn kunt u de makefile gebruiken om doelen te
maken: 'make html htmlhelp latex'.

Eens 'latex' aangemaakt is gaat u met cd naar de resultaatmap om 'make all-pdf'
te laten lopen om de eigenlijke PDF bestanden te maken.

Eens 'htmlhelp' gemaakt is kunt u de eigenlijke HTML Help Compiler laten lopen
op een Windows machine.

Als u geen make programma hebt voor Windows kunt u build.bat gebruiken.  Als
de HTML Help Compiler en MiKTeX geïnstalleerd zijn kunt u het CHM bestand
('build chm') en het PDF bestand ('build pdf') rechtstreeks genereren.

Hacking in de broncode
======================

Volg aub onderstaande regels als u de bronbestanden van de documentatie gaat
aanpassen.

- Zoals voorgesteld door Sphinx (zie http://sphinx.pocoo.org/rest.html#sections) gebruik:

  ***************
  Hoofdstuk titel
  ***************

  Sectie titel
  ============

  Subsectie titel
  ---------------

  Subsubsectie titel
  ^^^^^^^^^^^^^^^^^^

- Om een toets of toetscombinatie aan te geven gebruik :kbd:, bijvoorbeeld:

  :kbd:`Ctrl-A`

- Om een veldnaam of knop aan te geven, of eender wat in de
gebruikersinterfaces verschijnt, gebruik :guilabel:, bijvoorbeeld:

  :guilabel:`Commit`

- Om een menukeuze aan te geven gebruik :menuselection: en -->, bijvoorbeeld:

  :menuselection:`Bestand --> Instellingen...`

- Om een bestand aan te geven gebruik :file:, bijvoorbeeld:

  :file:`.hg/hgrc`

- Om een opdracht aan te geven om in het opdrachtvenster in te voeren gebruik
:command:, bijvoorbeeld:

  :command:`thg log`

- Om een tekst aan te geven om in te geven in een tekstveld in de GUI gebruik ``, bijvoorbeeld:

  ``myproxy:8000``
