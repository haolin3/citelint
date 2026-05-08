"""CLI entry point for citelint."""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time

from citelint import __version__
from citelint.html_builder import generate_html
from citelint.parser import (
    extract_contexts,
    extract_paper_title,
    find_files,
    parse_bbl,
    parse_bib,
)
from citelint.server import start_server, bump_generation, set_bibguard_status, set_parsed_data


def _run_bibguard(bib_path, n_entries, main_tex=None):
    """Run BibGuard. Returns parsed JSON data or None."""
    cmd = ["bibguard", bib_path, "--json"]
    if main_tex:
        cmd += ["--tex", main_tex]
    try:
        import shutil
        if not shutil.which("bibguard"):
            print("  BibGuard: not found — skipping. Install with: pip install bibguard")
            return None

        est_seconds = max(30, n_entries * 1.5)
        print(f"  BibGuard: checking {n_entries} entries against online databases...")
        print(f"  (queries DBLP, S2, arXiv, CrossRef — estimated ~{int(est_seconds)}s)")
        sys.stdout.flush()

        stop_spinner = threading.Event()

        set_bibguard_status("running", 0, n_entries)

        def _spinner():
            frames = ["|", "/", "-", "\\"]
            elapsed = 0
            while not stop_spinner.is_set():
                f = frames[elapsed % len(frames)]
                print(f"\r  BibGuard running... {f}  [{elapsed}s]", end="", flush=True)
                set_bibguard_status("running", elapsed, n_entries)
                stop_spinner.wait(1)
                elapsed += 1

        t = threading.Thread(target=_spinner, daemon=True)
        t.start()
        try:
            timeout = max(300, int(n_entries * 3))
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        finally:
            stop_spinner.set()
            t.join()
            print("\r" + " " * 50 + "\r", end="")

        output = result.stdout + result.stderr
        for marker in ['{"results"', '{"']:
            idx = output.find(marker)
            if idx >= 0:
                try:
                    return json.loads(output[idx:])
                except json.JSONDecodeError:
                    continue
        for i, ch in enumerate(output):
            if ch == "{":
                try:
                    return json.loads(output[i:])
                except json.JSONDecodeError:
                    continue
        print("  BibGuard: finished but returned no parseable data")
        set_bibguard_status("failed")
    except subprocess.TimeoutExpired:
        stop_spinner.set()
        print(f"\n  BibGuard: timed out ({timeout}s) — skipping")
        set_bibguard_status("failed")
    except Exception as e:
        print(f"  BibGuard: error — {e}")
        set_bibguard_status("failed")
    return None


def _save_bibguard_cache(path, bg_data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bg_data, f, ensure_ascii=False)


def _parse_common(paper_dir, bib_override=None):
    """Parse bib/bbl/tex — the fast part (no network). Returns a dict of parsed data."""
    bib_files, tex_files, bbl_files, main_tex = find_files(paper_dir)

    bib_path = bib_override or (bib_files[0] if bib_files else None)
    if not bib_path:
        print("  Error: no .bib file found.")
        sys.exit(1)

    bbl_path = bbl_files[0] if bbl_files else None

    print(f"  .bib  {os.path.basename(bib_path)}")
    if main_tex:
        print(f"  .tex  {os.path.basename(main_tex)} (+{len(tex_files) - 1} includes)")
    if bbl_path:
        print(f"  .bbl  {os.path.basename(bbl_path)}")
    else:
        print("  .bbl  not found (PDF rendered reference will be empty)")

    bib_entries = parse_bib(bib_path)
    print(f"  Parsed {len(bib_entries)} bib entries")

    bbl_order, bbl_entries = [], {}
    if bbl_path:
        bbl_order, bbl_entries = parse_bbl(bbl_path)
        print(f"  Parsed {len(bbl_entries)} rendered references")
    else:
        bbl_order = sorted(bib_entries.keys())

    contexts = extract_contexts(tex_files, set(bib_entries.keys()))
    cited = len([k for k in bib_entries if k in contexts])
    print(f"  Citation contexts: {cited}/{len(bib_entries)} entries cited")

    paper_title = extract_paper_title(main_tex)
    if paper_title:
        print(f"  Paper: {paper_title}")

    return dict(
        bib_entries=bib_entries, bbl_order=bbl_order, bbl_entries=bbl_entries,
        contexts=contexts, bib_path=bib_path, main_tex=main_tex,
        paper_title=paper_title,
    )


