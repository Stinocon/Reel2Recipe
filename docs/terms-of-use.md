# Terms of use

<p align="right"><a href="terms-of-use.it.md">Italiano</a> · <strong>English</strong></p>

> **The Italian version is the authoritative one.** This document exists in both languages and
> the two are meant to say the same thing. Where they appear to differ,
> [`terms-of-use.it.md`](terms-of-use.it.md) prevails. Keeping two legally operative versions
> in step is a commitment, not an automatism: the prevalence clause exists so that commitment
> has a defined resolution if it is ever not met.

This is the text addressed to **whoever uses** Reel2Recipe. The legal analysis behind the
design decisions is a different thing and lives in [`legal.md`](legal.md).

## What it is, and what it is not

Reel2Recipe is a **personal project**, put together for its author's own use and published as
is. It is not a finished product, it is not commercial, and it will not become either. It was
written largely **with the help of an AI assistant**, under human guidance and review: that
was part of the point — finding out how far these tools go by getting something genuinely
useful out of them, rather than a demonstration.

It is distributed **without warranty of any kind** (see [`LICENSE`](../LICENSE)): it plausibly
contains errors and edge cases nobody has thought of yet.

## The most important thing: check the amounts

Extraction is automatic. A model listens to the speech and reads the caption, and it can be
wrong: mishear a word, skip an ingredient, attach an amount to something that never had one.

The project is built to **reduce** that risk and to **make it visible**:

- the amounts are converted by the code and not by the model, with density tables that cite
  their source (USDA FoodData Central, King Arthur Baking) — you can go and check them;
- when a density is not known, the conversion **is not done**: the volume stays as it was, and
  the fact is declared;
- every amount carries its provenance — stated by the reel, converted from a table, or
  **estimated** (the eyeball measures, like "a pinch");
- the gaps go into every export, PDF included, instead of being hidden.

One rule remains that no software can take off your hands: **read the recipe before you cook
it**, especially the weights and the times. A declared gap you can deal with; a wrong weight
you do not know is wrong, you cannot.

If you have **allergies or intolerances**, do not trust the extracted list: go back to the
original source, which is always cited in the recipe.

## Personal use, and responsibility towards the platforms

The tool is meant for **personal use**, on content you actually care about.

Downloading a reel from Instagram **breaches that platform's Terms of Use**, regardless of
what you then do with it. It is the reason Reel2Recipe runs locally and is not a public
service, and the reason **the no-download alternative is always available**: you can hand it a
file you already have, or paste the caption by hand.

The choice to use the from-URL retrieval, and the consequences of that choice towards the
platform, **remain yours**. Whoever maintains this project does not take responsibility for
them.

## The recipes are not yours

An extracted recipe remains **the work of whoever published it**. Reel2Recipe is built to
respect that:

- the ingredient list is mere information and is not protected by copyright: extracting and
  reformatting it is lawful;
- the text of the method, on the other hand, **is** protected, which is why it gets *rephrased*
  in the tool's own words and never transcribed word for word;
- the **link to the source** is always included, in every export format.

Do not remove the attribution, and do not redistribute extracted recipes as if they were your
own. Keeping them for yourself, or sharing them while crediting the author, is another matter.

## Your data

It does not leave your machine. There is no telemetry, there are no calls to remote services
for the product to work, and no model is trained on what you extract. Videos, audio, captions
and the recipe library live in `workspace/`, which is excluded from git: if you publish your
own copy of the repository, that material does not travel with it.

## Licence

The **code** is MIT (see [`LICENSE`](../LICENSE)): use it, modify it and redistribute it
freely, commercially too, keeping the attribution. Third-party material included or used is
listed in [`NOTICE.md`](../NOTICE.md) with its respective licences.

The licence covers the software, **not** the recipes you extract with it: those follow the
rules of the section above.
