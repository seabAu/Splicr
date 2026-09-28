"""Expressions: letting a parameter be a formula over time instead of a
fixed number.

Two things matter here beyond "it evaluates".

**Safety.** These come from a text field, so `eval()` is not an option --
that is arbitrary code execution, not a stylistic preference. Expressions
are parsed with `ast` and walked against a whitelist of node types and
names; anything else is refused at compile time, before it can run once.
Attribute access, calls to anything not in FUNCTIONS, imports, comprehen-
sions, lambdas and dunder names are all rejected.

**Discoverability.** A formula language nobody can enumerate is unusable,
so VARIABLES and FUNCTIONS are registries carrying a description apiece,
and `reference()` returns them for the UI to show and filter. Adding a
variable in one place makes it appear in the reference automatically --
they cannot drift apart.
"""

import ast
import math

# name -> (description, example context value). The example value is what
# a preview uses when it has no real frame to evaluate against.
VARIABLES = {
    "t": ("Seconds since the start of the audio.", 3.0),
    "duration": ("Total length of the audio, in seconds.", 60.0),
    "progress": ("How far through, 0 at the start to 1 at the end.", 0.5),
    "frame": ("Frame number, counting from 0.", 90),
    "fps": ("Frames per second being rendered.", 30),
    "level": ("Overall loudness right now, 0 to 1.", 0.6),
    "bass": ("Loudness of the low bands right now, 0 to 1.", 0.7),
    "mid": ("Loudness of the middle bands right now, 0 to 1.", 0.5),
    "treble": ("Loudness of the high bands right now, 0 to 1.", 0.3),
    "pi": ("3.14159...", math.pi),
    "tau": ("6.28318... -- a full turn, so sin(tau*progress) is one "
            "complete cycle across the whole file.", math.tau),
    "e": ("2.71828...", math.e),
}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _lerp(a, b, x):
    return a + (b - a) * x


def _smoothstep(x, lo=0.0, hi=1.0):
    if hi == lo:
        return 0.0
    x = _clamp((x - lo) / (hi - lo))
    return x * x * (3 - 2 * x)


def _sign(x):
    return (x > 0) - (x < 0)


FUNCTIONS = {
    "sin": (math.sin, "Sine, in radians."),
    "cos": (math.cos, "Cosine, in radians."),
    "tan": (math.tan, "Tangent, in radians."),
    "abs": (abs, "Distance from zero."),
    "min": (min, "The smallest of its arguments."),
    "max": (max, "The largest of its arguments."),
    "clamp": (_clamp, "clamp(x, low, high) -- keeps x inside a range. "
                      "Defaults to 0 and 1."),
    "lerp": (_lerp, "lerp(from, to, x) -- blends between two values as x "
                    "goes 0 to 1."),
    "smoothstep": (_smoothstep, "smoothstep(x, low, high) -- like clamp "
                                "but eases in and out instead of "
                                "cornering."),
    "floor": (math.floor, "Rounds down."),
    "ceil": (math.ceil, "Rounds up."),
    "round": (round, "Rounds to the nearest whole number."),
    "sqrt": (math.sqrt, "Square root."),
    "pow": (pow, "pow(x, y) -- x to the power of y."),
    "exp": (math.exp, "e to the power of x."),
    "log": (math.log, "Natural logarithm."),
    "sign": (_sign, "-1, 0 or 1 depending on the sign of x."),
    "fmod": (math.fmod, "fmod(x, y) -- remainder after division, which is "
                        "how you make something repeat."),
}

# Only these node types can appear. Everything else -- attributes, calls
# to unknown names, subscripts, comprehensions, lambdas, imports -- is
# refused before the expression ever runs.
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
    ast.Load, ast.Call, ast.IfExp, ast.Compare, ast.BoolOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.And, ast.Or,
)


class ExpressionError(ValueError):
    """A formula that can't be used, with a reason meant for a person."""


