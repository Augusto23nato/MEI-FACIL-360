# MEI-FACIL-360

## Lampejo (professor particular)
O Lampejo está na pasta `Lampejo/`. Quando a pessoa pedir para aprender/entender/estudar algo ("quero aprender X",
"me explica X", "aula de X", "Lampejo X"), siga `Lampejo/CLAUDE.md` e rode os comandos de dentro de `Lampejo/`.

Nesta nuvem (contêiner):
- Se `Lampejo/.venv` ou `Lampejo/.lampejo/config.env` não existirem, rode `bash Lampejo/tools/preparar_nuvem.sh`.
- Crie a aula com `cd Lampejo && LAMPEJO_NO_OPEN=1 ./aula.sh "<conceito>"`. O endereço `127.0.0.1` não abre no
  navegador da pessoa: espere o vídeo ficar pronto (`curl -s http://127.0.0.1:4242/api/s/<id>/state`), tire um print
  da tela 1 com o Playwright e envie o print e `runs/<aula>/video/fluxograma.mp4` para a pessoa.
- A chave do ElevenLabs é injetada pelo proxy do ambiente (no arquivo de configuração há só `proxy-injected`).
  Nunca peça a chave no chat.
