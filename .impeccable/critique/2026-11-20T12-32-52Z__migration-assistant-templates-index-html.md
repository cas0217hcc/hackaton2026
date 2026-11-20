---
target: UI/UX review of the migration assistant, focus on colour palette and usability
total_score: 23
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/home/caladoh/repos/hackaton_repo/migration_assistant/templates/index.html"
target_fingerprint: "sha256:dcdb873de715e3660cea4a2155bffcc7049a93fae766f0b1a6f260ab8fe6dabe"
target_path: /home/caladoh/repos/hackaton_repo/migration_assistant/templates/index.html
timestamp: 2026-11-20T12-32-52Z
slug: migration-assistant-templates-index-html
---
Method: dual-agent (A: design review · B: detector scan and contrast)

Score 23/40 (Acceptable). Target: migration_assistant/templates/index.html (+ static/app.js, static/style.css).

## Design health score
| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Visibility of system status | 3 | Run-all has no in-flight state; LIVE under-signalled |
| 2 | Match with the real world | 3 | Raw names like post/privateNetworks; {objectStorageId} unexplained |
| 3 | User control and freedom | 2 | Re-running Discover or Generate plan wipes later stages silently |
| 4 | Consistency and standards | 2 | Amber pill means Rebuild, Needs values and Skipped; confirm timers 4s vs 15s |
| 5 | Error prevention | 2 | LIVE run-all allowed with incomplete rows; Ready ignores unmet dependencies |
| 6 | Recognition over recall | 2 | Migrate rows never name the Azure resource; identical bucket rows |
| 7 | Flexibility and efficiency | 2 | No prefill, Enter does not run a row, no shortcuts |
| 8 | Aesthetic and minimalist design | 3 | Clean; Migrate table dense, labels wrap mid-word |
| 9 | Error recovery | 2 | Errors in a top banner far from the failing row |
| 10 | Help and documentation | 2 | Good inline hints; nothing says where IDs come from |
| Total | | 23/40 | Acceptable |

## Design specificity
Content authored (Direct/Rebuild/Included, Azure icons, chained-ID notes, diffs); shell generic (teal accent, grey canvas, white card, pills). Logo reads as a pasted sticker. No source-to-target picture.
Detector: source scan 1 advisory (flat-type-hierarchy: body 14, h1 17, h2 20). Rendered scans 2-3 per stage: nested-cards (fair on details.plan, false positive on div.scroll table frames), straggler on Assess description.
Contrast: all text passes 4.5:1. UI components under 3:1: input border 1.62, tr.needs input border 1.91, focus ring on header 2.58, step number ring 2.08, ghost button border 2.08.

## What's working
- Safety copy where the worry is (dry-run default, mode pill, "never changed", placeholders skipped).
- ID provenance notes and enum dropdowns with descriptions.
- Plan progress with per-resource chips.

## Proposed palette (Leaseweb brand)
- Brand strip: orange #e86826, 6px top strip, chrome only (white on it 3.3:1).
- Header bar: navy #04052f (white 19.7:1; secondary #b9bbdc 10.5:1). Logo on a white tab hanging from the strip.
- Action / active step / links / focus: indigo #2d2e86, hover #212266, tint #eaebf7 (white on indigo 11.4:1). Focus ring white on navy.
- Text #15173a / #50536f (17.3:1 / 7.5:1). Canvas #f3f4f9. Input border #8f93b3 (3:1).
- Succeeded (Direct, Sent 2xx, plan done): #17612f on #e0f1e6.
- Needs your work (Rebuild, Needs values): #7a5200 on #fdf0c8. Open choice: Rebuild as indigo tint instead.
- No action (Included, Dry run, Skipped, pending): #50536f on #e7e9f2.
- Ready: indigo outline. LIVE/danger: solid red #b3261e. Error: #a3201a on #fbe6e4 plus icon. Code blocks #04052f.

## Priority issues
1. [P1] LIVE run-all can send a dependency-broken partial set; button not locked in flight. Fix: readiness includes chain; disable run-all in LIVE until all rows ready; lock with "Sending 3 of 7". Command: /impeccable harden
2. [P1] LIVE and armed states too quiet. Fix: red band under header; inline confirm panel listing calls with Send and Cancel. Command: /impeccable harden
3. [P2] Status colours carry several meanings; grey Ready looks disabled. Fix: palette above. Command: /impeccable colorize
4. [P2] Migrate rows detached from their Azure resource; no prefill. Fix: "for <resource>" with icon under each call; prefill names from Azure. Command: /impeccable clarify
5. [P2] Re-running a stage silently wipes later stages. Fix: two-click pattern or inline note. Command: /impeccable harden

## Persona red flags
- Alex: types every name; Enter does nothing in value fields; 14 clicks for 7 live calls; Continue below the fold on Assess.
- Jordan: {objectStorageId} has no source hint; grey Ready reads disabled; stat chips look clickable but are inert; no done/next state after a run.
- Sam: header focus ring 2.6:1; done step is CSS-only; no aria-live on results, mode pill, progress; reset confirm expires in 4s; Run column off-screen at 390px.

## Minor observations
Expand all label stale after manual open; restored banner not dismissible; row errors go to top banner; title repeats "Leaseweb"; mobile header ~225px; long keys wrap mid-word; flat type scale.

## Questions to consider
- What if every Migrate row arrived Ready from Discover data?
- Should a key flip the whole app to LIVE, or should each live run be armed on its own?
- Where is Azure-to-Leaseweb as one before/after picture?
