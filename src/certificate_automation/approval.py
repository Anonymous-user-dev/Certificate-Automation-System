"""Local workflow approval for a frozen set of certificate inputs.

Display names record operator actions; they do not authenticate identities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping


def _plain(value):
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _immutable(value):
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _immutable(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_immutable(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ApprovalInput:
    project_revision: int
    dataset_revision: int
    dataset_sha256: str
    source_sha256: str
    template_sha256: str
    mapping: Mapping[str, object]
    health_review: Mapping[str, object]
    preview_hashes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    warning_ack_digest: str | None
    outputs: Mapping[str, object]
    print_settings: Mapping[str, object]
    word_available: bool
    converter_identity: str
    locale: str
    recipient_count: int
    excluded_count: int
    output_counts: Mapping[str, int]
    expected_pages: int
    destination: str
    proposed_revision_folder: str
    template_name: str

    def __post_init__(self) -> None:
        for name in ("mapping", "health_review", "outputs", "print_settings", "output_counts"):
            object.__setattr__(self, name, _immutable(getattr(self, name)))
        object.__setattr__(self, "preview_hashes", _immutable(self.preview_hashes))
        object.__setattr__(self, "warning_codes", _immutable(self.warning_codes))

    def payload(self) -> dict[str, object]:
        return {name: _plain(getattr(self, name)) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class ApprovalSnapshot:
    digest: str
    project_revision: int
    recipient_count: int
    output_counts: Mapping[str, int]
    warning_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_counts", _immutable(self.output_counts))
        object.__setattr__(self, "warning_codes", _immutable(self.warning_codes))

    def to_json(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "project_revision": self.project_revision,
            "recipient_count": self.recipient_count,
            "output_counts": dict(self.output_counts),
            "warning_codes": list(self.warning_codes),
        }

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> "ApprovalSnapshot":
        return cls(
            str(value["digest"]), int(value["project_revision"]),
            int(value["recipient_count"]),
            {str(key): int(count) for key, count in dict(value["output_counts"]).items()},
            tuple(str(code) for code in value["warning_codes"]),
        )


@dataclass(frozen=True, slots=True)
class WorkflowApproval:
    snapshot: ApprovalSnapshot
    preparer_name: str
    prepared_at: datetime
    two_person: bool = False
    reviewer_name: str | None = None
    reviewed_at: datetime | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "snapshot": self.snapshot.to_json(),
            "preparer_name": self.preparer_name,
            "prepared_at": self.prepared_at.isoformat(),
            "two_person": self.two_person,
            "reviewer_name": self.reviewer_name,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> "WorkflowApproval":
        return cls(
            ApprovalSnapshot.from_json(value["snapshot"]),
            str(value["preparer_name"]),
            datetime.fromisoformat(str(value["prepared_at"])),
            bool(value.get("two_person", False)),
            str(value["reviewer_name"]) if value.get("reviewer_name") is not None else None,
            datetime.fromisoformat(str(value["reviewed_at"])) if value.get("reviewed_at") else None,
        )


@dataclass(frozen=True, slots=True)
class ApprovalVerification:
    valid: bool
    code: str


class ApprovalService:
    @staticmethod
    def snapshot(inputs: ApprovalInput, *, two_person: bool = False) -> ApprovalSnapshot:
        payload = inputs.payload()
        payload["two_person"] = two_person
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return ApprovalSnapshot(
            sha256(data.encode("utf-8")).hexdigest(), inputs.project_revision,
            inputs.recipient_count, dict(inputs.output_counts), tuple(inputs.warning_codes),
        )

    @staticmethod
    def freeze(inputs: ApprovalInput, preparer_name: str, *, two_person: bool = False) -> WorkflowApproval:
        name = preparer_name.strip()
        if not name:
            raise ValueError("approval.preparer_required")
        return WorkflowApproval(
            ApprovalService.snapshot(inputs, two_person=two_person), name, datetime.now(timezone.utc), two_person
        )

    @staticmethod
    def review(approval: WorkflowApproval, inputs: ApprovalInput, reviewer_name: str) -> WorkflowApproval:
        name = reviewer_name.strip()
        if not name:
            raise ValueError("approval.reviewer_required")
        if not approval.two_person or approval.snapshot != ApprovalService.snapshot(inputs, two_person=True):
            raise ValueError("approval.stale")
        if approval.prepared_at.tzinfo is None or approval.prepared_at.utcoffset() is None:
            raise ValueError("approval.stale")
        if name.casefold() == approval.preparer_name.casefold():
            raise ValueError("approval.distinct_reviewer_required")
        now = datetime.now(timezone.utc)
        if now <= approval.prepared_at:
            now = approval.prepared_at + timedelta(microseconds=1)
        return WorkflowApproval(
            approval.snapshot, approval.preparer_name, approval.prepared_at,
            True, name, now,
        )

    @staticmethod
    def verify(approval: WorkflowApproval | None, inputs: ApprovalInput) -> ApprovalVerification:
        if approval is None:
            return ApprovalVerification(False, "approval.required")
        if approval.snapshot != ApprovalService.snapshot(inputs, two_person=approval.two_person):
            return ApprovalVerification(False, "approval.stale")
        if not approval.preparer_name.strip():
            return ApprovalVerification(False, "approval.preparer_required")
        if approval.prepared_at.tzinfo is None or approval.prepared_at.utcoffset() is None:
            return ApprovalVerification(False, "approval.stale")
        if approval.two_person and (
            not approval.reviewer_name or not approval.reviewer_name.strip()
            or approval.reviewer_name.strip().casefold() == approval.preparer_name.strip().casefold()
            or approval.reviewed_at is None
            or approval.reviewed_at.tzinfo is None
            or approval.reviewed_at.utcoffset() is None
            or approval.reviewed_at <= approval.prepared_at
        ):
            return ApprovalVerification(False, "approval.reviewer_required")
        return ApprovalVerification(True, "approval.valid")
