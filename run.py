#!/usr/bin/env python3
"""
Citation Audit Tool — one command, zero config.

Usage:
    cd /path/to/your/paper
    python3 ~/Downloads/citation-audit/run.py

    # Or with options:
    python3 ~/Downloads/citation-audit/run.py --lang en --port 8899

Prerequisites:
    pip install bibguard
    export S2_API_KEY=your-key   # optional but recommended

That's it. Auto-detects .bib/.tex/.bbl, generates HTML, starts server, opens browser.
"""

import argparse
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import urllib.request
import webbrowser

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    parser = argparse.ArgumentParser(
        description="Generate citation audit HTML, start server, open browser.",
        epilog="Tip: export S2_API_KEY=your-key for Semantic Scholar access.",
    )
    parser.add_argument("paper_dir", nargs="?", default=".",
                        help="Paper directory (default: current directory)")
    parser.add_argument("--lang", default="zh", choices=["zh", "en"],
                        help="Output language (default: zh)")
    parser.add_argument("--port", type=int, default=8899,
                        help="Server port (default: 8899)")
    parser.add_argument("--bib", help="Specific .bib file (auto-detected if omitted)")
    parser.add_argument("--no-open", action="store_true",
                        help="Don't open browser automatically")
    parser.add_argument("--regenerate", action="store_true",
                        help="Force regenerate HTML even if it already exists")
    parser.add_argument("--generate-only", action="store_true",
                        help="Only generate HTML, don't start server")
    args = parser.parse_args()

    paper_dir = os.path.abspath(args.paper_dir)
    if not os.path.isdir(paper_dir):
        print(f"❌ Not a directory: {paper_dir}")
        sys.exit(1)

    s2_key = os.environ.get("S2_API_KEY", "")

    # ── Step 1: Generate (skip if HTML already exists) ──────────
    print(f"📂 {paper_dir}")
    if s2_key:
        print(f"🔑 S2 key: {s2_key[:8]}...")
    else:
        print("🔑 S2 key: not set (export S2_API_KEY=your-key)")

    html_en = os.path.join(paper_dir, "citation_audit.html")
    html_zh = os.path.join(paper_dir, "citation_audit_zh.html")
    need_generate = args.regenerate or (not os.path.exists(html_en) and not os.path.exists(html_zh))

    if need_generate:
        gen_cmd = [sys.executable, os.path.join(TOOL_DIR, "generate.py"), paper_dir]
        if args.bib:
            gen_cmd += ["--bib", args.bib]
        result = subprocess.run(gen_cmd)
        if result.returncode != 0:
            sys.exit(1)
    else:
        print("✅ HTML already exists, skipping generation. (use --regenerate to force)")

    html_file = "citation_audit_zh.html" if args.lang == "zh" else "citation_audit.html"
    if not os.path.exists(os.path.join(paper_dir, html_file)):
        # Fallback
        for fb in ["citation_audit_zh.html", "citation_audit.html"]:
            if os.path.exists(os.path.join(paper_dir, fb)):
                html_file = fb
                break

    if args.generate_only:
        print(f"\n✅ HTML generated. Open with:")
        print(f"   python3 {os.path.join(TOOL_DIR, 'run.py')} {paper_dir}")
        return

    # ── Step 2: Start server ───────────────────────────────────
    os.chdir(paper_dir)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/s2?"):
                q = self.path.split("?", 1)[1]
                h = {"x-api-key": s2_key} if s2_key else {}
                self._proxy(f"https://api.semanticscholar.org/graph/v1/paper/search?{q}", h)
            elif self.path.startswith("/api/dblp?"):
                q = self.path.split("?", 1)[1]
                self._proxy(f"https://dblp.org/search/publ/api?{q}")
            else:
                super().do_GET()

        def _proxy(self, url, extra=None):
            try:
                headers = {"User-Agent": "CitationAudit/1.0"}
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
            pass  # Silent

    srv = http.server.HTTPServer(("127.0.0.1", args.port), Handler)
    srv.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    url = f"http://localhost:{args.port}/{html_file}"
    print(f"\n🚀 http://localhost:{args.port}/{html_file}")
    print(f"   Ctrl+C to stop.\n")

    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Stopped.")


if __name__ == "__main__":
    main()
