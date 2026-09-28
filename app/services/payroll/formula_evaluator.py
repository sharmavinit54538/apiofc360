"""Safe sandboxed formula evaluator using AST.

Evaluates mathematical pay component expressions WITHOUT using raw eval().
Supports allowed operators: +, -, *, /, //, %, **
Supports allowed variables: basic, ctc, gross, hra, special, paid_days, lop_days, total_days
Supports allowed functions: min, max, round, abs, ceil, floor
"""

from __future__ import annotations

import ast
import math
import operator
from decimal import Decimal
from typing import Any, Mapping

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

ALLOWED_FUNCTIONS = {
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
}


class SafeFormulaEvaluator:
    """Safely evaluates arithmetic expressions within a sandboxed context."""

    @classmethod
    def evaluate(cls, expression: str, context: Mapping[str, Any]) -> float:
        """Parse and evaluate an arithmetic formula safely.
        
        Args:
            expression: The formula string, e.g. "basic * 0.40 + 1000" or "min(basic * 0.5, 15000)"
            context: Dictionary of variable values (e.g. {"basic": 50000, "ctc": 1200000})

        Returns:
            Result as float.

        Raises:
            ValueError: If expression contains disallowed operations, syntax errors, or unallowed names.
        """
        if not expression or not expression.strip():
            return 0.0

        clean_expr = expression.strip()
        try:
            tree = ast.parse(clean_expr, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid formula syntax: {e}") from e

        # Normalize context keys to lower case for case-insensitivity
        ctx = {k.lower(): float(v) if isinstance(v, (int, float, Decimal)) else v for k, v in context.items()}

        def _eval_node(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return _eval_node(node.body)

            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)):
                    return float(node.value)
                raise ValueError(f"Disallowed constant type: {type(node.value).__name__}")

            if isinstance(node, ast.Name):
                var_name = node.id.lower()
                if var_name in ctx:
                    val = ctx[var_name]
                    if isinstance(val, (int, float, Decimal)):
                        return float(val)
                    raise ValueError(f"Variable '{var_name}' is not numeric")
                raise ValueError(f"Unknown variable in formula: '{node.id}'")

            if isinstance(node, ast.BinOp):
                op_func = ALLOWED_OPERATORS.get(type(node.op))
                if not op_func:
                    raise ValueError(f"Disallowed operator: {type(node.op).__name__}")
                left = _eval_node(node.left)
                right = _eval_node(node.right)
                try:
                    return float(op_func(left, right))
                except ZeroDivisionError:
                    return 0.0

            if isinstance(node, ast.UnaryOp):
                op_func = ALLOWED_OPERATORS.get(type(node.op))
                if not op_func:
                    raise ValueError(f"Disallowed operator: {type(node.op).__name__}")
                val = _eval_node(node.operand)
                return float(op_func(val))

            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    fn_name = node.func.id.lower()
                    if fn_name in ALLOWED_FUNCTIONS:
                        args = [_eval_node(arg) for arg in node.args]
                        return float(ALLOWED_FUNCTIONS[fn_name](*args))
                raise ValueError(f"Disallowed function call: {ast.dump(node)}")

            raise ValueError(f"Disallowed expression element: {type(node).__name__}")

        return _eval_node(tree)

    @classmethod
    def validate_formula(cls, expression: str, sample_variables: list[str] | None = None) -> tuple[bool, str]:
        """Validate formula syntax and allowed constructs without full evaluation."""
        if not expression or not expression.strip():
            return False, "Formula expression cannot be empty"

        sample_ctx = {
            "basic": 10000.0,
            "ctc": 50000.0,
            "gross": 20000.0,
            "hra": 4000.0,
            "special": 2000.0,
            "paid_days": 30.0,
            "lop_days": 0.0,
            "total_days": 30.0,
        }
        if sample_variables:
            for v in sample_variables:
                sample_ctx[v.lower()] = 100.0

        try:
            cls.evaluate(expression, sample_ctx)
            return True, "Valid formula"
        except Exception as e:
            return False, str(e)
