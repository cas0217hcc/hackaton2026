import re
from collections import Counter
from pathlib import Path

JS = Path("migration_assistant/static/app.js").read_text()


def test_no_duplicate_top_level_functions():
    # A later duplicate silently overrides the earlier one in the browser.
    names = re.findall(r"^(?:async )?function (\w+)\(", JS, flags=re.M)
    dupes = [n for n, c in Counter(names).items() if c > 1]
    assert dupes == []
