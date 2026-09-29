from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache


class AudiogramExpressionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExpressionVariable:
    name: str
    description: str
    example: float


@dataclass(frozen=True, slots=True)
class ExpressionFunction:
    name: str
    signature: str
    description: str
    function: Callable[..., float]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _lerp(start: float, end: float, amount: float) -> float:
    return start + (end - start) * amount


def _smoothstep(value: float, low: float = 0.0, high: float = 1.0) -> float:
    if high == low:
        return 0.0
    amount = _clamp((value - low) / (high - low))
    return amount * amount * (3 - 2 * amount)


def _sign(value: float) -> float:
    return float((value > 0) - (value < 0))


def _absolute(value: float) -> float:
    return abs(value)


VARIABLES = {
    item.name: item
    for item in (
        ExpressionVariable("t", "Seconds since the audio started.", 3.0),
        ExpressionVariable("duration", "Total audio length in seconds.", 60.0),
        ExpressionVariable("progress", "Render progress from 0 to 1.", 0.5),
        ExpressionVariable("frame", "Current frame number, starting at 0.", 90.0),
        ExpressionVariable("fps", "Rendered frames per second.", 30.0),
        ExpressionVariable("level", "Current overall loudness from 0 to 1.", 0.6),
        ExpressionVariable("bass", "Current low-band energy from 0 to 1.", 0.7),
        ExpressionVariable("mid", "Current mid-band energy from 0 to 1.", 0.5),
        ExpressionVariable("treble", "Current high-band energy from 0 to 1.", 0.3),
        ExpressionVariable("pi", "The constant pi.", math.pi),
        ExpressionVariable("tau", "A full turn in radians.", math.tau),
        ExpressionVariable("e", "Euler's number.", math.e),
    )
}


FUNCTIONS = {
    item.name: item
    for item in (
        ExpressionFunction("sin", "sin(x)", "Sine in radians.", math.sin),
        ExpressionFunction("cos", "cos(x)", "Cosine in radians.", math.cos),
        ExpressionFunction("tan", "tan(x)", "Tangent in radians.", math.tan),
        ExpressionFunction("abs", "abs(x)", "Distance from zero.", _absolute),
        ExpressionFunction("min", "min(a, b, ...)", "Smallest argument.", min),
        ExpressionFunction("max", "max(a, b, ...)", "Largest argument.", max),
        ExpressionFunction("clamp", "clamp(x, low, high)", "Clamp to a range.", _clamp),
        ExpressionFunction("lerp", "lerp(a, b, x)", "Blend from a to b.", _lerp),
        ExpressionFunction(
            "smoothstep", "smoothstep(x, low, high)", "Smooth eased clamp.", _smoothstep
        ),
        ExpressionFunction("floor", "floor(x)", "Round down.", math.floor),
        ExpressionFunction("ceil", "ceil(x)", "Round up.", math.ceil),
        ExpressionFunction("round", "round(x)", "Round to the nearest integer.", round),
        ExpressionFunction("sqrt", "sqrt(x)", "Square root.", math.sqrt),
        ExpressionFunction("pow", "pow(x, y)", "x raised to y.", math.pow),
        ExpressionFunction("exp", "exp(x)", "e raised to x.", math.exp),
        ExpressionFunction("log", "log(x)", "Natural logarithm.", math.log),
        ExpressionFunction("sign", "sign(x)", "-1, 0, or 1 from the sign.", _sign),
        ExpressionFunction("fmod", "fmod(x, y)", "Floating-point remainder.", math.fmod),
    )
}


