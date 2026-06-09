from __future__ import annotations

import json
from pathlib import Path


def test_full_validation_notebooks_use_full_profile_and_no_src_notebook_package():
    notebooks = sorted(Path("notebooks").glob("*_full_validation_test.ipynb"))
    assert notebooks
    for path in notebooks:
        nb = json.loads(path.read_text(encoding="utf-8"))
        source = "\n".join("".join(cell.get("source") or []) for cell in nb.get("cells") or [])
        assert 'RUN_PROFILE = "full"' in source, path
        assert 'RUN_PROFILE = "balanced"' not in source, path
        assert "--profile balanced" not in source, path
        assert "Effective RUN_PROFILE: {RUN_PROFILE}" in source, path
    assert not (Path("src") / "camera_discovery" / "notebook").exists()
