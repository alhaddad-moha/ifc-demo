"""ifcaudit — a minimal, working IFC model auditor.

Layers implemented here:
    L0  schema / file validity      -> rules/project.py + ifcopenshell.validate
    L1  data integrity              -> rules/integrity.py
    L2  information requirements    -> rules/ids_runner.py  (IDS via IfcTester)

Not implemented yet (by design):
    L3  custom compliance logic     -> plug in via the @rule decorator
    L4  geometry / clash            -> ifcopenshell.geom.tree
"""

__version__ = "0.1.0"

from .context import AuditContext, load  # noqa: F401
from .engine import REGISTRY, rule, run  # noqa: F401
from .issues import AuditResult, Category, ElementRef, Issue, Severity  # noqa: F401

from . import rules  # noqa: F401  (registers all built-in rules)
