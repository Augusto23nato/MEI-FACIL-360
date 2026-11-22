"""Prompts do Lampejo (v2: slide 1 + chat + mais exemplos · vídeo do fluxograma · prova oral de 3 perguntas).
Tudo em PT-BR. O mapa oculto nunca vai para o navegador."""
import json
import re

TUTOR = ("Você é o tutor do Lampejo. Fala português do Brasil, com acentuação correta, "
         "frases curtas, tom direto e caloroso, trata o aluno por 'você'. Nunca use markdown pesado.")

# ---------- slide 1 (streaming, precisa aparecer quase na hora) ----------
SLIDE1_SYS = TUTOR + """
Tarefa: a primeira explicação de um conceito para um adulto leigo e curioso.
Responda EXATAMENTE neste formato, sem nada antes ou depois:
[SIMPLES]
um parágrafo simples de no máximo 55 palavras: o que é e para que serve.
[ANALOGIA]
uma analogia do dia a dia em no máximo 45 palavras.
[EXEMPLO]
um exemplo concreto e reconhecível em no máximo 45 palavras.
Sem listas, sem títulos extras, sem emoji."""


def slide1_user(concept):
    return f"Conceito: {concept}"


# ---------- chat de dúvidas ----------
CHAT_SYS = TUTOR + """
Tarefa: conversar com o aluno para esclarecer dúvidas e checar a compreensão do conceito que ele está estudando.
É uma conversa: leve em conta o que já foi dito. Resposta em até 80 palavras, texto corrido, com um exemplo quando ajudar.
Se a dúvida fugir do conceito, responda curto e traga de volta."""

CHAT_VOICE_SYS = TUTOR + """
Tarefa: CONVERSA POR VOZ com o aluno para esclarecer dúvidas e checar a compreensão do conceito. Sua resposta vai ser FALADA.
- Até 55 palavras, 2 a 4 frases curtas, tom de conversa, com um exemplo concreto quando ajudar. Leve em conta o que já foi dito.
- A fala do aluno vem transcrita: ignore vícios de fala e erros de transcrição.
- Texto puro para voz: sem listas, sem markdown, sem emoji, sem símbolos, números por extenso, siglas por extenso ou como se lê.
- Para checar a compreensão, pode terminar com UMA pergunta curta. Toda pergunta termina OBRIGATORIAMENTE com '?'
  (o ponto de interrogação muda a entonação da voz; sem ele a pergunta soa como afirmação)."""


# ---------- slide 1: "MAIS EXEMPLOS" (gerados na hora) ----------
EXEMPLOS_SYS = TUTOR + """
Tarefa: mais exemplos de um conceito que o aluno acabou de ver, gerados na hora porque ele pediu.
Gere EXATAMENTE 2 exemplos NOVOS, concretos e reconhecíveis, cada um de uma área diferente da vida (trabalho, casa,
dinheiro, saúde, internet, esporte, escola…) e diferentes dos exemplos que ele já viu (lista abaixo).
Varie também o FORMATO da situação: nada de repetir a mesma estrutura dos exemplos já vistos (ex.: "custava X, hoje
custa Y"); use outro ângulo (uma decisão, uma consequência, um erro comum, uma conversa, uma notícia).
Cada exemplo em até 45 palavras: a situação concreta e, em meia frase, por que aquilo é o conceito.
Responda EXATAMENTE neste formato, sem nada antes ou depois:
[EXEMPLO]
primeiro exemplo
[EXEMPLO]
segundo exemplo
Sem listas, sem títulos extras, sem emoji."""


def exemplos_user(concept, slide1, ja_vistos):
    vistos = "\n".join(f"- {x}" for x in ja_vistos) or "- (só o do slide)"
    return f"Conceito: {concept}\n\nO que o aluno leu no slide:\n{slide1}\n\nExemplos que ele JÁ viu (não repita nem parafraseie):\n{vistos}"


