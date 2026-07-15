import pytest

from Lance.HRIQ_Report_Tool.query_engine.safety import (
    UnsafeQueryError,
    bind_parameters,
    detect_parameters,
    validate_read_only_sql,
)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM Claims",
        "WITH Recent AS (SELECT * FROM Claims) SELECT * FROM Recent",
        "-- report query\nSELECT 'DROP TABLE is text' AS Note",
    ],
)
def test_read_queries_are_allowed(query: str) -> None:
    assert validate_read_only_sql(query)


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM Claims",
        "SELECT * INTO ClaimsCopy FROM Claims",
        "SELECT * FROM Claims; DROP TABLE Claims",
        "EXEC dbo.ReportProcedure",
    ],
)
def test_mutating_or_multiple_queries_are_blocked(query: str) -> None:
    with pytest.raises(UnsafeQueryError, match="only read-only SQL|one read-only"):
        validate_read_only_sql(query)


def test_parameters_are_detected_and_bound_without_touching_literals() -> None:
    query = "SELECT * FROM Claims WHERE CompCode=@CompCode AND UserID=@UserID AND Note='@CompCode @Ignored'"
    names = detect_parameters(query)
    assert names == ["CompCode", "UserID"]
    prepared = bind_parameters(query, names)
    assert "CompCode=:CompCode" in prepared
    assert "UserID=:UserID" in prepared
    assert "Note='@CompCode @Ignored'" in prepared
