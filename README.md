# Roaring Kittens 🐱📈

Telegram-native AI investment co-pilot for MOEX.

- Spec: `docs/superpowers/specs/2026-06-04-roaring-kittens-design.md`
- Plan: `docs/superpowers/plans/2026-06-12-phase-0-1-foundation-analyst.md`

## Dev

Tests run in GitHub Actions CI (Python 3.12 + Postgres service container).
Locally (optional):

```
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest
```
