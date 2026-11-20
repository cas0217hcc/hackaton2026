import re
from collections import Counter
from pathlib import Path

JS = Path("migration_assistant/static/app.js").read_text()


def test_no_duplicate_top_level_functions():
    # A later duplicate silently overrides the earlier one in the browser.
    names = re.findall(r"^(?:async )?function (\w+)\(", JS, flags=re.M)
    dupes = [n for n, c in Counter(names).items() if c > 1]
    assert dupes == []


def test_row_run_button_state_is_set_before_the_finished_row_early_return():
    body = re.search(r"function updateRowStatus\(row\) \{(.*?)\n\}", JS, flags=re.S).group(1)
    assert body.index("row.runBtn.disabled") < body.index("if (row.ran) return;")
