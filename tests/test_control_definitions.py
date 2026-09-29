from __future__ import annotations

import pytest

from splicr.domain import (
    ControlCondition,
    ControlDefinition,
    ControlValueType,
    validate_control_values,
)


def test_control_definitions_validate_ranges_choices_and_conditions() -> None:
    definition = ControlDefinition(
        key="temperature",
        value_type=ControlValueType.NUMBER,
        label="Temperature",
        description="Generation randomness.",
        group="Generation",
        default=0.75,
        choices=(0.5, 0.75, 1.0),
        minimum=0,
        maximum=2,
        step=0.05,
        unit="ratio",
        visible_when=(ControlCondition("sampling_enabled", True),),
    )

    assert validate_control_values((definition,), {}) == {"temperature": 0.75}
    assert validate_control_values((definition,), {"temperature": 1.0}) == {
        "temperature": 1.0
    }
    with pytest.raises(ValueError, match="declared choices"):
        validate_control_values((definition,), {"temperature": 1.5})


def test_control_values_reject_unknown_types_and_bounds_but_allow_internal_state() -> None:
    definitions = (
        ControlDefinition(
            key="seed",
            value_type=ControlValueType.INTEGER,
            required=True,
            minimum=0,
            maximum=100,
        ),
    )

    with pytest.raises(ValueError, match="unknown advanced control"):
        validate_control_values(definitions, {"mystery": 1, "seed": 2})
    with pytest.raises(ValueError, match="must be integer"):
        validate_control_values(definitions, {"seed": 2.5})
    with pytest.raises(ValueError, match="at most 100"):
        validate_control_values(definitions, {"seed": 101})
    assert validate_control_values(
        definitions,
        {"seed": 2, "__splicr_voice_profile": {"id": "voice-1"}},
    ) == {"seed": 2, "__splicr_voice_profile": {"id": "voice-1"}}
    with pytest.raises(ValueError, match="unknown advanced control"):
        validate_control_values((), {"legacy_provider_value": 3})
    assert validate_control_values((), {"legacy_provider_value": 3}, allow_unknown=True) == {
        "legacy_provider_value": 3
    }


def test_invalid_control_metadata_is_rejected_early() -> None:
    with pytest.raises(ValueError, match="minimum cannot exceed maximum"):
        ControlDefinition(
            key="speed",
            value_type=ControlValueType.NUMBER,
            minimum=2,
            maximum=1,
        )
    with pytest.raises(ValueError, match="cannot condition itself"):
        ControlDefinition(
            key="speed",
            visible_when=(ControlCondition("speed", True),),
        )
    with pytest.raises(ValueError, match="range metadata"):
        ControlDefinition(key="voice", minimum=0)
    secret = "do-not-repeat-this-value"
    with pytest.raises(ValueError, match="secret storage") as raised:
        validate_control_values(
            (ControlDefinition(key="token", sensitive=True),),
            {"token": secret},
        )
    assert secret not in str(raised.value)
    with pytest.raises(ValueError, match="randomizable controls must be integers"):
        ControlDefinition(
            key="temperature",
            value_type=ControlValueType.NUMBER,
            randomizable=True,
        )
