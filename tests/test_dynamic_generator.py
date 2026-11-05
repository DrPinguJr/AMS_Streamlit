from __future__ import annotations

import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest
from docx import Document
from streamlit.testing.v1 import AppTest

from Contracts.generators import cfs_generator
from Contracts.generators import dynamic_generator as dg
from Contracts.shared.template_lint import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    canonical_key,
    find_leftover_template_text,
    prepare_template,
)


def make_docx(*paragraphs: str | list[str], table_cell: str | None = None) -> bytes:
    """Build a .docx; a list item becomes one paragraph split across several runs."""
    document = Document()
    for paragraph in paragraphs:
        if isinstance(paragraph, list):
            new_paragraph = document.add_paragraph()
            for run_text in paragraph:
                new_paragraph.add_run(run_text)
        else:
            document.add_paragraph(paragraph)
    if table_cell is not None:
        document.add_table(rows=1, cols=1).cell(0, 0).text = table_cell
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def paragraph_texts(docx_bytes: bytes) -> list[str]:
    return [paragraph.text for paragraph in Document(BytesIO(docx_bytes)).paragraphs]


def issue_for(prepared, found_text: str):
    return next(issue for issue in prepared.issues if issue.found_text == found_text)


# --------------------------------------------------------------------------- #
# Template check
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("4D Number", "f_4d_number"),
        ("4d  number", "f_4d_number"),
        ("Contractor Name", "contractor_name"),
        ("contractor_name", "contractor_name"),
        ("E-mail", "e_mail"),
        ("if", "f_if"),
        ("!!", None),
    ],
)
def test_canonical_key(name: str, expected: str | None) -> None:
    assert canonical_key(name) == expected


def test_spelling_variants_and_broken_braces_merge_into_one_field() -> None:
    prepared = prepare_template(make_docx("Your {{4D Number}} and again {4d Number}} here."))

    assert [(f.name, f.label) for f in prepared.fields] == [("f_4d_number", "4D Number")]
    assert issue_for(prepared, "{{4D Number}}").severity == SEVERITY_ERROR
    broken = issue_for(prepared, "{4d Number}}")
    assert broken.severity == SEVERITY_ERROR
    assert "Broken braces" in broken.problem
    assert broken.action == "Repaired to {{ f_4d_number }}"
    assert not prepared.blocking_issues
    merge = next(issue for issue in prepared.issues if issue.severity == SEVERITY_WARNING)
    assert merge.found_text == "4D Number + 4d Number"

    rendered = dg.render_contract_docx(prepared, {"f_4d_number": "1234"})
    assert paragraph_texts(rendered)[0] == "Your 1234 and again 1234 here."


def test_placeholder_split_across_word_runs_is_found_and_repaired() -> None:
    prepared = prepare_template(make_docx(["Dear {{ Contr", "actor Na", "me }},"]))

    assert [f.name for f in prepared.fields] == ["contractor_name"]
    rendered = dg.render_contract_docx(prepared, {"contractor_name": "Jane"})
    assert paragraph_texts(rendered)[0] == "Dear Jane,"


def test_valid_capitalised_name_is_only_info_and_can_be_kept_as_its_own_field() -> None:
    template = make_docx("Hi {{ Name }}, also {{ name }}.", table_cell="{{ Name }}")
    prepared = prepare_template(template)

    name_issue = issue_for(prepared, "{{ Name }}")
    assert name_issue.severity == SEVERITY_INFO
    assert [f.name for f in prepared.fields] == ["name"]

    kept = prepare_template(template, [name_issue.issue_id])
    assert sorted(f.name for f in kept.fields) == ["Name", "name"]
    assert issue_for(kept, "{{ Name }}").kept


def test_unfixable_errors_block_until_kept_and_are_then_printed_literally() -> None:
    template = make_docx("Price {{ fee_amount }} {{ broken and {{ bad| }} {{}}")
    prepared = prepare_template(template)

    blocking = {issue.found_text for issue in prepared.blocking_issues}
    assert {"{{", "{{ bad| }}", "{{}}"} <= blocking

    keep = [issue.issue_id for issue in prepared.issues if issue.can_keep and issue.blocking]
    kept = prepare_template(template, keep)
    assert not kept.blocking_issues
    rendered = dg.render_contract_docx(kept, {"fee_amount": "20.00"})
    assert paragraph_texts(rendered)[0] == "Price 20.00 {{ broken and {{ bad| }} {{}}"


def test_logic_and_expression_tags_are_left_unchanged() -> None:
    prepared = prepare_template(make_docx("{% if paid %}Paid {{ amount|upper }}{% endif %}"))

    assert not prepared.blocking_issues
    assert {f.name for f in prepared.fields} == {"paid", "amount"}
    rendered = dg.render_contract_docx(prepared, {"paid": "yes", "amount": "ten"})
    assert paragraph_texts(rendered)[0] == "Paid TEN"


