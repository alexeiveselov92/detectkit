"""Public surface of the internal-tables package.

Importers should always go through :class:`InternalTablesManager`; the
underlying mixins are implementation details and may be reorganised
without notice.
"""

from detectkit.database.internal_tables.manager import InternalTablesManager

__all__ = ["InternalTablesManager"]
