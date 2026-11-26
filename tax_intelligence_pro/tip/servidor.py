"""API HTTP + dashboard (biblioteca padrão, como o restante do projeto).

    python -m tip.servidor            # http://127.0.0.1:8360
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import analise, db, relatorios, seguranca, servico
from .importers import importar
from .importers.base import TAM_MAX, ArquivoInvalido
from .importers import tabular
from .regras import MotorRegras, RegraInexistente
from .seguranca import AcessoNegado, exigir, registrar

WEB = Path(__file__).resolve().parent.parent / "web"
_lock = threading.RLock()
_tentativas: dict = {}


class App:
    def __init__(self, caminho_db=None):
        self.caminho_db = caminho_db or (db.DATA_DIR / "tip.db")
        self.con = db.conectar(self.caminho_db)
        self.motor = MotorRegras(self.con)
        self.motor.semear()
        self.senha_inicial = seguranca.garantir_admin(self.con)

    def reabrir(self):
        self.con.close()
        self.con = db.conectar(self.caminho_db)
        self.motor = MotorRegras(self.con)


ROTAS = []


def rota(metodo, padrao, perm="ver"):
    def deco(fn):
        ROTAS.append((metodo, re.compile("^" + padrao + "$"), perm, fn))
        return fn
    return deco


class Resposta(Exception):
    def __init__(self, corpo, tipo="application/json; charset=utf-8", codigo=200, nome=None):
        self.corpo, self.tipo, self.codigo, self.nome = corpo, tipo, codigo, nome


# ------------------------------------------------------------------ rotas
@rota("POST", r"/api/login", perm=None)
def r_login(app, req, u, m):
    b = req.json()
    ip = req.client_address[0]
    janela = [t for t in _tentativas.get(ip, []) if t > time.time() - 300]
    if len(janela) >= 10:
        raise AcessoNegado("muitas tentativas: aguarde 5 minutos")
    try:
        return seguranca.login(app.con, b.get("login", ""), b.get("senha", ""), ip)
    except AcessoNegado:
        _tentativas[ip] = janela + [time.time()]
        raise


@rota("POST", r"/api/logout")
def r_logout(app, req, u, m):
    seguranca.logout(app.con, req.token())
    return {"ok": True}


@rota("GET", r"/api/me")
def r_me(app, req, u, m):
    return u


@rota("POST", r"/api/me/senha")
def r_senha(app, req, u, m):
    b = req.json()
    seguranca.trocar_senha(app.con, u["id"], b.get("atual", ""), b.get("nova", ""))
    return {"ok": True}


@rota("GET", r"/api/empresas")
def r_empresas(app, req, u, m):
    return [dict(r) for r in app.con.execute("SELECT * FROM empresas ORDER BY razao_social")]


@rota("POST", r"/api/empresas", perm="empresas_editar")
def r_empresa_nova(app, req, u, m):
    return servico.criar_empresa(app.con, req.json(), u)


@rota("PUT", r"/api/empresas/(\d+)", perm="empresas_editar")
def r_empresa_upd(app, req, u, m):
    return servico.atualizar_empresa(app.con, int(m[1]), req.json(), u)


@rota("GET", r"/api/empresas/(\d+)/contas")
def r_contas(app, req, u, m):
    eid = int(m[1])
    contas = [dict(r) for r in app.con.execute(
        "SELECT conta, MAX(descricao) descricao FROM saldos_contabeis WHERE empresa_id=? GROUP BY conta ORDER BY conta", (eid,))]
    mapa = {r["conta"]: r["grupo"] for r in app.con.execute("SELECT * FROM mapa_contas WHERE empresa_id=?", (eid,))}
    for c in contas:
        c["grupo"] = mapa.get(c["conta"])
    return contas


@rota("PUT", r"/api/empresas/(\d+)/contas", perm="empresas_editar")
def r_contas_put(app, req, u, m):
    servico.mapear_contas(app.con, int(m[1]), req.json(), u)
    return {"ok": True}


@rota("DELETE", r"/api/empresas/(\d+)/dados", perm="lgpd")
def r_eliminar(app, req, u, m):
    eid = int(m[1])
    app.con.execute("DELETE FROM importacoes WHERE empresa_id=?", (eid,))
    app.con.execute("DELETE FROM analises WHERE empresa_id=?", (eid,))
    app.con.commit()
    registrar(app.con, u["login"], "lgpd.eliminar_dados", f"empresa:{eid}", {})
    return {"ok": True}


@rota("POST", r"/api/empresas/(\d+)/anonimizar", perm="lgpd")
def r_anon(app, req, u, m):
    return seguranca.anonimizar_empresa(app.con, int(m[1]), u["login"])


@rota("POST", r"/api/simular/(simples|presumido|real|comparativo|reforma)", perm="simular")
def r_simular(app, req, u, m):
    b = req.json()
    return servico.simular(app.con, app.motor, m[1], b.get("dados") or {}, u, b.get("empresa_id"), b.get("titulo"),
                           salvar=b.get("salvar", True))


@rota("GET", r"/api/simples/curva")
def r_curva(app, req, u, m):
    from .calc import simples
    q = req.query()
    return simples.curva(app.motor, q.get("anexo", "I"), q.get("data", time.strftime("%Y-%m-%d")))


@rota("GET", r"/api/simulacoes")
def r_sims(app, req, u, m):
    q = req.query()
    sql, args = "SELECT id, empresa_id, tipo, titulo, criado_em, hash FROM simulacoes", []
    if q.get("empresa"):
        sql += " WHERE empresa_id=?"
        args.append(int(q["empresa"]))
    return [dict(r) for r in app.con.execute(sql + " ORDER BY id DESC LIMIT 200", args)]


@rota("GET", r"/api/simulacoes/(\d+)")
def r_sim(app, req, u, m):
    s = db.row(app.con.execute("SELECT * FROM simulacoes WHERE id=?", (int(m[1]),)).fetchone())
    if not s:
        raise LookupError("simulação inexistente")
    return s


@rota("GET", r"/api/simulacoes/(\d+)/memoria\.html")
def r_sim_html(app, req, u, m):
    s = r_sim(app, req, u, m)
    raise Resposta(relatorios.html_simulacao(s).encode(), "text/html; charset=utf-8")


@rota("POST", r"/api/importar", perm="importar")
def r_importar(app, req, u, m):
    q = req.query()
    nome = unquote(req.headers.get("X-Filename", "") or q.get("nome", ""))
    if not nome:
        raise ValueError("informe o nome do arquivo (cabeçalho X-Filename)")
    dados = req.corpo(TAM_MAX)
    return importar(app.con, int(q["empresa"]), nome, dados, u, q.get("tipo", "auto"),
                    {"perfil": q.get("perfil"), "tipo_planilha": q.get("tipo_planilha"), "forcar": q.get("forcar") == "1"})


@rota("GET", r"/api/importacoes")
def r_imps(app, req, u, m):
    q = req.query()
    return [db.row(r) for r in app.con.execute("SELECT * FROM importacoes WHERE empresa_id=? ORDER BY id DESC LIMIT 300",
                                               (int(q.get("empresa", 0)),))]


@rota("DELETE", r"/api/importacoes/(\d+)", perm="importar")
def r_imp_del(app, req, u, m):
    app.con.execute("DELETE FROM importacoes WHERE id=?", (int(m[1]),))
    app.con.commit()
    registrar(app.con, u["login"], "importacao.excluir", f"importacao:{m[1]}", {})
    return {"ok": True}


@rota("GET", r"/api/perfis")
def r_perfis(app, req, u, m):
    p = tabular.perfis()
    return {"perfis": [k for k in p if not k.startswith("_")], "tipos": list(tabular.TIPOS), "nota": p.get("_nota")}


@rota("POST", r"/api/analisar", perm="analisar")
def r_analisar(app, req, u, m):
    b = req.json()
    return analise.executar(app.con, app.motor, int(b["empresa_id"]), b["periodo_ini"], b["periodo_fim"], u)


@rota("GET", r"/api/analises")
def r_analises(app, req, u, m):
    q = req.query()
    return [db.row(r) for r in app.con.execute("SELECT id, empresa_id, periodo_ini, periodo_fim, regime, criado_em, hash, resumo FROM analises"
                                               " WHERE empresa_id=? ORDER BY id DESC LIMIT 100", (int(q.get("empresa", 0)),))]


@rota("GET", r"/api/analises/(\d+)")
def r_analise(app, req, u, m):
    return analise.obter(app.con, int(m[1]), req.query().get("cor"))


@rota("GET", r"/api/analises/(\d+)/relatorio\.html")
def r_rel_html(app, req, u, m):
    a = analise.obter(app.con, int(m[1]), req.query().get("cor"))
    registrar(app.con, u["login"], "relatorio.html", f"analise:{m[1]}", {})
    raise Resposta(relatorios.html_analise(a, u).encode(), "text/html; charset=utf-8")


@rota("GET", r"/api/analises/(\d+)/achados\.csv")
def r_rel_csv(app, req, u, m):
    a = analise.obter(app.con, int(m[1]))
    raise Resposta(relatorios.csv_analise(a).encode(), "text/csv; charset=utf-8", nome=f"achados-analise-{m[1]}.csv")


@rota("POST", r"/api/achados/(\d+)/validar", perm="validar")
def r_validar(app, req, u, m):
    b = req.json()
    return analise.validar(app.con, int(m[1]), b.get("status"), b.get("justificativa"), b.get("documentos"), u)


@rota("GET", r"/api/dashboard")
def r_dash(app, req, u, m):
    q = req.query()
    return servico.dashboard(app.con, int(q["empresa"]) if q.get("empresa") else None)


@rota("GET", r"/api/regras")
def r_regras(app, req, u, m):
    q = req.query()
    return app.motor.listar(q.get("tributo"), q.get("regime"), q.get("data"))


@rota("GET", r"/api/regras/historico/(.+)")
def r_hist(app, req, u, m):
    return app.motor.historico(unquote(m[1]))


@rota("POST", r"/api/regras", perm="regras_editar")
def r_regra_nova(app, req, u, m):
    b = req.json()
    return {"id": app.motor.criar(b["regra"], u["login"], b.get("motivo"))}


@rota("PUT", r"/api/regras/(\d+)", perm="regras_editar")
def r_regra_upd(app, req, u, m):
    b = req.json()
    return {"id": app.motor.atualizar(int(m[1]), b.get("mudancas") or {}, u["login"], b.get("motivo", ""))}


@rota("GET", r"/api/usuarios", perm="usuarios")
def r_users(app, req, u, m):
    return [{k: r[k] for k in ("id", "login", "nome", "papel", "ativo", "criado_em", "ultimo_login")}
            for r in app.con.execute("SELECT * FROM usuarios ORDER BY login")]


@rota("POST", r"/api/usuarios", perm="usuarios")
def r_user_novo(app, req, u, m):
    b = req.json()
    return {"id": seguranca.criar_usuario(app.con, b["login"], b["nome"], b["senha"], b["papel"], u["login"])}


@rota("PUT", r"/api/usuarios/(\d+)", perm="usuarios")
def r_user_upd(app, req, u, m):
    b = req.json()
    if "papel" in b and b["papel"] not in seguranca.PAPEIS:
        raise ValueError("papel inválido")
    for k in ("papel", "ativo"):
        if k in b:
            app.con.execute(f"UPDATE usuarios SET {k}=? WHERE id=?", (b[k], int(m[1])))
    if b.get("ativo") in (0, False):
        app.con.execute("DELETE FROM sessoes WHERE usuario_id=?", (int(m[1]),))
    app.con.commit()
    registrar(app.con, u["login"], "usuario.atualizar", f"usuario:{m[1]}", {k: b[k] for k in ("papel", "ativo") if k in b})
    return {"ok": True}


@rota("GET", r"/api/auditoria", perm="auditoria_ver")
def r_aud(app, req, u, m):
    return {"trilha": [db.row(r) for r in app.con.execute("SELECT * FROM auditoria ORDER BY id DESC LIMIT 500")],
            "verificacao": seguranca.verificar_trilha(app.con)}


@rota("POST", r"/api/backup", perm="backup")
def r_backup(app, req, u, m):
    return servico.backup(app.con, u)


@rota("GET", r"/api/backups", perm="backup")
def r_backups(app, req, u, m):
    return servico.listar_backups()


@rota("POST", r"/api/restaurar", perm="backup")
def r_restaurar(app, req, u, m):
    b = req.json()
    with _lock:
        app.con.close()
        try:
            res = servico.restaurar(Path(app.caminho_db), b["arquivo"])
        finally:
            app.reabrir()
    registrar(app.con, u["login"], "restaurar", b["arquivo"], res)
    return res


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TIP"
    app: App = None  # type: ignore[assignment]

    def log_message(self, fmt, *a):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % a))

    def query(self):
        return {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}

    def token(self):
        h = self.headers.get("Authorization", "")
        return h[7:] if h.startswith("Bearer ") else None

    def corpo(self, limite=2 * 1024 * 1024) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > limite:
            raise ArquivoInvalido("corpo da requisição grande demais")
        return self.rfile.read(n) if n else b""

    def json(self):
        b = self.corpo()
        try:
            return json.loads(b or b"{}")
        except ValueError as e:
            raise ValueError("JSON inválido") from e

    def _enviar(self, codigo, corpo: bytes, tipo, nome=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                                    "script-src 'self'; frame-ancestors 'none'")
        if nome:
            self.send_header("Content-Disposition", f'attachment; filename="{nome}"')
        self.end_headers()
        self.wfile.write(corpo)

    def _api(self, metodo):
        caminho = urlparse(self.path).path
        for met, padrao, perm, fn in ROTAS:
            m = padrao.match(caminho)
            if met == metodo and m:
                try:
                    with _lock:
                        u = seguranca.sessao(self.app.con, self.token()) if perm is not None else None
                        if perm is not None:
                            exigir(u, perm)
                        res = fn(self.app, self, u, m)
                    self._enviar(200, json.dumps(res, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")
                except Resposta as r:
                    self._enviar(r.codigo, r.corpo, r.tipo, r.nome)
                except AcessoNegado as e:
                    self._erro(401 if "autenticação" in str(e) or "inválidos" in str(e) else 403, str(e))
                except (ValueError, ArquivoInvalido, RegraInexistente, KeyError) as e:
                    self._erro(400, str(e) if not isinstance(e, KeyError) else f"campo obrigatório ausente: {e}")
                except LookupError as e:
                    self._erro(404, str(e))
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    self._erro(500, f"erro interno: {type(e).__name__}")
                return
        self._erro(404, "rota inexistente")

    def _erro(self, codigo, msg):
        self._enviar(codigo, json.dumps({"erro": msg}, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        p = urlparse(self.path).path
        if p.startswith("/api/"):
            return self._api("GET")
        alvo = (WEB / (p.lstrip("/") or "index.html")).resolve()
        if not str(alvo).startswith(str(WEB.resolve())) or not alvo.is_file():
            alvo = WEB / "index.html"
        tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo.endswith("javascript"):
            tipo += "; charset=utf-8"
        self._enviar(200, alvo.read_bytes(), tipo)

    def do_POST(self):
        self._api("POST")

    def do_PUT(self):
        self._api("PUT")

    def do_DELETE(self):
        self._api("DELETE")


def criar_servidor(host="127.0.0.1", porta=8360, caminho_db=None) -> tuple[ThreadingHTTPServer, App]:
    mimetypes.add_type("text/javascript", ".js")
    app = App(caminho_db)
    Handler.app = app
    srv = ThreadingHTTPServer((host, porta), Handler)
    return srv, app


def main():
    host = os.environ.get("TIP_HOST", "127.0.0.1")
    porta = int(os.environ.get("TIP_PORTA", "8360"))
    srv, app = criar_servidor(host, porta)
    if app.senha_inicial:
        arq = db.DATA_DIR / "SENHA_INICIAL_ADMIN.txt"
        arq.write_text(f"login: admin\nsenha: {app.senha_inicial}\nTroque após o primeiro acesso e apague este arquivo.\n")
        os.chmod(arq, 0o600)
        print(f"Administrador criado. Senha inicial gravada em {arq}")
    print(f"TAX INTELLIGENCE PRO em http://{host}:{porta}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
