# Contributing

Thanks for your interest in citelint!

## Adding support for a new template

The easiest way to contribute is adding test fixtures for your LaTeX template:

1. Compile a paper using your template to generate a `.bbl` file
2. Add the `.bbl` file to `tests/fixtures/` (name it after the template, e.g., `aaai.bbl`)
3. Add a test class in `tests/test_parser.py` following the existing pattern
4. If parsing fails, the fix is likely in `citelint/parser.py` — the `_parse_bbl_plain()` function handles most templates, and `_clean_bbl_body()` strips LaTeX commands

## Development setup

```bash
git clone https://github.com/haolin3/citelint.git
cd citelint
pip install -e ".[all]"
pip install pytest
pytest tests/ -v
```

## Pull requests

- Keep changes focused — one fix or feature per PR
- Add tests for new functionality
- Run `pytest` before submitting
