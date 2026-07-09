from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _namespace_uri(tag: str) -> str | None:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return None


def _child(element: ET.Element, local_name: str) -> ET.Element | None:
    for child in element:
        if _strip_namespace(child.tag) == local_name:
            return child
    return None


def _children(element: ET.Element, local_name: str) -> list[ET.Element]:
    return [child for child in element if _strip_namespace(child.tag) == local_name]


def _text(element: ET.Element | None) -> str:
    return "" if element is None or element.text is None else element.text


def _walk(element: ET.Element, path: str = ""):
    local_name = _strip_namespace(element.tag)
    current_path = f"{path}/{local_name}" if path else local_name
    yield element, current_path
    counts: dict[str, int] = {}
    for child in element:
        child_name = _strip_namespace(child.tag)
        counts[child_name] = counts.get(child_name, 0) + 1
        indexed_path = f"{current_path}/{child_name}[{counts[child_name]}]"
        yield from _walk(child, indexed_path)


def _xml_to_dict(element: ET.Element) -> dict[str, Any]:
    node: dict[str, Any] = {"tag": _strip_namespace(element.tag)}
    if element.attrib:
        node["attributes"] = dict(element.attrib)
    if element.text and element.text.strip():
        node["text"] = element.text
    children = [_xml_to_dict(child) for child in element]
    if children:
        node["children"] = children
    return node


def parse_rdl(rdl_path: Path) -> dict[str, Any]:
    try:
        tree = ET.parse(rdl_path)
    except ET.ParseError as exc:
        raise ValueError(f"The XML could not be parsed: {exc}") from exc

    root = tree.getroot()
    namespace = _namespace_uri(root.tag)

    textboxes = []
    datasets = []
    parameters = []

    for element, path in _walk(root):
        local_name = _strip_namespace(element.tag)

        if local_name == "Textbox":
            textbox_name = element.attrib.get("Name", "")
            value_element = _child(element, "Value")
            textboxes.append(
                {
                    "name": textbox_name,
                    "value": _text(value_element),
                    "path": path,
                }
            )

        elif local_name == "DataSet":
            dataset_name = element.attrib.get("Name", "")
            query = _child(element, "Query")
            command_text = _text(_child(query, "CommandText")) if query is not None else ""
            command_type = _text(_child(query, "CommandType")) if query is not None else ""
            data_source_name = _text(_child(query, "DataSourceName")) if query is not None else ""
            datasets.append(
                {
                    "name": dataset_name,
                    "data_source_name": data_source_name,
                    "command_type": command_type,
                    "command_text": command_text,
                    "path": path,
                }
            )

        elif local_name == "ReportParameter":
            parameter_name = element.attrib.get("Name", "")
            parameters.append(
                {
                    "name": parameter_name,
                    "data_type": _text(_child(element, "DataType")),
                    "nullable": _text(_child(element, "Nullable")),
                    "allow_blank": _text(_child(element, "AllowBlank")),
                    "prompt": _text(_child(element, "Prompt")),
                    "path": path,
                }
            )

    return {
        "report_name": rdl_path.stem,
        "source_file": rdl_path.name,
        "namespace": namespace,
        "textboxes": textboxes,
        "datasets": datasets,
        "parameters": parameters,
        "raw": _xml_to_dict(root),
    }


def build_edited_rdl(original_rdl_path: Path, parsed_json: dict[str, Any]) -> bytes:
    tree = ET.parse(original_rdl_path)
    root = tree.getroot()
    namespace = _namespace_uri(root.tag)
    if namespace:
        ET.register_namespace("", namespace)

    textboxes_by_name = {
        textbox.get("name"): textbox.get("value", "")
        for textbox in parsed_json.get("textboxes", [])
        if textbox.get("name")
    }

    for element, _path in _walk(root):
        if _strip_namespace(element.tag) != "Textbox":
            continue

        textbox_name = element.attrib.get("Name", "")
        if textbox_name not in textboxes_by_name:
            continue

        value_element = _child(element, "Value")
        if value_element is not None:
            value_element.text = textboxes_by_name[textbox_name]

    root_copy = copy.deepcopy(root)
    ET.indent(root_copy, space="  ")
    return ET.tostring(root_copy, encoding="utf-8", xml_declaration=True)
