from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_python_package_and_console_entry_use_release_seal_identity() -> None:
    project = (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "releaseseal"' in project
    assert 'releaseseal = "releaseseal.cli:main"' in project
    assert (ROOT / "backend" / "src" / "releaseseal" / "api.py").is_file()
    assert not (ROOT / "backend" / "src" / ("creator" + "_preflight")).exists()


def test_current_product_sources_do_not_retain_old_identity() -> None:
    legacy_values = (
        "Creator" + " Preflight",
        "creator" + "-preflight",
        "creator" + "_preflight",
    )
    allowed_external_reference = ROOT / "docs" / "STATUS.md"
    found: list[tuple[Path, str]] = []
    roots = [ROOT / "backend", ROOT / "frontend" / "src", ROOT / "scripts", ROOT / "config", ROOT / "docs", ROOT / "README.md"]
    paths = [item for root in roots for item in ([root] if root.is_file() else root.rglob("*"))]
    for path in paths:
        if not path.is_file() or path.suffix in {".pyc", ".mp4", ".jpg", ".jpeg", ".png"} or any(part in {".venv", "node_modules", "dist"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for legacy in legacy_values:
            if legacy in text and path != allowed_external_reference:
                found.append((path.relative_to(ROOT), legacy))
    assert found == []
