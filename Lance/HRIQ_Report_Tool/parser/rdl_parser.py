from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def children(element: ET.Element | None, name: str) -> list[ET.Element]:
    if element is None:
        return []
    return [child for child in element if local_name(child.tag) == name]


def child(element: ET.Element | None, name: str) -> ET.Element | None:
    return next(iter(children(element, name)), None)


def descendants(element: ET.Element, name: str) -> Iterable[ET.Element]:
    return (node for node in element.iter() if local_name(node.tag) == name)


def text(element: ET.Element | None) -> str:
    return "" if element is None or element.text is None else element.text


def _redact_connection_string(value: str) -> str:
    sensitive = {"password", "pwd", "user id", "uid"}
    parts = []
    for part in value.split(";"):
        key, separator, _stored_value = part.partition("=")
        parts.append(f"{key}=<redacted>" if separator and key.strip().casefold() in sensitive else part)
    return ";".join(parts)


def _field(field: ET.Element) -> dict[str, str]:
    return {
        "name": field.attrib.get("Name", ""),
        "data_field": text(child(field, "DataField")),
        "value": text(child(field, "Value")),
    }


def _query_parameter(parameter: ET.Element) -> dict[str, str]:
    return {
        "name": parameter.attrib.get("Name", ""),
        "value": text(child(parameter, "Value")),
    }


def _business_logic(root: ET.Element) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"filters": [], "groups": [], "expressions": []}
    for node in root.iter():
        name = local_name(node.tag)
        value = (node.text or "").strip()
        if not value:
            continue
        if name == "FilterExpression":
            result["filters"].append(value)
        elif name == "GroupExpression":
            result["groups"].append(value)
        elif value.startswith("="):
            result["expressions"].append(value)
    return {key: list(dict.fromkeys(values)) for key, values in result.items()}


def parse_rdl_content(
    content: bytes,
    logical_path: str,
    modified_at: datetime | None = None,
    *,
    source_type: str = "directory",
    source_archive: str | None = None,
) -> dict[str, Any]:
    """Parse useful SSRS metadata without retaining bulky report styling/XML."""
    try:
        root = ET.parse(BytesIO(content)).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Invalid RDL XML: {exc}") from exc

    if local_name(root.tag) != "Report":
        raise ValueError("Invalid RDL XML: root element is not Report")

    namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    logical = logical_path.replace("\\", "/")

    data_sources = []
    for source in descendants(root, "DataSource"):
        properties = child(source, "ConnectionProperties")
        data_sources.append(
            {
                "name": source.attrib.get("Name", ""),
                "provider": text(child(properties, "DataProvider")),
                "connect_string": _redact_connection_string(text(child(properties, "ConnectString"))),
                "shared_reference": text(child(source, "DataSourceReference")),
            }
        )

    datasets = []
    for dataset in descendants(root, "DataSet"):
        query = child(dataset, "Query")
        fields_container = child(dataset, "Fields")
        query_parameters = child(query, "QueryParameters")
        datasets.append(
            {
                "name": dataset.attrib.get("Name", ""),
                "data_source_name": text(child(query, "DataSourceName")),
                "command_type": text(child(query, "CommandType")) or "Text",
                "command_text": text(child(query, "CommandText")),
                "query_parameters": [
                    _query_parameter(item) for item in children(query_parameters, "QueryParameter")
                ],
                "fields": [_field(item) for item in children(fields_container, "Field")],
            }
        )

    report_parameters = []
    for parameter in descendants(root, "ReportParameter"):
        defaults = child(child(parameter, "DefaultValue"), "Values")
        report_parameters.append(
            {
                "name": parameter.attrib.get("Name", ""),
                "data_type": text(child(parameter, "DataType")),
                "nullable": text(child(parameter, "Nullable")).lower() == "true",
                "allow_blank": text(child(parameter, "AllowBlank")).lower() == "true",
                "prompt": text(child(parameter, "Prompt")),
                "default_values": [text(value) for value in children(defaults, "Value")],
            }
        )

    return {
        "report_name": Path(logical).stem,
        "source_path": logical,
        "source_type": source_type,
        "source_archive": source_archive,
        "source_member": logical if source_type == "zip" else None,
        "source_modified_at": modified_at.isoformat() if modified_at else None,
        "namespace": namespace,
        "description": text(child(root, "Description")),
        "data_sources": data_sources,
        "datasets": datasets,
        "report_parameters": report_parameters,
        "business_logic": _business_logic(root),
        "warnings": [],
    }


def parse_rdl(rdl_path: Path, raw_root: Path | None = None) -> dict[str, Any]:
    """Compatibility wrapper for callers that parse a normal RDL file."""
    relative = rdl_path.relative_to(raw_root) if raw_root else Path(rdl_path.name)
    logical = relative.as_posix()
    modified = datetime.fromtimestamp(rdl_path.stat().st_mtime)
    parsed = parse_rdl_content(rdl_path.read_bytes(), logical, modified)
    parsed["source_path"] = str(relative)
    return parsed
