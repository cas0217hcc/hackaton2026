// Pure helpers for unified diffs (no DOM): parse them and lay them out side by side.
// Loaded by the page before app.js; also loadable from Node for tests.
(function (root) {
  const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

  // -> { meta: ["--- a/x", "+++ b/x"], hunks: [{ header, lines: [{ type: "ctx"|"add"|"del", text, oldNo, newNo }] }] }
  // AI-written diffs often lack "@@" headers; those become one hunk with no line numbers.
  function parseDiff(text) {
    const result = { meta: [], hunks: [] };
    if (typeof text !== "string" || !text.trim()) return result;
    let hunk = null;
    let oldNo = null;
    let newNo = null;
    const open = (header, o, n) => {
      hunk = { header, lines: [] };
      result.hunks.push(hunk);
      oldNo = o;
      newNo = n;
    };
    const lines = text.replace(/\r\n/g, "\n").split("\n");
    if (lines.length && lines[lines.length - 1] === "") lines.pop();
    for (const line of lines) {
      const m = HUNK.exec(line);
      if (m) { open(line.trim(), Number(m[1]), Number(m[2])); continue; }
      if (!hunk && (line.startsWith("--- ") || line.startsWith("+++ ") || line.startsWith("diff ") || line.startsWith("index "))) {
        result.meta.push(line);
        continue;
      }
      if (line.startsWith("\\")) continue;  // "\ No newline at end of file"
      if (!hunk) open("", null, null);
      const sign = line[0];
      const body = line.slice(1);
      if (sign === "+") {
        hunk.lines.push({ type: "add", text: body, oldNo: null, newNo });
        if (newNo !== null) newNo++;
      } else if (sign === "-") {
        hunk.lines.push({ type: "del", text: body, oldNo, newNo: null });
        if (oldNo !== null) oldNo++;
      } else {
        hunk.lines.push({ type: "ctx", text: sign === " " ? body : line, oldNo, newNo });
        if (oldNo !== null) oldNo++;
        if (newNo !== null) newNo++;
      }
    }
    return result;
  }

  function diffStats(text) {
    let added = 0;
    let removed = 0;
    parseDiff(text).hunks.forEach((h) => h.lines.forEach((l) => {
      if (l.type === "add") added++;
      else if (l.type === "del") removed++;
    }));
    return { added, removed };
  }

  // One row per visual line: removed and added lines that follow each other are paired up.
  // -> [{ left: line|null, right: line|null }]
  function sideBySide(hunk) {
    const rows = [];
    let dels = [];
    let adds = [];
    const flush = () => {
      const n = Math.max(dels.length, adds.length);
      for (let i = 0; i < n; i++) rows.push({ left: dels[i] || null, right: adds[i] || null });
      dels = [];
      adds = [];
    };
    for (const l of hunk.lines) {
      if (l.type === "del") dels.push(l);
      else if (l.type === "add") adds.push(l);
      else { flush(); rows.push({ left: l, right: l }); }
    }
    flush();
    return rows;
  }

  const api = { parseDiff, diffStats, sideBySide };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.DiffLib = api;
})(typeof window !== "undefined" ? window : globalThis);
