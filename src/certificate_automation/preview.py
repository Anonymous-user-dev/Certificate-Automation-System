"""Verified, revision-scoped certificate previews stored only in temporary space."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile

from certificate_automation.dataset import TabularDataset
from certificate_automation.mapping import MappingPlan, evaluate_plan
from certificate_automation.template import TemplateInspection, render_template
from certificate_automation.verification import verify_docx, verify_pdf


@dataclass(frozen=True, slots=True)
class PreviewRecord:
    row_id: str
    dataset_revision: int
    template_sha256: str
    pdf_path: Path


class PreviewService:
    """Generate and cache one verified PDF preview for the current revision."""

    def __init__(self, converter, root: Path | None = None) -> None:
        self._converter = converter
        self._root = Path(root or Path(tempfile.gettempdir()) / "certificate-automation-previews")
        self._revision: int | None = None
        self._records: dict[str, PreviewRecord] = {}

    def generate(
        self,
        dataset: TabularDataset,
        row_id: str,
        template: TemplateInspection,
        plan: MappingPlan,
    ) -> PreviewRecord:
        dataset.row(row_id)
        if self._revision != dataset.revision:
            self.clear()
            self._revision = dataset.revision
        key = self._cache_key(dataset, row_id, template, plan)
        cached = self._records.get(key)
        if cached is not None and cached.pdf_path.is_file():
            return cached
        self._root.mkdir(parents=True, exist_ok=True)
        docx_path = self._root / f"{key}.docx"
        pdf_path = self._root / f"{key}.pdf"
        render_template(template.path, docx_path, evaluate_plan(plan, dataset, row_id))
        verify_docx(docx_path, set(template.names))
        self._converter.convert(docx_path, pdf_path)
        verify_pdf(pdf_path)
        record = PreviewRecord(row_id, dataset.revision, template.sha256, pdf_path)
        self._records[key] = record
        return record

    def clear(self) -> None:
        if self._root.exists():
            shutil.rmtree(self._root)
        self._records.clear()

    @staticmethod
    def _cache_key(
        dataset: TabularDataset,
        row_id: str,
        template: TemplateInspection,
        plan: MappingPlan,
    ) -> str:
        payload = json.dumps(
            {
                "revision": dataset.revision,
                "row_id": row_id,
                "template": template.sha256,
                "plan": plan.to_json(),
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(payload).hexdigest()
