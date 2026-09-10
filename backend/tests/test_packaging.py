from pathlib import Path
import tomllib


def test_openrouter_http_client_is_a_runtime_dependency():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert any(dependency.startswith("httpx") for dependency in project["dependencies"])
