"""Discover and safely remove incomplete diagnostic batch directories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


INCOMPLETE_PREFIX = ".certificate-incomplete-"


@dataclass(frozen=True, slots=True)
class IncompleteBatch:
    batch_id: str
    path: Path
    diagnostic_path: Path


class RecoveryService:
    def find_incomplete(self, destination: Path) -> tuple[IncompleteBatch, ...]:
        destination = Path(destination)
        if not destination.is_dir():
            return ()
        records = []
        for path in sorted(destination.iterdir(), key=lambda item: item.name.casefold()):
            if (
                path.is_dir()
                and not path.is_symlink()
                and path.name.startswith(INCOMPLETE_PREFIX)
            ):
                records.append(
                    IncompleteBatch(
                        path.name[len(INCOMPLETE_PREFIX) :],
                        path,
                        path / "diagnostic.json",
                    )
                )
        return tuple(records)

    def remove(self, record: IncompleteBatch) -> None:
        path = Path(record.path)
        if (
            not path.name.startswith(INCOMPLETE_PREFIX)
            or path.name == INCOMPLETE_PREFIX
            or path.is_symlink()
            or not path.is_dir()
        ):
            raise ValueError("Only an exact incomplete batch directory can be removed.")
        diagnostic = Path(record.diagnostic_path)
        if diagnostic.parent.resolve() != path.resolve():
            raise ValueError("The diagnostic file is outside the incomplete batch directory.")
        shutil.rmtree(path)

