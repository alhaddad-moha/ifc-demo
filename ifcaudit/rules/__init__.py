"""Importing this package registers every rule in the engine registry.

To add a ruleset, drop a module here and import it below. Later you can
switch this to entry-point discovery so rulesets ship as separate packages
(ifcaudit-sbc, ifcaudit-acme-bep) without touching the core.
"""

from . import integrity  # noqa: F401
from . import project    # noqa: F401
from . import ids_runner  # noqa: F401
