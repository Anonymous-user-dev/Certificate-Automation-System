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

## Fix round 1: review findings

Addressed all three Important findings:

- Transparency inspection now walks reachable Form XObjects iteratively, resolves indirect resource dictionaries and streams, detects nested `/Group /Transparency` and `/ExtGState`, and tracks visited objects so cycles terminate. The test covers indirect page resources, nested forms, an 80-form chain, and a cyclic self-reference.
- PDF inspection hashes and parses the same immutable byte snapshot by using `PdfReader(BytesIO(snapshot))`. A deterministic path-open probe supplies different PDFs on successive reads and verifies geometry matches the bytes whose digest was recorded.
- `ProjectState.pdf_layout` is now recursively frozen: nested mappings are mapping proxies and JSON arrays are tuples. `to_payload()` still returns ordinary JSON-compatible dictionaries and arrays, and the payload round-trip remains valid.

Test-first evidence (all commands executed in Ubuntu WSL from the worktree with `QT_QPA_PLATFORM=offscreen` and its `.venv`):

RED, before implementation, for the first three regression tests:

```text
cd /home/faridun/projects/certificate_automation/.worktrees/operator-workspace-v2 && QT_QPA_PLATFORM=offscreen /home/faridun/projects/certificate_automation/.venv/bin/python -m pytest tests/test_pdf_template.py::test_transparency_in_nested_indirect_form_xobject_is_reported tests/test_pdf_template.py::test_inspection_hash_and_geometry_come_from_same_byte_snapshot tests/test_project.py::test_pdf_layout_is_deeply_immutable_and_remains_json_serializable -q
FFF                                                                      [100%]
3 failed in 0.76s
```

The failures were the intended behaviors: the transparency issue was absent, geometry came from the replacement PDF despite the original digest, and nested layout mutation did not raise.

RED for the deep-chain/cycle regression, also before implementation:

```text
cd /home/faridun/projects/certificate_automation/.worktrees/operator-workspace-v2 && QT_QPA_PLATFORM=offscreen /home/faridun/projects/certificate_automation/.venv/bin/python -m pytest tests/test_pdf_template.py::test_transparency_scan_handles_deep_form_chains_and_cycles -q
F                                                                        [100%]
1 failed in 0.31s
```

An initial implementation attempt exposed a traversal bug in the new resolver: pypdf `DictionaryObject` also provides `get_object()`, returning itself. Treating every such object as an indirect reference caused dictionaries to be considered cycles. After tracing this to indirect-reference detection, the resolver was narrowed to actual indirect objects. The intermediate targeted run showed `2 failed, 2 passed in 0.52s`; the two remaining failures were the nested and deep transparency cases.

GREEN after the resolver correction:

```text
cd /home/faridun/projects/certificate_automation/.worktrees/operator-workspace-v2 && QT_QPA_PLATFORM=offscreen /home/faridun/projects/certificate_automation/.venv/bin/python -m pytest tests/test_pdf_template.py::test_transparency_in_nested_indirect_form_xobject_is_reported tests/test_pdf_template.py::test_transparency_scan_handles_deep_form_chains_and_cycles tests/test_pdf_template.py::test_inspection_hash_and_geometry_come_from_same_byte_snapshot tests/test_project.py::test_pdf_layout_is_deeply_immutable_and_remains_json_serializable -q
....                                                                     [100%]
4 passed in 0.52s
```

Final verification after all fixes:

```text
cd /home/faridun/projects/certificate_automation/.worktrees/operator-workspace-v2 && QT_QPA_PLATFORM=offscreen /home/faridun/projects/certificate_automation/.venv/bin/python -m pytest tests/test_pdf_template.py tests/test_project.py tests/test_project_migration.py -q
66 passed in 1.37s

cd /home/faridun/projects/certificate_automation/.worktrees/operator-workspace-v2 && QT_QPA_PLATFORM=offscreen /home/faridun/projects/certificate_automation/.venv/bin/python -m pytest -m "not word_integration" -q
727 passed, 7 skipped, 4 deselected in 44.55s
```
