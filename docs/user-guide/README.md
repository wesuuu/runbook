# Batchrite User Guide

This directory is the curated knowledge corpus for the in-app **App Help**
chat subagent (`app_help`, F-0089). Each `.md` page documents one shipped
Batchrite feature surface in end-user voice.

## How it works

The chat agent dispatches the `app_help` subagent for product questions
("how do I…", "what is…", "where is…"). The subagent lists these pages by
their frontmatter, reads the relevant one, and answers with a citation.
Adding or editing a page takes effect immediately — the tools read disk on
every call. (Adding a *new subagent* or changing prompts needs a process
restart; editing corpus `.md` files does not.)

## Authoring rules

- End-user voice — second person ("You can…"), no developer jargon, no
  internal file paths in user-facing prose.
- Document only features shipped and on-by-default. Flag-gated-off features
  (offline mode, external protocols) and unbuilt features (voice/dictation)
  are excluded until shipped on by default.
- Every page starts with YAML frontmatter: `title`, `summary`, `keywords`.
- ~150–500 words per page. Follow the template: overview → "What you can
  do" bullets → "How to …" sections.

## Pages

- `getting-started.md` — What Batchrite is and how to navigate the app.
- `protocols-and-editor.md` — Creating, editing, validating, and publishing protocols.

## Excluded (not shipped on production defaults)

- Offline / PWA mode — flag-gated off (`features.offline_mode`).
- External protocols / OpenWetWare — flag-gated off (`features.external_protocols`).
- Voice / dictation — not built.
