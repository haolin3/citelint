"""Local HTTP server with API proxy for Semantic Scholar and DBLP."""

import http.server
import json
import os
import socket
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

_generation = 0
_generation_lock = threading.Lock()

_s2_key = ""
_s2_key_lock = threading.Lock()

# BibGuard progress — updated by CLI background thread, polled by browser
_bibguard = {"status": "idle", "elapsed": 0, "total": 0}
_bibguard_lock = threading.Lock()

# Parsed data — set by CLI before server starts, used for export
_parsed_data = None
_parsed_lock = threading.Lock()

# Reviews file path (relative to paper_dir, resolved after os.chdir)
_REVIEWS_FILE = ".citelint-reviews.json"
_SEARCH_CACHE_FILE = ".citelint-search-cache.json"


def set_bibguard_status(status, elapsed=0, total=0):
    global _bibguard
    with _bibguard_lock:
        _bibguard = {"status": status, "elapsed": elapsed, "total": total}


def set_parsed_data(parsed):
    """Store parsed bib data for use by the export endpoint."""
    global _parsed_data
    with _parsed_lock:
        _parsed_data = parsed


def _read_reviews():
    """Read reviews from disk. Returns dict."""
    if os.path.exists(_REVIEWS_FILE):
        try:
            with open(_REVIEWS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_reviews(reviews):
    """Write reviews dict to disk."""
    with open(_REVIEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)


def _read_search_cache():
    if os.path.exists(_SEARCH_CACHE_FILE):
        try:
            with open(_SEARCH_CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_search_cache(cache):
    with open(_SEARCH_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _persist_s2_key(key):
    """Write S2_API_KEY to ~/.zshrc (or ~/.bashrc) for permanent persistence."""
    import pathlib
    for rc in ["~/.zshrc", "~/.bashrc"]:
        rc_path = pathlib.Path(rc).expanduser()
        if rc_path.exists():
            content = rc_path.read_text(encoding="utf-8")
            # Remove existing S2_API_KEY line if present
            lines = [l for l in content.splitlines() if not l.strip().startswith("export S2_API_KEY=")]
            lines.append(f"export S2_API_KEY={key}")
            rc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    return False


def _generate_export_markdown(reviews):
    """Generate a Markdown export of all reviewed entries."""
    with _parsed_lock:
        parsed = _parsed_data

    if not parsed:
        return "# Citation Review\n\nNo parsed data available for export.\n"

    search_cache = _read_search_cache()

    bib_entries = parsed.get("bib_entries", {})
    bbl_order = parsed.get("bbl_order", [])
    bbl_entries = parsed.get("bbl_entries", {})
    contexts = parsed.get("contexts", {})
    paper_title = parsed.get("paper_title", "")
    bg_data = parsed.get("bg_data")

    bg_map = {}
    if bg_data:
        bg_map = {r["key"]: r for r in bg_data.get("results", [])}

    kn = {k: i + 1 for i, k in enumerate(bbl_order)}
    now = time.strftime("%Y-%m-%d %H:%M")
    total = len(bib_entries)
    n_reviewed = len(reviews)

    review_icons = {"passed": "✅ Passed", "warning": "⚠️ Warning", "error": "❌ Error"}
    bg_icons = {"OK": "✅ OK", "WARN": "⚠️ WARN", "FAIL": "❌ FAIL"}
    bg_check_icons = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}

    def esc_pipe(s):
        return s.replace("|", "\\|") if s else s

    lines = []
    lines.append(f"# Citation Review — {paper_title or 'Untitled'}")
    lines.append("")
    lines.append(f"Reviewed {n_reviewed}/{total} references · {now}")
    lines.append("")

    reviewed_keys = sorted(
        reviews.keys(),
        key=lambda k: (kn.get(k, 9999), k),
    )

    for key in reviewed_keys:
        rev = reviews[key]
        label = rev.get("label", "")
        note = rev.get("note", "")
        rev_time = rev.get("time", "")

        pn = kn.get(key, "—")
        label_display = review_icons.get(label, label)

        lines.append("---")
        lines.append("")
        lines.append(f"## [{pn}] {key} — {label_display}")
        lines.append("")
        if note:
            lines.append(f"**Review:** {note}")
        if rev_time:
            lines.append(f"**Reviewed:** {rev_time}")
        lines.append("")

        f = bib_entries.get(key, {})
        if f:
            from citelint.parser import clean_latex, format_authors, extract_url
            ti = esc_pipe(clean_latex(f.get("title", "N/A")))
            au = esc_pipe(format_authors(f.get("author", "N/A")))
            ve = esc_pipe(clean_latex(f.get("booktitle", "") or f.get("journal", "") or ""))
            yr = f.get("year", "N/A")
            et = f.get("_type", "")
            url_val = extract_url(f)

            lines.append("| Field | Value |")
            lines.append("|-------|-------|")
            lines.append(f"| Type | @{et} |")
            lines.append(f"| Title | {ti} |")
            lines.append(f"| Authors | {au} |")
            lines.append(f"| Venue | {ve or '—'} |")
            lines.append(f"| Year | {yr} |")
            if url_val:
                lines.append(f"| URL | {esc_pipe(url_val)} |")
            lines.append("")

        sc = search_cache.get(key)
        if sc:
            lines.append(f"**Verified match ({sc.get('source', '')} — {sc.get('match', 0)}%):**")
            lines.append(f"> {esc_pipe(sc.get('title', ''))} · {esc_pipe(sc.get('authors', ''))} · {sc.get('venue', '')} {sc.get('year', '')}")
            if sc.get("url"):
                lines.append(f"> {sc['url']}")
            lines.append("")

        bt = bbl_entries.get(key, "")
        if bt:
            lines.append("**PDF rendered reference:**")
            lines.append(f"> {bt}")
            lines.append("")

        bg_r = bg_map.get(key)
        if bg_r:
            overall = bg_r.get("overall", "—")
            lines.append(f"**BibGuard:** {bg_icons.get(overall, overall)}")
            for c in bg_r.get("checks", []):
                cs = c.get("status", "")
                icon = bg_check_icons.get(cs, cs)
                lines.append(f"- {icon} {c.get('field', '')}: {c.get('detail', '')}")
            lines.append("")

        ctxs = contexts.get(key, [])
        if ctxs:
            lines.append("**Cited in:**")
            for fn, ln, ct in ctxs:
                ct_clean = ct.replace("★THIS★", "**THIS REF**")
                lines.append(f"- `{fn}:{ln}` {ct_clean}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by citelint*")
    return "\n".join(lines)


def bump_generation():
    global _generation
    with _generation_lock:
        _generation += 1


def _find_free_port(start):
    for offset in range(100):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


def start_server(paper_dir, html_file, port=8899, open_browser=True):
    global _s2_key
    _s2_key = os.environ.get("S2_API_KEY", "")

    original_dir = os.getcwd()
    os.chdir(paper_dir)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/s2?"):
                q = self.path.split("?", 1)[1]
                with _s2_key_lock:
                    key = _s2_key
                h = {"x-api-key": key} if key else {}
                self._proxy(f"https://api.semanticscholar.org/graph/v1/paper/search?{q}", h)
            elif self.path.startswith("/api/dblp?"):
                q = self.path.split("?", 1)[1]
                self._proxy(f"https://dblp.org/search/publ/api?{q}")
            elif self.path == "/api/reload":
                self._json_response({"generation": _generation})
            elif self.path == "/api/bibguard-status":
                with _bibguard_lock:
                    self._json_response(dict(_bibguard))
            elif self.path == "/api/key-status":
                with _s2_key_lock:
                    key = _s2_key
                self._json_response({"configured": bool(key), "key": key})
            elif self.path == "/api/reviews":
                self._json_response(_read_reviews())
            else:
                super().do_GET()

        def do_POST(self):
            if self.path == "/api/set-key":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode()
                try:
                    data = json.loads(body)
                    new_key = data.get("key", "").strip()
                    global _s2_key
                    with _s2_key_lock:
                        _s2_key = new_key
                    persisted = False
                    if new_key:
                        persisted = _persist_s2_key(new_key)
                    self._json_response({"ok": True, "configured": bool(new_key), "persisted": persisted})
                    if new_key:
                        print(f"  S2 API key set: {new_key}" + (" (saved to ~/.zshrc)" if persisted else ""))
                    else:
                        print("  S2 API key cleared")
                except Exception as e:
                    self._json_response({"ok": False, "error": str(e)})
            elif self.path == "/api/reviews":
                self._handle_review_save()
            elif self.path == "/api/reviews/delete":
                self._handle_review_delete()
            elif self.path == "/api/reviews/clear":
                self._handle_review_clear()
            elif self.path == "/api/reviews/export":
                self._handle_review_export()
            elif self.path == "/api/search-cache":
                self._handle_search_cache_save()
            else:
                self.send_error(404)

        def _read_post_body(self):
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length).decode())

        def _handle_review_save(self):
            try:
                data = self._read_post_body()
                key = data.get("key", "").strip()
                label = data.get("label", "").strip()
                if not key or not label:
                    self._json_response({"ok": False, "error": "key and label required"})
                    return
                reviews = _read_reviews()
                reviews[key] = {
                    "label": label,
                    "note": data.get("note", "").strip(),
                    "time": time.strftime("%Y-%m-%d %H:%M"),
                }
                _write_reviews(reviews)
                self._json_response({"ok": True, "review": reviews[key]})
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)})

        def _handle_review_delete(self):
            try:
                data = self._read_post_body()
                key = data.get("key", "").strip()
                if not key:
                    self._json_response({"ok": False, "error": "key required"})
                    return
                reviews = _read_reviews()
                reviews.pop(key, None)
                _write_reviews(reviews)
                self._json_response({"ok": True})
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)})

        def _handle_review_clear(self):
            try:
                _write_reviews({})
                self._json_response({"ok": True})
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)})

        def _handle_review_export(self):
            try:
                reviews = _read_reviews()
                md = _generate_export_markdown(reviews)
                body = md.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="citelint-review.md"')
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)})

        def _handle_search_cache_save(self):
            try:
                data = self._read_post_body()
                key = data.get("key", "").strip()
                if not key:
                    self._json_response({"ok": False, "error": "missing key"})
                    return
                cache = _read_search_cache()
                cache[key] = {
                    "source": data.get("source", ""),
                    "title": data.get("title", ""),
                    "authors": data.get("authors", ""),
                    "venue": data.get("venue", ""),
                    "year": data.get("year", ""),
                    "url": data.get("url", ""),
                    "match": data.get("match", 0),
                }
                _write_search_cache(cache)
                self._json_response({"ok": True})
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)})

        def _json_response(self, data):
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _proxy(self, url, extra=None):
            try:
                headers = {"User-Agent": "citelint/2.0"}
                if extra:
                    headers.update(extra)
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        def log_message(self, fmt, *a):
            pass

    actual_port = _find_free_port(port)
    if actual_port is None:
        print(f"\n  Error: no free port found (tried {port}-{port + 99})")
        os.chdir(original_dir)
        return
    if actual_port != port:
        print(f"  Port {port} in use, using {actual_port} instead")

    srv = http.server.HTTPServer(("127.0.0.1", actual_port), Handler)

    url = f"http://localhost:{actual_port}/{html_file}"
    print(f"\n  Server running at {url}")
    print(f"  Press Ctrl+C to stop.\n")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        os.chdir(original_dir)
