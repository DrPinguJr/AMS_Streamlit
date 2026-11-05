"""Template check for hand-written ``{{ placeholder }}`` Word templates.

Templates typed by hand are messy: ``{{4D Number}}`` (spaces / leading digit are
not valid Jinja names), ``{4d Number}}`` (broken braces, which Jinja would print
as literal text in every contract), or the same field spelled two ways.

``prepare_template`` scans every paragraph of the document body, tables, text
boxes, headers, footers, footnotes and endnotes (with Word's split runs joined
back together), reports each problem as a ``TemplateIssue``, and returns an
in-memory cleaned copy of the template containing only valid ``{{ name }}``
tags. The original file is never modified.
"""

from __future__ import annotations

import re
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field
from io import BytesIO
from typing import Iterable

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W_P = f"{{{W_NS}}}p"
W_T = f"{{{W_NS}}}t"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

TEXT_PART_PATTERN = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
BRACE_GROUP = re.compile(r"\{+[^{}]*\}+")
STRAY_BRACES = re.compile(r"\{+|\}+")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Characters that mean the tag is a Jinja expression (filters, calls, maths,
# attribute access, strings) rather than a plain field name.
EXPRESSION_CHARS = re.compile(r"[|()\[\]'\".+*/=<>,~!%]")
JINJA_RESERVED = frozenset(
    {
        "and", "or", "not", "in", "is", "if", "else", "elif", "endif", "for",
        "endfor", "true", "false", "none", "True", "False", "None", "loop",
        "block", "macro", "set", "with", "import", "include", "raw",
    }
)

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
SEVERITY_ORDER = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}
SEVERITY_LABELS = {
    SEVERITY_ERROR: "🔴 Error",
    SEVERITY_WARNING: "🟡 Warning",
    SEVERITY_INFO: "🔵 Info",
}


@dataclass(frozen=True)
class TemplateIssue:
    """One thing the template check wants the user to see."""

    issue_id: str
    number: int
    severity: str
    found_text: str
    location: str
    context: str
    problem: str
    action: str
    can_keep: bool
    kept: bool = False
    blocking: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "#": self.number,
            "Severity": SEVERITY_LABELS.get(self.severity, self.severity),
            "Found text": self.found_text,
            "Problem": self.problem,
            "Where": self.location,
            "Nearby text": self.context,
            "What happens": self.action,
            "Kept as written": "Yes" if self.kept else "",
        }


@dataclass(frozen=True)
class TemplateField:
    """A field the cleaned template expects, with how it was spelled."""

    name: str
    label: str
    spellings: tuple[str, ...]


@dataclass(frozen=True)
class PreparedTemplate:
    """Result of checking and cleaning a template."""

    cleaned_bytes: bytes
    fields: tuple[TemplateField, ...]
    issues: tuple[TemplateIssue, ...]
    literal_texts: frozenset[str] = field(default_factory=frozenset)

    @property
    def blocking_issues(self) -> tuple[TemplateIssue, ...]:
        return tuple(issue for issue in self.issues if issue.blocking)

    def count(self, severity: str) -> int:
        return sum(1 for issue in self.issues if issue.severity == severity)


def canonical_key(name: str) -> str | None:
    """Turn any spelling into one safe Jinja name: ``4D Number`` -> ``f_4d_number``."""
    key = re.sub(r"[^0-9a-z]+", "_", str(name).strip().lower()).strip("_")
    if not key:
        return None
    if key[0].isdigit() or key in JINJA_RESERVED:
        key = f"f_{key}"
    return key


def is_valid_identifier(name: str) -> bool:
    return bool(IDENTIFIER.match(name)) and name not in JINJA_RESERVED


def literal_jinja(text: str) -> str:
    """Wrap text so Jinja prints it exactly as written."""
    return "{% raw %}" + text + "{% endraw %}"


# --------------------------------------------------------------------------- #
# XML helpers
# --------------------------------------------------------------------------- #


