"""Regression guard for the silent loop-stop bug: run_career resets `backend_loop_stop = False` at
loop start, but that only clears the MODULE flag if backend_loop_stop is declared `global` in
run_career. Without it the reset makes a dead local, so after any Stop the flag stays True and the
next looped run does nothing. This asserts (via AST, no heavy main.py import) that run_career both
assigns backend_loop_stop AND declares it global.

Run:
    python tests/test_loop_stop_reset.py
    python -m pytest tests/test_loop_stop_reset.py
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_career_node():
    tree = ast.parse(open(os.path.join(ROOT, "main.py"), encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_career":
            return node
    raise AssertionError("run_career not found in main.py")


def test_run_career_declares_backend_loop_stop_global():
    fn = _run_career_node()
    assigns = any(
        isinstance(n, ast.Name) and n.id == "backend_loop_stop" and isinstance(n.ctx, ast.Store)
        for n in ast.walk(fn)
    )
    declared_global = any(
        isinstance(n, ast.Global) and "backend_loop_stop" in n.names for n in ast.walk(fn)
    )
    assert assigns, "run_career should reset backend_loop_stop at loop start"
    assert declared_global, (
        "run_career assigns backend_loop_stop but does NOT declare it `global` -> the reset is a dead "
        "local and looped runs silently no-op after a Stop"
    )
    print("loop-stop OK (run_career resets backend_loop_stop AND declares it global)")


if __name__ == "__main__":
    test_run_career_declares_backend_loop_stop_global()
