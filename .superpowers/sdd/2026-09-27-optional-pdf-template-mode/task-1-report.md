# Task 1 report: PDF template domain and project persistence

## Outcome

Implemented immutable PDF layout and inspection models, read-only PDF inspection with blocking and warning classifications, and schema 3 project persistence with schema 1/2 backup migration. Changing the referenced PDF bytes clears its layout and dependent review, mapping, output, acknowledgement, and approval state.

## Review

- The layout validates field names, unique names, page references, geometry, style values, and template digest; its JSON round-trip and digest are deterministic.
- Inspection records page count, media/crop boxes, normalized rotation, and original-byte SHA-256 without modifying the source. Encrypted, unreadable, and zero-page PDFs fail closed.
- Interactive forms, annotations, transparency, embedded-file indicators, and rotation are surfaced as warnings; existing signatures are blocking.
- Project payloads default legacy data to DOCX mode. Schema 1 and 2 migrations validate source and backup copies and produce schema 3 while preserving the existing lease, source-fingerprint, WAL/SHM, and atomic publication protections.
- Reviewed all inherited changes, including workspace tests that assert schema 3 and newer-schema read-only behavior. No spec gap was identified during final review.
- `git diff --check` completed cleanly.

## Test evidence

The prior implementer reported 57 focused tests passing. This is inherited status only: no command output or runner record was available to recover, so it is not treated as independently verified. The original RED run was likewise not recoverable and is not represented as observed evidence.

Commands run personally in the repository's baseline Ubuntu WSL virtual environment with `QT_QPA_PLATFORM=offscreen`:

```text
python -m pytest tests/test_pdf_template.py tests/test_project.py tests/test_project_migration.py -q
62 passed in 1.66s

python -m pytest -m "not word_integration" -q
723 passed, 7 skipped, 4 deselected in 45.07s
```

The first attempt to run migration tests under Windows Python was discarded as platform-invalid: migration tests intentionally exercise Linux SQLite locks and filesystem behavior. The passing results above are from the baseline Linux environment.

## Commit

Commit message: `feat: add versioned PDF template layouts`.
