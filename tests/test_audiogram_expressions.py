from __future__ import annotations

import pytest

from splicr.studio.audiogram_expressions import (
    AudiogramExpressionError,
    compile_expression,
    expression_reference,
    resolve_numeric,
    sample_context,
)


def test_safe_expression_supports_time_progress_and_audio_reactivity() -> None:
    context = sample_context(duration=120, fps=24)
    context.update(
        {
            "t": 30,
            "progress": 0.25,
            "frame": 720,
            "level": 0.8,
            "bass": 0.7,
            "mid": 0.4,
            "treble": 0.2,
        }
    )

    assert resolve_numeric("lerp(0.2, 0.8, progress)", context) == pytest.approx(0.35)
    assert resolve_numeric("0.5 + sin(tau * progress) * level", context) == pytest.approx(1.3)
    assert resolve_numeric("bass if bass > treble else treble", context) == pytest.approx(0.7)
    assert resolve_numeric("frame / fps", context) == pytest.approx(30)
    assert resolve_numeric(0.42, context) == pytest.approx(0.42)


@pytest.mark.parametrize(
    "source",
    [
        "__import__('os').system('whoami')",
        "(1).__class__",
        "level[0]",
        "[x for x in (1, 2)]",
        "lambda: 1",
        "open('secret')",
        "sin(x=1)",
        "{'value': 1}",
    ],
)
def test_expression_escape_attempts_are_rejected_without_eval(source: str) -> None:
    with pytest.raises(AudiogramExpressionError):
        compile_expression(source)


def test_expression_complexity_numeric_limits_and_runtime_errors_are_structured() -> None:
    with pytest.raises(AudiogramExpressionError, match="longer"):
        compile_expression("1+" * 130 + "1")
    with pytest.raises(AudiogramExpressionError, match="exponents"):
        resolve_numeric("2 ** 13", sample_context())
    with pytest.raises(AudiogramExpressionError, match="failed"):
        resolve_numeric("1 / 0", sample_context())
    with pytest.raises(AudiogramExpressionError, match="finite"):
        resolve_numeric(float("inf"), sample_context())


def test_expression_reference_is_generated_from_the_runtime_registry() -> None:
    reference = expression_reference()
    names = {(item["kind"], item["name"]) for item in reference}
    assert ("variable", "level") in names
    assert ("variable", "progress") in names
    assert ("function", "smoothstep") in names
    assert expression_reference("treb") == [
        {
            "name": "treble",
            "kind": "variable",
            "signature": "treble",
            "detail": "Current high-band energy from 0 to 1.",
        }
    ]
