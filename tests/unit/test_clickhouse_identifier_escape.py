"""Tests for the identifier-escaping helpers in clickhouse_manager.

These do not require a running ClickHouse — just validate the module-level
helpers that every DDL/DML splice site in the manager now funnels through.
"""

import pytest

from detectkit.database.clickhouse_manager import _quote_ident, _quote_qualified


class TestQuoteIdent:
    def test_accepts_plain_name(self):
        assert _quote_ident("metrics") == "`metrics`"

    def test_accepts_underscore_and_digits(self):
        assert _quote_ident("_dtk_v2") == "`_dtk_v2`"
        assert _quote_ident("Table123") == "`Table123`"

    @pytest.mark.parametrize(
        "bad",
        [
            "metrics; DROP TABLE x",
            "me trics",
            "me-trics",
            "me.trics",
            "1leading_digit",
            "",
            "`backticked`",
        ],
    )
    def test_rejects_unsafe(self, bad):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _quote_ident(bad)

    def test_rejects_non_string(self):
        with pytest.raises(ValueError):
            _quote_ident(None)  # type: ignore[arg-type]


class TestQuoteQualified:
    def test_quotes_each_part(self):
        assert _quote_qualified("detectk_internal._dtk_tasks") == (
            "`detectk_internal`.`_dtk_tasks`"
        )

    def test_single_part(self):
        assert _quote_qualified("metrics") == "`metrics`"

    def test_strips_preexisting_backticks(self):
        # Callers sometimes pass through already-quoted names; the helper
        # should not double-quote them.
        assert _quote_qualified("`db`.`tbl`") == "`db`.`tbl`"

    def test_rejects_injection(self):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _quote_qualified("db.tbl; DROP TABLE x")
