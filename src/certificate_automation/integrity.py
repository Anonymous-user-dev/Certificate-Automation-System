"""Verify the bytes and structure of a published certificate revision."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re

from certificate_automation.audit import pdf_page_fingerprints, pdf_page_geometry, sha256_file
from certificate_automation.approval import ApprovalSnapshot
from certificate_automation.batch_journal import approval_facts_digest
from certificate_automation.verification import pdf_page_count


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    valid: bool
    issues: tuple[str, ...]


def _safe_name(value: object) -> str | None:
    if not isinstance(value, str) or not value or value in (".", ".."):
        return None
    if any(char in value for char in ("/", "\\", ":", "\0")):
        return None
    if Path(value).name != value or value.endswith((" ", ".")):
        return None
    return value


class IntegrityService:
    def verified_artifact(self, revision: Path, kind: str) -> Path | None:
        """Locate a requested artifact only after the whole revision verifies."""
        revision = Path(revision)
        if kind not in {"audit", "combined"} or not self.verify_revision(revision).valid:
            return None
        try:
            manifest = json.loads((revision / "manifest.json").read_text("utf-8"))
            if kind == "audit":
                name = "batch_summary.html"
                if not any(item.get("filename") == name for item in manifest.get("artifacts", [])):
                    return None
            else:
                combined = manifest.get("combined_pdf")
                name = combined.get("filename") if isinstance(combined, dict) else None
            if _safe_name(name) is None:
                return None
            path = revision / name
            return path if path.is_file() and not path.is_symlink() else None
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def verify_revision(
        self, path: Path, *, allow_ready: bool = False,
        approved_snapshot: ApprovalSnapshot | None = None,
        approved_row_ids: tuple[str, ...] | None = None,
    ) -> IntegrityReport:
        folder = Path(path)
        issues: list[str] = []
        try:
            if not folder.is_dir() or folder.is_symlink():
                return IntegrityReport(False, ("integrity.folder_missing",))
            manifest_path = folder / "manifest.json"
            manifest = json.loads(manifest_path.read_text("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("schema_version") != 3:
                return IntegrityReport(False, ("integrity.manifest_invalid",))
            expected: dict[str, tuple[str, int | None, int | None]] = {}
            names: set[str] = {"manifest.json"}

            def add(filename: object, digest: object, size: object, pages: object = None) -> None:
                name = _safe_name(filename)
                if name is None:
                    issues.append("integrity.unsafe_filename")
                    return
                folded = name.casefold()
                if folded in names:
                    issues.append("integrity.duplicate_filename")
                    return
                names.add(folded)
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    issues.append("integrity.invalid_hash")
                    return
                expected[name] = (digest, size, pages)

            outputs = manifest.get("outputs")
            order = manifest.get("ordered_row_ids")
            if not isinstance(outputs, list) or not isinstance(order, list) or (
                [item.get("row_id") for item in outputs if isinstance(item, dict)] != order
            ):
                issues.append("integrity.order_mismatch")
                outputs = []
            for output in outputs:
                for prefix in ("docx", "pdf"):
                    filename = output.get(f"{prefix}_filename")
                    if filename is not None:
                        add(filename, output.get(f"{prefix}_sha256"), output.get(f"{prefix}_size"),
                            output.get("pdf_pages") if prefix == "pdf" else None)
                if output.get("pdf_filename") is not None:
                    try:
                        if output.get("pdf_geometry") != pdf_page_geometry(folder / output["pdf_filename"]):
                            issues.append("integrity.page_geometry_mismatch")
                    except Exception:
                        issues.append("integrity.pdf_invalid")
            combined = manifest.get("combined_pdf")
            counts = manifest.get("counts", {})
            actual_counts = {
                "recipients": len(outputs),
                "docx": sum(item.get("docx_filename") is not None for item in outputs),
                "pdf": sum(item.get("pdf_filename") is not None for item in outputs),
                "combined_pdf": int(combined is not None),
            }
            if any(counts.get(key) != value for key, value in actual_counts.items()):
                issues.append("integrity.count_mismatch")
            if approved_snapshot is not None and (
                manifest.get("approval_digest") != approved_snapshot.digest
                or approved_snapshot.recipient_count != actual_counts["recipients"]
                or any(
                    approved_snapshot.output_counts.get(key) != actual_counts[manifest_key]
                    for key, manifest_key in (("docx", "docx"), ("pdf", "pdf"), ("combined", "combined_pdf"))
                )
            ):
                issues.append("integrity.external_approval_mismatch")
            if approved_row_ids is not None and tuple(order) != approved_row_ids:
                issues.append("integrity.external_approval_mismatch")
            if combined is not None:
                if not isinstance(combined, dict) or combined.get("source_order") != order:
                    issues.append("integrity.combined_order_mismatch")
                else:
                    add(combined.get("filename"), combined.get("sha256"),
                        combined.get("size"), combined.get("page_count"))
                    individual_pages = [item.get("pdf_pages") for item in outputs]
                    separator_positions = combined.get("separator_positions", [])
                    if (
                        not isinstance(separator_positions, list)
                        or any(type(position) is not int or position < 1 for position in separator_positions)
                        or separator_positions != sorted(set(separator_positions))
                    ):
                        issues.append("integrity.combined_pages_mismatch")
                        separator_positions = []
                    if all(isinstance(count, int) for count in individual_pages) and (
                        sum(individual_pages) + len(separator_positions) != combined.get("page_count")
                    ):
                        issues.append("integrity.combined_pages_mismatch")
                    fingerprints = combined.get("page_fingerprints")
                    if not isinstance(fingerprints, list) or len(fingerprints) != combined.get("page_count"):
                        issues.append("integrity.combined_order_mismatch")
                    else:
                        try:
                            if tuple(fingerprints) != pdf_page_fingerprints(folder / combined["filename"]):
                                issues.append("integrity.combined_order_mismatch")
                        except Exception:
                            issues.append("integrity.pdf_invalid")
                    try:
                        if combined.get("page_geometry") != pdf_page_geometry(folder / combined["filename"]):
                            issues.append("integrity.page_geometry_mismatch")
                    except Exception:
                        issues.append("integrity.pdf_invalid")
            for artifact in manifest.get("artifacts", []):
                add(artifact.get("filename"), artifact.get("sha256"), artifact.get("size"))
            journal = folder / "batch_journal.json"
            if not journal.is_file() or journal.is_symlink():
                issues.append("integrity.journal_missing")
            else:
                names.add("batch_journal.json")
                try:
                    record = json.loads(journal.read_text("utf-8"))
                    allowed = {"published", "ready_to_publish"} if allow_ready else {"published"}
                    if (
                        record.get("schema_version") != 1
                        or record.get("batch_id") != manifest.get("journal_id")
                        or record.get("approval_digest") != manifest.get("approval_digest")
                        or record.get("revision") != manifest.get("revision")
                        or record.get("state") not in allowed
                    ):
                        issues.append("integrity.journal_mismatch")
                    if approved_snapshot is not None and record.get("approval_digest") != approved_snapshot.digest:
                        issues.append("integrity.external_approval_mismatch")
                    if approved_row_ids is not None and record.get("approved_row_ids") != list(approved_row_ids):
                        issues.append("integrity.external_approval_mismatch")
                    intended = record.get("intended_counts")
                    approved_rows = record.get("approved_row_ids")
                    if not isinstance(intended, dict) or not isinstance(approved_rows, list):
                        issues.append("integrity.approval_facts_missing")
                    else:
                        expected_counts = {
                            "recipients": actual_counts["recipients"],
                            "docx": actual_counts["docx"],
                            "pdf": actual_counts["pdf"],
                            "combined": actual_counts["combined_pdf"],
                        }
                        if any(intended.get(key) != value for key, value in expected_counts.items()) or approved_rows != order:
                            issues.append("integrity.approval_output_mismatch")
                        if record.get("approval_facts_sha256") != approval_facts_digest(
                            record.get("approval_digest"), intended, approved_rows
                        ):
                            issues.append("integrity.approval_binding_mismatch")
                        workflow = manifest.get("workflow")
                        snapshot = workflow.get("snapshot") if isinstance(workflow, dict) else None
                        approved_counts = snapshot.get("output_counts") if isinstance(snapshot, dict) else None
                        if (
                            not isinstance(approved_counts, dict)
                            or snapshot.get("digest") != record.get("approval_digest")
                            or snapshot.get("recipient_count") != intended.get("recipients")
                            or any(approved_counts.get(key) != intended.get(key) for key in ("docx", "pdf", "combined"))
                        ):
                            issues.append("integrity.approval_output_mismatch")
                except (ValueError, OSError):
                    issues.append("integrity.journal_invalid")
            for name, (digest, size, pages) in expected.items():
                artifact = folder / name
                if not artifact.is_file() or artifact.is_symlink():
                    issues.append("integrity.artifact_missing")
                    continue
                if not isinstance(size, int) or size < 0 or artifact.stat().st_size != size:
                    issues.append("integrity.artifact_size_mismatch")
                if sha256_file(artifact) != digest:
                    issues.append("integrity.artifact_changed")
                if pages is not None:
                    try:
                        if pdf_page_count(artifact) != pages:
                            issues.append("integrity.page_count_mismatch")
                    except Exception:
                        issues.append("integrity.pdf_invalid")
            for item in folder.iterdir():
                actual_names = {"manifest.json", *expected}
                if journal.is_file():
                    actual_names.add("batch_journal.json")
                if item.name not in actual_names:
                    issues.append("integrity.extra_artifact")
                    break
            actual_folded = [item.name.casefold() for item in folder.iterdir()]
            if len(actual_folded) != len(set(actual_folded)):
                issues.append("integrity.duplicate_filename")
            if not allow_ready:
                suffix = re.search(r"-revision-(\d+)$", folder.name, re.IGNORECASE)
                if suffix is None or int(suffix.group(1)) != manifest.get("revision"):
                    issues.append("integrity.revision_mismatch")
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            issues.append("integrity.manifest_invalid")
        return IntegrityReport(not issues, tuple(dict.fromkeys(issues)))

    def clone_for_correction(self, project, revision: Path):
        """Create a new editable project state linked to an unchanged prior revision."""
        report = self.verify_revision(revision)
        if not report.valid:
            raise ValueError("integrity.invalid_revision")
        published = tuple(getattr(project, "published_revisions", ()))
        lineage = published if str(revision) in published else published + (str(revision),)
        return replace(
            project, revision=project.revision + 1, approval=None,
            acknowledgements=(), preview_revision=None, active_step="review",
            published_revisions=lineage,
        )