def _paragraph_text_nodes(paragraph) -> list:
    """Return the ``w:t`` nodes that belong to this paragraph (not nested text boxes)."""
    nodes = []
    for node in paragraph.iter(W_T):
        owner = node.getparent()
        while owner is not None and owner.tag != W_P:
            owner = owner.getparent()
        if owner is paragraph:
            nodes.append(node)
    return nodes


def _part_label(part_name: str) -> str:
    stem = part_name.rsplit("/", 1)[-1].removesuffix(".xml")
    if stem == "document":
        return "Body"
    if stem.startswith("header"):
        return f"Header ({stem})"
    if stem.startswith("footer"):
        return f"Footer ({stem})"
    return stem.capitalize()


def _paragraph_location(root, paragraph, part_name: str, paragraph_number: int) -> str:
    label = _part_label(part_name)
    table = paragraph.xpath("ancestor::w:tbl[1]", namespaces=NS)
    if table:
        table = table[0]
        tables = root.xpath(".//w:tbl", namespaces=NS)
        row = paragraph.xpath("ancestor::w:tr[1]", namespaces=NS)
        cell = paragraph.xpath("ancestor::w:tc[1]", namespaces=NS)
        position = f"table {tables.index(table) + 1}"
        if row:
            position += f", row {table.xpath('./w:tr', namespaces=NS).index(row[0]) + 1}"
            if cell:
                position += f", cell {row[0].xpath('./w:tc', namespaces=NS).index(cell[0]) + 1}"
        return f"{label}, {position}"
    if paragraph.xpath("ancestor::w:txbxContent", namespaces=NS):
        return f"{label}, text box"
    return f"{label}, paragraph {paragraph_number}"


def _snippet(text: str, start: int, end: int, radius: int = 30) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}".strip()


def _replace_span(nodes: list, start: int, end: int, replacement: str) -> None:
    """Replace characters [start, end) of the concatenated node text.

    The replacement goes into the first touched run (so it keeps that run's
    formatting); the rest of the span is removed from the following runs.
    """
    offset = 0
    placed = False
    for node in nodes:
        text = node.text or ""
        node_start, node_end = offset, offset + len(text)
        offset = node_end
        if node_end <= start or node_start >= end:
            continue
        local_start = max(start, node_start) - node_start
        local_end = min(end, node_end) - node_start
        if not placed:
            node.text = text[:local_start] + replacement + text[local_end:]
            placed = True
        else:
            node.text = text[:local_start] + text[local_end:]
        node.set(XML_SPACE, "preserve")


def iter_text_parts(docx_bytes: bytes) -> Iterable[tuple[str, object]]:
    """Yield ``(part_name, xml_root)`` for every part that holds document text."""
    with zipfile.ZipFile(BytesIO(docx_bytes)) as archive:
        for name in archive.namelist():
            if TEXT_PART_PATTERN.match(name):
                yield name, etree.fromstring(archive.read(name))


def _rewrite_zip(docx_bytes: bytes, replacements: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(docx_bytes)) as source, zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for item in source.infolist():
            data = replacements.get(item.filename, source.read(item.filename))
            target.writestr(item, data)
    return output.getvalue()


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


@dataclass
class _Finding:
    severity: str
    problem: str
    fix_action: str
    keep_action: str
    can_keep: bool
    replacement: str | None  # text to write when not kept (None = leave unchanged)
    keep_replacement: str | None  # text to write when kept (None = leave unchanged)
    target_field: str | None = None  # field name the tag maps to when not kept
    keep_field: str | None = None  # field name the tag maps to when kept
    spelling: str | None = None
    blocking_unless_kept: bool = False


