from pathlib import Path


def test_dashboard_is_dark_only():
    text = Path("app.py").read_text(encoding="utf-8")
    assert '"light"' not in text
    assert '["Light", "Dark"]' not in text
    assert 'THEME = _THEME["dark"]' in text


def test_streamlit_theme_is_dark():
    text = Path(".streamlit/config.toml").read_text(encoding="utf-8")
    assert 'base = "dark"' in text
    assert 'base = "light"' not in text
