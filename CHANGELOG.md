# Changelog

## 2.0.0 (2025-05-07)

Rebranded from `citation-audit` to `citelint`. Restructured as a proper Python package.

### New features
- **Universal template support**: auto-detects ACM, natbib (NeurIPS/ICML/AAAI), IEEE, Springer LNCS, and biblatex `.bbl` formats
- **Universal citation detection**: handles `\citep`, `\citet`, `\autocite`, `\parencite`, `\textcite`, and all natbib/biblatex variants
- **Watch mode** (`--watch`): auto-regenerate on file changes, browser auto-reloads
- **Auto port selection**: if the default port is busy, automatically finds the next free one
- **BibGuard progress indicator**: shows a spinner with elapsed time instead of freezing silently
- **PyPI distribution**: `pip install citelint`
- Test suite covering all supported template formats
- GitHub Actions CI

### Improvements
- Clearer UI terminology: "Uncited" instead of "Orphan", "Entry Fields" instead of "Field Decomposition"
- Extended LaTeX accent support (tilde, cedilla, caron)
- BibGuard is now a default dependency

## 1.0.0 (2025-04-27)

- Initial release as `citation-audit`
- ACM template support
- BibGuard integration
- Semantic Scholar and DBLP search
- English and Chinese UI
