"""Issue schema — the single currency of the whole tool.

Every rule, every reporter and (later) the run-diff engine speaks in these
objects. Getting this stable early is what lets you add rules, reporters and
a web UI later without rewriting anything.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    ERROR = "error"      # model is wrong / unusable downstream
    WARNING = "warning"  # likely wrong, needs a human decision
    INFO = "info"        # informational, good-practice

    @property
    def rank(self) -> int:
        return {"error": 0, "warning": 1, "info": 2}[self.value]


class Category(str, Enum):
    SCHEMA = "schema"          # L0 - file/schema validity
    INTEGRITY = "integrity"    # L1 - data integrity / sanity
    IDS = "ids"                # L2 - information requirements
    COMPLIANCE = "compliance"  # L3 - custom logic / code rules
    CLASH = "clash"            # L4 - geometry (not in this demo)


@dataclass
class ElementRef:
    """A pointer back to something in the model, rich enough for a report row."""
    guid: Optional[str] = None
    ifc_class: Optional[str] = None
    name: Optional[str] = None
    storey: Optional[str] = None
    source_file: Optional[str] = None

    @classmethod
    def from_entity(cls, entity, storey: Optional[str] = None,
                    source_file: Optional[str] = None) -> "ElementRef":
        return cls(
            guid=getattr(entity, "GlobalId", None),
            ifc_class=entity.is_a(),
            name=getattr(entity, "Name", None),
            storey=storey,
            source_file=source_file,
        )

    def label(self) -> str:
        bits = [self.ifc_class or "?"]
        if self.name:
            bits.append(f"'{self.name}'")
        if self.guid:
            bits.append(f"#{self.guid}")
        return " ".join(bits)


@dataclass
class Issue:
    rule_id: str
    severity: Severity
    category: Category
    title: str
    description: str = ""
    elements: list[ElementRef] = field(default_factory=list)
    location: Optional[tuple[float, float, float]] = None
    evidence: dict[str, Any] = field(default_factory=dict)

    # Filled in by __post_init__ — a stable hash, NOT a random uuid.
    # Same defect in the same element produces the same id on every run, which
    # is what makes "12 new / 30 resolved since last audit" possible later.
    id: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.severity, str):
            self.severity = Severity(self.severity)
        if isinstance(self.category, str):
            self.category = Category(self.category)
        if not self.id:
            self.id = self._stable_id()

    def _stable_id(self) -> str:
        guids = sorted(e.guid or e.label() for e in self.elements)
        seed = "|".join([self.rule_id, *guids, str(self.evidence.get("key", ""))])
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["category"] = self.category.value
        return d


@dataclass
class AuditResult:
    """Everything one run produced. Reporters consume only this."""
    model_path: str
    schema: str
    project_name: Optional[str]
    units: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    rules_run: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for i in self.issues:
            out[i.severity.value] += 1
        return out

    def by_category(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self.issues:
            out[i.category.value] = out.get(i.category.value, 0) + 1
        return out

    def sorted_issues(self) -> list[Issue]:
        return sorted(self.issues, key=lambda i: (i.severity.rank, i.rule_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_path": self.model_path,
            "schema": self.schema,
            "project_name": self.project_name,
            "units": self.units,
            "stats": self.stats,
            "counts": self.counts(),
            "by_category": self.by_category(),
            "rules_run": self.rules_run,
            "duration_s": round(self.duration_s, 3),
            "issues": [i.to_dict() for i in self.sorted_issues()],
        }
