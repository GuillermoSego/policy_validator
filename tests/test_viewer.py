"""Smoke test: every viewer page renders from the committed outputs without errors."""

import pytest
from streamlit.testing.v1 import AppTest

from policy_validator.config import ROOT

VIEWER = str(ROOT / "app" / "viewer.py")


@pytest.mark.parametrize("view", ["Receipt list", "Receipt detail", "Metrics"])
@pytest.mark.parametrize(
    "system",
    [
        "Pipeline (LLM)",
        "Prompt ablation (no examples)",
        "Second model (Gemini Flash)",
        "Two-model agreement",
        "Keyword baseline",
        "Oracle ablation",
    ],
)
def test_viewer_pages_render(view, system):
    app = AppTest.from_file(VIEWER, default_timeout=30).run()
    app.sidebar.radio[0].set_value(view)
    app.sidebar.selectbox[0].set_value(system)
    app.run()
    assert not app.exception, app.exception
