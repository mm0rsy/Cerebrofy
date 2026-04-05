@echo off
REM Build a self-contained cerebrofy.exe using Nuitka.
REM Requires: pip install nuitka "cerebrofy[mcp]"

echo Building cerebrofy.exe with Nuitka...

nuitka ^
  --standalone ^
  --onefile ^
  --output-filename=cerebrofy.exe ^
  --include-package=tree_sitter_languages ^
  --include-data-dir=src\cerebrofy\queries=cerebrofy\queries ^
  --windows-console-mode=attach ^
  --windows-company-name=Cerebrofy ^
  --windows-product-name=Cerebrofy ^
  src\cerebrofy\__main__.py

if %ERRORLEVEL% NEQ 0 (
  echo Error: Nuitka build failed.
  exit /b 1
)

echo Build complete: cerebrofy.exe