def _classify_group(raw: str) -> _Finding | None:
    opening = len(raw) - len(raw.lstrip("{"))
    closing = len(raw) - len(raw.rstrip("}"))
    inner = raw[opening : len(raw) - closing]
    literal = literal_jinja(raw)

    # Control tags such as {% if x %} or comments {# ... #}.
    if inner[:1] in {"%", "#"}:
        marker = inner[0]
        if opening == 1 and closing == 1 and len(inner) >= 2 and inner.endswith(marker):
            return _Finding(
                severity=SEVERITY_INFO,
                problem="Word logic tag",
                fix_action="Left unchanged",
                keep_action="Left unchanged",
                can_keep=False,
                replacement=None,
                keep_replacement=None,
            )
        return _Finding(
            severity=SEVERITY_ERROR,
            problem="Broken logic tag",
            fix_action="Cannot auto-repair: fix it in Word, or keep it as written",
            keep_action="Printed exactly as written",
            can_keep=True,
            replacement=None,
            keep_replacement=literal,
            blocking_unless_kept=True,
        )

    name = inner.strip()
    braces_ok = opening == 2 and closing == 2
    # A lone single-brace word like {x} is far more likely to be a typo for a
    # field than real text, but it is not clear-cut, so it is still an error.
    if not name:
        return _Finding(
            severity=SEVERITY_ERROR,
            problem="Empty placeholder",
            fix_action="Cannot auto-repair: fix it in Word, or keep it as written",
            keep_action="Printed exactly as written",
            can_keep=True,
            replacement=None,
            keep_replacement=literal,
            blocking_unless_kept=True,
        )

    if EXPRESSION_CHARS.search(name):
        expression_error = _expression_error(name)
        if expression_error:
            return _Finding(
                severity=SEVERITY_ERROR,
                problem=f"Invalid expression ({expression_error})",
                fix_action="Cannot auto-repair: fix it in Word, or keep it as written",
                keep_action="Printed exactly as written",
                can_keep=True,
                replacement=None,
                keep_replacement=literal,
                blocking_unless_kept=True,
            )
        if braces_ok:
            return _Finding(
                severity=SEVERITY_INFO,
                problem="Expression tag",
                fix_action="Left unchanged",
                keep_action="Left unchanged",
                can_keep=False,
                replacement=None,
                keep_replacement=None,
            )
        return _Finding(
            severity=SEVERITY_ERROR,
            problem="Broken braces",
            fix_action=f"Repaired to {{{{ {name} }}}}",
            keep_action="Printed exactly as written",
            can_keep=True,
            replacement=f"{{{{ {name} }}}}",
            keep_replacement=literal,
        )

    key = canonical_key(name)
    if key is None:
        return _Finding(
            severity=SEVERITY_ERROR,
            problem="Placeholder has no letters or numbers",
            fix_action="Cannot auto-repair: fix it in Word, or keep it as written",
            keep_action="Printed exactly as written",
            can_keep=True,
            replacement=None,
            keep_replacement=literal,
            blocking_unless_kept=True,
        )

    valid_name = is_valid_identifier(name)
    problems = []
    if not braces_ok:
        problems.append("broken braces")
    if not valid_name:
        problems.append("invalid field name")

    if problems:
        return _Finding(
            severity=SEVERITY_ERROR,
            problem=" + ".join(problems).capitalize(),
            fix_action=f"Repaired to {{{{ {key} }}}}",
            keep_action="Printed exactly as written",
            can_keep=True,
            replacement=f"{{{{ {key} }}}}",
            keep_replacement=literal,
            target_field=key,
            spelling=name,
        )

    if name != key:
        return _Finding(
            severity=SEVERITY_INFO,
            problem="Field name normalised",
            fix_action=f"Renamed to {key} (merged with any other spelling)",
            keep_action=f"Kept as its own field: {name}",
            can_keep=True,
            replacement=f"{{{{ {key} }}}}",
            keep_replacement=None,
            target_field=key,
            keep_field=name,
            spelling=name,
        )

    # Already clean: {{ name }}.
    return _Finding(
        severity="",
        problem="",
        fix_action="",
        keep_action="",
        can_keep=False,
        replacement=None,
        keep_replacement=None,
        target_field=key,
        spelling=name,
    )


