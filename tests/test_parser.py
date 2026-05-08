"""Tests for citelint.parser — bib, bbl, and citation extraction."""

import os
import tempfile

import pytest

from citelint.parser import (
    _CITE_RE,
    clean_latex,
    extract_contexts,
    format_authors,
    parse_bbl,
    parse_bib,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


# ── clean_latex ───────────────────────────────────────────────

class TestCleanLatex:
    def test_acute(self):
        assert clean_latex(r"caf{\'e}") == "café"

    def test_umlaut(self):
        assert clean_latex(r'M{\"u}ller') == "Müller"

    def test_grave(self):
        assert clean_latex(r"{\`o}") == "ò"

    def test_tilde(self):
        assert clean_latex(r"\~{n}") == "ñ"

    def test_cedilla(self):
        assert clean_latex(r"\c{c}") == "ç"

    def test_caron(self):
        assert clean_latex(r"\v{c}") == "č"

    def test_braces_stripped(self):
        assert clean_latex("{Hello} {World}") == "Hello World"

    def test_plain_passthrough(self):
        assert clean_latex("plain text") == "plain text"


# ── format_authors ────────────────────────────────────────────

class TestFormatAuthors:
    def test_single(self):
        assert format_authors("Doe, John") == "John Doe"

    def test_multiple(self):
        assert format_authors("Doe, John and Smith, Jane") == "John Doe / Jane Smith"

    def test_no_comma(self):
        assert format_authors("John Doe") == "John Doe"


# ── parse_bib ─────────────────────────────────────────────────

class TestParseBib:
    def test_sample_bib(self):
        entries = parse_bib(os.path.join(FIXTURES, "sample.bib"))
        assert len(entries) == 4
        assert "vaswani2017attention" in entries
        assert entries["vaswani2017attention"]["year"] == "2017"
        assert "Attention" in entries["vaswani2017attention"]["title"]
        assert entries["vaswani2017attention"]["_type"] == "inproceedings"

    def test_eprint_field(self):
        entries = parse_bib(os.path.join(FIXTURES, "sample.bib"))
        assert entries["vaswani2017attention"]["eprint"] == "1706.03762"

    def test_doi_field(self):
        entries = parse_bib(os.path.join(FIXTURES, "sample.bib"))
        assert "doi" in entries["brown2020language"]


# ── parse_bbl — all template formats ─────────────────────────

class TestParseBblAcm:
    def test_detects_entries(self):
        order, entries = parse_bbl(os.path.join(FIXTURES, "acm.bbl"))
        assert len(order) == 2
        assert order[0] == "vaswani2017attention"
        assert order[1] == "devlin2019bert"

    def test_cleans_acm_commands(self):
        _, entries = parse_bbl(os.path.join(FIXTURES, "acm.bbl"))
        text = entries["vaswani2017attention"]
        assert "\\bibfield" not in text
        assert "\\bibinfo" not in text
        assert "Attention" in text


class TestParseBblNeurips:
    def test_detects_entries(self):
        order, entries = parse_bbl(os.path.join(FIXTURES, "neurips.bbl"))
        assert len(order) == 2
        assert "vaswani2017attention" in order

    def test_cleans_newblock(self):
        _, entries = parse_bbl(os.path.join(FIXTURES, "neurips.bbl"))
        text = entries["vaswani2017attention"]
        assert "\\newblock" not in text
        assert "Attention" in text


class TestParseBblIeee:
    def test_detects_entries(self):
        order, entries = parse_bbl(os.path.join(FIXTURES, "ieee.bbl"))
        assert len(order) == 2

    def test_content(self):
        _, entries = parse_bbl(os.path.join(FIXTURES, "ieee.bbl"))
        text = entries["vaswani2017attention"]
        assert "Attention" in text


class TestParseBblBiblatex:
    def test_detects_entries(self):
        order, entries = parse_bbl(os.path.join(FIXTURES, "biblatex.bbl"))
        assert len(order) == 2
        assert "vaswani2017attention" in order

    def test_extracts_fields(self):
        _, entries = parse_bbl(os.path.join(FIXTURES, "biblatex.bbl"))
        text = entries["vaswani2017attention"]
        assert "Ashish Vaswani" in text
        assert "Attention" in text
        assert "2017" in text


class TestParseBblEmpty:
    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".bbl", delete=False) as f:
            f.write("\\begin{thebibliography}{}\n\\end{thebibliography}\n")
            f.flush()
            order, entries = parse_bbl(f.name)
            assert order == []
            assert entries == {}
        os.unlink(f.name)


# ── Citation regex ────────────────────────────────────────────

class TestCiteRegex:
    @pytest.mark.parametrize("cmd,expected", [
        (r"\cite{key1}", "key1"),
        (r"\citep{key1}", "key1"),
        (r"\citet{key1}", "key1"),
        (r"\citealt{key1}", "key1"),
        (r"\citealp{key1}", "key1"),
        (r"\citeauthor{key1}", "key1"),
        (r"\citeyear{key1}", "key1"),
        (r"\citenum{key1}", "key1"),
        (r"\Citep{key1}", "key1"),
        (r"\Citet{key1}", "key1"),
        (r"\citep*{key1}", "key1"),
        (r"\citet*{key1}", "key1"),
        (r"\citeA{key1}", "key1"),
        (r"\autocite{key1}", "key1"),
        (r"\parencite{key1}", "key1"),
        (r"\textcite{key1}", "key1"),
        (r"\fullcite{key1}", "key1"),
        (r"\footcite{key1}", "key1"),
        (r"\smartcite{key1}", "key1"),
    ])
    def test_cite_commands(self, cmd, expected):
        m = _CITE_RE.search(cmd)
        assert m is not None, f"Failed to match: {cmd}"
        assert m.group(1) == expected

    def test_multi_keys(self):
        m = _CITE_RE.search(r"\cite{key1, key2, key3}")
        assert m.group(1) == "key1, key2, key3"

    def test_optional_args(self):
        m = _CITE_RE.search(r"\citep[see][p.~5]{key1}")
        assert m is not None
        assert m.group(1) == "key1"

    def test_nocite_not_matched(self):
        m = _CITE_RE.search(r"\nocite{key1}")
        assert m is None


# ── extract_contexts ──────────────────────────────────────────

class TestExtractContexts:
    def test_basic(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tex", delete=False) as f:
            f.write("This is a great paper \\cite{key1} about transformers.\n")
            f.flush()
            contexts = extract_contexts([f.name], {"key1"})
            assert "key1" in contexts
            assert len(contexts["key1"]) == 1
            assert "THIS" in contexts["key1"][0][2]
        os.unlink(f.name)

    def test_natbib(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tex", delete=False) as f:
            f.write("As shown by \\citet{key1}, transformers are powerful.\n")
            f.flush()
            contexts = extract_contexts([f.name], {"key1"})
            assert "key1" in contexts
        os.unlink(f.name)

    def test_biblatex(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tex", delete=False) as f:
            f.write("Recent work \\autocite{key1} demonstrates this.\n")
            f.flush()
            contexts = extract_contexts([f.name], {"key1"})
            assert "key1" in contexts
        os.unlink(f.name)

    def test_unknown_key_ignored(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tex", delete=False) as f:
            f.write("See \\cite{unknown_key} for details.\n")
            f.flush()
            contexts = extract_contexts([f.name], {"key1"})
            assert "unknown_key" not in contexts
        os.unlink(f.name)
