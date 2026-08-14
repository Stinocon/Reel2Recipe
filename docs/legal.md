# Copyright, patents and Terms of Use

<p align="right"><a href="legal.it.md">Italiano</a> · <strong>English</strong></p>

> **The Italian version is the authoritative one.** This document exists in both languages and
> the two are meant to say the same thing. Where they appear to differ,
> [`legal.it.md`](legal.it.md) prevails: it is the version written first, and it carries the
> citations in their original wording. Say so plainly rather than pretend two texts can never
> drift — they can, and naming which one wins is what makes a bilingual legal document usable
> instead of ambiguous.

This note explains why Reel2Recipe is built the way it is. It is not legal advice: it is the
honest survey that guided the design decisions. Its conclusions shape the code; they are not
a footnote to it.

In one line: **extracting a recipe for personal use is lawful; redistributing a creator's
prose is not; downloading from Instagram breaches that platform's Terms of Use.**

---

## 1. Ingredient lists are not protected by copyright

An ingredient list is **information**, not a work of authorship. It lacks the creative
character that Italian copyright law (L. 633/1941, art. 1) requires for protection: it is a
fact, like a chemical recipe or a formula.

The same conclusion holds in the United States: in *Publications International v. Meredith
Corp.* (7th Circuit, 1996) the court held that «the identification of ingredients necessary
for the preparation of a dish is a statement of facts […] there is no expressive element
deserving copyright protection».

**Consequence for Reel2Recipe:** extracting the ingredient list from a reel and reformatting
it — converting the amounts, grouping it, translating it — is lawful.

---

## 2. A creator's descriptive text, on the other hand, is protected

The narration, the anecdote, the phrasing with which a creator tells you how a dish is made
are **creative expression** and are protected by copyright. Copying them word for word and
republishing them would be an infringement.

**Consequence for Reel2Recipe — two concrete design decisions:**

1. `extract.py` **rephrases** the method in its own words, as short operative instructions. It
   does not transcribe the creator's text: it extracts the actions from it. The model's prompt
   requires this explicitly.
2. The `link` field of every exported recipe points **always** to the original reel, where one
   is available. Crediting the author is not an optional extra: it is the correct way to use
   their work. The recipe points back to the source; it does not replace it.

---

## 3. Patents do not come into it

Home cooking recipes **are not patentable inventions**: they do not have the novelty and
industrial application a patent protects. The worry about patents has no real counterpart in
this context.

(Patents on industrial *food processes* do exist — a pasteurisation method, a machine — but
they are another world, unrelated to the domestic use of this tool.)

---

## 4. Instagram's Terms of Use — this is where the real point is

It is the legally most relevant aspect, and it is not about copyright.

**Instagram's Terms of Use** forbid the automated collection of content from the platform
without authorisation. Downloading a reel with a tool like `yt-dlp` is a **breach of
contract** against those Terms — not a crime, not a copyright infringement, but a breach of
the agreement you accept by using Instagram all the same.

This is why Reel2Recipe is designed the way it is:

- **It is a local tool, for personal use.** It is not a public service that downloads reels on
  other people's behalf on demand. The difference is substantive: personal, limited use of
  content you have chosen to look at is a different thing from systematic collection at scale.
- **The download is an explicit choice by the user**, not hidden behaviour: the from-URL
  feature invokes `yt-dlp` only when the user pastes a link and presses *Cook*.
- **The no-download alternative is always available**: upload a video file you already have,
  or paste the caption alone. That path does not touch the Terms of Use at all.

**If this project were ever published** as a web application open to everybody, the public
version would have to accept **only files supplied by the user**, with no download-from-URL
feature: a public service downloading from Instagram on its users' behalf would draw the
liability for the breach onto itself, multiplied by every user. For the local, personal use
the project is meant for today, the boundary is the one described above.

---

## 5. Downloaded material never leaves the computer

Every video, audio track, frame and caption that gets downloaded ends up in `workspace/`,
which is excluded from git (`.gitignore`). That material:

- **is never committed** to the repository;
- **is never redistributed** or uploaded anywhere;
- **is never used to train models** (the models run locally and send nothing out).

Only the **code** and the impersonal conversion tables go into the public repository. The
anti-leak guard in `check.sh` mechanically verifies, before every commit, that no file from
`workspace/` has found its way under git by mistake.

---

## In summary

| Aspect | Status | How we handle it |
|---|---|---|
| Ingredient list | Not protected | Extracted and reformatted freely |
| Method prose | Protected | Rephrased, never copied; source always credited |
| Patents | Not relevant | — |
| Instagram's Terms of Use | Downloading breaches them | Local tool, personal use, no-download alternative |
| Downloaded material | Third-party | Local only, never shared, anti-leak guard |