def _expression_error(expression: str) -> str | None:
    """Return Jinja's complaint about ``{{ expression }}`` on its own, if any."""
    from jinja2 import Environment, TemplateSyntaxError

    try:
        Environment().parse("{{ " + expression + " }}")
    except TemplateSyntaxError as exc:
        return exc.message or "syntax error"
    return None


def _stray_finding(raw: str) -> _Finding:
    return _Finding(
        severity=SEVERITY_ERROR,
        problem="Unmatched brace",
        fix_action="Cannot auto-repair: fix it in Word, or keep it as written",
        keep_action="Printed exactly as written",
        can_keep=True,
        replacement=None,
        keep_replacement=literal_jinja(raw),
        blocking_unless_kept=True,
    )


def _find_brace_spans(text: str) -> list[tuple[int, int, str, bool]]:
    """Return ``(start, end, raw, is_stray)`` for every brace group in ``text``."""
    spans = [(m.start(), m.end(), m.group(0), False) for m in BRACE_GROUP.finditer(text)]
    masked = list(text)
    for start, end, _, _ in spans:
        masked[start:end] = [" "] * (end - start)
    masked_text = "".join(masked)
    spans += [(m.start(), m.end(), m.group(0), True) for m in STRAY_BRACES.finditer(masked_text)]
    return sorted(spans)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def prepare_template(template_bytes: bytes, keep_as_written: Iterable[str] = ()) -> PreparedTemplate:
    """Check a template, apply automatic repairs, and return a cleaned copy.

    ``keep_as_written`` holds ``issue_id`` values the user marked "Not an
    error": those tags are left alone (valid names keep their own spelling) or
    printed literally (broken tags), instead of being repaired.
    """
    kept_ids = set(keep_as_written)
    issues: list[TemplateIssue] = []
    literal_texts: set[str] = set()
    # field name -> ordered unique spellings, in order of first appearance.
    field_spellings: "OrderedDict[str, list[str]]" = OrderedDict()
    rewritten_parts: dict[str, bytes] = {}

    for part_name, root in iter_text_parts(template_bytes):
        part_changed = False
        for paragraph_number, paragraph in enumerate(root.iter(W_P), start=1):
            nodes = _paragraph_text_nodes(paragraph)
            text = "".join(node.text or "" for node in nodes)
            if "{" not in text and "}" not in text:
                continue

            edits: list[tuple[int, int, str]] = []
            for start, end, raw, is_stray in _find_brace_spans(text):
                finding = _stray_finding(raw) if is_stray else _classify_group(raw)
                if finding is None:
                    continue
                issue_id = f"{part_name}:{paragraph_number}:{start}"
                kept = finding.can_keep and issue_id in kept_ids

                replacement = finding.keep_replacement if kept else finding.replacement
                if replacement is not None and replacement != raw:
                    edits.append((start, end, replacement))
                if kept and finding.keep_replacement is not None and finding.keep_replacement.startswith("{% raw"):
                    literal_texts.add(raw)

                mapped_field = (finding.keep_field if kept else finding.target_field)
                if kept and finding.keep_field is None:
                    mapped_field = None
                if mapped_field:
                    spellings = field_spellings.setdefault(mapped_field, [])
                    if finding.spelling and finding.spelling not in spellings:
                        spellings.append(finding.spelling)

                if finding.severity:
                    issues.append(
                        TemplateIssue(
                            issue_id=issue_id,
                            number=0,
                            severity=finding.severity,
                            found_text=raw,
                            location=_paragraph_location(root, paragraph, part_name, paragraph_number),
                            context=_snippet(text, start, end),
                            problem=finding.problem,
                            action=finding.keep_action if kept else finding.fix_action,
                            can_keep=finding.can_keep,
                            kept=kept,
                            blocking=finding.blocking_unless_kept and not kept,
                        )
                    )

            for start, end, replacement in sorted(edits, reverse=True):
                _replace_span(nodes, start, end, replacement)
                part_changed = True

        if part_changed:
            rewritten_parts[part_name] = etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )

    for field_name, spellings in field_spellings.items():
        if len(spellings) > 1:
            issues.append(
                TemplateIssue(
                    issue_id=f"merge:{field_name}",
                    number=0,
                    severity=SEVERITY_WARNING,
                    found_text=" + ".join(spellings),
                    location="Whole template",
                    context="",
                    problem="Same field spelled differently",
                    action=f"Merged into one field: {spellings[0]}",
                    can_keep=False,
                )
            )

    cleaned_bytes = _rewrite_zip(template_bytes, rewritten_parts) if rewritten_parts else template_bytes

    fields, parse_error = _discover_fields(cleaned_bytes, field_spellings)
    if parse_error:
        other_blockers = [issue for issue in issues if issue.blocking]
        logic_tags = [issue for issue in issues if issue.problem == "Word logic tag"]
        if other_blockers:
            parse_error += ". This is usually caused by the other red errors: fix or keep those first."
        elif logic_tags:
            parse_error += (
                ". Check the Word logic tags (each {% if %} needs a condition and a matching {% endif %}): "
                + ", ".join(f"{issue.found_text} at {issue.location}" for issue in logic_tags[:5])
            )
        issues.append(
            TemplateIssue(
                issue_id="parse",
                number=0,
                severity=SEVERITY_ERROR,
                found_text="",
                location="Whole template",
                context="",
                problem="Template could not be read",
                action=f"Fix in Word: {parse_error}",
                can_keep=False,
                blocking=True,
            )
        )

    issues.sort(key=lambda issue: SEVERITY_ORDER.get(issue.severity, 9))
    numbered = tuple(
        TemplateIssue(**{**issue.__dict__, "number": index}) for index, issue in enumerate(issues, start=1)
    )
    return PreparedTemplate(
        cleaned_bytes=cleaned_bytes,
        fields=fields,
        issues=numbered,
        literal_texts=frozenset(literal_texts),
    )


