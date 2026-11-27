"""CEDA 10.2: the domain layer is pure: no HTTP, database or vendor imports."""

import ast
import pathlib

DOMAIN = pathlib.Path(__file__).parents[2] / "src" / "astemia" / "domain"
FORBIDDEN = (
    "sqlalchemy",
    "fastapi",
    "pydantic",
    "mysql",
    "jwt",
    "httpx",
    "astemia.adapters",
    "astemia.application",
    "astemia.api",
)


def test_domain_imports_are_pure() -> None:
    offenders = []
    for path in DOMAIN.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [f"{path.name}: {n}" for n in names if n.startswith(FORBIDDEN)]
    assert offenders == []
