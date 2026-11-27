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
echo  Carregando a demonstracao com 2 empresas ficticias...
%PY% exemplos\demo.py
echo.
if exist "data\SENHA_INICIAL_ADMIN.txt" (
  echo  Usuario e senha para o primeiro acesso:
  type "data\SENHA_INICIAL_ADMIN.txt"
)
echo.
echo  Pronto. Agora clique duas vezes em INICIAR.bat
echo.
pause
