# Setup do Lampejo (primeira conversa)

Você (Claude) conduz esta configuração **conversando em português simples**, um passo por vez. A pessoa
pode nunca ter usado um terminal: explique o que vai acontecer antes de cada passo e o que deu certo depois.
Rode todos os comandos a partir da raiz desta pasta.

## Passo 1 — Conferir o computador
`python3 setup/setup.py check` → mostre em linguagem simples o que já está pronto e o que falta.
- Se o `claude_code.logado` vier `false`: peça para a pessoa digitar `/login` e entrar com a conta do Claude
  (é a assinatura do Claude que gera as aulas — sem custo extra por aula).

## Passo 2 — Instalar os programas
Avise o que falta de verdade (segundo o `check`): o ffmpeg (monta o vídeo), o draw.io (desenha o fluxograma),
um ambiente Python só do Lampejo e um navegador invisível que grava a animação (download de ~300 MB).
Leva de 2 a 10 minutos, conforme a internet e o que já estiver instalado.
Rode `python3 setup/setup.py install` (timeout longo, até 15 min).
- Saída `precisa_homebrew: true` (Mac sem Homebrew): peça para a pessoa rodar ela mesma, no Claude Code,
  `! <comando_para_o_usuario>` — o instalador pede a senha do Mac. Depois rode `install` de novo.
- Linux: o `sudo` pode pedir senha → peça para a pessoa rodar com `!` o comando que falhou.
- Windows: siga a mensagem de `falhas` (winget) e rode `check` de novo.
Só siga quando `check` mostrar `ffmpeg`, `drawio`, `ambiente_python` e `navegador_de_captura` como `true`.

## Passo 3 — Conta e chave do ElevenLabs (a voz das aulas)
1. Pergunte se a pessoa já tem conta no ElevenLabs. Se não tiver, rode `python3 setup/setup.py open-signup`
   (abre a página de cadastro; o plano gratuito serve para começar).
2. Rode `python3 setup/setup.py open-keys` e guie: "clique em Create API Key, dê o nome Lampejo, deixe
   liberado Text to Speech, Speech to Text e Voices, crie e copie a chave".
3. Peça para colar a chave aqui. Rode `python3 setup/setup.py eleven-test --key <chave>`.
   - Erro: explique a `dica` e peça a chave de novo.

## Passo 4 — Escolher a voz do narrador
A lista do passo anterior já vem ordenada (clones primeiro, depois vozes em português). Mostre só as 5 a 8
primeiras (nome + descrição). Se houver `cloned`, sugira ("parece ser a sua própria voz"). Prefira vozes com
`portugues: true` — as aulas são faladas em português. Se não houver nenhuma boa, sugira uma multilíngue e
diga que dá para clonar a própria voz no ElevenLabs depois e trocar.
Anote o `voice_id` escolhido.

## Passo 5 — (Opcional) Imagens do conceito
O slide de ilustrações usa o OpenRouter (cerca de US$ 0,03 por imagem). Pergunte se a pessoa quer ativar.
- Sim: `python3 setup/setup.py open-openrouter`, peça a chave, valide com `openrouter-test --key <chave>`.
- Não: tudo funciona, só o slide de imagens mostra um aviso.

## Passo 6 — Salvar
`python3 setup/setup.py save --eleven-key <chave> --voice <voice_id> --voice-name "<nome>" [--openrouter-key <chave>]`
Explique: "suas chaves ficaram só neste computador, em `.lampejo/config.env`".

## Passo 7 — Testar de verdade
`python3 setup/setup.py verify`. Se `ok: false`, resolva o item de `faltando` e repita.
Depois rode a primeira aula de exemplo: `./aula.sh "juros compostos"` e diga que ela abriu no navegador:
o texto chega em segundos e o vídeo em cerca de 1 minuto (aparece o aviso *pronto →*).

## Passo 8 — Fechar o setup
Só com o `verify` aprovado: `python3 setup/setup.py finish` (apaga esta pasta `setup/` e o bloco de setup do
CLAUDE.md). Diga: "Pronto! A partir de agora é só me dizer: *quero aprender X*."
