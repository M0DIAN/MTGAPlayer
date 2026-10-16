# Read-only visual evidence

`visual_observation.py` accepts independently interpreted pixel counts and
separately sourced counts from the existing GRE projection. It does not identify
cards, parse GRE or infer game actions.

`visual_count` records a frame reference/hash, a visible value or `None`, and
visibility (`visible`, `partial`, `uncertain`). Coverage defaults to
`visible_subset`. `explicit_complete_coverage` requires a separate textual
coverage justification. A visible pile count is not a physical-card count;
attached, covered and animated objects must remain explicit limitations.

`gre_presence_count` always carries source `GRE` and visibility
`GRE_presence_only`. Its value is never filled into a visual observation.

`compare_counts` preserves both numeric values. Missing/unknown evidence remains
insufficient; changing GRE endpoints remain temporally uncertain. A visible
subset compared to a complete GRE zone returns `scope_mismatch`, even when the
numbers happen to match. Complete, justified coverage may establish observed
numeric agreement or disagreement within the collection bracket. Neither result
proves renderer synchronization, causality or a parser defect. The real frame309
case stays visually 5 versus GRE 6; the attached Aura is GRE evidence, not a sixth
independently recognized card. Capture events are never deduplicated by content
hash, because identical pixels at different times are distinct observations.

The local collector adds `diagnostics` to each screenshot index row. New capture
results explicitly distinguish pixel acquisition (`not_attempted`, `attempted`,
`succeeded`, `failed`) and the last capture stage from the overall result.
Quality thresholds and failed-quality refusal remain unchanged. A near-black
loading screen may have successful pixel acquisition and failed quality; it is
not thereby a usable battlefield observation. Legacy metadata without an
explicit pixel status stays `unknown`, even when a file is saved.

Freshness diagnostics retain capture clocks, file hash changes or repetition and
an optional GRE-progress observation. Repetition does not establish stale pixels;
GRE progress with repeated pixels is only uncertain. Changed pixels do not prove
current rendering either. Renderer time, source-to-render age and network delay
remain unknown. These diagnostics perform no OCR or independent visual review.
