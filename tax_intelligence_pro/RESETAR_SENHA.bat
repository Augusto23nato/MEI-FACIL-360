@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY ( py --version >nul 2>&1 && set PY=py )
if not defined PY ( echo Python nao encontrado. & pause & exit /b 1 )
if not exist "tip\db.py" (
  echo.
  echo  Coloque este arquivo DENTRO da pasta TaxIntelligencePro ^(junto do INICIAR^) e tente de novo.
  echo.
  pause
  exit /b 1
)
echo.
echo  Gerando uma nova senha para o usuario admin...
%PY% -c "import secrets,sys;sys.path.insert(0,'.');from tip import db,seguranca as s;c=db.conectar();l=sys.argv[1] if len(sys.argv)>1 else 'admin';p=secrets.token_urlsafe(9);n=c.execute('UPDATE usuarios SET senha_hash=?,ativo=1 WHERE login=?',(s.hash_senha(p),l)).rowcount;c.execute('DELETE FROM sessoes');c.commit();s.registrar(c,'acesso-local','usuario.senha_redefinida','usuario:'+l,{}) if n else None;(db.DATA_DIR/'SENHA_INICIAL_ADMIN.txt').write_text('login: '+l+chr(10)+'senha: '+p+chr(10),encoding='utf-8') if n else None;print(chr(10)+'  Usuario: '+l+chr(10)+'  Nova senha: '+p+chr(10)) if n else print('  Usuario nao encontrado: '+l)" %*
echo  Anote a senha acima. Feche e abra de novo o INICIAR antes de entrar.
echo.
pause
