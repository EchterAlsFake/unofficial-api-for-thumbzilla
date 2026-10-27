# Changelog

## 1.4.3 — 2026-10-27

- Handle playlists with missing optional metadata or fewer statistics fields without crashing.
- Encode search terms correctly, including reserved characters and Unicode.
- Close CLI sessions reliably and report unsuccessful downloads as errors.
- Add regression coverage for playlist metadata and filtered pagination. Live playlist support remains unverified without a public fixture.
- Use the published `eaf-base-api>=4.2.5` dependency.

