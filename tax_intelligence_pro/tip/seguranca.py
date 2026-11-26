"""Usuários, permissões, sessões, trilha de auditoria encadeada e LGPD."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from .db import agora, js

PAPEIS = {
    "admin": {"ver", "simular", "importar", "analisar", "validar", "regras_editar", "usuarios", "backup",
              "auditoria_ver", "empresas_editar", "lgpd"},
    "auditor": {"ver", "simular", "importar", "analisar", "validar", "empresas_editar"},
    "analista": {"ver", "simular", "importar", "analisar"},
    "leitura": {"ver"},
}
SESSAO_HORAS = 8
_ITER = 310_000


class AcessoNegado(PermissionError):
    pass


def hash_senha(senha: str) -> str:
    if len(senha) < 10:
        raise ValueError("a senha deve ter pelo menos 10 caracteres")
    sal = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, _ITER)
    return f"pbkdf2_sha256${_ITER}${sal.hex()}${h.hex()}"


def conferir_senha(senha: str, armazenado: str) -> bool:
    try:
        _, it, sal, h = armazenado.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(sal), int(it))
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, TypeError):
        return False


def criar_usuario(con, login: str, nome: str, senha: str, papel: str, por: str = "sistema") -> int:
    if papel not in PAPEIS:
        raise ValueError(f"papel inválido: {papel}")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,40}", login):
        raise ValueError("login inválido (3–40 caracteres: letras, números, . _ -)")
    cur = con.execute("INSERT INTO usuarios (login, nome, senha_hash, papel, criado_em) VALUES (?,?,?,?,?)",
                      (login, nome, hash_senha(senha), papel, agora()))
    con.commit()
    registrar(con, por, "usuario.criar", f"usuario:{cur.lastrowid}", {"login": login, "papel": papel})
    return cur.lastrowid


def garantir_admin(con) -> str | None:
    """Cria o administrador inicial na primeira execução; devolve a senha gerada."""
    if con.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone():
        return None
    senha = secrets.token_urlsafe(12)
    criar_usuario(con, "admin", "Administrador", senha, "admin")
    return senha


def login(con, usuario: str, senha: str, ip: str = "") -> dict:
    u = con.execute("SELECT * FROM usuarios WHERE login=? AND ativo=1", (usuario,)).fetchone()
    if not u or not conferir_senha(senha, u["senha_hash"]):
        registrar(con, usuario, "login.falha", None, {}, ip)
        raise AcessoNegado("usuário ou senha inválidos")
    token = secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + timedelta(hours=SESSAO_HORAS)).replace(microsecond=0).isoformat()
    con.execute("INSERT INTO sessoes VALUES (?,?,?,?,?)", (_th(token), u["id"], agora(), exp, ip))
    con.execute("UPDATE usuarios SET ultimo_login=? WHERE id=?", (agora(), u["id"]))
    con.commit()
    registrar(con, usuario, "login", f"usuario:{u['id']}", {}, ip)
    return {"token": token, "expira_em": exp, "usuario": publico(u)}


def logout(con, token: str):
    con.execute("DELETE FROM sessoes WHERE token_hash=?", (_th(token),))
    con.commit()


def sessao(con, token: str | None) -> dict | None:
    if not token:
        return None
    r = con.execute("SELECT u.*, s.expira_em FROM sessoes s JOIN usuarios u ON u.id=s.usuario_id "
                    "WHERE s.token_hash=? AND u.ativo=1", (_th(token),)).fetchone()
    if not r or r["expira_em"] < agora():
        return None
    return publico(r)


def publico(u) -> dict:
    return {"id": u["id"], "login": u["login"], "nome": u["nome"], "papel": u["papel"],
            "permissoes": sorted(PAPEIS.get(u["papel"], set()))}


def exigir(usuario: dict | None, permissao: str):
    if not usuario:
        raise AcessoNegado("autenticação necessária")
    if permissao not in PAPEIS.get(usuario["papel"], set()):
        raise AcessoNegado(f"o papel '{usuario['papel']}' não tem a permissão '{permissao}'")


def trocar_senha(con, usuario_id: int, atual: str, nova: str):
    u = con.execute("SELECT * FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
    if not u or not conferir_senha(atual, u["senha_hash"]):
        raise AcessoNegado("senha atual incorreta")
    con.execute("UPDATE usuarios SET senha_hash=? WHERE id=?", (hash_senha(nova), usuario_id))
    con.execute("DELETE FROM sessoes WHERE usuario_id=?", (usuario_id,))
    con.commit()
    registrar(con, u["login"], "usuario.senha", f"usuario:{usuario_id}", {})


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- auditoria
def registrar(con, usuario, acao: str, objeto, detalhe: dict, ip: str = "") -> str:
    """Grava um evento na trilha. Cada registro carrega o hash do anterior, de modo que
    qualquer alteração/remoção posterior quebra a cadeia e é detectada por ``verificar_trilha``."""
    ant = con.execute("SELECT hash FROM auditoria ORDER BY id DESC LIMIT 1").fetchone()
    h_ant = ant["hash"] if ant else "0" * 64
    quando = agora()
    det = js(mascarar(detalhe))
    h = hashlib.sha256(f"{h_ant}|{usuario}|{acao}|{objeto}|{det}|{ip}|{quando}".encode()).hexdigest()
    con.execute("INSERT INTO auditoria (usuario, acao, objeto, detalhe, ip, criado_em, hash_anterior, hash) "
                "VALUES (?,?,?,?,?,?,?,?)", (str(usuario), acao, objeto, det, ip, quando, h_ant, h))
    con.commit()
    return h


def verificar_trilha(con) -> dict:
    h_ant = "0" * 64
    n = 0
    for r in con.execute("SELECT * FROM auditoria ORDER BY id"):
        esperado = hashlib.sha256(f"{h_ant}|{r['usuario']}|{r['acao']}|{r['objeto']}|{r['detalhe']}|"
                                  f"{r['ip']}|{r['criado_em']}".encode()).hexdigest()
        if r["hash_anterior"] != h_ant or r["hash"] != esperado:
            return {"integra": False, "registros": n, "quebra_no_id": r["id"]}
        h_ant = r["hash"]
        n += 1
    return {"integra": True, "registros": n}


# ---------------------------------------------------------------- LGPD
_CPF = re.compile(r"\b(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})\b")


def mascarar_cpf(texto: str) -> str:
    return _CPF.sub(lambda m: f"***.{m.group(2)}.{m.group(3)[:1]}**-**", texto)


def mascarar(obj):
    """Mascara CPFs (dado pessoal) em estruturas destinadas a logs e relatórios.
    CNPJ é dado de pessoa jurídica e permanece visível para viabilizar a auditoria."""
    if isinstance(obj, str):
        return mascarar_cpf(obj) if len(re.sub(r"\D", "", obj)) == 11 or "cpf" in obj.lower() else obj
    if isinstance(obj, dict):
        return {k: (mascarar_cpf(str(v)) if "cpf" in k.lower() and v else mascarar(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mascarar(v) for v in obj]
    return obj


def anonimizar_empresa(con, empresa_id: int, por: str) -> dict:
    """Direito de anonimização (LGPD art. 18, IV): remove nomes e CPFs de participantes
    pessoas físicas preservando valores e chaves fiscais necessários à guarda legal."""
    n = 0
    for d in con.execute("SELECT id, cnpj_emit, cnpj_dest FROM documentos WHERE empresa_id=?", (empresa_id,)).fetchall():
        upd = {}
        for campo in ("cnpj_emit", "cnpj_dest"):
            v = d[campo] or ""
            if len(v) == 11:
                upd[campo] = "CPF-" + hashlib.sha256(v.encode()).hexdigest()[:10]
        sets = "".join(f", {k}=?" for k in upd)
        con.execute(f"UPDATE documentos SET nome_part='[anonimizado]'{sets} WHERE id=?", (*upd.values(), d["id"]))
        n += 1
    con.commit()
    registrar(con, por, "lgpd.anonimizar", f"empresa:{empresa_id}", {"documentos": n})
    return {"documentos_anonimizados": n}


def dumps_seguro(obj) -> str:
    return json.dumps(mascarar(obj), ensure_ascii=False, default=str)
