TortoiseHg マニュアル

このマニュアルをビルドするには sphinx をインストールする必要があります。
Ubuntu では python-sphinx パッケージとして提供されており、Windows では
easy_install コマンドを使ってインストールするのが最も簡単です。
バージョン 0.6 以降の sphinx であれば問題なくビルドできます。

PDF 形式で出力するには LaTeX パッケージが必要になります。Ubuntu では
texlive-latex-extra パッケージとその全ての依存パッケージで、Windows では
MiKTeX がオススメです。

ビルドに必要なツールが揃ったら Makefile を使って以下のターゲットを指定して
ビルドできます: html htmlhelp latex

PDF 形式のビルドをするには、まず LaTeX 形式のビルドを完了させてから、
cd コマンドで出力ディレクトリに移動して "make all-pdf" を実行してください。

HTML ヘルプ形式のビルドが完了したら、さらにヘルプコンパイラを実行する必要が
あります。

Windows で GNU Make が使えない場合は Build.bat を使うこともできます。
HTML ヘルプコンパイラと MiKTeX がインストールされているのであれば、直接
CHM 形式と PDF 形式で出力することができます。

マニュアル記述ガイドライン
======================

マニュアルのソースファイルを変更する場合は以下のガイドラインに従ってください。

- このガイドラインは Sphinx 推奨のものです:
  http://sphinx.pocoo.org/rest.html#sections
  
  *********
  章タイトル
  *********

  節タイトル
  =========

  小節タイトル
  -----------

  小々節タイトル
  ^^^^^^^^^^^^^

- キーまたはキーの組み合わせを示す場合は :kbd: を使用してください。例えば

  :kbd:`Ctrl-A`

- ラベル、ボタンなどユーザインターフェイスに表示されるものは :guilabel: を
  使います。例えば

  :guilabel:`Commit`

- メニューの選択は :menuselection: と --> を利用してください。例えば

  :menuselection:`TortoiseHg... --> About`

- ファイルやディレクトリの場所は :file: を使います。例えば

  :file:`.hg/hgrc`

- :command: はコマンドプロンプトで入力を意味します。例えば

  :command:`hgtk log`

- GUI のテキストボックスへの入力は ``(バッククオーテーション2つ)を使います。
例えば

  ``myproxy:8000``

