from pathlib import Path


def test_all_package_modules_compile():
    package_root = Path(__file__).parents[1] / "w_agent"
    failures = []
    for source_file in package_root.rglob("*.py"):
        try:
            compile(
                source_file.read_text(encoding="utf-8"),
                str(source_file),
                "exec",
            )
        except Exception as exc:
            failures.append(f"{source_file}: {exc}")
    assert not failures, "\n".join(failures)
