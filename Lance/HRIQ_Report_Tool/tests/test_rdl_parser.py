from pathlib import Path

from Lance.HRIQ_Report_Tool.parser.rdl_parser import parse_rdl


def test_parser_extracts_lightweight_namespace_independent_metadata(tmp_path: Path, sample_rdl: str) -> None:
    source = tmp_path / "Claims" / "PreClaimForm.rdl"
    source.parent.mkdir()
    source.write_text(sample_rdl, encoding="utf-8")

    parsed = parse_rdl(source, tmp_path)

    assert parsed["report_name"] == "PreClaimForm"
    assert parsed["source_path"] == str(Path("Claims") / "PreClaimForm.rdl")
    assert parsed["datasets"][0]["name"] == "Claims"
    assert len(parsed["datasets"][0]["fields"]) == 2
    assert parsed["datasets"][0]["query_parameters"][0]["name"] == "@CompCode"
    assert parsed["report_parameters"][0]["name"] == "CompCode"
    assert parsed["data_sources"][0]["connect_string"] == (
        "Data Source=example;User ID=<redacted>;Password=<redacted>"
    )
    assert parsed["business_logic"]["filters"] == ["=Fields!Amount.Value"]
    assert "raw" not in parsed
