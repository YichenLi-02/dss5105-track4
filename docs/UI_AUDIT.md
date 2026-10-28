# UI audit: Student Work Assistant

This audit applies the `refactoring-ui` skill vendored in this repository ([.claude/skills/refactoring-ui](../.claude/skills/refactoring-ui), MIT licence, from edisonmbli/refactoring-ui-skill @ 4459662c). Section numbers (§) refer to that skill's references.

**Stack.** React and Vite with plain CSS: no Tailwind, no component library and no dark mode. The CSS variables inherited from the prototype are the existing design system, so the rules were mapped onto them. Brand colours were kept and no dependencies were added.

**Method.** Rendered screenshots were checked at 1280 px and 375 px widths, and contrast was measured with a small script.

## Summary

There were no P0 issues:

- All 14 text and background pairs reach 4.5:1.
- Every page has an empty state.
- Nothing overflows horizontally at 375 px.

The problems were systemic: spacing, type size, weight, radius and colour had no scale and had been tuned value by value.

## Systemic issues (fixed)

| # | Dimension | Rule | Before | After |
| --- | --- | --- | --- | --- |
| S1 | Type size | §4.1 | 10 sizes (10–23 px), neighbours about 8% apart | 5 steps: `--text-xs/sm/base/lg/xl` = 12/14/16/20/24 |
| S2 | Weight | §2.2.b | 5 weights (400/500/600/650/750) | 2: `--weight-normal` 400, `--weight-bold` 600 |
| S3 | Spacing | §3.2, §3.2.1 | 14 gap values, including 7/9/13/15/17/21 px | 7 steps `--space-1…7` = 4/8/12/16/24/32/48, each at least 25% apart |
| S4 | Radius | §1.4.3 | 8 values (4–99 px) | Controls 6, containers 12, pills 999 |
| S5 | Colour | §1.5, §5.2.1 | 16 hard-coded colours outside the variables | All named in `tokens.css`, values unchanged, 2 near-identical greys merged |
| S6 | Line height | §4.5 | All small text 1.7–1.9 | Body 1.6, headings 1.25 |

## Local issues (fixed)

| # | Dimension | Level | Where | Rule | Before | After |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Hierarchy | P1 | Mail status bar | §2.8 | *Refresh mail* and *Smart classification* were both dark primary buttons | Only *Smart classification* is primary; *Refresh mail* is secondary |
| 2 | Hierarchy | P1 | Mail cards | §2.4, §8.5.1 | Important mail had a red border, a pink background and a solid red tag, so 8 cards were all red | Important mail gets one red left edge only; the pink background is reserved for account-security notices and date conflicts |
| 3 | Hierarchy | P1 | Mail cards and detail | §2.5 | Real mail showed internal IDs, and times appeared in both ISO and local format | Internal IDs only on sample mail; one local time format, with ISO in a tooltip |
| 4 | Typography | P1 | Original mail text | §4.2.3, §4.3, §4.5 | Monospace, unlimited line length, line height 1.85, "blank line after every line" exports shown as is | Body font, 70ch measure, line height 1.6; `\r` removed and extra blank lines merged for display only (stored text and evidence offsets unchanged) |

Files changed: `src/frontend/src/styles/{tokens,prototype,app}.css`, `pages/MailPage.tsx`, `components/MailDetail.tsx` and `api/types.ts`. In the backend, `providers/mail_readers.py` now normalises line endings when storing synced mail.

## Not changed (left for later)

| # | Dimension | Level | Where | Rule | Now | Suggestion |
| --- | --- | --- | --- | --- | --- | --- |
| a | Hierarchy | P2 | Mail count cards | §2.1 | Academic, career and events showing 0 are as prominent as non-zero cards | Grey out or hide zero values |
| b | Colour | P2 | "Important" count card | §2.4 | The number uses danger red, while the card tag is neutral | Use `--ink` to match |
| c | Hierarchy | P2 | Task rows | §2.4 | "To check" and "No date" tags are both yellow | Keep status yellow; make date tags neutral |
| d | Finish | P2 | Account connections | §8.1 | Granted permissions show as a disabled button with ✓, which looks unavailable | Show a "Granted" status tag instead |

## Re-check

New screenshots at 1280 px and 375 px confirmed the result:

- Only one primary button remains.
- Important and warning states are now distinct.
- The original mail text is readable.
- Nothing overflows at 375 px.

## Later adjustments (2026-10-20)

- **Background:** changed to a light blue-grey (`--bg` #EEF2F7, `--soft` #F6F8FB, `--line` #DDE3EC). All light tints now share one blue-grey hue, so warm and cool greys are not mixed (§5.5.1). Dark text greys are unchanged.
- **Contrast re-measured:** grey text is 4.73:1 on the new background and 5.00:1 on the light surface, still above the 4.5:1 required by §5.6.
- **Important mail:** all important mail uses the red left edge (`.mail-card.important`) without a pink background. Pink stays reserved for account-security notices and date conflicts, so the list does not turn red (§2.4).
