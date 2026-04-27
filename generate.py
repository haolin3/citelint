#!/usr/bin/env python3
"""
Generate citation audit HTML from a LaTeX paper directory.

Usage:
    python3 generate.py /path/to/paper/directory [--bib paper.bib] [--main main.tex]

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │  parse_bib()       .bib  → field decomposition             │  Template-independent
    │  extract_contexts() .tex → citation contexts               │  Template-independent
    │  run_bibguard()    .bib  → automated checks                │  Template-independent
    │  parse_bbl()       .bbl  → PDF rendered reference text     │  ⚠️ TEMPLATE-SPECIFIC
    │  build_urls()       →  quick search links                  │  Template-independent
    │  generate_html()    →  final HTML output                   │  Template-independent
    └─────────────────────────────────────────────────────────────┘

    To adapt for a different LaTeX template, you only need to
    modify parse_bbl(). Everything else works universally.

Output:
    - citation_audit.html (English)
    - citation_audit_zh.html (Chinese)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from html import escape as esc_html


# ── LaTeX Cleaning ─────────────────────────────────────────────

def clean_latex(s):
    """Convert LaTeX accent commands to Unicode and strip braces."""
    for pat, repl_map in [
        (r"\{\\`([a-zA-Z])\}", {"o":"ò","a":"à","e":"è","u":"ù","i":"ì"}),
        (r"\{\\'([a-zA-Z])\}", {"o":"ó","a":"á","e":"é","u":"ú","i":"í","n":"ń","E":"É"}),
        (r'\{\\"([a-zA-Z])\}', {"o":"ö","a":"ä","e":"ë","u":"ü","O":"Ö","U":"Ü"}),
        (r'\\"([a-zA-Z])',     {"o":"ö","a":"ä","e":"ë","u":"ü","O":"Ö","U":"Ü"}),
        (r"\\'([a-zA-Z])",     {"o":"ó","a":"á","e":"é","u":"ú","i":"í","n":"ń","E":"É"}),
        (r"\\`([a-zA-Z])",     {"o":"ò","a":"à","e":"è","u":"ù","i":"ì"}),
    ]:
        s = re.sub(pat, lambda m, rm=repl_map: rm.get(m.group(1), m.group(0)), s)
    s = re.sub(r'[{}]', '', s)
    return s


def format_authors(raw):
    """Convert 'Last, First and Last, First' to 'First Last / First Last'."""
    raw = clean_latex(raw)
    parts = re.split(r'\s+and\s+', raw)
    names = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if ',' in p:
            segs = p.split(',', 1)
            last = segs[0].strip()
            first = segs[1].strip() if len(segs) > 1 else ''
            names.append(f"{first} {last}" if first else last)
        else:
            names.append(p)
    return ' / '.join(names)


# ── Parsers ────────────────────────────────────────────────────

def parse_bib(bib_path):
    """Parse .bib file into {key: {fields...}}."""
    with open(bib_path) as f:
        bib_raw = f.read()
    entries = {}
    for m in re.finditer(r'@(\w+)\{([^,]+),(.*?)(?=\n@|\Z)', bib_raw, re.DOTALL):
        key = m.group(2).strip()
        body = m.group(3)
        fields = {"_type": m.group(1).strip().lower()}
        for fm in re.finditer(
            r'(\w+)\s*=\s*(?:\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}|(\d+))', body
        ):
            fields[fm.group(1).lower()] = (
                fm.group(2) if fm.group(2) is not None else fm.group(3)
            ).strip()
        entries[key] = fields
    return entries


def parse_bbl(bbl_path):
    """Parse .bbl file into {key: rendered_text} and ordered key list.

    ┌──────────────────────────────────────────────────────────────┐
    │  TEMPLATE-SPECIFIC — this is the only function you need to  │
    │  adapt for a different LaTeX template.                       │
    │                                                              │
    │  Current implementation: ACM (ACM-Reference-Format.bst)      │
    │                                                              │
    │  The .bbl format depends on the .bst style file:             │
    │    ACM     → \bibfield{...} \bibinfo{...} (complex)          │
    │    IEEE    → \bibitem{key} plain text (simple)               │
    │    USENIX  → \bibitem{key} plain text (simple)               │
    │    Springer→ \bibitem{key} plain text (simple)               │
    │                                                              │
    │  For non-ACM templates, you likely just need to:             │
    │    1. Change the regex pattern to match \bibitem{key}        │
    │    2. Remove the ACM-specific cleanup (bibfield, bibinfo)    │
    │    3. Keep the LaTeX accent → Unicode conversion             │
    │                                                              │
    │  Input:  path to .bbl file                                   │
    │  Output: (order, entries)                                    │
    │    order   = [key1, key2, ...] in PDF reference order        │
    │    entries = {key: "rendered plain text as in PDF"}           │
    └──────────────────────────────────────────────────────────────┘
    """
    with open(bbl_path) as f:
        bbl = f.read()
    pattern = (
        r'\\bibitem\[([^\]]*(?:\{[^}]*\}[^\]]*)*)\]%?\s*\n'
        r'\s*\{([a-zA-Z0-9_:.-]+)\}\s*\n'
        r'(.*?)(?=\\bibitem\[|\s*\\end\{thebibliography\})'
    )
    order = []
    entries = {}
    for m in re.finditer(pattern, bbl, re.DOTALL):
        key = m.group(2)
        body = m.group(3).strip()
        order.append(key)
        # Clean LaTeX commands
        clean = body
        clean = re.sub(r'\\bibfield\{[^}]*\}', '', clean)
        clean = re.sub(r'\\bibinfo\{person\}\{([^}]*(?:\{[^}]*\}[^}]*)*)\}', r'\1', clean)
        clean = re.sub(r'\\bibinfo\{(\w+)\}\{([^}]*(?:\{[^}]*\}[^}]*)*)\}', r'\2', clean)
        clean = re.sub(r'\\natexlab\{[^}]*\}', '', clean)
        clean = re.sub(r'\\showarticletitle\s*', '', clean)
        clean = re.sub(r'\\emph\{([^}]*)\}', r'\1', clean)
        clean = re.sub(r'\\newblock\s*', '', clean)
        clean = re.sub(r'\\showDOI\{[^}]*\}', '', clean)
        clean = re.sub(r'\\showURL\s*\{[^}]*\}', '', clean)
        clean = re.sub(r'\\showeprint\s*(?:\[[^\]]*\])?\s*\{[^}]*\}', '', clean)
        clean = re.sub(r'\\url\{([^}]*)\}', r'\1', clean)
        clean = re.sub(r'\\path\|([^|]*)\|', r'\1', clean)
        clean = re.sub(r'et~al\\mbox\{\.\}', 'et al.', clean)
        clean = re.sub(r'\\mbox\{([^}]*)\}', r'\1', clean)
        clean = re.sub(r'et~al\.', 'et al.', clean)
        clean = re.sub(r'~', ' ', clean)
        # LaTeX accents → Unicode BEFORE removing braces
        clean = re.sub(r"\{\\`([a-zA-Z])\}", lambda m: {"o":"ò","a":"à","e":"è","u":"ù","i":"ì"}.get(m.group(1), m.group(0)), clean)
        clean = re.sub(r"\{\\'([a-zA-Z])\}", lambda m: {"o":"ó","a":"á","e":"é","u":"ú","i":"í","n":"ń","E":"É"}.get(m.group(1), m.group(0)), clean)
        clean = re.sub(r'\{\\"([a-zA-Z])\}', lambda m: {"o":"ö","a":"ä","e":"ë","u":"ü","O":"Ö","U":"Ü"}.get(m.group(1), m.group(0)), clean)
        clean = re.sub(r'[{}]', '', clean)
        clean = re.sub(r'\n', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        entries[key] = clean
    return order, entries


def extract_contexts(tex_files, bib_keys, window=120):
    """Extract citation contexts from .tex files, windowed around the target cite."""
    contexts = {}
    for fpath in tex_files:
        fname = os.path.basename(fpath)
        with open(fpath) as f:
            lines = f.readlines()
        for i, line in enumerate(lines, 1):
            if '\\cite{' not in line:
                continue
            cited = set()
            for cm in re.finditer(r'\\cite\{([^}]+)\}', line):
                for k in cm.group(1).split(','):
                    cited.add(k.strip())
            for tk in cited:
                if tk not in bib_keys:
                    continue
                ctx = line.strip()
                # Mark target ref, remove others
                def repl(m, _tk=tk):
                    keys = [k.strip() for k in m.group(1).split(',')]
                    return '★THIS★' if len(keys) == 1 and keys[0] == _tk else ', '.join(
                        '★THIS★' if k == _tk else '' for k in keys
                    )
                ctx = re.sub(r'\\cite\{([^}]+)\}', repl, ctx)
                # Clean LaTeX
                for p in [r'\\textbf\{([^}]*)\}', r'\\textit\{([^}]*)\}',
                          r'\\emph\{([^}]*)\}', r'\\[a-zA-Z]+\{([^}]*)\}']:
                    ctx = re.sub(p, r'\1', ctx)
                ctx = re.sub(r'\\[a-zA-Z]+', '', ctx)
                ctx = re.sub(r'[{}~]', ' ', ctx)
                ctx = re.sub(r'\s+', ' ', ctx).strip()
                # Remove empty commas from cleaned multi-cites
                ctx = re.sub(r',\s*,', ',', ctx)
                ctx = re.sub(r',\s*\.', '.', ctx)
                ctx = re.sub(r'\(\s*,', '(', ctx)
                ctx = re.sub(r',\s*\)', ')', ctx)
                # Window around ★THIS★
                idx = ctx.find('★THIS★')
                if idx >= 0:
                    start = max(0, idx - window)
                    end = min(len(ctx), idx + len('★THIS★') + window)
                    snippet = ctx[start:end]
                    if start > 0:
                        snippet = '...' + snippet
                    if end < len(ctx):
                        snippet = snippet + '...'
                    ctx = snippet
                elif len(ctx) > 300:
                    ctx = ctx[:300] + '...'
                contexts.setdefault(tk, []).append((fname, i, ctx))
    return contexts


def run_bibguard(bib_path, main_tex=None):
    """Run BibGuard and return parsed results."""
    cmd = ["bibguard", bib_path, "--json"]
    if main_tex:
        cmd += ["--tex", main_tex]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        idx = output.find('{')
        if idx >= 0:
            return json.loads(output[idx:])
    except FileNotFoundError:
        print("  ⚠️  bibguard not installed. Run: pip install bibguard")
    except Exception as e:
        print(f"  ⚠️  bibguard error: {e}")
    return None


# ── URL Builders ───────────────────────────────────────────────

def build_urls(key, fields):
    title = clean_latex(fields.get("title", ""))
    enc = title.replace(' ', '+').replace(':', '%3A')
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
    um = re.search(r'\\url\{([^}]+)\}', hp)
    if um:
        urls.append(("Original URL", um.group(1)))
    urls.append(("Google", f"https://www.google.com/search?q={enc}"))
    return urls


def extract_url(fields):
    """Extract URL from bib entry (howpublished, eprint, doi, url)."""
    hp = fields.get("howpublished", "")
    um = re.search(r'\\url\{([^}]+)\}', hp)
    if um:
        return um.group(1)
    if fields.get("eprint"):
        return f"https://arxiv.org/abs/{fields['eprint']}"
    if fields.get("doi"):
        return f"https://doi.org/{fields['doi']}"
    if fields.get("url"):
        return clean_latex(fields["url"])
    return ""


# ── HTML Generator ─────────────────────────────────────────────

def esc(s):
    """HTML escape for display text only, NOT for URLs."""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def generate_html(bib_entries, bbl_order, bbl_entries, contexts, bg_data, orphan_keys, lang="en"):
    """Generate the full HTML string."""
    L = {
        "en": dict(pt="Citation Audit Tool", sub="Generated by citation-audit", refs="references",
            bo="BibGuard ✅", bw="BibGuard ⚠️", bf="BibGuard ❌", orp="Orphans",
            se="Search by key, title, or author...",
            fa="All", ff="Fail", fw="Warn", fk="OK", fo="Orphan",
            pr="PDF RENDERED REFERENCE (what reviewer sees)",
            fd="FIELD DECOMPOSITION", cx="CITATION CONTEXTS",
            vl="QUICK SEARCH", bc="BIBGUARD CHECK",
            ob="ORPHAN", om="⚠️ ORPHAN — not cited", np="(Not in PDF)",
            sr="SEARCH & VERIFY", srb="Search",
            tp="Type", au="Author", ti="Title", ve="Venue", yr="Year", pg="Pages", ci="cite(s)", ur="URL",
            tl="Title", al="Authors", vl2="Venue"),
        "zh": dict(pt="引用审计工具", sub="由 citation-audit 生成", refs="条引用",
            bo="BibGuard ✅", bw="BibGuard ⚠️", bf="BibGuard ❌", orp="孤立条目",
            se="搜索 key、标题或作者...",
            fa="全部", ff="失败", fw="警告", fk="通过", fo="孤立",
            pr="PDF 渲染原文（审稿人实际看到的）",
            fd="字段解构", cx="引用上下文",
            vl="快捷搜索", bc="BIBGUARD 检查结果",
            ob="孤立", om="⚠️ 孤立 — 未被引用", np="（不在 PDF 中）",
            sr="检索验证", srb="检索",
            tp="类型", au="作者", ti="标题", ve="发表场所", yr="年份", pg="页码", ci="处引用", ur="URL",
            tl="标题", al="作者", vl2="发表"),
    }[lang]

    bg_map = {}
    if bg_data:
        bg_map = {r["key"]: r for r in bg_data.get("results", [])}

    stats = {"ok": 0, "warn": 0, "fail": 0}
    for k in bib_entries:
        r = bg_map.get(k)
        if r:
            o = r["overall"]
            if o == "OK": stats["ok"] += 1
            elif o == "WARN": stats["warn"] += 1
            elif o == "FAIL": stats["fail"] += 1

    ordered = list(bbl_order)
    for k in sorted(bib_entries.keys()):
        if k not in ordered:
            ordered.append(k)
    total = len(bib_entries)
    kn = {k: i + 1 for i, k in enumerate(bbl_order)}

    bib_json = {}
    for key, fields in bib_entries.items():
        bib_json[key] = {"title": clean_latex(fields.get("title", "")), "year": fields.get("year", "")}

    cards = []
    for key in ordered:
        if key not in bib_entries:
            continue
        f = bib_entries[key]
        bg_r = bg_map.get(key)
        sc, si = "unknown", "❓"
        if bg_r:
            o = bg_r["overall"]
            if o == "OK": sc, si = "ok", "✅"
            elif o == "WARN": sc, si = "warn", "⚠️"
            elif o == "FAIL": sc, si = "fail", "❌"
        io = key in orphan_keys
        ctxs = contexts.get(key, [])
        bt = bbl_entries.get(key, "")
        pn = kn.get(key)
        ti = clean_latex(f.get("title", "N/A"))
        au = format_authors(f.get("author", "N/A"))
        yr = f.get("year", "N/A")
        ve = clean_latex(f.get("booktitle", "") or f.get("journal", "") or "")
        pg = f.get("pages", "")
        et = f.get("_type", "")
        url_val = extract_url(f)
        if url_val:
            safe_url = url_val.replace("'", "\\'")
            url_display = esc(url_val[:60]) + ("..." if len(url_val) > 60 else "")
            url_cell = f'<a class="vl" onclick="openSide(\'{safe_url}\')" style="padding:2px 8px;font-size:11px">{url_display} ↗</a>'
        else:
            url_cell = '<span class="mi">—</span>'

        ch = ""
        if bg_r:
            for c in bg_r.get("checks", []):
                cs = c.get("status", "")
                ic = "✅" if cs == "OK" else "❌" if cs == "FAIL" else "⚠️"
                ch += f'<div class="ci {cs.lower()}">{ic} <b>{esc(c.get("field", ""))}</b>: {esc(c.get("detail", ""))}</div>'

        urls = build_urls(key, f)
        ub = ""
        for label, url in urls:
            safe_url = url.replace("'", "\\'")
            ub += f'''<a class="vl" onclick="openSide('{safe_url}')">{esc(label)} ↗</a>'''

        cx = ""
        if ctxs:
            for fn, ln, ct in ctxs[:6]:
                ct_h = esc(ct).replace('★THIS★', '<mark class="tr">⟵ THIS REF</mark>')
                cx += f'<div class="cx"><span class="cl">{esc(fn)}:{ln}</span> {ct_h}</div>'
            if len(ctxs) > 6:
                cx += f'<div class="cm">... +{len(ctxs) - 6}</div>'
        else:
            cx = f'<div class="co">{L["om"]}</div>'

        pd = f'[{pn}] {esc(bt)}' if bt else f'<span class="mi">{L["np"]}</span>'
        ob = f' <span class="ob">{L["ob"]}</span>' if io else ''
        pl = f'[{pn}]' if pn else '—'

        cards.append(f'''<div class="rc {sc}" id="r-{key}" data-o="{1 if io else 0}">
<div class="rh" onclick="toggle(this.parentElement)">
<span class="ri">{pl}</span><span class="rs">{si}</span><span class="rk"><code>{key}</code></span>
<span class="rt">{esc(ti[:80])}{"..." if len(ti) > 80 else ""}</span>
<span class="rm">{esc(et)}·{esc(yr)}</span>{ob}
<span class="rn">📌{len(ctxs)}{L["ci"]}</span><span class="ei">▶</span></div>
<div class="rb"><div class="rc2">
<div class="rl">
<div class="sl">📄 {L["pr"]}</div><div class="br">{pd}</div>
<div class="sl">🔍 {L["fd"]}</div>
<table class="ft"><tr><td class="fl">{L["tp"]}</td><td><code>@{esc(et)}</code></td></tr>
<tr><td class="fl">{L["au"]}</td><td>{esc(au)}</td></tr>
<tr><td class="fl">{L["ti"]}</td><td>{esc(ti)}</td></tr>
<tr><td class="fl">{L["ve"]}</td><td>{esc(ve) if ve else '<span class="mi">—</span>'}</td></tr>
<tr><td class="fl">{L["yr"]}</td><td>{esc(yr)}</td></tr>
<tr><td class="fl">{L["pg"]}</td><td>{esc(pg) if pg else '<span class="mi">—</span>'}</td></tr>
<tr><td class="fl">{L["ur"]}</td><td>{url_cell}</td></tr></table>
<div class="sl">📌 {L["cx"]}</div><div class="cxl">{cx}</div></div>
<div class="rr">
<div class="sl">🔗 {L["vl"]}</div><div class="vls">{ub}</div>
<div class="sl">🤖 {L["bc"]}</div><div class="bgc">{ch if ch else '<span class="mi">—</span>'}</div>
<div class="sl">🔍 {L["sr"]}</div>
<div class="sr" id="sr-{key}"><button class="srb" onclick="search('{key}')">{L["srb"]}</button></div>
</div></div></div></div>''')

    return f'''<!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>📋 {L["pt"]}</title>
<style>
:root{{--bg:#0d1117;--sf:#161b22;--bd:#30363d;--tx:#e6edf3;--t2:#8b949e;--t3:#484f58;--ok:#238636;--wn:#d29922;--wnb:#1a1604;--fl:#f85149;--bl:#58a6ff;--pu:#bc8cff}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:var(--bg);color:var(--tx);padding:20px;line-height:1.5}}
.db{{max-width:1200px;margin:0 auto}}h1{{font-size:24px;margin-bottom:8px}}.sb{{color:var(--t2);margin-bottom:20px;font-size:14px}}
.st{{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}}.s{{padding:12px 20px;border-radius:8px;border:1px solid var(--bd);background:var(--sf)}}
.sn{{font-size:28px;font-weight:bold}}.sl2{{font-size:12px;color:var(--t2)}}.so .sn{{color:var(--ok)}}.sw .sn{{color:var(--wn)}}.sf .sn{{color:var(--fl)}}
.fs{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}.fb{{padding:6px 14px;border-radius:6px;border:1px solid var(--bd);background:var(--sf);color:var(--tx);cursor:pointer;font-size:13px}}
.fb:hover{{border-color:var(--bl)}}.fb.a{{background:var(--bl);color:#fff;border-color:var(--bl)}}
.rc{{border:1px solid var(--bd);border-radius:8px;margin-bottom:8px;overflow:hidden;background:var(--sf)}}
.rc.fail{{border-left:3px solid var(--fl)}}.rc.warn{{border-left:3px solid var(--wn)}}.rc.ok{{border-left:3px solid var(--ok)}}
.rh{{display:flex;align-items:center;gap:10px;padding:10px 16px;cursor:pointer;font-size:13px;flex-wrap:wrap}}.rh:hover{{background:rgba(255,255,255,.03)}}
.ri{{color:var(--bl);min-width:30px;font-weight:bold;font-family:monospace}}.rs{{font-size:16px}}.rk{{font-size:12px;color:var(--pu)}}
.rt{{flex:1;min-width:200px;font-weight:500}}.rm,.rn{{color:var(--t2);font-size:11px;white-space:nowrap}}
.ei{{color:var(--t3);transition:transform .2s}}.rc.ex .ei{{transform:rotate(90deg)}}
.ob{{background:var(--wn);color:#000;font-size:10px;padding:1px 6px;border-radius:4px;font-weight:bold}}
.rb{{display:none;padding:16px;border-top:1px solid var(--bd)}}.rc.ex .rb{{display:block}}
.rc2{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}@media(max-width:900px){{.rc2{{grid-template-columns:1fr}}}}
.sl{{font-size:12px;font-weight:600;color:var(--t2);margin:16px 0 6px;text-transform:uppercase;letter-spacing:.5px}}.sl:first-child{{margin-top:0}}
.br{{background:#1c2128;padding:12px;border-radius:6px;font-size:13px;line-height:1.6;border:1px solid var(--bd);color:#d2a8ff}}
.ft{{width:100%;font-size:13px}}.ft td{{padding:3px 8px;border-bottom:1px solid var(--bd);vertical-align:top}}.fl{{color:var(--t2);width:70px;font-weight:500;white-space:nowrap}}.mi{{color:var(--t3);font-style:italic}}
.cxl{{font-size:12px}}.cx{{padding:6px 8px;border-left:2px solid var(--bd);margin-bottom:4px;background:rgba(255,255,255,.02)}}
.cl{{color:var(--bl);font-family:monospace;font-size:11px;display:block;margin-bottom:2px}}
.co{{color:var(--wn);font-weight:500;padding:8px;background:var(--wnb);border-radius:4px}}.cm{{color:var(--t3);font-style:italic;padding:4px 8px}}
mark.tr{{background:#f0883e;color:#000;padding:1px 4px;border-radius:3px;font-weight:bold;font-size:11px}}
.vls{{display:flex;flex-wrap:wrap;gap:6px}}.vl{{display:inline-block;padding:5px 12px;border-radius:6px;border:1px solid var(--bd);color:var(--bl);text-decoration:none;font-size:12px;white-space:nowrap;cursor:pointer}}.vl:hover{{background:rgba(88,166,255,.1);border-color:var(--bl)}}
.bgc{{font-size:12px}}.ci{{padding:4px 0}}.ci.fail{{color:var(--fl)}}.ci.warn{{color:var(--wn)}}.ci.ok{{color:var(--tx)}}
.sr{{font-size:12px}}
.srb{{padding:6px 16px;border-radius:6px;border:1px solid var(--bl);background:rgba(88,166,255,.1);color:var(--bl);cursor:pointer;font-size:13px;font-weight:500}}.srb:hover{{background:rgba(88,166,255,.2)}}
.sr-box{{margin-top:8px}}.sr-src{{font-size:10px;color:var(--t3);text-transform:uppercase;letter-spacing:1px;margin:8px 0 4px;padding-top:8px;border-top:1px solid var(--bd)}}.sr-src:first-child{{border-top:none;padding-top:0}}
.sr-item{{background:#1c2128;padding:8px 10px;border-radius:6px;border:1px solid var(--bd);margin-bottom:4px;position:relative}}
.sr-item .x{{position:absolute;top:4px;right:8px;color:var(--t3);cursor:pointer;font-size:14px}}.sr-item .x:hover{{color:var(--fl)}}
.sr-t{{color:var(--ok);font-weight:bold;font-size:12px;padding-right:20px}}.sr-a{{color:var(--t2);font-size:11px;margin:2px 0}}
.sr-v{{color:var(--pu);font-size:11px}}.sr-ab{{color:var(--t2);font-size:11px;margin-top:4px;line-height:1.4}}
.sr-c{{font-size:10px;margin-bottom:2px}}.sr-c.high{{color:var(--ok)}}.sr-c.med{{color:var(--wn)}}.sr-c.low{{color:var(--fl)}}
.sr-l{{margin-top:4px;display:flex;gap:4px;flex-wrap:wrap}}
.sr-l a{{color:var(--bl);font-size:10px;text-decoration:none;padding:1px 6px;border:1px solid var(--bd);border-radius:3px;cursor:pointer}}.sr-l a:hover{{border-color:var(--bl)}}
.sr-e{{color:var(--fl);font-size:12px;margin-top:4px}}
.sr-lb{{color:var(--t3);font-weight:normal;font-size:10px;margin-right:6px;text-transform:uppercase}}
.hd{{display:none!important}}
.sx{{width:100%;padding:8px 12px;border-radius:6px;border:1px solid var(--bd);background:var(--sf);color:var(--tx);font-size:14px;margin-bottom:12px}}.sx::placeholder{{color:var(--t3)}}
</style></head><body>
<div class="db"><h1>📋 {L["pt"]}</h1>
<div class="sb">{L["sub"]} — {total} {L["refs"]} · <code>localhost:8899</code></div>
<div class="st">
<div class="s so"><div class="sn">{stats["ok"]}</div><div class="sl2">{L["bo"]}</div></div>
<div class="s sw"><div class="sn">{stats["warn"]}</div><div class="sl2">{L["bw"]}</div></div>
<div class="s sf"><div class="sn">{stats["fail"]}</div><div class="sl2">{L["bf"]}</div></div>
<div class="s"><div class="sn">{len(orphan_keys)}</div><div class="sl2">{L["orp"]}</div></div></div>
<input class="sx" id="sq" placeholder="{L["se"]}" oninput="fc()">
<div class="fs">
<button class="fb a" onclick="sf('all',this)">{L["fa"]} ({total})</button>
<button class="fb" onclick="sf('fail',this)">❌ {L["ff"]} ({stats["fail"]})</button>
<button class="fb" onclick="sf('warn',this)">⚠️ {L["fw"]} ({stats["warn"]})</button>
<button class="fb" onclick="sf('ok',this)">✅ {L["fk"]} ({stats["ok"]})</button>
<button class="fb" onclick="sf('orphan',this)">🔕 {L["fo"]} ({len(orphan_keys)})</button></div>
<div id="rl">{"".join(cards)}</div>
</div>
<script>
const B={json.dumps(bib_json, ensure_ascii=False)};
let sw=null;
function toggle(c){{c.classList.toggle('ex');}}
function openSide(url){{
  const w=650,h=window.innerHeight,l=window.screenX+window.outerWidth,t=window.screenY;
  if(sw&&!sw.closed){{sw.location.href=url;sw.focus();}}
  else{{sw=window.open(url,'aside','width='+w+',height='+h+',left='+l+',top='+t+',scrollbars=yes,resizable=yes');}}
}}
function score(bt,at,by,ay){{
  const bw=new Set(bt.toLowerCase().match(/\\w+/g)||[]);
  const aw=new Set(at.toLowerCase().match(/\\w+/g)||[]);
  let s=[...bw].filter(w=>aw.has(w)).length/Math.max(bw.size,aw.size);
  if(by===ay)s+=0.1;return s;
}}
const s2c={{}};
async function search(key){{
  const el=document.getElementById('sr-'+key);
  const d=B[key];if(!d)return;
  el.innerHTML='<span style="color:var(--t2)">⏳ S2 + DBLP...</span>';
  const enc=encodeURIComponent(d.title);
  const [sR,dR]=await Promise.allSettled([
    fetch('/api/s2?query='+enc+'&limit=3&fields=title,authors,year,venue,abstract,tldr,externalIds,url').then(r=>r.json()),
    fetch('/api/dblp?q='+enc+'&format=json&h=3').then(r=>r.json())
  ]);
  let h='<div class="sr-box">';
  h+='<div class="sr-src">Semantic Scholar</div>';
  if(sR.status==='fulfilled'&&!sR.value.error){{
    const papers=sR.value.data||[];
    if(papers.length){{s2c[key]=papers;for(const p of papers){{
      const t=p.title||'',au=(p.authors||[]).map(x=>x.name).join(' / ');
      const sc=score(d.title,t,d.year,String(p.year||'')),pct=(sc*100).toFixed(0);
      const cls=sc>0.85?'high':sc>0.6?'med':'low';const ext=p.externalIds||{{}};
      const tldr=p.tldr?.text||'';const ab=tldr||(p.abstract||'').slice(0,250)+(p.abstract?.length>250?'...':'');
      let lk='';if(p.url)lk+=`<a onclick="openSide('${{p.url}}')">S2 ↗</a>`;
      if(ext.DOI)lk+=`<a onclick="openSide('https://doi.org/${{ext.DOI}}')">DOI ↗</a>`;
      if(ext.ArXiv)lk+=`<a onclick="openSide('https://arxiv.org/abs/${{ext.ArXiv}}')">arXiv ↗</a>`;
      h+=`<div class="sr-item"><span class="x" onclick="this.parentElement.remove()">✕</span>
        <div class="sr-c ${{cls}}">Match: ${{pct}}%</div>
        <div class="sr-t"><span class="sr-lb">{L["tl"]}</span>${{t}}</div>
        <div class="sr-a"><span class="sr-lb">{L["al"]}</span>${{au}}</div>
        <div class="sr-v"><span class="sr-lb">{L["vl2"]}</span>${{p.venue||''}} · ${{p.year||''}}</div>
        ${{ab?'<div class="sr-ab">'+(tldr?'<b>TLDR:</b> ':'')+ab+'</div>':''}}<div class="sr-l">${{lk}}</div></div>`;
    }}}} else h+='<div class="sr-e">No results</div>';
  }} else {{ const err=sR.value?.error||sR.reason||'Error';
    h+=`<div class="sr-e">❌ S2: ${{err}} <a style="color:var(--bl);cursor:pointer;margin-left:8px" onclick="retryS2('${{key}}')">🔄</a></div>`; }}
  h+='<div class="sr-src">DBLP</div>';
  if(dR.status==='fulfilled'&&!dR.value.error){{
    const hits=dR.value.result?.hits?.hit||[];
    if(hits.length){{for(const hi of hits){{
      const i=hi.info||{{}};const t=(i.title||'').replace(/\\.$/,'');
      const aus=i.authors?.author||[];const aL=Array.isArray(aus)?aus:[aus];
      const a=aL.map(x=>x.text||x).join(' / ');
      const sc=score(d.title,t,d.year,i.year||''),pct=(sc*100).toFixed(0);
      const cls=sc>0.85?'high':sc>0.6?'med':'low';
      let lk='';if(i.url)lk+=`<a onclick="openSide('${{i.url}}')">DBLP ↗</a>`;
      if(i.doi)lk+=`<a onclick="openSide('https://doi.org/${{i.doi}}')">DOI ↗</a>`;
      if(i.ee)lk+=`<a onclick="openSide('${{i.ee}}')">Publisher ↗</a>`;
      h+=`<div class="sr-item"><span class="x" onclick="this.parentElement.remove()">✕</span>
        <div class="sr-c ${{cls}}">Match: ${{pct}}%</div>
        <div class="sr-t"><span class="sr-lb">{L["tl"]}</span>${{t}}</div>
        <div class="sr-a"><span class="sr-lb">{L["al"]}</span>${{a}}</div>
        <div class="sr-v"><span class="sr-lb">{L["vl2"]}</span>${{i.venue||''}} · ${{i.year||''}}</div>
        <div class="sr-l">${{lk}}</div></div>`;
    }}}} else h+='<div class="sr-e">No results</div>';
  }} else h+=`<div class="sr-e">❌ DBLP: ${{dR.value?.error||dR.reason||'Error'}}</div>`;
  h+='</div>';el.innerHTML=h;
}}
async function retryS2(key){{
  const el=document.getElementById('sr-'+key);
  const box=el.querySelector('.sr-box');if(!box)return;
  const divs=[...box.children];let s=-1,e=-1;
  for(let i=0;i<divs.length;i++){{if(divs[i].classList.contains('sr-src')&&divs[i].textContent.includes('Semantic')){{s=i;}}if(s>=0&&i>s&&divs[i].classList.contains('sr-src')){{e=i;break;}}}}
  if(s<0)return;if(e<0)e=divs.length;
  for(let i=s+1;i<e;i++)divs[i].remove();
  const ld=document.createElement('div');ld.style.color='var(--t2)';ld.textContent='⏳...';divs[s].after(ld);
  const d=B[key];if(!d)return;
  try{{const r=await fetch('/api/s2?query='+encodeURIComponent(d.title)+'&limit=3&fields=title,authors,year,venue,abstract,tldr,externalIds,url');
    if(!r.ok)throw new Error('HTTP '+r.status);const j=await r.json();if(j.error)throw new Error(j.error);
    const papers=j.data||[];ld.remove();
    if(!papers.length){{const e2=document.createElement('div');e2.className='sr-e';e2.textContent='No results';divs[s].after(e2);return;}}
    s2c[key]=papers;let anchor=divs[s];
    for(const p of papers){{const t=p.title||'',au=(p.authors||[]).map(x=>x.name).join(' / ');
      const sc=score(d.title,t,d.year,String(p.year||'')),pct=(sc*100).toFixed(0),cls=sc>0.85?'high':sc>0.6?'med':'low';
      const ext=p.externalIds||{{}};const tldr=p.tldr?.text||'';const ab=tldr||(p.abstract||'').slice(0,250)+(p.abstract?.length>250?'...':'');
      let lk='';if(p.url)lk+=`<a onclick="openSide('${{p.url}}')">S2 ↗</a>`;
      if(ext.DOI)lk+=`<a onclick="openSide('https://doi.org/${{ext.DOI}}')">DOI ↗</a>`;
      if(ext.ArXiv)lk+=`<a onclick="openSide('https://arxiv.org/abs/${{ext.ArXiv}}')">arXiv ↗</a>`;
      const item=document.createElement('div');item.className='sr-item';
      item.innerHTML=`<span class="x" onclick="this.parentElement.remove()">✕</span>
        <div class="sr-c ${{cls}}">Match: ${{pct}}%</div><div class="sr-t"><span class="sr-lb">{L["tl"]}</span>${{t}}</div>
        <div class="sr-a"><span class="sr-lb">{L["al"]}</span>${{au}}</div><div class="sr-v"><span class="sr-lb">{L["vl2"]}</span>${{p.venue||''}} · ${{p.year||''}}</div>
        ${{ab?'<div class="sr-ab">'+(tldr?'<b>TLDR:</b> ':'')+ab+'</div>':''}}<div class="sr-l">${{lk}}</div>`;
      anchor.after(item);anchor=item;}}
  }}catch(err){{ld.innerHTML='❌ S2: '+err.message+' <a style="color:var(--bl);cursor:pointer" onclick="retryS2(\\''+key+'\\')">🔄</a>';}}
}}
let cf='all';
function sf(f,b){{cf=f;document.querySelectorAll('.fb').forEach(x=>x.classList.remove('a'));b.classList.add('a');fc();}}
function fc(){{const q=document.getElementById('sq').value.toLowerCase();document.querySelectorAll('.rc').forEach(c=>{{
  const t=c.textContent.toLowerCase(),ms=!q||t.includes(q);let mf=true;
  if(cf==='fail')mf=c.classList.contains('fail');else if(cf==='warn')mf=c.classList.contains('warn');
  else if(cf==='ok')mf=c.classList.contains('ok');else if(cf==='orphan')mf=c.dataset.o==='1';
  c.classList.toggle('hd',!(ms&&mf));}});}}
</script></body></html>'''


# ── Main ───────────────────────────────────────────────────────

def find_files(paper_dir):
    """Auto-detect .bib, .tex, .bbl, and main .tex files."""
    bib_files = []
    tex_files = []
    bbl_files = []
    main_tex = None

    for root, dirs, files in os.walk(paper_dir):
        # Skip hidden dirs and common non-source dirs
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('acmart-primary', '__pycache__')]
        for f in files:
            fpath = os.path.join(root, f)
            if f.endswith('.bib') and 'acmart' not in f:
                bib_files.append(fpath)
            elif f.endswith('.tex') and 'bak' not in f.lower():
                tex_files.append(fpath)
                # Detect main tex (has \documentclass)
                try:
                    with open(fpath) as fh:
                        head = fh.read(2000)
                        if '\\documentclass' in head:
                            main_tex = fpath
                except:
                    pass
            elif f.endswith('.bbl'):
                bbl_files.append(fpath)

    return bib_files, tex_files, bbl_files, main_tex


def main():
    parser = argparse.ArgumentParser(description='Generate citation audit HTML.')
    parser.add_argument('paper_dir', help='Path to the paper directory')
    parser.add_argument('--bib', help='Specific .bib file (auto-detected if omitted)')
    parser.add_argument('--main-tex', help='Main .tex file for BibGuard (auto-detected if omitted)')
    args = parser.parse_args()

    paper_dir = os.path.abspath(args.paper_dir)
    if not os.path.isdir(paper_dir):
        print(f"❌ Not a directory: {paper_dir}")
        sys.exit(1)

    print(f"📂 Paper directory: {paper_dir}")

    # Auto-detect files
    bib_files, tex_files, bbl_files, main_tex = find_files(paper_dir)

    bib_path = args.bib or (bib_files[0] if bib_files else None)
    if not bib_path:
        print("❌ No .bib file found.")
        sys.exit(1)
    print(f"📄 BibTeX: {os.path.basename(bib_path)} ({len(open(bib_path).readlines())} lines)")

    main_tex = args.main_tex or main_tex
    if main_tex:
        print(f"📄 Main TeX: {os.path.basename(main_tex)}")

    bbl_path = bbl_files[0] if bbl_files else None
    if bbl_path:
        print(f"📄 BBL: {os.path.basename(bbl_path)}")
    else:
        print("⚠️  No .bbl file found. 'PDF rendered reference' will be empty.")
        print("   Compile with: pdflatex + bibtex + pdflatex + pdflatex")

    print(f"📄 TeX files: {len(tex_files)} files")

    # Step 1: Parse .bib
    print("\n[1/4] Parsing .bib...")
    bib_entries = parse_bib(bib_path)
    print(f"  → {len(bib_entries)} entries")

    # Step 2: Parse .bbl (if available)
    print("[2/4] Parsing .bbl...")
    bbl_order, bbl_entries = [], {}
    if bbl_path:
        bbl_order, bbl_entries = parse_bbl(bbl_path)
        print(f"  → {len(bbl_entries)} rendered references")
    else:
        bbl_order = sorted(bib_entries.keys())
        print("  → skipped (no .bbl)")

    # Step 3: Run BibGuard
    print("[3/4] Running BibGuard...")
    bg_data = run_bibguard(bib_path, main_tex)
    orphan_keys = set()
    if bg_data:
        n_ok = sum(1 for r in bg_data.get("results", []) if r["overall"] == "OK")
        n_warn = sum(1 for r in bg_data.get("results", []) if r["overall"] == "WARN")
        n_fail = sum(1 for r in bg_data.get("results", []) if r["overall"] == "FAIL")
        print(f"  → ✅{n_ok} ⚠️{n_warn} ❌{n_fail}")
        for ti in bg_data.get("tex_issues", []):
            m = re.search(r"Orphan entry: '([^']+)'", ti.get("message", ""))
            if m:
                orphan_keys.add(m.group(1))
    else:
        print("  → skipped")

    # Step 4: Extract citation contexts
    print("[4/4] Extracting citation contexts...")
    contexts = extract_contexts(tex_files, set(bib_entries.keys()))
    cited_keys = len([k for k in bib_entries if k in contexts])
    print(f"  → {cited_keys}/{len(bib_entries)} entries have citation contexts")

    # Generate HTML
    print("\n🔨 Generating HTML...")
    for lang, fn in [("en", "citation_audit.html"), ("zh", "citation_audit_zh.html")]:
        html = generate_html(bib_entries, bbl_order, bbl_entries, contexts, bg_data, orphan_keys, lang)
        out_path = os.path.join(paper_dir, fn)
        with open(out_path, 'w') as f:
            f.write(html)
        print(f"  ✅ {out_path}")

    print(f"\n🎉 Done! Now run:")
    print(f"   ~/Downloads/citation-audit/start.sh {paper_dir}")


if __name__ == "__main__":
    main()
