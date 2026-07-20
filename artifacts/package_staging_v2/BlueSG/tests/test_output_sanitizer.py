import json
import math

from Flexar.BlueSG.output_sanitizer import sanitize_for_output


def test_nested_nan_and_infinity_are_finite_and_serialisable() -> None:
    value = {"a": math.nan, "nested": [math.inf, {"b": -math.inf}]}
    safe = sanitize_for_output(value)
    assert safe == {"a": 0.0, "nested": [0.0, {"b": 0.0}]}
    assert "NaN" not in json.dumps(safe, allow_nan=False)

