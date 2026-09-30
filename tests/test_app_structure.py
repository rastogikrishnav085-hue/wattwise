from pathlib import Path


def test_dashboard_declares_whatts_on_tab():
    source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    assert "tab_whatts" in source
    assert '"WhattsOn"' in source