def test_cfs_template_is_clean() -> None:
    prepared = prepare_template(cfs_generator.CFS_TEMPLATE_PATH.read_bytes())

    assert prepared.issues == ()
    assert [f.name for f in prepared.fields] == [
        "agreement_date",
        "contractor_name",
        "nric",
        "residential_address",
        "start_date",
        "end_date",
        "service_start_time",
        "service_end_time",
        "service_fee",
    ]


def test_leftover_check_catches_single_brace_text_but_allows_kept_literals() -> None:
    docx = make_docx("Hello {name}} and {{ kept }}")
    assert find_leftover_template_text(docx) == ["{name}}", "{{ kept }}"]
    assert find_leftover_template_text(docx, {"{{ kept }}"}) == ["{name}}"]


def test_values_with_xml_characters_render_safely() -> None:
    prepared = prepare_template(make_docx("Address: {{ address }}"))
    rendered = dg.render_contract_docx(prepared, {"address": "Blk 1 & 2 <Unit>"})
    assert paragraph_texts(rendered)[0] == "Address: Blk 1 & 2 <Unit>"


def test_value_containing_braces_fails_that_row_with_the_exact_text() -> None:
    prepared = prepare_template(make_docx("Name: {{ name }}"))
    with pytest.raises(RuntimeError, match=r"'\{oops\}\}'"):
        dg.render_contract_docx(prepared, {"name": "{oops}}"})


# --------------------------------------------------------------------------- #
# Field types and values
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("agreement_date", dg.TYPE_DATE),
        ("service_start_time", dg.TYPE_TIME),
        ("service_fee", dg.TYPE_MONEY),
        ("nric", dg.TYPE_UPPER),
        ("contractor_name", dg.TYPE_TEXT),
        ("f_4d_number", dg.TYPE_TEXT),
        ("update_notes", dg.TYPE_TEXT),
    ],
)
def test_infer_field_type(name: str, expected: str) -> None:
    assert dg.infer_field_type(name) == expected


@pytest.mark.parametrize(
    ("value", "field_type", "expected"),
    [
        ("1/7/2026", dg.TYPE_DATE, "1 July 2026"),
        ("2026-07-01 00:00:00", dg.TYPE_DATE, "1 July 2026"),
        (datetime.date(2026, 6, 30), dg.TYPE_DATE, "30 June 2026"),
        ("14:00", dg.TYPE_TIME, "2:00 p.m."),
        ("2:30 pm", dg.TYPE_TIME, "2:30 p.m."),
        ("9am", dg.TYPE_TIME, "9:00 a.m."),
        ("$1,234.5", dg.TYPE_MONEY, "1,234.50"),
        (20.0, dg.TYPE_MONEY, "20.00"),
        ("  s1234567a ", dg.TYPE_UPPER, "S1234567A"),
    ],
)
def test_format_value(value, field_type: str, expected: str) -> None:
    assert dg.format_value(value, field_type) == expected


def test_bad_values_give_readable_errors() -> None:
    with pytest.raises(ValueError, match="not a date"):
        dg.format_value("next tuesday", dg.TYPE_DATE)
    with pytest.raises(ValueError, match="not an amount"):
        dg.format_value("twenty", dg.TYPE_MONEY)


def cfs_style_settings() -> list[dg.FieldSetting]:
    return [
        dg.FieldSetting("contractor_name", "contractor_name", dg.TYPE_UPPER, shared=False),
        dg.FieldSetting("f_4d_number", "4D Number", dg.TYPE_TEXT, shared=False),
        dg.FieldSetting("start_date", "start_date", dg.TYPE_DATE, shared=False),
        dg.FieldSetting("notes", "notes", dg.TYPE_TEXT, shared=False, required=False),
        dg.FieldSetting("service_fee", "service_fee", dg.TYPE_MONEY, shared=True),
    ]


def test_uploaded_headers_match_fields_forgivingly() -> None:
    upload = pd.DataFrame(
        [{"Contractor Name": "a", "4d number": "1", "Start Date": "1/7/2026", "Extra": "x"}]
    )
    matched, unmatched, missing = dg.match_uploaded_columns(upload, cfs_style_settings())

    assert list(matched.columns) == ["contractor_name", "4D Number", "start_date", "notes"]
    assert matched.iloc[0].tolist() == ["a", "1", "1/7/2026", ""]
    assert unmatched == ["Extra"]
    assert missing == ["notes"]


def test_row_contexts_validate_each_row_independently() -> None:
    settings = cfs_style_settings()
    shared, shared_errors = dg.build_shared_context(settings, {"service_fee": 20})
    rows = pd.DataFrame(
        [
            {"contractor_name": "jane tan", "4D Number": "12", "start_date": "1/7/2026", "notes": ""},
            {"contractor_name": "", "4D Number": "13", "start_date": "someday", "notes": ""},
        ]
    )
    ready, errors = dg.build_row_contexts(rows, settings, shared)

    assert shared_errors == []
    assert len(ready) == 1
    assert ready[0].context == {
        "service_fee": "20.00",
        "contractor_name": "JANE TAN",
        "f_4d_number": "12",
        "start_date": "1 July 2026",
        "notes": "",
    }
    assert errors.iloc[0]["Row Number"] == 2
    assert "Missing contractor_name" in errors.iloc[0]["Issue"]
    assert "not a date" in errors.iloc[0]["Issue"]