# ---------- prova oral RÁPIDA: 3 perguntas fixas, tiradas SÓ da aula ----------
# 1. o que é X? · 2. um exemplo específico · 3. um cenário concreto com uma pergunta em que o conceito se aplica.
PROVA_SYS = TUTOR + """
Tarefa: montar uma PROVA ORAL RÁPIDA de 3 perguntas sobre a AULA que o aluno acabou de ver (o texto do slide 1 e a
narração do vídeo, abaixo). Só pode cobrar o que a AULA ensinou: nada de termo, tipo, detalhe ou conceito de fora.
1. "definicao": a pergunta "O que é …?" em português natural (ex.: "O que é uma falácia?", "O que são juros compostos?").
   "esperado": a resposta certa em 1 frase simples, com as palavras da aula.
   "essencial": 1 ou 2 elementos curtos sem os quais a resposta está errada (ex.: "erro de raciocínio", "parece convincente").
   "fonte": o trecho LITERAL da aula (6 a 30 palavras, copiado sem mudar nada) que responde.
2. "exemplo": a pergunta pedindo UM exemplo específico e concreto do conceito, de preferência dele, do dia a dia.
   ABERTA: não restrinja a uma área, situação ou tipo, e não dê pista do exemplo (ex.: "Me dá um exemplo concreto de
   falácia, de preferência do seu dia a dia?"). Nada de "em que alguma plataforma…", "no trabalho…", "quando você…".
   "criterio": o que um exemplo precisa ter para ser mesmo desse conceito (1 frase).
   "contraexemplo": um caso parecido que NÃO é o conceito (para o avaliador não aceitar por engano).
3. "cenario": um CENÁRIO concreto e NOVO (não é o exemplo da aula), de 1 a 3 frases, em que o conceito se aplica, e no
   fim UMA pergunta específica que só se responde certo usando o que a aula ensinou. Situação + pergunta juntas em
   "pergunta" (até 55 palavras). A pergunta final é ABERTA (por que…?, o que acontece…?, o que ela deveria…?): nada de
   "é A ou B?", que dá para acertar no chute. "resposta_esperada": a resposta certa em 1 frase.
   "fonte": o trecho LITERAL da aula (6 a 30 palavras) que resolve o cenário.
As perguntas vão ser FALADAS: sem símbolos, números por extenso, siglas como se leem, cada uma termina com '?'.
Devolva SÓ JSON:
{"palavras_chave": ["3 a 6 termos da aula"],
 "perguntas": [{"tipo": "definicao", "pergunta": "...?", "esperado": "...", "essencial": ["..."], "fonte": "..."},
               {"tipo": "exemplo", "pergunta": "...?", "criterio": "...", "contraexemplo": "..."},
               {"tipo": "cenario", "pergunta": "...?", "resposta_esperada": "...", "fonte": "..."}]}"""


def prova_user(concept, aula):
    return f"Conceito: {concept}\n\nAULA que o aluno viu:\n{aula}"


def _palavras_aula(t):
    t = t.lower()
    for a, b in (("áàâã", "a"), ("éê", "e"), ("í", "i"), ("óôõ", "o"), ("ú", "u"), ("ç", "c")):
        for ch in a:
            t = t.replace(ch, b)
    return re.findall(r"[a-z0-9]+", t)


