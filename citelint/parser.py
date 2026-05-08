"""Parsers for .bib, .bbl, and .tex files.

Supports:
  - BibTeX .bib (universal)
  - .bbl: ACM, plain (natbib/IEEE/LNCS/AAAI), biblatex
  - .tex citations: standard, natbib, biblatex, apacite
"""

import os
import re

# ── LaTeX Cleaning ─────────────────────────────────────────────

_ACCENT_MAPS = [
    (r"\{\\`([a-zA-Z])\}", {"o": "ò", "a": "à", "e": "è", "u": "ù", "i": "ì"}),
    (r"\{\\'([a-zA-Z])\}", {"o": "ó", "a": "á", "e": "é", "u": "ú", "i": "í", "n": "ń", "E": "É", "c": "ć"}),
    (r'\{\\"([a-zA-Z])\}', {"o": "ö", "a": "ä", "e": "ë", "u": "ü", "O": "Ö", "U": "Ü"}),
    (r"\\~\{([a-zA-Z])\}", {"n": "ñ", "a": "ã", "o": "õ"}),
    (r"\\c\{([a-zA-Z])\}", {"c": "ç", "C": "Ç", "s": "ş", "S": "Ş"}),
    (r"\\v\{([a-zA-Z])\}", {"c": "č", "s": "š", "z": "ž", "r": "ř", "e": "ě"}),
    (r'\\"([a-zA-Z])', {"o": "ö", "a": "ä", "e": "ë", "u": "ü", "O": "Ö", "U": "Ü"}),
    (r"\\'([a-zA-Z])", {"o": "ó", "a": "á", "e": "é", "u": "ú", "i": "í", "n": "ń", "E": "É", "c": "ć"}),
    (r"\\`([a-zA-Z])", {"o": "ò", "a": "à", "e": "è", "u": "ù", "i": "ì"}),
]


def clean_latex(s):
    """Convert LaTeX accent commands to Unicode and strip braces."""
    for pat, repl_map in _ACCENT_MAPS:
        s = re.sub(pat, lambda m, rm=repl_map: rm.get(m.group(1), m.group(0)), s)
    s = re.sub(r"[{}]", "", s)
    return s


def format_authors(raw):
    """Convert 'Last, First and Last, First' to 'First Last / First Last'."""
    raw = clean_latex(raw)
    parts = re.split(r"\s+and\s+", raw)
    names = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if "," in p:
            segs = p.split(",", 1)
            last = segs[0].strip()
            first = segs[1].strip() if len(segs) > 1 else ""
            names.append(f"{first} {last}" if first else last)
        else:
            names.append(p)
    return " / ".join(names)


# ── .bib Parser ───────────────────────────────────────────────

def parse_bib(bib_path):
    """Parse .bib file into {key: {fields...}}."""
    with open(bib_path, encoding="utf-8", errors="replace") as f:
        bib_raw = f.read()
    entries = {}
    for m in re.finditer(r"@(\w+)\{([^,]+),(.*?)(?=\n@|\Z)", bib_raw, re.DOTALL):
        key = m.group(2).strip()
        body = m.group(3)
        fields = {"_type": m.group(1).strip().lower()}
        for fm in re.finditer(
            r"(\w+)\s*=\s*(?:\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}|(\d+))",
            body,
        ):
            fields[fm.group(1).lower()] = (
                fm.group(2) if fm.group(2) is not None else fm.group(3)
            ).strip()
        entries[key] = fields
    return entries


# ── .bbl Parser ───────────────────────────────────────────────