def _check(node):
    for child in ast.walk(node):
        if not isinstance(child, _ALLOWED_NODES):
            raise ExpressionError(
                f"'{type(child).__name__}' isn't allowed in a formula. "
                "Only numbers, the listed variables and functions, and "
                "ordinary arithmetic can be used.")
        if isinstance(child, ast.Name):
            if child.id.startswith("_"):
                raise ExpressionError(f"'{child.id}' isn't available.")
            if child.id not in VARIABLES and child.id not in FUNCTIONS:
                raise ExpressionError(
                    f"'{child.id}' isn't a known variable or function. "
                    "See the reference list for what's available.")
        if isinstance(child, ast.Call):
            if not isinstance(child.func, ast.Name):
                raise ExpressionError("Only the listed functions can be "
                                      "called.")
            if child.func.id not in FUNCTIONS:
                raise ExpressionError(
                    f"'{child.func.id}' isn't a known function.")
            if child.keywords:
                raise ExpressionError("Functions here take plain arguments, "
                                      "not name=value.")


def compile_expression(source):
    """Turn a formula string into a callable taking a context dict.
    Raises ExpressionError for anything unsafe or unknown -- at compile
    time, so a bad formula never runs even once."""
    if not isinstance(source, str) or not source.strip():
        raise ExpressionError("The formula is empty.")
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"That isn't a valid formula: {exc.msg}")
    _check(tree)
    code = compile(tree, "<formula>", "eval")
    namespace = {name: fn for name, (fn, _desc) in FUNCTIONS.items()}

    def evaluate(context):
        scope = dict(namespace)
        scope.update(context)
        try:
            value = eval(code, {"__builtins__": {}}, scope)  # noqa: S307
        except ZeroDivisionError:
            return 0.0
        except Exception as exc:
            raise ExpressionError(f"The formula failed: {exc}")
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if not isinstance(value, (int, float)):
            raise ExpressionError("A formula has to work out to a number.")
        if math.isnan(value) or math.isinf(value):
            return 0.0
        return float(value)

    evaluate.source = source.strip()
    return evaluate


def is_expression(value):
    """Whether a stored parameter is a formula rather than a number."""
    return isinstance(value, str) and value.strip() != ""


def resolve(value, context, default=0.0):
    """A parameter's value for one frame: numbers pass through, formulas
    are evaluated. A broken formula falls back to `default` rather than
    aborting a render that may be thousands of frames in."""
    if not is_expression(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    try:
        return compile_expression(value)(context)
    except ExpressionError:
        return default


def sample_context(duration=60.0, fps=30):
    """A plausible context for previewing or validating a formula without
    real audio."""
    ctx = {name: example for name, (_desc, example) in VARIABLES.items()}
    ctx["duration"] = duration
    ctx["fps"] = fps
    return ctx


def validate(source, context=None):
    """(ok, message) for showing under an input field as it's typed."""
    try:
        fn = compile_expression(source)
    except ExpressionError as exc:
        return False, str(exc)
    try:
        value = fn(context or sample_context())
    except ExpressionError as exc:
        return False, str(exc)
    return True, f"OK -- currently {value:.4g}"


def reference(filter_text=""):
    """Everything available, optionally filtered, for the UI's lookup
    list. Names that START with the filter sort first, the same ordering
    rule the pronunciation search uses."""
    q = (filter_text or "").strip().lower()
    items = [{"name": n, "kind": "variable", "detail": d}
            for n, (d, _v) in VARIABLES.items()]
    items += [{"name": n, "kind": "function", "detail": d}
             for n, (_f, d) in FUNCTIONS.items()]
    if q:
        starts = [i for i in items if i["name"].lower().startswith(q)]
        contains = [i for i in items
                   if q in i["name"].lower() and i not in starts]
        contains += [i for i in items
                    if q in i["detail"].lower() and i not in starts
                    and i not in contains]
        items = starts + contains
    else:
        items.sort(key=lambda i: (i["kind"] != "variable", i["name"]))
    return items
