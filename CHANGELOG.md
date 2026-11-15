# 2.0.0

Release 2.0.0

Update pagination handling, validation, and documentation.

Changes since 1.4.3:

```text
README.md             | 24 ++++++++++++-
 pyproject.toml        |  4 +--
 thumbzilla_api/api.py | 98 +++++++++++++++++++++++++++++++++++++++++----------
 3 files changed, 105 insertions(+), 21 deletions(-)
```

# Changelog

## 1.4.3 — 2026-10-27

- Handle playlists with missing optional metadata or fewer statistics fields without crashing.
- Encode search terms correctly, including reserved characters and Unicode.
- Close CLI sessions reliably and report unsuccessful downloads as errors.
- Add regression coverage for playlist metadata and filtered pagination. Live playlist support remains unverified without a public fixture.
- Use the published `eaf-base-api>=4.2.5` dependency.