_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_COMPARATORS: dict[type[ast.cmpop], Callable[[float, float], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_MAX_SOURCE_LENGTH = 256
_MAX_AST_NODES = 96
_MAX_ABSOLUTE_RESULT = 1_000_000_000.0


@dataclass(frozen=True, slots=True)
class SafeAudiogramExpression:
    source: str
    body: ast.expr

    def evaluate(self, context: Mapping[str, float]) -> float:
        scope = {name: float(variable.example) for name, variable in VARIABLES.items()}
        scope.update({name: float(value) for name, value in context.items() if name in VARIABLES})
        try:
            result = _evaluate_node(self.body, scope)
        except AudiogramExpressionError:
            raise
        except (ArithmeticError, OverflowError, ValueError) as error:
            raise AudiogramExpressionError(f"The formula failed: {error}") from error
        value = float(result)
        if not math.isfinite(value) or abs(value) > _MAX_ABSOLUTE_RESULT:
            raise AudiogramExpressionError(
                "The formula result must be finite and reasonably sized."
            )
        return value


@lru_cache(maxsize=256)
def compile_expression(source: str) -> SafeAudiogramExpression:
    if not isinstance(source, str) or not source.strip():
        raise AudiogramExpressionError("The formula is empty.")
    normalized = source.strip()
    if len(normalized) > _MAX_SOURCE_LENGTH:
        raise AudiogramExpressionError(
            f"The formula is longer than the {_MAX_SOURCE_LENGTH}-character limit."
        )
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as error:
        raise AudiogramExpressionError(f"That is not a valid formula: {error.msg}.") from error
    nodes = list(ast.walk(tree))
    if len(nodes) > _MAX_AST_NODES:
        raise AudiogramExpressionError("The formula is too complex.")
    _validate_node(tree.body)
    return SafeAudiogramExpression(source=normalized, body=tree.body)


def resolve_numeric(value: float | str, context: Mapping[str, float]) -> float:
    if isinstance(value, str):
        return compile_expression(value).evaluate(context)
    if isinstance(value, bool):
        raise AudiogramExpressionError("Boolean values are not numeric formulas.")
    result = float(value)
    if not math.isfinite(result):
        raise AudiogramExpressionError("Numeric values must be finite.")
    return result


def sample_context(*, duration: float = 60.0, fps: float = 30.0) -> dict[str, float]:
    context = {name: float(variable.example) for name, variable in VARIABLES.items()}
    context.update({"duration": duration, "fps": fps})
    return context


def expression_reference(query: str = "") -> list[dict[str, str]]:
    items = [
        {"name": item.name, "kind": "variable", "signature": item.name, "detail": item.description}
        for item in VARIABLES.values()
    ]
    items.extend(
        {
            "name": item.name,
            "kind": "function",
            "signature": item.signature,
            "detail": item.description,
        }
        for item in FUNCTIONS.values()
    )
    needle = query.strip().casefold()
    if needle:
        items = [
            item
            for item in items
            if needle in item["name"].casefold()
            or needle in item["signature"].casefold()
            or needle in item["detail"].casefold()
        ]
    return sorted(
        items,
        key=lambda item: (
            not item["name"].casefold().startswith(needle),
            item["kind"] != "variable",
            item["name"],
        ),
    )


def _validate_node(node: ast.AST) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise AudiogramExpressionError("Only numeric constants are allowed.")
        return
    if isinstance(node, ast.Name):
        if node.id not in VARIABLES:
            raise AudiogramExpressionError(f"'{node.id}' is not a known variable.")
        return
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BINARY_OPERATORS:
            raise AudiogramExpressionError("That arithmetic operator is not allowed.")
        _validate_node(node.left)
        _validate_node(node.right)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            raise AudiogramExpressionError("That unary operator is not allowed.")
        _validate_node(node.operand)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise AudiogramExpressionError("Only listed formula functions can be called.")
        if node.keywords:
            raise AudiogramExpressionError("Formula functions do not accept named arguments.")
        for argument in node.args:
            _validate_node(argument)
        return
    if isinstance(node, ast.IfExp):
        _validate_node(node.test)
        _validate_node(node.body)
        _validate_node(node.orelse)
        return
    if isinstance(node, ast.Compare):
        if any(type(item) not in _COMPARATORS for item in node.ops):
            raise AudiogramExpressionError("That comparison is not allowed.")
        _validate_node(node.left)
        for comparator in node.comparators:
            _validate_node(comparator)
        return
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise AudiogramExpressionError("That boolean operator is not allowed.")
        for value in node.values:
            _validate_node(value)
        return
    raise AudiogramExpressionError(
        f"'{type(node).__name__}' is not allowed; use only arithmetic and listed names."
    )


def _evaluate_node(node: ast.AST, scope: Mapping[str, float]) -> float | bool:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise AudiogramExpressionError("Only numeric constants are allowed.")
        return float(node.value)
    if isinstance(node, ast.Name):
        return scope[node.id]
    if isinstance(node, ast.BinOp):
        left = float(_evaluate_node(node.left, scope))
        right = float(_evaluate_node(node.right, scope))
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise AudiogramExpressionError(
                "Power exponents are limited to an absolute value of 12."
            )
        return _BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp):
        value = _evaluate_node(node.operand, scope)
        if isinstance(node.op, ast.Not):
            return not bool(value)
        return float(value) if isinstance(node.op, ast.UAdd) else -float(value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        arguments = [float(_evaluate_node(argument, scope)) for argument in node.args]
        return float(FUNCTIONS[node.func.id].function(*arguments))
    if isinstance(node, ast.IfExp):
        return _evaluate_node(node.body if _evaluate_node(node.test, scope) else node.orelse, scope)
    if isinstance(node, ast.Compare):
        left = float(_evaluate_node(node.left, scope))
        for operation, comparator in zip(node.ops, node.comparators, strict=True):
            right = float(_evaluate_node(comparator, scope))
            if not _COMPARATORS[type(operation)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        values = [_evaluate_node(value, scope) for value in node.values]
        return all(map(bool, values)) if isinstance(node.op, ast.And) else any(map(bool, values))
    raise AudiogramExpressionError("The formula contains an unsupported value.")
