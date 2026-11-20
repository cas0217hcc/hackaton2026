import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = Path("migration_assistant/static/app.js").read_text()


def test_no_duplicate_top_level_functions():
    # A later duplicate silently overrides the earlier one in the browser.
    names = re.findall(r"^(?:async )?function (\w+)\(", JS, flags=re.M)
    dupes = [n for n, c in Counter(names).items() if c > 1]
    assert dupes == []


def test_row_run_button_state_is_set_before_the_finished_row_early_return():
    body = re.search(r"function updateRowStatus\(row[^)]*\) \{(.*?)\n\}", JS, flags=re.S).group(1)
    assert body.index("row.runBtn.disabled") < body.index("if (row.ran) return;")


def test_the_model_row_of_the_ai_panel_is_not_hidden_in_the_page():
    # The model dropdown is used by every provider, so nothing may hide its row.
    html = (ROOT / "migration_assistant" / "templates" / "index.html").read_text()
    row = re.search(r'<div[^>]*id="ai-model-row"[^>]*>', html).group(0)
    assert "hidden" not in row
    assert "ai-model-row" not in JS or '$("ai-model-row").hidden' not in JS


def _body(name):
    return re.search(r"^(?:async )?function " + name + r"\([^)]*\) \{(.*?)\n\}", JS, flags=re.S | re.M).group(1)


def test_loading_the_group_list_hands_the_button_back_to_the_gates():
    # setLoading(false) re-enables the button, even without an Azure sign-in.
    body = _body("loadGroups")
    assert body.rindex("refreshGates()") > body.rindex('setLoading($("rg-refresh"), false)')


def test_stage_actions_do_not_start_while_another_stage_runs():
    for name in ("discover", "assess", "plan", "resetAll"):
        assert "running" in _body(name), name


def test_start_over_is_hidden_until_there_is_something_to_erase():
    html = (ROOT / "migration_assistant" / "templates" / "index.html").read_text()
    assert "hidden" in re.search(r'<button[^>]*id="reset-btn"[^>]*>', html).group(0)
    assert "btn.hidden = !hasResults()" in _body("refreshStartOver")
