"""Slide 3: imagens do conceito — Gemini Flash Lite Image pelo OpenRouter (~4 s e ~US$ 0,03 por imagem)."""
import base64
import os
import time

import requests

from . import config

MODEL = os.environ.get("LSL_IMAGE_MODEL", "google/gemini-3.1-flash-lite-image")

ESTILO = ("Editorial scientific illustration in the style of a high-end science magazine explainer "
          "(Scientific American, The Economist, Kurzgesagt-for-adults): clean confident ink linework with soft painterly "
          "shading, cutaway or diagrammatic view when it helps understanding, muted slate and ivory palette with one or two "
          "vivid accent colors, cinematic soft lighting, one clear focal subject, generous negative space. Sophisticated and "
          "adult, suitable for a university lecture: NOT cartoonish, no mascots, no cute characters, no clip-art, no stock-photo look. "
          "Absolutely no text, letters, words, labels, logos or numbers anywhere in the image. 16:9 widescreen.")


def gerar(cena, out_path):
    t = time.time()
    body = {"model": MODEL, "modalities": ["image", "text"], "image_config": {"aspect_ratio": "16:9"},
            "usage": {"include": True},
            "messages": [{"role": "user", "content": f"{cena}\n\nStyle: {ESTILO}"}]}
    if not config.openrouter_key():
        raise RuntimeError("imagens desligadas: adicione uma chave do OpenRouter (rode o setup de novo ou edite .lampejo/config.env)")
    last = None
    for _ in range(2):
        try:
            r = requests.post(config.OPENROUTER_URL, headers={"Authorization": "Bearer " + config.openrouter_key()},
                              json=body, timeout=90)
            j = r.json()
            if r.status_code != 200:
                raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {str(j)[:200]}")
            url = j["choices"][0]["message"]["images"][0]["image_url"]["url"]
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(base64.b64decode(url.split(",", 1)[1]))
            return {"usd": (j.get("usage") or {}).get("cost") or 0.0, "secs": time.time() - t}
        except (requests.RequestException, KeyError, IndexError, ValueError, RuntimeError) as e:
            last = e
    raise RuntimeError(f"imagem não saiu: {last}")
