# Deterministic shadow decision policy

`DecisionConsumer.shadow_decision()` explicitly opts into
`mtgaplayer.shadow-decision.v1`, policy `deterministic_shadow.v1`. The CLI adds
`shadow_decision` to Consumer diagnostics only when requested:

```powershell
python -m mtgaplayer watch <Player.log> --decision-events --decision-state-version 15 |
    python -m mtgaplayer consume-events --shadow-decision
```

State14 supplies Equip revision context;15 supplies Cast context, with the
existing parallel contracts. There is no new State/Event version. To inspect
the underlying options alongside the decision, also pass
`--current-decision-options`; both use the same MP65 cached collection/ref.

The four statuses are `research_preference`, `abstain`, `expired`, and
`unsupported`. A preference retains the current request binding, snapshot ref,
MP65 `preferred_option_key`, policy version, evidence level, validation scope,
basis and remaining unknowns. It is data for research. Every legality,
execution and input permission remains false, even after a local constraint
check. It provides no response payload or executable plan.

## Supported judgments

The first policy has two narrow preference cases:

- **Unique complete reviewed target proposal:** exactly one `final_target_set`
  option, locally verified and eligible for research; its existing Candidate v2
  source proves total=returned=1 under reviewed request constraints. Both global
  and source coverage must have no truncation or constructed omission, and no
  other option or observed constraint contradiction may compete. This does not
  establish a complete MTG target domain or strategic benefit.
- **Existing simple action heuristic:** directly reuse Advisor
  `simple_type_research.v1`. Its complete simple inventory/structure/identity
  checks and unique Play rule remain unchanged. Map its actual list position
  to exactly one current MP65 engine option with matching request/ref. This is
  the same unverified simple-type heuristic, not a new Play/Pass rule.

The policy never ranks evidence levels, object IDs, names or array positions.
One locally verified Cast row among unknown rows cannot win. Parent member
probes, target/payment associations and current-selected literal probes are
not whole final proposals. SelectN, Discard and combat inventory abstain even
when only one member is observed, because combination/tactical evidence is
missing. Other unsupported strategies stay unsupported. Unknown counts remain
null; they do not mean no legal action exists. All effects, complete payment,
response encoding, server acceptance, full legality and optimality stay unknown.

## Currentness and evidence

The existing Consumer owner flow calls `current_decision_options()`, reuses
Advisor where applicable and passes the existing before/after request/ref/lease
gate. A changed ref during assessment discards the result. No shadow preference
cache or `last_valid` fallback is retained. MP65's data cache cannot establish
freshness. Consumption, replacement, partial source, reset, identity changes,
expiry and stopping withdraw old preferences. Consumer diagnostics include
shadow results in the shared final sidecar check.

Returned dictionaries and queued diagnostics describe their bound observation;
they cannot mutate themselves when the game later changes. Callers must consume
revocations/recheck the current Consumer rather than treat stored output as
execution authority. An asynchronous or blocked output sink does not establish
freshness at the receiver's eventual read time.

The retained Cast103→104→105→106→107→109→110 chain always abstains or expires:
103 has multiple parent actions/probes;106 has four target proposals without
tactical evidence;107/110 consume requests, and109 cannot reuse106's Select
domain. Frozen Equip1402→1421→1422→1424→1425→1426 is checked independently under
State14/15:1422 permits the unique reviewed final-set research preference;
1425's own selected literal abstains and is no Submit proof. Consumed parents
stay historical. Existing public samples are unchanged; original Equip bytes
are checked by the owner verifier at each cutoff, not published or read by the
independent reviewer. See the [MP65 evidence boundaries](current-decision-options.md).

## Local measurement

`python scripts/measure_shadow_decision.py --samples 20 --output <report.json>`
reuses production watch/Publisher timings and existing performance quantiles.
Twenty fresh watcher sessions read the public Cast history102, then append
103/104/105/106/107/109/110, each through the same RawReducer, Publisher,
Consumer, MP65 and shadow API to flushed JSON output and controller validation.
Report groups distinguish startup history, incremental updates, Consumer time,
whole shadow API and instrumented pure policy interpretation. Production
timings are sampled once per poll at liveness; nested stages and quantiles are
never added. A separate positive Equip core measurement uses an already built
portable real state via synthetic transport, without replay inside its timer.

This is a controlled same-process local file path with an already running
interpreter, no scheduling delay, and no controlled OS cold-cache condition.
Pure core timing excludes MP65 generation, Advisor calculation and freshness
gates; the whole API and append-to-output timing include them. Raw durations,
sample counts, p50/p95/p99/max, code and fixture hashes are retained. These
measurements do not prove real MTGA end-to-end or three-second performance.
`input_sent=false`; `P10=NOT_RUN`.
