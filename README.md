# citelint

> Easy, transparent citation linting for LaTeX papers.

[![PyPI version](https://img.shields.io/pypi/v/citelint)](https://pypi.org/project/citelint/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://pypi.org/project/citelint/)
[![CI](https://github.com/haolin3/citelint/actions/workflows/ci.yml/badge.svg)](https://github.com/haolin3/citelint/actions)

![screenshot](screenshot_overview.png)

## Why citelint?

Existing citation checkers tell you "this reference is OK" or "this reference has a problem" — but you can't see *what* they checked, *how* they checked it, or *what they might have missed*. You're left trusting a black box.

**citelint takes a different approach: instead of giving you pass/fail verdicts, it puts all the information in front of you and lets you decide.**

Because verifying a citation is not just one question — it's three:

| Layer | Question | What citelint shows you |
|-------|----------|------------------------|
| **Existence** | Does this paper actually exist? | One-click search across Semantic Scholar, DBLP, Google Scholar, arXiv |
| **Accuracy** | Are the authors, year, and venue correct? | Bib fields decomposed side-by-side with the PDF-rendered reference and online search results |
| **Context** | Does this citation make sense where it's used? | Every citation site highlighted in its surrounding text, so you can judge the fit |

Automated tools can help with the first question. Only a human can answer the third. citelint gives you what you need for all three — in one page, for every reference in your paper.

---

## Install

```bash
pip install citelint
```

## Use

```bash
cd /path/to/your/paper
citelint
```

That's it. Auto-detects your `.bib`, `.tex`, and `.bbl` files, generates an interactive audit page, opens it in your browser.

### Try it with an example paper

```bash
git clone https://github.com/haolin3/citelint.git
cd citelint/examples/lora-iclr2022
citelint
```

Three real papers are included for testing:

| Directory | Paper | Template |
|-----------|-------|----------|
| `examples/lora-iclr2022/` | LoRA (Hu et al., 2022) | ICLR |
| `examples/llava-neurips2023/` | LLaVA (Liu et al., 2023) | NeurIPS |
| `examples/llama2-meta2023/` | LLaMA 2 (Touvron et al., 2023) | arXiv |

---

## What each reference card shows

```
Left (your paper)                    Right (verification)
-------------------------------------------------------
PDF rendered reference               Quick search links
  the exact text the reviewer          DBLP / Semantic Scholar /
  sees in your References section      Google Scholar / arXiv

Entry fields                         BibGuard automated checks
  Type / Author / Title /              Field-by-field validation
  Venue / Year / Pages / URL           against online databases

Citation contexts                    Search & verify
  "...shown by THIS REF that..."       One-click S2 + DBLP search,
  every place this ref is cited,       top 3 results with match %,
  with surrounding text visible        TLDR, and direct links
```

![detail view](screenshot_detail.png)

---

## The review-fix-review workflow

```bash
citelint --watch
```

Edit your `.bib` or `.tex` in your editor. citelint detects the change, regenerates the audit page, and the browser auto-refreshes. No manual reloading, no re-running commands. Keep fixing until everything looks right, then `Ctrl+C`.

---

## Supported templates

Works out of the box with any BibTeX-based LaTeX template:

| Template | Venues | Status |
|----------|--------|--------|
| natbib (`plainnat.bst`) | NeurIPS, ICML, ICLR, AAAI, AISTATS, ... | Tested |
| `acmart.cls` | ACM (SIGCHI, KDD, WWW, ...) | Tested |
| `IEEEtran.cls` | IEEE (CVPR, ICCV, ...) | Tested |
| `llncs.cls` | Springer LNCS (ECCV, ...) | Tested |
| biblatex | Journals using biblatex | Tested |
| Any `\bibitem{key}` format | Everything else | Works |

> **Don't see your template?** It probably works — the parser handles any standard `.bbl` format. If it doesn't, [open an issue](https://github.com/haolin3/citelint/issues) with your `.bbl` file and we'll add support.

---

## Options

```bash
citelint                       # current directory, English UI
citelint ~/papers/my-paper     # specific directory
citelint --lang zh             # Chinese UI
citelint --watch               # auto-regenerate + auto-reload on file changes
citelint --port 9000           # different port
citelint --bib custom.bib      # specific .bib file
citelint --no-server           # generate HTML only
citelint --no-open             # don't open browser
citelint --regenerate          # force regenerate
```

---

## Semantic Scholar API key (optional)

Without a key, Semantic Scholar search is rate-limited (~10 requests/min). Get a free key at https://www.semanticscholar.org/product/api#api-key-form :

```bash
echo 'export S2_API_KEY=your-key-here' >> ~/.zshrc
source ~/.zshrc
```

---

## What files does it need?

| File | What it provides | Required? |
|------|-----------------|-----------|
| `.bib` | Entry fields, search links, BibGuard checks | **Yes** |
| `.tex` | Citation contexts (where each ref is cited) | No |
| `.bbl` | PDF rendered reference (what the reviewer sees) | No |

Minimum: just a `.bib` file. Everything else enriches the audit.

---

## How it works

```
citelint /path/to/paper
  |
  +-- parse .bib       -> entry field decomposition
  +-- parse .bbl       -> PDF rendered text  (auto-detects template format)
  +-- scan .tex files  -> citation contexts
  +-- run BibGuard     -> automated field checks  (included by default)
  +-- generate HTML    -> citelint.html
  |
  +-- local server (localhost:8899)
       +-- serves the audit page
       +-- proxies Semantic Scholar API  (your key stays local)
       +-- proxies DBLP API
```

---

## FAQ

**Q: Why a local server? Can I just open the HTML file?**
A: The "Search & Verify" feature calls Semantic Scholar and DBLP APIs, which browsers block from `file://` URLs (CORS). The local server proxies these requests. Static content (rendered reference, entry fields, citation contexts) works fine by opening the HTML directly.

**Q: My `.bbl` isn't parsed correctly.**
A: Open an [issue](https://github.com/haolin3/citelint/issues) and attach your `.bbl` file. The parser auto-detects ACM, plain (natbib/IEEE/LNCS), and biblatex formats, but there may be edge cases.

**Q: BibGuard is slow.**
A: BibGuard queries DBLP, Semantic Scholar, OpenAlex, arXiv, and CrossRef for each entry. 60 entries takes about 60-90 seconds. A progress indicator shows elapsed time while it runs. This only happens during generation — re-running `citelint` without `--regenerate` skips it.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The easiest way to help: add your template's `.bbl` file as a test fixture.

## License

MIT