def _clean_bbl_body(body):
    """Shared cleanup for .bbl entry bodies."""
    clean = body
    clean = re.sub(r"\\newblock\s*", "", clean)
    clean = re.sub(r"\\emph\{([^}]*)\}", r"\1", clean)
    clean = re.sub(r"\\textit\{([^}]*)\}", r"\1", clean)
    clean = re.sub(r"\\textbf\{([^}]*)\}", r"\1", clean)
    clean = re.sub(r"\\url\{([^}]*)\}", r"\1", clean)
    clean = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", clean)
    clean = re.sub(r"\\path\|([^|]*)\|", r"\1", clean)
    clean = re.sub(r"et~al\\mbox\{\.\}", "et al.", clean)
    clean = re.sub(r"\\mbox\{([^}]*)\}", r"\1", clean)
    clean = re.sub(r"et~al\.", "et al.", clean)
    clean = re.sub(r"~", " ", clean)
    # IEEE-specific
    clean = re.sub(r"\\BIBentry\w+\b", "", clean)
    clean = re.sub(r"\\bbl\w+\{([^}]*)\}", r"\1", clean)
    # Accents
    for pat, repl_map in _ACCENT_MAPS:
        clean = re.sub(pat, lambda m, rm=repl_map: rm.get(m.group(1), m.group(0)), clean)
    clean = re.sub(r"[{}]", "", clean)
    clean = re.sub(r"\n", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _parse_bbl_acm(bbl):
    """Parse ACM-style .bbl (bibfield/bibinfo commands)."""
    pattern = (
        r"\\bibitem\[([^\]]*(?:\{[^}]*\}[^\]]*)*)\]%?\s*\n"
        r"\s*\{([a-zA-Z0-9_:.\-/]+)\}\s*\n"
        r"(.*?)(?=\\bibitem\[|\s*\\end\{thebibliography\})"
    )
    matches = list(re.finditer(pattern, bbl, re.DOTALL))
    if not matches:
        return None, None
    order = []
    entries = {}
    for m in matches:
        key = m.group(2)
        body = m.group(3).strip()
        order.append(key)
        clean = body
        clean = re.sub(r"\\bibfield\{[^}]*\}", "", clean)
        clean = re.sub(r"\\bibinfo\{person\}\{([^}]*(?:\{[^}]*\}[^}]*)*)\}", r"\1", clean)
        clean = re.sub(r"\\bibinfo\{(\w+)\}\{([^}]*(?:\{[^}]*\}[^}]*)*)\}", r"\2", clean)
        clean = re.sub(r"\\natexlab\{[^}]*\}", "", clean)
        clean = re.sub(r"\\showarticletitle\s*", "", clean)
        clean = re.sub(r"\\showDOI\{[^}]*\}", "", clean)
        clean = re.sub(r"\\showURL\s*\{[^}]*\}", "", clean)
        clean = re.sub(r"\\showeprint\s*(?:\[[^\]]*\])?\s*\{[^}]*\}", "", clean)
        entries[key] = _clean_bbl_body(clean)
    return order, entries


def _parse_bbl_biblatex(bbl):
    """Parse biblatex-style .bbl (\\entry{key}{type}{} blocks)."""
    if "\\entry{" not in bbl:
        return None, None
    order = []
    entries = {}
    for m in re.finditer(
        r"\\entry\{([^}]+)\}\{([^}]+)\}\{[^}]*\}\s*\n(.*?)\\endentry",
        bbl,
        re.DOTALL,
    ):
        key = m.group(1)
        body = m.group(3)
        order.append(key)
        # Extract fields
        authors = []
        for name_m in re.finditer(r"family=\{([^}]+)\}.*?given=\{([^}]+)\}", body):
            authors.append(f"{name_m.group(2)} {name_m.group(1)}")
        title = ""
        title_m = re.search(r"\\field\{(?:title|booktitle)\}\{([^}]+)\}", body)
        if title_m:
            title = title_m.group(1)
        year = ""
        year_m = re.search(r"\\field\{year\}\{([^}]+)\}", body)
        if year_m:
            year = year_m.group(1)
        venue = ""
        for vf in ("journaltitle", "booktitle"):
            vm = re.search(rf"\\field\{{{vf}\}}\{{([^}}]+)\}}", body)
            if vm:
                venue = vm.group(1)
                break
        parts = []
        if authors:
            parts.append(", ".join(authors))
        if title:
            parts.append(f'"{clean_latex(title)}"')
        if venue:
            parts.append(clean_latex(venue))
        if year:
            parts.append(year)
        entries[key] = ". ".join(parts) + "." if parts else ""
    return (order, entries) if order else (None, None)


def _parse_bbl_plain(bbl):
    """Parse plain-style .bbl (unsrt, plain, ieeetr, abbrv, natbib, etc.)."""
    # Handle both \bibitem{key} and \bibitem[label]{key}
    pattern = (
        r"\\bibitem(?:\[[^\]]*\])?\{([a-zA-Z0-9_:.\-/]+)\}\s*\n"
        r"(.*?)(?=\\bibitem(?:\[|\{)|\s*\\end\{thebibliography\})"
    )
    matches = list(re.finditer(pattern, bbl, re.DOTALL))
    if not matches:
        return None, None
    order = []
    entries = {}
    for m in matches:
        key = m.group(1)
        body = m.group(2).strip()
        order.append(key)
        entries[key] = _clean_bbl_body(body)
    return order, entries


def parse_bbl(bbl_path):
    """Parse .bbl file, auto-detecting format.

    Tries in order: ACM → biblatex → plain.
    Returns: (order, entries) where order=[key,...] and entries={key: text}.
    """
    with open(bbl_path, encoding="utf-8", errors="replace") as f:
        bbl = f.read()

    # Try ACM format first (most specific pattern)
    order, entries = _parse_bbl_acm(bbl)
    if order:
        return order, entries

    # Try biblatex format
    order, entries = _parse_bbl_biblatex(bbl)
    if order:
        return order, entries

    # Fall back to plain format (most universal)
    order, entries = _parse_bbl_plain(bbl)
    if order:
        return order, entries

    return [], {}


# ── Citation Context Extraction ───────────────────────────────

# Matches all common citation commands:
#   standard: \cite
#   natbib:   \citep, \citet, \citealt, \citealp, \citeauthor, \citeyear, \citenum
#   natbib*:  \citep*, \citet*
#   natbib cap: \Citep, \Citet, etc.
#   apacite:  \citeA
#   biblatex: \autocite, \parencite, \textcite, \fullcite, \footcite, \smartcite
_CITE_RE = re.compile(
    r"\\(?:"
    r"[Cc]ite(?:p|t|alt|alp|author|year|num|title|A)?"
    r"|(?:auto|par(?:en)?|text|full|foot|smart)cite"
    r")\*?"
    r"(?:\[[^\]]*\])*"
    r"\{([^}]+)\}"
)


def extract_contexts(tex_files, bib_keys, window=120):
    """Extract citation contexts from .tex files."""
    contexts = {}
    for fpath in tex_files:
        fname = os.path.basename(fpath)
        with open(fpath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for i, line in enumerate(lines, 1):
            if "\\cite" not in line and "cite{" not in line:
                continue
            cited = set()
            for cm in _CITE_RE.finditer(line):
                for k in cm.group(1).split(","):
                    cited.add(k.strip())
            for tk in cited:
                if tk not in bib_keys:
                    continue
                ctx = line.strip()

                def repl(m, _tk=tk):
                    keys = [k.strip() for k in m.group(1).split(",")]
                    if len(keys) == 1 and keys[0] == _tk:
                        return "★THIS★"
                    return ", ".join(
                        "★THIS★" if k == _tk else "" for k in keys
                    )

                ctx = _CITE_RE.sub(repl, ctx)
                for p in [
                    r"\\textbf\{([^}]*)\}",
                    r"\\textit\{([^}]*)\}",
                    r"\\emph\{([^}]*)\}",
                    r"\\[a-zA-Z]+\{([^}]*)\}",
                ]:
                    ctx = re.sub(p, r"\1", ctx)
                ctx = re.sub(r"\\[a-zA-Z]+", "", ctx)
                ctx = re.sub(r"[{}~]", " ", ctx)
                ctx = re.sub(r"\s+", " ", ctx).strip()
                ctx = re.sub(r",\s*,", ",", ctx)
                ctx = re.sub(r",\s*\.", ".", ctx)
                ctx = re.sub(r"\(\s*,", "(", ctx)
                ctx = re.sub(r",\s*\)", ")", ctx)
                idx = ctx.find("★THIS★")
                if idx >= 0:
                    start = max(0, idx - window)
                    end = min(len(ctx), idx + len("★THIS★") + window)
                    snippet = ctx[start:end]
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(ctx):
                        snippet = snippet + "..."
                    ctx = snippet
                elif len(ctx) > 300:
                    ctx = ctx[:300] + "..."
                contexts.setdefault(tk, []).append((fname, i, ctx))
    return contexts


# ── URL Builders ──────────────────────────────────────────────

def build_urls(key, fields):
    """Build quick search URLs for a bib entry."""
    title = clean_latex(fields.get("title", ""))
    enc = title.replace(" ", "+").replace(":", "%3A")
    etype = fields.get("_type", "")
    urls = []
    if etype in ("inproceedings", "article"):
        urls.append(("DBLP", f"https://dblp.org/search?q={enc}"))
    eprint = fields.get("eprint", "")
    if eprint:
        urls.append(("arXiv", f"https://arxiv.org/abs/{eprint}"))
    elif etype == "misc" and not fields.get("howpublished"):
        urls.append(("arXiv", f"https://arxiv.org/search/?query={enc}&searchtype=all"))
    urls.append(("Semantic Scholar", f"https://www.semanticscholar.org/search?q={enc}&sort=relevance"))
    urls.append(("Google Scholar", f"https://scholar.google.com/scholar?q=%22{enc}%22"))
    hp = fields.get("howpublished", "")
    um = re.search(r"\\url\{([^}]+)\}", hp)
    if um:
        urls.append(("Original URL", um.group(1)))
    urls.append(("Google", f"https://www.google.com/search?q={enc}"))
    return urls


def extract_url(fields):
    """Extract URL from bib entry fields."""
    hp = fields.get("howpublished", "")
    um = re.search(r"\\url\{([^}]+)\}", hp)
    if um:
        return um.group(1)
    if fields.get("eprint"):
        return f"https://arxiv.org/abs/{fields['eprint']}"
    if fields.get("doi"):
        return f"https://doi.org/{fields['doi']}"
    if fields.get("url"):
        return clean_latex(fields["url"])
    return ""


# ── File Discovery ────────────────────────────────────────────

def find_files(paper_dir):
    """Auto-detect .bib, .tex, .bbl, and main .tex files."""
    bib_files = []
    tex_files = []
    bbl_files = []
    main_tex = None
    skip_dirs = {".git", "__pycache__", "node_modules", ".tox", "venv", ".venv"}

    for root, dirs, files in os.walk(paper_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip_dirs]
        for f in files:
            fpath = os.path.join(root, f)
            if f.endswith(".bib") and "acmart" not in f:
                bib_files.append(fpath)
            elif f.endswith(".tex") and "bak" not in f.lower():
                tex_files.append(fpath)
                try:
                    with open(fpath, encoding="utf-8", errors="replace") as fh:
                        head = fh.read(2000)
                        if "\\documentclass" in head:
                            main_tex = fpath
                except OSError:
                    pass
            elif f.endswith(".bbl"):
                bbl_files.append(fpath)

    return bib_files, tex_files, bbl_files, main_tex


def extract_paper_title(main_tex):
    """Extract \\title{...} from the main .tex file."""
    if not main_tex:
        return ""
    try:
        with open(main_tex, encoding="utf-8", errors="replace") as f:
            text = f.read()
        m = re.search(r"\\title\s*(?:\[[^\]]*\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}", text)
        if m:
            title = m.group(1).strip()
            title = re.sub(r"\\\\", " ", title)
            title = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", title)
            title = re.sub(r"\\[a-zA-Z]+", "", title)
            title = re.sub(r"[{}]", "", title)
            title = re.sub(r"\s+", " ", title).strip()
            return title
    except OSError:
        pass
    return ""