def test_shared_required_value_missing_is_reported() -> None:
    _, errors = dg.build_shared_context(cfs_style_settings(), {"service_fee": None})
    assert errors == ["service_fee is required."]


def test_filename_pattern() -> None:
    settings = cfs_style_settings()
    assert dg.default_filename_pattern("AMS - CFS - REB - Template.docx", settings) == (
        "AMS - CFS - REB - {{ contractor_name }}"
    )
    assert dg.validate_filename_pattern("X - {{ 4d Number }}", settings) == []
    assert dg.validate_filename_pattern("X - {{ nope }}", settings)
    assert dg.render_filename(
        "X - {{ 4D Number }} / {{contractor_name}}.pdf",
        {"f_4d_number": "12", "contractor_name": "JANE"},
        settings,
    ) == "X - 12 JANE.pdf"


def test_library_lists_committed_templates() -> None:
    labels = [dg.library_label(path) for path in dg.list_library_templates()]
    assert "CFS/AMS - CFS - REB - Template.docx" in labels
    assert dg.post_processor_for("AMS - CFS - REB - Template.docx") is cfs_generator._apply_cfs_pagination


# --------------------------------------------------------------------------- #
# Bulk generation
# --------------------------------------------------------------------------- #


class ProgressRecorder:
    def __init__(self) -> None:
        self.updates: list[tuple[float, str]] = []

    def progress(self, value: float, text: str) -> None:
        self.updates.append((value, text))


def test_bulk_batch_keeps_successes_after_a_row_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = prepare_template(make_docx("Contract for {{ Full Name }}"))
    settings = [dg.FieldSetting("full_name", "Full Name", dg.TYPE_TEXT, shared=False)]
    rows = [
        dg.RowContext(1, "Same Name", {"full_name": "Same Name"}),
        dg.RowContext(2, "Broken", {"full_name": "{bad}}"}),
        dg.RowContext(3, "Same Name", {"full_name": "Same Name"}),
    ]
    row_directories: list[Path] = []

    def fake_convert(docx_path: Path, output_directory: Path) -> Path:
        assert "Contract for" in paragraph_texts(Path(docx_path).read_bytes())[0]
        row_directories.append(Path(output_directory))
        pdf_path = Path(output_directory) / f"{Path(docx_path).stem}.pdf"
        pdf_path.write_bytes(b"%PDF-fake")
        return pdf_path

    monkeypatch.setattr(dg, "convert_docx_to_pdf", fake_convert)
    progress = ProgressRecorder()

    result = dg.build_dynamic_bulk_batch(prepared, rows, "Contract - {{ Full Name }}", settings, progress)

    assert result.successful_count == 2
    assert [f.row_number for f in result.failures] == [2]
    assert "Leftover template text" in result.failures[0].message
    with ZipFile(BytesIO(result.zip_bytes)) as archive:
        assert archive.namelist() == ["Contract - Same Name.pdf", "Contract - Same Name (2).pdf"]
    assert progress.updates[-1][0] == 1
    assert all(not directory.exists() for directory in row_directories)


def test_cfs_template_renders_identically_through_the_dynamic_engine() -> None:
    """The bulk page must produce the same contract text as the existing CFS page."""
    context = cfs_generator.build_contract_context(
        agreement_date=datetime.date(2026, 7, 1),
        contractor_name="Jane Tan",
        nric="s1234567a",
        residential_address="1 Example Street",
        start_date=datetime.date(2026, 7, 1),
        end_date=datetime.date(2026, 7, 31),
        service_start_time=datetime.time(14, 0),
        service_end_time=datetime.time(17, 0),
        service_fee=20,
    )
    expected = cfs_generator.generate_cfs_docx(context).getvalue()

    prepared = prepare_template(cfs_generator.CFS_TEMPLATE_PATH.read_bytes())
    actual = dg.render_contract_docx(
        prepared, context, dg.post_processor_for(cfs_generator.CFS_TEMPLATE_PATH.name)
    )

    assert paragraph_texts(actual) == paragraph_texts(expected)
    expected_breaks = [p.paragraph_format.page_break_before for p in Document(BytesIO(expected)).paragraphs]
    actual_breaks = [p.paragraph_format.page_break_before for p in Document(BytesIO(actual)).paragraphs]
    assert actual_breaks == expected_breaks


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #


def test_page_loads_every_library_template_without_errors() -> None:
    app = AppTest.from_file("Contracts/pages/Bulk_Template_Generator.py", default_timeout=60).run()
    assert not app.exception

    template_box = app.selectbox(key="dyn_template_choice")
    assert template_box.value == "CFS/AMS - CFS - REB - Template.docx"
    assert app.text_input(key=next(k for k in app.session_state.filtered_state if k.startswith("dyn_filename_"))).value == (
        "AMS - CFS - REB - {{ contractor_name }}"
    )

    for option in template_box.options:
        app.selectbox(key="dyn_template_choice").set_value(option).run()
        assert not app.exception, option
