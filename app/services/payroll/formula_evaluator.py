"""Safe arithmetic formula evaluation with a Decimal/integer-paise path.

The original float-returning ``evaluate`` API is retained for callers that
validate formulas.  Production payroll uses ``evaluate_decimal`` or
``evaluate_paise`` so expressions such as ``basic * 0.40 + 1000`` never acquire
binary floating-point rounding errors.
"""
from __future__ import annotations

import ast
import math
import operator
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping

from app.services.payroll.money import as_decimal, round_paise

ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

def _round_decimal(value: Decimal, digits: Decimal = Decimal("0")) -> Decimal:
    quantum = Decimal("1").scaleb(-int(digits))
    return as_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


ALLOWED_FUNCTIONS = {
    "min": min,
    "max": max,
    "round": _round_decimal,
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
}


class SafeFormulaEvaluator:
    """Safely evaluates arithmetic expressions within a small AST sandbox."""

    @classmethod
    def evaluate_decimal(cls, expression: str, context: Mapping[str, Any]) -> Decimal:
        if not expression or not expression.strip():
            return Decimal("0")
        try:
            tree = ast.parse(expression.strip(), mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Invalid formula syntax: {exc}") from exc

        ctx = {str(k).lower(): as_decimal(v) for k, v in context.items()}

        def _eval_node(node: ast.AST) -> Decimal:
            if isinstance(node, ast.Expression):
                return _eval_node(node.body)
            if isinstance(node, ast.Constant):
                if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                    raise ValueError(f"Disallowed constant type: {type(node.value).__name__}")
                return Decimal(str(node.value))
            if isinstance(node, ast.Name):
                name = node.id.lower()
                if name not in ctx:
                    raise ValueError(f"Unknown variable in formula: '{node.id}'")
                return ctx[name]
            if isinstance(node, ast.BinOp):
                op_func = ALLOWED_OPERATORS.get(type(node.op))
                if op_func is None:
                    raise ValueError(f"Disallowed operator: {type(node.op).__name__}")
                left, right = _eval_node(node.left), _eval_node(node.right)
                try:
                    return as_decimal(op_func(left, right))
                except ZeroDivisionError:
                    return Decimal("0")
                except (ArithmeticError, ValueError) as exc:
                    raise ValueError(f"Invalid formula arithmetic: {exc}") from exc
            if isinstance(node, ast.UnaryOp):
                op_func = ALLOWED_OPERATORS.get(type(node.op))
                if op_func is None:
                    raise ValueError(f"Disallowed operator: {type(node.op).__name__}")
                return as_decimal(op_func(_eval_node(node.operand)))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                fn_name = node.func.id.lower()
                if fn_name not in ALLOWED_FUNCTIONS or node.keywords:
                    raise ValueError(f"Disallowed function call: {ast.dump(node)}")
                args = [_eval_node(arg) for arg in node.args]
                try:
                    return as_decimal(ALLOWED_FUNCTIONS[fn_name](*args))
                except (ArithmeticError, ValueError, TypeError) as exc:
                    raise ValueError(f"Invalid formula function: {exc}") from exc
            raise ValueError(f"Disallowed expression element: {type(node).__name__}")

        return _eval_node(tree)

    @classmethod
    def evaluate_paise(cls, expression: str, context: Mapping[str, Any]) -> int:
        return round_paise(cls.evaluate_decimal(expression, context))

    @classmethod
    def evaluate(cls, expression: str, context: Mapping[str, Any]) -> float:
        """Backward-compatible float facade; do not use for money persistence."""
        return float(cls.evaluate_decimal(expression, context))

    @classmethod
    def validate_formula(cls, expression: str, sample_variables: list[str] | None = None) -> tuple[bool, str]:
        if not expression or not expression.strip():
            return False, "Formula expression cannot be empty"
        sample_ctx = {
            "basic": Decimal("10000"), "ctc": Decimal("50000"), "gross": Decimal("20000"),
            "hra": Decimal("4000"), "special": Decimal("2000"), "paid_days": Decimal("30"),
            "lop_days": Decimal("0"), "total_days": Decimal("30"),
        }
        if sample_variables:
            for variable in sample_variables:
                sample_ctx[variable.lower()] = Decimal("100")
        try:
            cls.evaluate_decimal(expression, sample_ctx)
            return True, "Valid formula"
        except Exception as exc:
            return False, str(exc)
