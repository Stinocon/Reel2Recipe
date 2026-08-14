# Third-party material and licences

Reel2Recipe is distributed under the MIT licence (see [`LICENSE`](LICENSE)). This file records
what, inside or around the project, is **somebody else's work**, and on what terms. The same
criterion applies as to the densities in `data/`: an attribution nobody can verify is not an
attribution.

This file is in English, unlike the two legal documents in `docs/`, and deliberately so: those
are authoritative in Italian for the user of this tool, whereas a NOTICE is read by whoever
reuses the code — and Apache-2.0, which is what governs the entry below, expects it in English.

The two categories below are distinct, and the difference matters legally as much as
practically.

## 1. Third-party material redistributed in this repository

This is what you receive by cloning. It is covered by its own licence, not by Reel2Recipe's.

| What | Where | Author | Licence |
|---|---|---|---|
| **Material Symbols**, icon outlines (Outlined, 24 px, `viewBox 0 -960 960 960`), embedded as SVG path data | `web/icons.js` (`ICON_PATHS`), the favicon in `web/index.html`, the gap marker in `web/style.css` | Google | [Apache-2.0](https://github.com/google/material-design-icons/blob/master/LICENSE) |

The icons are **embedded rather than loaded from a CDN** because the interface has to work
without a network, like the rest of the product: no request to Google, neither the first time
nor afterwards. Embedding them does not change their licence — the attribution above travels
with every copy of this repository.

The original name of each icon is recorded in the comment above its entry in `web/icons.js`, so
it can be found again in the catalogue at [fonts.google.com/icons](https://fonts.google.com/icons).

## 2. Tools Reel2Recipe uses but does **not** include

None of these is redistributed here. They are installed separately (`./install.sh` takes care
of it) and remain under the licence and terms of their respective authors, **which you accept
by installing them**, not by using Reel2Recipe.

| Tool | Role here | Author | Licence |
|---|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | fetching the reel and its metadata | yt-dlp contributors | Unlicense |
| [Whisper](https://github.com/openai/whisper) via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / [mlx-whisper](https://github.com/ml-explore/mlx-examples) | local speech transcription | OpenAI; SYSTRAN; Apple | MIT |
| [Ollama](https://ollama.com) and the [Qwen2.5](https://github.com/QwenLM/Qwen2.5) models | structuring the recipe, locally | Ollama; Alibaba Cloud | MIT; Qwen (Apache-2.0 for most sizes) |
| [ffmpeg](https://ffmpeg.org) | extracting the audio track | FFmpeg | LGPL/GPL depending on the build |
| [ReportLab](https://www.reportlab.com/opensource/) | PDF export (optional `doc` extra) | ReportLab | BSD-3-Clause |
| [FastAPI](https://fastapi.tiangolo.com) and [uvicorn](https://www.uvicorn.org) | local web interface (`api` extra) | Sebastián Ramírez; Encode | MIT; BSD-3-Clause |

## 3. Conversion data

The densities in `data/densities.yaml` derive from **USDA FoodData Central** (public domain) and
from **King Arthur Baking's Ingredient Weight Chart**, cited entry by entry in the `source`
field. They are matters of fact, not protected material: the value added here is having
verified them and made them traceable.

## 4. Ideas distilled, not installed

Some practices in this repository come from third-party projects, adopted as an **idea** and
rewritten in native form — never installed as code or as a hook. The most visible is the
criterion against over-engineering described in [`docs/architecture.md`](docs/architecture.md)
("what gets added is what solves a problem already seen"), distilled from the "decision ladder"
of [Ponytail](https://github.com/DietrichGebert/ponytail) (MIT). An idea is not protected
material and this citation is not a licence obligation: it is here because it is right to say
where something came from.
