from io import BytesIO
from zipfile import ZipFile

from docx import Document

from Contracts.generators.cfs_generator import BLANK_CFS_CONTEXT, generate_blank_cfs_docx


def test_blank_cfs_form_has_writing_lines_and_no_template_markers() -> None:
    output = generate_blank_cfs_docx().getvalue()

    with ZipFile(BytesIO(output)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "{{" not in document_xml
    assert "{%" not in document_xml

    document = Document(BytesIO(output))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    for writing_line in BLANK_CFS_CONTEXT.values():
        assert writing_line in text

    assert "Name: ________________________________________" in text
    assert "Date: ____________________" in text