def _write_html(paper_dir, parsed, bg_data, has_s2_key):
    """Generate and write HTML files. Returns list of paths."""
    orphan_keys = set()
    if bg_data:
        for ti in bg_data.get("tex_issues", []):
            m = re.search(r"Orphan entry: '([^']+)'", ti.get("message", ""))
            if m:
                orphan_keys.add(m.group(1))

    paths = []
    for lang, fn in [("en", "citelint.html"), ("zh", "citelint_zh.html")]:
        html = generate_html(
            parsed["bib_entries"], parsed["bbl_order"], parsed["bbl_entries"],
            parsed["contexts"], bg_data, orphan_keys, lang, has_s2_key,
            parsed.get("paper_title", ""),
        )
        out_path = os.path.join(paper_dir, fn)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        paths.append(out_path)
    return paths


def _get_file_mtimes(paper_dir):
    """Get mtimes of all .bib/.tex/.bbl files for watch mode."""
    mtimes = {}
    for root, dirs, files in os.walk(paper_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith((".bib", ".tex", ".bbl")):
                fpath = os.path.join(root, f)
                try:
                    mtimes[fpath] = os.path.getmtime(fpath)
                except OSError:
                    pass
    return mtimes


def main():
    parser = argparse.ArgumentParser(
        prog="citelint",
        description="Easy, transparent citation linting for LaTeX papers.",
        epilog="Tip: export S2_API_KEY=your-key for Semantic Scholar search.",
    )
    parser.add_argument("paper_dir", nargs="?", default=".",
                        help="paper directory (default: current directory)")
    parser.add_argument("--lang", default="en", choices=["en", "zh"],
                        help="UI language (default: en)")
    parser.add_argument("--port", type=int, default=8899,
                        help="server port (default: 8899)")
    parser.add_argument("--bib", help="specific .bib file (auto-detected if omitted)")
    parser.add_argument("--no-open", action="store_true",
                        help="don't open browser automatically")
    parser.add_argument("--no-server", action="store_true",
                        help="only generate HTML, don't start server")
    parser.add_argument("--regenerate", action="store_true",
                        help="regenerate HTML (skip BibGuard for speed)")
    parser.add_argument("--regenerate-all", action="store_true",
                        help="regenerate HTML + re-run BibGuard")
    parser.add_argument("--watch", action="store_true",
                        help="watch for file changes and auto-regenerate")
    parser.add_argument("--no-bibguard", action="store_true",
                        help="skip BibGuard checks entirely")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    paper_dir = os.path.abspath(args.paper_dir)
    if not os.path.isdir(paper_dir):
        print(f"  Error: not a directory: {paper_dir}")
        sys.exit(1)

    s2_key = os.environ.get("S2_API_KEY", "")
    has_s2_key = bool(s2_key)

    print(f"\n  citelint v{__version__}")
    print(f"  Directory: {paper_dir}")
    if s2_key:
        print(f"  S2 API key: {s2_key}")
    else:
        print()
        print("  ┌─ Semantic Scholar API key not configured ────────────────────┐")
        print("  │                                                              │")
        print("  │  citelint works without it, but the \"Search & Verify\"        │")
        print("  │  feature will be rate-limited (~10 searches per minute).     │")
        print("  │                                                              │")
        print("  │  To get a free key (takes ~1 minute to apply, may take a    │")
        print("  │  few hours to receive):                                      │")
        print("  │                                                              │")
        print("  │    1. Go to: https://www.semanticscholar.org/product/api     │")
        print("  │    2. Click \"Request API Key\" and fill the short form        │")
        print("  │    3. Once you receive the key, run:                         │")
        print("  │                                                              │")
        print("  │       echo 'export S2_API_KEY=your-key' >> ~/.zshrc          │")
        print("  │       source ~/.zshrc                                        │")
        print("  │                                                              │")
        print("  │  You can keep using citelint now — this is not blocking.     │")
        print("  └──────────────────────────────────────────────────────────────┘")
    print()

    # ── Check if generation needed ──
    html_en = os.path.join(paper_dir, "citelint.html")
    html_zh = os.path.join(paper_dir, "citelint_zh.html")
    need_generate = args.regenerate or args.regenerate_all or (not os.path.exists(html_en) and not os.path.exists(html_zh))
    # BibGuard runs on first generation or --regenerate-all, but NOT on --regenerate
    run_bibguard = not args.no_bibguard and (args.regenerate_all or not args.regenerate)

    bg_cache_path = os.path.join(paper_dir, ".citelint-bibguard.json")

    if need_generate:
        # Phase 1: parse everything (fast, no network)
        parsed = _parse_common(paper_dir, args.bib)

        # Phase 2: load cached BibGuard data (if not re-running)
        bg_data = None
        if not run_bibguard and os.path.exists(bg_cache_path):
            try:
                with open(bg_cache_path, encoding="utf-8") as f:
                    bg_data = json.load(f)
                n_r = len(bg_data.get("results", []))
                print(f"  BibGuard: loaded {n_r} cached results (use --regenerate-all to re-run)")
            except (json.JSONDecodeError, OSError):
                bg_data = None

        # Phase 3: generate HTML with whatever BibGuard data we have
        _write_html(paper_dir, parsed, bg_data, has_s2_key)
        print("  Generated: citelint.html, citelint_zh.html")

        parsed["bg_data"] = bg_data
        set_parsed_data(parsed)

        if args.no_server:
            if run_bibguard:
                bg_data = _run_bibguard(parsed["bib_path"], len(parsed["bib_entries"]), parsed["main_tex"])
                if bg_data:
                    _save_bibguard_cache(bg_cache_path, bg_data)
                    n_ok = sum(1 for r in bg_data.get("results", []) if r["overall"] == "OK")
                    n_warn = sum(1 for r in bg_data.get("results", []) if r["overall"] == "WARN")
                    n_fail = sum(1 for r in bg_data.get("results", []) if r["overall"] == "FAIL")
                    print(f"  BibGuard: {n_ok} ok, {n_warn} warn, {n_fail} fail")
                    _write_html(paper_dir, parsed, bg_data, has_s2_key)
                    parsed["bg_data"] = bg_data
                    set_parsed_data(parsed)
                    print("  Regenerated with BibGuard data")
            print(f"\n  Done. Open with: citelint {paper_dir}")
            return
    else:
        parsed = _parse_common(paper_dir, args.bib)
        if os.path.exists(bg_cache_path):
            try:
                with open(bg_cache_path, encoding="utf-8") as f:
                    parsed["bg_data"] = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        set_parsed_data(parsed)
        print("  HTML already exists (use --regenerate to force)")

    # ── Determine HTML file to serve ──
    html_file = "citelint_zh.html" if args.lang == "zh" else "citelint.html"
    if not os.path.exists(os.path.join(paper_dir, html_file)):
        for fb in ["citelint.html", "citelint_zh.html"]:
            if os.path.exists(os.path.join(paper_dir, fb)):
                html_file = fb
                break

    if args.no_server:
        print(f"\n  Done. Open with: citelint {paper_dir}")
        return

    # ── Phase 3: BibGuard in background (runs while user already has the page open) ──
    if need_generate and parsed and run_bibguard:
        def _bibguard_background():
            bg_data = _run_bibguard(parsed["bib_path"], len(parsed["bib_entries"]), parsed["main_tex"])
            if bg_data:
                n_ok = sum(1 for r in bg_data.get("results", []) if r["overall"] == "OK")
                n_warn = sum(1 for r in bg_data.get("results", []) if r["overall"] == "WARN")
                n_fail = sum(1 for r in bg_data.get("results", []) if r["overall"] == "FAIL")
                print(f"  BibGuard: {n_ok} ok, {n_warn} warn, {n_fail} fail")
                set_bibguard_status("done")
                _save_bibguard_cache(bg_cache_path, bg_data)
                _write_html(paper_dir, parsed, bg_data, has_s2_key)
                parsed["bg_data"] = bg_data
                set_parsed_data(parsed)
                bump_generation()
                print("  BibGuard results added — browser will auto-refresh")
            else:
                print("  BibGuard: no results available")

        bg_thread = threading.Thread(target=_bibguard_background, daemon=True)
        bg_thread.start()

    # ── Watch mode ──
    if args.watch:
        last_mtimes = _get_file_mtimes(paper_dir)

        def _watch_loop():
            nonlocal last_mtimes
            while True:
                time.sleep(2)
                current = _get_file_mtimes(paper_dir)
                if current != last_mtimes:
                    changed = [
                        os.path.basename(f)
                        for f in current
                        if current.get(f) != last_mtimes.get(f)
                    ]
                    print(f"\n  File changed: {', '.join(changed[:3])} — regenerating...")
                    try:
                        new_parsed = _parse_common(paper_dir, args.bib)
                        _write_html(paper_dir, new_parsed, None, has_s2_key)
                        bump_generation()
                        print("  Done. Browser will auto-reload.")
                    except Exception as e:
                        print(f"  Regeneration error: {e}")
                    last_mtimes = current

        t = threading.Thread(target=_watch_loop, daemon=True)
        t.start()
        print("  Watch mode: edit .bib/.tex/.bbl → auto-regenerate → browser auto-reloads")

    start_server(paper_dir, html_file, args.port, not args.no_open)


if __name__ == "__main__":
    main()
