@echo off
setlocal

if not exist %hhc_compiler%. (
	set hhc_compiler=hhc.exe
)
if not exist %qcollectiongenerator%. (
	set qcollectiongenerator=qcollectiongenerator.exe
)
set PDFLATEX=PdfLatex
set SPHINXBUILD=sphinx-build
set OUTPUTDIRSUFFIX=
if not "%2" == "" (
	set OUTPUTDIRSUFFIX=-%2
)
if "%2" == "en" (
	set OUTPUTDIRSUFFIX=
)
set OUTPUTDIR=build%OUTPUTDIRSUFFIX%
set ALLSPHINXOPTS=-d %OUTPUTDIR%/doctrees %SPHINXOPTS% source%OUTPUTDIRSUFFIX%
if not "%PAPER%" == "" (
	set ALLSPHINXOPTS=-D latex_paper_size=%PAPER% %ALLSPHINXOPTS%
)

if "%1" == "" goto help

if "%1" == "help" (
	:help
	echo.Please use `Build.bat ^<target^> [^<lang^>]` where ^<target^> is one of
	echo.  html      to make standalone HTML files
	echo.  htmlhelp  to make HTML files and a HTML help project
	echo.  chm       to make CHM file
	echo.  qthelp    to make HTML files and a qthelp project
	echo.  qhc       to make QHC file
	echo.  latex     to make LaTeX files, you can set PAPER=a4 or PAPER=letter
	echo.  pdf       to make PDF file, you can set PAPER=a4 or PAPER=letter
	echo.
	echo.and where ^<lang^> is one of
	echo.  en  to make target in English ^(default^)
	echo.  ja  to make target in Japanese
	echo.  cs  to make target in Czech
	goto end
)

if "%1" == "clean" (
	for /d %%i in (%OUTPUTDIR%\*) do rmdir /q /s %%i
	del /q /s %OUTPUTDIR%\*
	goto end
)

if "%1" == "html" (
	%SPHINXBUILD% -b html %ALLSPHINXOPTS% %OUTPUTDIR%/html
	echo.
	echo.Build finished. The HTML pages are in %OUTPUTDIR%/html.
	goto end
)

if "%1" == "htmlhelp" (
	%SPHINXBUILD% -b htmlhelp %ALLSPHINXOPTS% %OUTPUTDIR%/htmlhelp
	echo.
	echo.Build finished; now you can run HTML Help Workshop with the ^
.hhp project file in %OUTPUTDIR%/htmlhelp.
	goto end
)

if "%1" == "chm" (
	%SPHINXBUILD% -b htmlhelp %ALLSPHINXOPTS% %OUTPUTDIR%/chm
	%hhc_compiler% %OUTPUTDIR%/chm/TortoiseHg.hhp
	echo.
	echo.Build finished. The CHM file is in %OUTPUTDIR%/chm.
	goto end
)

if "%1" == "qthelp" (
	%SPHINXBUILD% -b qthelp %ALLSPHINXOPTS% %OUTPUTDIR%/qthelp
	echo.
	echo.Build finished; now you can run "qcollectiongenerator" with the ^
.qhcp project file in %OUTPUTDIR%/qthelp, like this:
	echo.^> qcollectiongenerator %OUTPUTDIR%\qthelp\foo.qhcp
	echo.To view the help file:
	echo.^> assistant -collectionFile %OUTPUTDIR%\qthelp\foo.ghc
	goto end
)

if "%1" == "qhc" (
	%SPHINXBUILD% -b qthelp %ALLSPHINXOPTS% %OUTPUTDIR%/qthelp
	%qcollectiongenerator% %OUTPUTDIR%/qthelp/TortoiseHg.qhcp
	echo.
	echo.Build finished. The QHC file is in %OUTPUTDIR%/qthelp.
	goto end
)

if "%1" == "latex" (
	%SPHINXBUILD% -b latex %ALLSPHINXOPTS% %OUTPUTDIR%/latex
	echo.
	echo.Build finished; the LaTeX files are in %OUTPUTDIR%/latex.
	goto end
)

if "%1" == "pdf" (
	%SPHINXBUILD% -b latex %ALLSPHINXOPTS% %OUTPUTDIR%/pdf
	pushd .
	cd %OUTPUTDIR%\pdf
	%PDFLATEX% TortoiseHg.tex
	%PDFLATEX% TortoiseHg.tex
	%PDFLATEX% TortoiseHg.tex
	makeindex -s python.ist TortoiseHg.idx
	makeindex -s python.ist modTortoiseHg.idx
	%PDFLATEX% TortoiseHg.tex
	%PDFLATEX% TortoiseHg.tex
	popd
	echo.
	echo.Build finished; the PDF file is in %OUTPUTDIR%/pdf.
	goto end
)

:end



