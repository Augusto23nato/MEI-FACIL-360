@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY ( py --version >nul 2>&1 && set PY=py )
if not defined PY (
  echo.
  echo  Python nao encontrado.
  echo  Instale em https://www.python.org/downloads/ marcando a opcao "Add Python to PATH"
  echo  e depois clique de novo neste arquivo.
  echo.
  pause
  exit /b 1
)
%PY% -c "import openpyxl" >nul 2>&1 || (
  echo Instalando o leitor de planilhas Excel ^(so na primeira vez^)...
  %PY% -m pip install --quiet openpyxl
)
echo.
echo  ==============================================
echo   TAX INTELLIGENCE PRO
echo   O navegador vai abrir em http://127.0.0.1:8360
echo   NAO FECHE esta janela enquanto usar o sistema.
echo  ==============================================
echo.
if exist "data\SENHA_INICIAL_ADMIN.txt" (
  echo  Primeiro acesso:
  type "data\SENHA_INICIAL_ADMIN.txt"
  echo.
)
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8360"
%PY% -m tip.servidor
if errorlevel 1 (
  echo.
  echo  O servidor parou com erro. Copie a mensagem acima e envie para o suporte.
)
pause