def _discover_fields(
    cleaned_bytes: bytes, field_spellings: "OrderedDict[str, list[str]]"
) -> tuple[tuple[TemplateField, ...], str | None]:
    """List the variables the cleaned template needs, in order of appearance."""
    from docxtpl import DocxTemplate

    parse_error = None
    try:
        variables = set(DocxTemplate(BytesIO(cleaned_bytes)).get_undeclared_template_variables())
    except Exception as exc:  # Jinja syntax errors from tags we could not repair.
        parse_error = f"{type(exc).__name__}: {exc}"
        variables = set(field_spellings)

    ordered = [name for name in field_spellings if name in variables]
    ordered += sorted(variables - set(ordered))
    fields = []
    used_labels: set[str] = set()
    for name in ordered:
        spellings = tuple(field_spellings.get(name, []))
        label = spellings[0] if spellings else name
        if label.casefold() in used_labels:
            label = name
        used_labels.add(label.casefold())
        fields.append(TemplateField(name=name, label=label, spellings=spellings or (name,)))
    return tuple(fields), parse_error


def find_leftover_template_text(docx_bytes: bytes, allowed_literals: Iterable[str] = ()) -> list[str]:
    """Return brace text still present in a rendered document.

    Catches what ``ensure_no_unresolved_placeholders`` misses, such as a
    single-brace ``{name}}`` that Jinja silently printed. Text the user chose to
    keep as written is ignored.
    """
    allowed = set(allowed_literals)
    leftovers: list[str] = []
    for _, root in iter_text_parts(docx_bytes):
        for paragraph in root.iter(W_P):
            text = "".join(node.text or "" for node in _paragraph_text_nodes(paragraph))
            if "{" not in text and "}" not in text:
                continue
            for _, _, raw, _ in _find_brace_spans(text):
                if raw not in allowed and raw not in leftovers:
                    leftovers.append(raw)
    return leftovers