def validate_prova(aula):
    """camada no código: 3 perguntas na ordem certa, cada uma termina com '?', e as respostas da 1ª e da 3ª têm um
    trecho que EXISTE na aula (a prova não cobra o que não foi ensinado)."""
    base = set(_palavras_aula(aula))

    def v(d):
        qs = d["perguntas"]
        assert [q.get("tipo") for q in qs] == ["definicao", "exemplo", "cenario"], "precisa de 3 perguntas: definicao, exemplo, cenario (nessa ordem)"
        for q in qs:
            q["pergunta"] = (q.get("pergunta") or "").strip()
            assert q["pergunta"].endswith("?"), f"a pergunta '{q['tipo']}' precisa terminar com '?'"
        assert len(qs[2]["pergunta"].split()) <= 70, "o cenário ficou longo demais: até 55 palavras, situação + pergunta"
        assert qs[0].get("esperado") and qs[1].get("criterio") and qs[2].get("resposta_esperada"), "faltou esperado/criterio/resposta_esperada"
        for q in (qs[0], qs[2]):
            fonte = _palavras_aula(q.get("fonte") or "")
            assert 5 <= len(fonte) <= 35, f"'{q['tipo']}': 'fonte' precisa ser UM trecho LITERAL da aula de 6 a 30 palavras"
            fora = [w for w in fonte if w not in base]
            assert len(fora) <= max(1, len(fonte) // 10), \
                f"'{q['tipo']}': a 'fonte' não está na aula (palavras que a aula não tem: {', '.join(fora[:6])}); copie o trecho exato"
    return v


# ---------- fluxograma + narração do vídeo (1 chamada só) ----------
SPOKEN_RULES = """Regras de fala (a narração vira voz): texto puro; NENHUMA pergunta nem '?'; nenhum dígito (números por extenso);
nenhuma sigla em CAIXA ALTA (escreva por extenso ou como se lê); nenhum símbolo (%, /, &, +, =, #, @, →, *); sem reticências;
sem emoji ou markdown; 'você' e 'a gente' (nunca 'vocês', 'galera'); frases de 10 a 24 palavras."""

VIDEO_SYS = TUTOR + f"""
Tarefa (em português do Brasil COM acentuação correta em tudo): um fluxograma didático do conceito + a narração de um vídeo de 50 a 70 segundos que percorre o fluxograma caixa por caixa.
Formato do fluxograma (o layout é feito pelo código):
- "fluxo": 3 a 5 nós PRINCIPAIS em sequência, da esquerda para a direita (entrada → processo → saída).
- "laterais": 0 a 3 nós laterais; cada um fica EMBAIXO de UM principal (no máximo 1 por principal): riscos, variações, apoio.
- "volta": opcional, 1 seta de retorno de um principal para um anterior (ciclo de ajuste).
Rótulos: "rotulo" até 3 palavras; "detalhe" até 9 palavras; "seta" até 2 palavras. papel ∈ entrada | processo | saida | risco | apoio.
Cada nó tem "fala": UMA frase (termina em ponto, sem outro ponto no meio) explicando aquela caixa, na ordem da história.
Na "fala", termos técnicos com sigla ou número vão escritos como se falam (ex.: "efe um"). Nesses casos (e só neles)
inclua "legenda": a MESMA frase na grafia normal (ex.: "F1"), que aparece na tela. "rotulo" e "detalhe" usam grafia normal.
"abertura" apresenta o fluxograma inteiro e "fechamento" amarra a ideia central — uma frase cada.
{SPOKEN_RULES}
Devolva SÓ JSON:
{{"titulo": "até 7 palavras", "abertura": "...",
 "fluxo": [{{"id": "n1", "rotulo": "...", "detalhe": "...", "papel": "entrada", "seta": "...", "fala": "...", "legenda": "(opcional)"}}],
 "laterais": [{{"id": "l1", "abaixo_de": "n2", "rotulo": "...", "detalhe": "...", "papel": "risco", "seta": "...", "fala": "..."}}],
 "volta": {{"de": "n4", "para": "n2", "rotulo": "..."}} ou null, "fechamento": "..."}}"""


def video_user(concept):
    return f"Conceito: {concept}"


SEM_ACENTO = re.compile(r"\b(nao|sao|voce|voces|maquina|maquinas|comeca|padrao|padroes|entao|tambem|informacao|decisao|"
                        r"previsao|avaliacao|funcao|aplicacao|solucao|atencao|questao|possivel|facil|dificil|unico|numero|pratica)\b", re.I)


def accents_ok(text):
    """camada no código: o LLM às vezes devolve PT sem acento → legenda e pronúncia erradas."""
    letras = sum(ch.isalpha() for ch in text) or 1
    acentos = sum(ch in "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ" for ch in text)
    return len(SEM_ACENTO.findall(text)) < 2 and (letras < 200 or acentos / letras >= 0.008)


def validate_video(d):
    assert 3 <= len(d["fluxo"]) <= 6, "fluxo precisa de 3 a 5 nós"
    assert d.get("abertura") and d.get("fechamento"), "falta abertura/fechamento"
    for n in d["fluxo"] + d.get("laterais", []):
        assert n.get("fala"), f"nó {n.get('id')} sem fala"
    todo = " ".join([d["abertura"], d["fechamento"]] + [n["fala"] + " " + n.get("rotulo", "") + " " + n.get("detalhe", "")
                                                        for n in d["fluxo"] + d.get("laterais", [])])
    assert accents_ok(todo), "o texto veio SEM ACENTUAÇÃO (ex.: 'nao', 'maquina'); reescreva tudo em português com acentos corretos"


# ---------- slide 3: o conceito em imagens ----------
IMAGENS_SYS = TUTOR + """
Tarefa: planejar 4 ilustrações que ajudem o aluno a VER o conceito que ele acabou de estudar (texto do slide + vídeo abaixo).
Cada imagem mostra UMA ideia da aula, na ordem da história:
1) o panorama: o que é, a cena inteira;
2) e 3) os dois mecanismos mais importantes do fluxograma, mostrados por dentro (corte, vista explodida, antes/depois);
4) a analogia ou o exemplo da aula tornado visual.
Para cada uma:
- "titulo": até 6 palavras, em português com acentos;
- "legenda": 1 ou 2 frases, até 35 palavras, em português com acentos, dizendo o que a imagem mostra e a ideia que ela ensina;
- "cena": em INGLÊS, até 70 palavras, a descrição visual concreta para um gerador de imagem: o que aparece, onde, em que
  escala, com que cores de destaque (ex.: frio em azul, quente em laranja). Nada de texto, rótulos ou números na imagem;
  a ideia tem de ficar clara só pelo desenho. Tom adulto e editorial, nada infantil.
Devolva SÓ JSON: {"imagens": [{"titulo": "...", "legenda": "...", "cena": "..."}]} com EXATAMENTE 4 itens."""


def imagens_user(concept, aula):
    return f"Conceito: {concept}\n\nA AULA:\n{aula}"


def validate_imagens(d):
    im = d["imagens"]
    assert len(im) == 4, "precisa de EXATAMENTE 4 imagens"
    for x in im:
        assert x.get("titulo") and x.get("legenda") and x.get("cena"), "cada imagem precisa de titulo, legenda e cena"
    assert accents_ok(" ".join(x["titulo"] + " " + x["legenda"] for x in im)), "títulos e legendas vieram SEM ACENTUAÇÃO; reescreva com acentos"


# ---------- correção de cada resposta da prova (roda em 2º plano enquanto a próxima pergunta já é feita) ----------
AVALIA_SYS = TUTOR + """
Você corrige UMA resposta de uma prova oral RÁPIDA e LEVE sobre a aula que o aluno acabou de ver (a aula vem abaixo).
A resposta vem transcrita de voz: ignore vícios de fala e erros de transcrição.
Seja generoso: vale o essencial CERTO com as palavras dele, mesmo simples e curto. Saber mais do que a aula não é problema.
O aluno pode divagar por assuntos adjacentes, dar contexto extra ou se estender por outras áreas relacionadas — isso
NUNCA torna a resposta errada por si só. Procure DENTRO da resposta (mesmo longa ou dispersa) se o essencial do
conceito aparece corretamente em algum ponto; se aparecer, conta como certa mesmo cercado de outros assuntos.
- definicao: certa se, em algum trecho da resposta, traz o "essencial" sem erro grave — mesmo que o resto divague.
- exemplo: certa se, em algum trecho, dá um caso ESPECÍFICO e concreto (uma situação, não a definição de novo nem algo
  genérico como "quando alguém erra") que é mesmo do conceito (atende ao critério; não é o contraexemplo). Exemplo
  tirado da aula também vale.
- cenario: certa se, em algum trecho, responde à pergunta do cenário corretamente, aplicando o conceito.
- repeticao: o professor acabou de explicar; certa se, em algum trecho, o aluno disse com as palavras dele o essencial
  da explicação (não precisa ser igual; paráfrase curta vale).
Se o gabarito trouxer "nao_vale_repetir", repetir aquele caso (que ele acabou de ver no cartão) não conta: tem de ser outro.
Só marque ERRADA se pelo menos uma destas for verdadeira: (1) o essencial do conceito está ausente ou claramente mal
entendido em toda a resposta; (2) alguma afirmação sobre o CONCEITO em si (não sobre os assuntos adjacentes) é
factualmente falsa ou contraria o que a aula ensinou; (3) é "não sei"/vazio/sem tentativa real.
Divagar sem chegar a errar o conceito, ser prolixo, ou tocar em temas fora da aula: NÃO são motivo para marcar errada.
"evidencia": o trecho LITERAL da resposta (3 a 25 palavras, copiado exatamente) que mostra o acerto; null se errada.
"motivo": até 18 palavras para a tela, direto: o que estava certo, ou o que faltou/errou. Sem sermão, sem elogio vazio.
Devolva SÓ JSON: {"correta": true ou false, "evidencia": "..." ou null, "motivo": "..."}"""


def avalia_user(aula, pergunta, resposta):
    gab = {k: v for k, v in pergunta.items() if k not in ("fonte",)}
    return (f"AULA que o aluno viu:\n{aula}\n\nPERGUNTA ({pergunta['tipo']}) e gabarito:\n{json.dumps(gab, ensure_ascii=False, indent=1)}"
            f"\n\nRESPOSTA DO ALUNO:\n{resposta}")


# ---------- reaprendizagem (no fim da prova, só no que o aluno errou; preparada em 2º plano durante a prova) ----------
REAPRENDER_SYS = TUTOR + """
Tarefa: o aluno ERROU uma pergunta da prova oral sobre a AULA que ele acabou de ver (a aula vem abaixo). Monte a
reaprendizagem dessa pergunta, curta e no formato que conserta esse tipo de erro. Esta é a ÚNICA chance: ele não vai
revisar depois, então o conceito precisa ficar fechado agora. Use só o que a aula ensinou (sem termo ou detalhe de fora).
Tudo o que for "fala" ou "pergunta" vai ser FALADO: sem símbolos, números por extenso, siglas como se leem.

PASSO 1 — mini-aula + uma pergunta NOVA do mesmo tipo (nunca a mesma pergunta de antes):
- "fala": até 45 palavras. Tranquilo e direto, sem culpar: mostre o ponto certo contrastando com o que ele disse, sem
  entregar a resposta da nova pergunta. Nada de "entendi", "boa tentativa" ou elogio vazio. Se ele disse "não sei" ou
  não respondeu, NÃO comente isso: vá direto ao ponto da aula.
- "cartao" (aparece na tela), conforme o tipo da pergunta:
  · definicao → {"e": "o conceito É … (até 20 palavras, com as palavras da aula)", "nao_e": "o conceito NÃO é … (o equívoco que ele mostrou, até 20 palavras)"}
  · exemplo → {"caso_sim": "um caso concreto que É do conceito (até 30 palavras)", "caso_nao": "um caso parecido que NÃO é (até 30 palavras)", "por_que": "o que faz um exemplo valer (1 frase)"}
  · cenario → {"situacao": "um cenário parecido com o da prova (até 30 palavras)", "passos": ["o que está acontecendo", "que parte da aula explica", "a resposta"]}
- "segmento": o número do trecho do vídeo que melhor ensina isso (da lista recebida) ou null.
- "pergunta": a pergunta nova, terminando com '?':
  · definicao → pedir para explicar de novo com as palavras dele, como para um amigo;
  · exemplo → pedir OUTRO exemplo dele, diferente dos que ele já viu no cartão e na aula;
  · cenario → um cenário NOVO com a mesma lógica, em outra situação, MAIS SIMPLES e mais fácil que o da prova: uma
    situação só, até 40 palavras, e uma pergunta ABERTA e direta (nada de "A ou B?", nada de comparação complicada).
- "gabarito": a resposta certa da pergunta nova em 1 frase (para cenário) ou o que a resposta precisa ter.

PASSO 2 — só se ele errar de novo: o professor explica e pede para ele repetir.
- "fala": 15 a 40 palavras com a resposta certa da pergunta do PASSO 1, explicada com as palavras da aula.
- "pergunta": pede que ele diga com as palavras dele (termina com '?').
- "gabarito": o essencial que a repetição precisa conter (1 frase).

Devolva SÓ JSON:
{"passo1": {"fala": "...", "cartao": {...}, "segmento": 0 ou null, "pergunta": "...?", "gabarito": "..."},
 "passo2": {"fala": "...", "pergunta": "...?", "gabarito": "..."}}"""


def reaprender_user(aula, pergunta, resposta, motivo, trechos):
    gab = {k: v for k, v in pergunta.items() if k not in ("fonte",)}
    tr = json.dumps([{"i": t["i"], "texto": t["texto"]} for t in trechos], ensure_ascii=False) if trechos else "(vídeo ainda sem trechos)"
    return (f"AULA que o aluno viu:\n{aula}\n\nTrechos do vídeo (para o campo segmento): {tr}\n\n"
            f"PERGUNTA que ele errou ({pergunta['tipo']}) e gabarito:\n{json.dumps(gab, ensure_ascii=False, indent=1)}\n\n"
            f"O que ele respondeu: {resposta}\nPor que estava errado: {motivo}")


def validate_reaprender(tipo):
    campos = {"definicao": ("e", "nao_e"), "exemplo": ("caso_sim", "caso_nao", "por_que"), "cenario": ("situacao", "passos")}[tipo]

    def v(d):
        p1, p2 = d["passo1"], d["passo2"]
        for p, nome in ((p1, "passo1"), (p2, "passo2")):
            assert p.get("fala") and p.get("pergunta") and p.get("gabarito"), f"{nome} precisa de fala, pergunta e gabarito"
            p["pergunta"] = p["pergunta"].strip()
            assert p["pergunta"].endswith("?"), f"a pergunta do {nome} precisa terminar com '?'"
        c = p1.get("cartao") or {}
        assert all(c.get(k) for k in campos), f"o cartão de '{tipo}' precisa de: {', '.join(campos)}"
        if tipo == "cenario":
            assert isinstance(c["passos"], list) and len(c["passos"]) == 3, "o cartão de cenário precisa de exatamente 3 passos"
        assert len(p2["fala"].split()) >= 12, "a fala do passo2 TEM de explicar a resposta (15 a 40 palavras)"
    return v
