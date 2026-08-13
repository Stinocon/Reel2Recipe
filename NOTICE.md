# Materiale di terzi e licenze

Reel2Recipe è distribuito con licenza MIT (v. [`LICENSE`](LICENSE)). Questo file registra ciò
che, dentro o attorno al progetto, è **lavoro di qualcun altro**, e a quali condizioni. Vale
lo stesso criterio delle densità in `data/`: un'attribuzione che nessuno può verificare non è
un'attribuzione.

Le due categorie sotto sono distinte, e la differenza conta legalmente quanto praticamente.

## 1. Materiale di terzi ridistribuito in questo repository

È ciò che ricevi clonando. È coperto dalla propria licenza, non da quella di Reel2Recipe.

| Cosa | Dove | Autore | Licenza |
|---|---|---|---|
| **Material Symbols**, tracciati delle icone (Outlined, 24 px, `viewBox 0 -960 960 960`), incorporati come dati di percorso SVG | `web/icons.js` (`ICON_PATHS`), la favicon in `web/index.html`, il marcatore delle lacune in `web/style.css` | Google | [Apache-2.0](https://github.com/google/material-design-icons/blob/master/LICENSE) |

Le icone sono **incorporate anziché caricate da un CDN** perché l'interfaccia deve funzionare
senza rete, come tutto il resto del prodotto: nessuna richiesta a Google, né la prima volta né
dopo. Incorporarle non cambia la loro licenza — l'attribuzione qui sopra viaggia con ogni
copia di questo repository.

Il nome originale di ogni icona è riportato nel commento sopra la sua voce in `web/icons.js`,
così è ritrovabile nel catalogo su [fonts.google.com/icons](https://fonts.google.com/icons).

## 2. Strumenti che Reel2Recipe usa ma **non** include

Nessuno di questi è ridistribuito qui. Si installano a parte (`./install.sh` se ne occupa) e
restano sotto la licenza e i termini dei rispettivi autori, **che accetti installandoli**, non
usando Reel2Recipe.

| Strumento | Ruolo qui | Autore | Licenza |
|---|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | acquisizione del reel e dei suoi metadati | contributori yt-dlp | Unlicense |
| [Whisper](https://github.com/openai/whisper) via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / [mlx-whisper](https://github.com/ml-explore/mlx-examples) | trascrizione locale del parlato | OpenAI; SYSTRAN; Apple | MIT |
| [Ollama](https://ollama.com) e i modelli [Qwen2.5](https://github.com/QwenLM/Qwen2.5) | strutturazione della ricetta, in locale | Ollama; Alibaba Cloud | MIT; Qwen (Apache-2.0 per la maggior parte delle taglie) |
| [ffmpeg](https://ffmpeg.org) | estrazione della traccia audio | FFmpeg | LGPL/GPL secondo la build |
| [ReportLab](https://www.reportlab.com/opensource/) | export in PDF (extra opzionale `doc`) | ReportLab | BSD-3-Clause |
| [FastAPI](https://fastapi.tiangolo.com) e [uvicorn](https://www.uvicorn.org) | interfaccia web locale (extra `api`) | Sebastián Ramírez; Encode | MIT; BSD-3-Clause |

## 3. Dati di conversione

Le densità in `data/densita.yaml` derivano da **USDA FoodData Central** (dominio pubblico) e
dalla **Ingredient Weight Chart di King Arthur Baking**, citate voce per voce nel campo
`fonte`. Sono dati di fatto, non materiale protetto: il valore aggiunto qui è averli
verificati e resi tracciabili.

## 4. Idee distillate, non installate

Alcune pratiche di questo repository vengono da progetti di terzi, adottate come **idea** e
riscritte in forma nativa — mai installate come codice o hook. La più visibile è il criterio
contro l'over-engineering descritto in [`docs/architecture.md`](docs/architecture.md)
(«si aggiunge ciò che risolve un problema già visto»), distillato dalla "decision ladder" di
[Ponytail](https://github.com/DietrichGebert/ponytail) (MIT). Un'idea non è materiale
protetto e questa citazione non è un obbligo di licenza: sta qui perché è giusto dire da dove
viene.
