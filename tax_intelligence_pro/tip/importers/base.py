"""Validação de arquivos importados e detecção de tipo."""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field

TAM_MAX = 200 * 1024 * 1024          # 200 MB por arquivo
ZIP_MAX_DESCOMPACTADO = 1024 * 1024 * 1024
ZIP_MAX_ARQUIVOS = 20000
EXTENSOES = {".xml", ".txt", ".csv", ".xlsx", ".zip", ".json"}


class ArquivoInvalido(ValueError):
    pass


@dataclass
class Lote:
    """Resultado normalizado de um importador (modelo canônico)."""
    tipo: str
    fonte: str
    documentos: list = field(default_factory=list)   # dicts com chaves das colunas de `documentos` + 'itens'
    apuracoes: list = field(default_factory=list)    # {tributo, periodo, campo, valor}
    saldos: list = field(default_factory=list)       # {periodo, conta, descricao, saldo_ini, debitos, creditos, saldo_fim}
    mensagens: list = field(default_factory=list)    # {nivel: info|aviso|erro, texto}
    cnpj: str | None = None
    periodo_ini: str | None = None
    periodo_fim: str | None = None

    def aviso(self, texto):
        self.mensagens.append({"nivel": "aviso", "texto": texto})

    def erro(self, texto):
        self.mensagens.append({"nivel": "erro", "texto": texto})

    def info(self, texto):
        self.mensagens.append({"nivel": "info", "texto": texto})


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def validar_basico(nome: str, dados: bytes):
    if not dados:
        raise ArquivoInvalido("arquivo vazio")
    if len(dados) > TAM_MAX:
        raise ArquivoInvalido(f"arquivo maior que {TAM_MAX // (1024 * 1024)} MB")
    ext = "." + nome.lower().rsplit(".", 1)[-1] if "." in nome else ""
    if ext not in EXTENSOES:
        raise ArquivoInvalido(f"extensão não aceita: {ext or '(nenhuma)'} — use {', '.join(sorted(EXTENSOES))}")
    if re.search(r"[\\/]|\.\.", nome):
        raise ArquivoInvalido("nome de arquivo inválido")


def texto(dados: bytes) -> str:
    """SPED é ISO-8859-1 (Latin-1) por especificação; XML/CSV costumam ser UTF-8."""
    if dados.startswith(b"\xef\xbb\xbf"):
        return dados[3:].decode("utf-8")
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode("latin-1")


def xml_seguro(dados: bytes):
    """Rejeita DTD/entidades (XXE, 'billion laughs') antes de analisar o XML."""
    import xml.etree.ElementTree as ET
    cabeca = dados[:4096].lower()
    if b"<!doctype" in cabeca or b"<!entity" in dados.lower():
        raise ArquivoInvalido("XML com DTD/entidades não é aceito por segurança")
    try:
        return ET.fromstring(dados)
    except ET.ParseError as e:
        raise ArquivoInvalido(f"XML malformado: {e}") from e


def abrir_zip(dados: bytes):
    """Itera (nome, bytes) dos arquivos de um ZIP com proteção contra zip-bomb e path traversal."""
    try:
        z = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile as e:
        raise ArquivoInvalido("ZIP inválido") from e
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > ZIP_MAX_ARQUIVOS:
        raise ArquivoInvalido("ZIP com arquivos demais")
    if sum(i.file_size for i in infos) > ZIP_MAX_DESCOMPACTADO:
        raise ArquivoInvalido("ZIP descompactado excede o limite")
    for i in infos:
        nome = i.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if nome.startswith(".") or "." not in nome:
            continue
        yield nome, z.read(i)


def detectar(nome: str, dados: bytes) -> str:
    n = nome.lower()
    if n.endswith(".zip"):
        return "zip"
    if n.endswith(".xlsx"):
        return "tabular"
    if n.endswith(".csv"):
        return "tabular"
    if n.endswith(".json"):
        return "json"
    cab = dados[:3000]
    if n.endswith(".xml") or cab.lstrip().startswith(b"<"):
        c = cab.lower()
        if b"<cteproc" in c or b"<cte " in c or b"<cte>" in c or b"infcte" in c:
            return "cte"
        if b"nfse" in c or b"compnfse" in c or b"<dps" in c or b"infdps" in c:
            return "nfse"
        if b"proceventonfe" in c or b"<evento" in c:
            return "evento_nfe"
        return "nfe"
    if dados.lstrip()[:6] in (b"|0000|",):
        primeira = texto(dados[:600]).splitlines()[0].split("|")
        if len(primeira) > 2 and primeira[2] == "LECD":
            return "ecd"
        if len(primeira) > 2 and primeira[2] == "LECF":
            return "ecf"
        if len(primeira) > 4 and re.fullmatch(r"\d{8}", primeira[4] or "") and not re.fullmatch(r"\d{8}", primeira[6] or "x"):
            return "efd_icms_ipi"
        return "efd_contribuicoes"
    raise ArquivoInvalido("tipo de arquivo não reconhecido")
