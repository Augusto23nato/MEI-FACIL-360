"""Redefine a senha de um usuário diretamente no banco local (recuperação de acesso).

    python -m tip.redefinir_senha            # usuário admin
    python -m tip.redefinir_senha fulano

Só quem tem acesso à pasta do sistema consegue rodar. Reativa o usuário, encerra as sessões abertas,
grava a nova senha em data/SENHA_INICIAL_ADMIN.txt e registra o evento na trilha de auditoria.
"""
import secrets
import sys

from . import db, seguranca


def redefinir(con, login: str = "admin") -> str | None:
    senha = secrets.token_urlsafe(9)
    n = con.execute("UPDATE usuarios SET senha_hash=?, ativo=1 WHERE login=?", (seguranca.hash_senha(senha), login)).rowcount
    if not n:
        return None
    con.execute("DELETE FROM sessoes WHERE usuario_id=(SELECT id FROM usuarios WHERE login=?)", (login,))
    con.commit()
    seguranca.registrar(con, "acesso-local", "usuario.senha_redefinida", f"usuario:{login}", {})
    return senha


def main():
    login = sys.argv[1] if len(sys.argv) > 1 else "admin"
    con = db.conectar()
    senha = redefinir(con, login)
    if senha is None:
        usuarios = [r["login"] for r in con.execute("SELECT login FROM usuarios ORDER BY login")]
        print(f"Usuário '{login}' não encontrado. Usuários existentes: {', '.join(usuarios) or 'nenhum'}")
        sys.exit(1)
    (db.DATA_DIR / "SENHA_INICIAL_ADMIN.txt").write_text(
        f"login: {login}\nsenha: {senha}\nTroque após entrar e apague este arquivo.\n", encoding="utf-8")
    print(f"Usuário: {login}\nNova senha: {senha}")


if __name__ == "__main__":
    main()
