# Task 6 report — Frozen final approval

## Inherited implementation evidence (reported by prior agent; not independently observed)

- Approval service: RED because `certificate_automation.approval` was missing; then 19 passed.
- Approval page: RED because the UI module was missing; then 3 passed.
- Workflow: RED because output skipped approval and generation could start without approval; then the approval/domain/page/workspace set passed 80 tests.
- Later workflow round: 84 passed after live output invalidation and two-person binding changes. The reopened-project representative-preview reviewer test was reported GREEN.
- Prior final focused suite: 204 passed.
- Prior non-Word suite: 489 passed, 6 skipped, 4 deselected. Prior diff check was reported clean.

These counts are retained as prior-agent reports, not fresh evidence from this finalization pass.

## Finalization TDD evidence

Found an uncovered case: changing the two-person checkbox after freezing a single-person approval kept the old approval usable. Added `test_changing_two_person_mode_clears_frozen_approval` first.

- RED: focused new test failed as expected (`1 failed`); the failure showed a still-live `WorkflowApproval(..., two_person=False)` after the checkbox changed.
- GREEN: after connecting user mode changes to approval invalidation, the new test passed. The reopened-project two-person reviewer test then exposed a hydration signal regression; programmatic checkbox updates were changed to block signals.
- Final targeted pair: `2 passed` (`test_changing_two_person_mode_clears_frozen_approval` and `test_two_person_freeze_requires_project_reopen_and_survives_disk_roundtrip`).

## Fresh verification

All commands ran in `/home/faridun/projects/certificate_automation/.worktrees/operator-workspace-v2` with `/home/faridun/projects/certificate_automation/.venv/bin/python`.

- Focused approval/page/workspace/project/operator/validation/i18n suite: `228 passed`.
- Full non-Word suite: `491 passed, 6 skipped, 4 deselected`.
- Bare full suite: `491 passed, 10 skipped`.
- `python -m compileall -q src tests`: passed.
- `git diff --check`: passed.

## Self-review

- The approval digest is canonical JSON (sorted keys, compact separators, UTF-8) over project/data/source/template revisions and hashes, mapping, Task 4 layout review and preview hashes, Task 5 warning codes and acknowledgment digest, output options/counts, destination, print settings, locale, Word/converter status, and expected pages.
- The UI inserts approval between output and generation. Generation recomputes validation and approval inputs, checks source/template bytes and current layout/warning state, and calls `ApprovalService.verify` directly before constructing `BatchRequest`.
- Two-person approval persists the freeze, requires reopening, rejects the preparer's case-folded name as reviewer, requires a rendered representative-preview review visit, and persists the explicit reviewer action. Display names are explicitly described as workflow records, not authentication or signatures.
- Output and layout edits, data/template/mapping/duplicate-policy/warning changes, locale changes, stale hashes, and now approval-mode changes clear frozen approval. Programmatic state restoration suppresses mode-change signals so reopening preserves valid approval.
- Read-only mode disables approval controls and generation. Approval text is present in English, Russian, and Simplified Chinese catalogs.

## Limitations

The ten Windows-specific packaged/release/Word acceptance tests are skipped in this Linux run (six require a packaged executable; four require Windows). Native Word and installer acceptance remain pending the Windows release task.
