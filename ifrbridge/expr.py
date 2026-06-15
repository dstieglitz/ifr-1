"""Tiny safe evaluator for MobiFlight transform expressions.

MobiFlight expressions in these configs are simple arithmetic/bitwise ops on a
single placeholder ``$`` (the incoming value), e.g. ``$``, ``$&16``,
``$&524288``. We evaluate them with a restricted AST whitelist — no names,
calls, or attribute access — so untrusted-looking strings can't execute code.
"""
from __future__ import annotations

import ast
import operator

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Invert: operator.invert,
}


def _eval_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        # Bitwise ops require ints; coerce cleanly.
        if isinstance(node.op, (ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift)):
            return _BIN_OPS[type(node.op)](int(left), int(right))
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        operand = _eval_node(node.operand)
        if isinstance(node.op, ast.Invert):
            return _UNARY_OPS[type(node.op)](int(operand))
        return _UNARY_OPS[type(node.op)](operand)
    raise ValueError(f"unsupported expression node: {ast.dump(node)}")


def evaluate(expression: str, value: float) -> float | int:
    """Evaluate a MobiFlight transform with ``$`` bound to ``value``."""
    if not expression or expression.strip() in ("$", ""):
        return value
    # Substitute the placeholder. Values can be negative, so wrap in parens.
    src = expression.replace("$", f"({value!r})")
    tree = ast.parse(src, mode="eval")
    return _eval_node(tree)
