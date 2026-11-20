import json
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

SCRIPT = """
const d = require('./migration_assistant/static/diff.js');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(d[input.fn](...input.args)));
"""


def run(fn, *args):
    out = subprocess.run(["node", "-e", SCRIPT], input=json.dumps({"fn": fn, "args": list(args)}), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


DIFF = """--- a/app/main.py
+++ b/app/main.py
@@ -25,4 +25,3 @@
 from typing import Optional
-import old_one
-import old_two
+import new_one
 import os
"""


def test_parse_reads_meta_hunk_header_and_numbers_lines():
    d = run("parseDiff", DIFF)
    assert d["meta"] == ["--- a/app/main.py", "+++ b/app/main.py"]
    [h] = d["hunks"]
    assert h["header"] == "@@ -25,4 +25,3 @@"
    assert [(l["type"], l["oldNo"], l["newNo"], l["text"]) for l in h["lines"]] == [
        ("ctx", 25, 25, "from typing import Optional"),
        ("del", 26, None, "import old_one"),
        ("del", 27, None, "import old_two"),
        ("add", None, 26, "import new_one"),
        ("ctx", 28, 27, "import os"),
    ]


def test_parse_counts_additions_and_removals():
    assert run("diffStats", DIFF) == {"added": 1, "removed": 2}


def test_parse_handles_a_diff_without_hunk_headers():
    d = run("parseDiff", "-a\n+b\n c\n")
    [h] = d["hunks"]
    assert d["meta"] == [] and h["header"] == ""
    assert [(l["type"], l["oldNo"], l["newNo"]) for l in h["lines"]] == [("del", None, None), ("add", None, None), ("ctx", None, None)]


def test_parse_keeps_several_hunks_and_ignores_no_newline_markers():
    d = run("parseDiff", "@@ -1,1 +1,1 @@\n-a\n+b\n\\ No newline at end of file\n@@ -10,1 +10,1 @@\n-c\n+d\n")
    assert [h["header"] for h in d["hunks"]] == ["@@ -1,1 +1,1 @@", "@@ -10,1 +10,1 @@"]
    assert [len(h["lines"]) for h in d["hunks"]] == [2, 2]
    assert d["hunks"][1]["lines"][0]["oldNo"] == 10


def test_side_by_side_pairs_removed_and_added_lines():
    [h] = run("parseDiff", DIFF)["hunks"]
    rows = run("sideBySide", h)
    shape = [(r["left"] and r["left"]["text"], r["right"] and r["right"]["text"]) for r in rows]
    assert shape == [
        ("from typing import Optional", "from typing import Optional"),
        ("import old_one", "import new_one"),
        ("import old_two", None),
        ("import os", "import os"),
    ]


def test_side_by_side_leaves_the_left_empty_for_pure_additions():
    [h] = run("parseDiff", "@@ -1,1 +1,3 @@\n a\n+b\n+c\n")["hunks"]
    rows = run("sideBySide", h)
    assert [(r["left"] is None, r["right"] and r["right"]["text"]) for r in rows] == [(False, "a"), (True, "b"), (True, "c")]


def test_empty_or_garbage_input_gives_no_hunks_without_crashing():
    assert run("parseDiff", "")["hunks"] == []
    assert run("parseDiff", None)["hunks"] == []
