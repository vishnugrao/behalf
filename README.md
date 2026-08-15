# behalf

A personal context store, and an agent that argues from it on your behalf.

Everyone on a team keeps their own store of what they know — updated whenever
they have something, not on a meeting schedule. Each person runs their own
agent process. The agents meet in a shared chatroom, argue from their
respective stores, and converge on a **one-page pre-read** that everyone needs
before the meeting starts.

```
  you ──note──▶ capture log ──curate──▶ ledger ──index──▶ hybrid retrieval
                                          │                      │
                                    audit trail            your agent ──┐
                                                                        ├─▶ chatroom ─▶ PREREAD.md
                              other people's machines: same loop  ──────┘
```

## Setup

```bash
git clone <this repo> && cd behalf
make setup
```

`make setup` creates a venv, installs the package, copies `.env.example` to
`.env`, and builds the index over the sample ledger. It works with no API key —
retrieval uses a keyless embedder and the agents fall back to a scripted brain.

For real reasoning, add one key to `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY=sk-...
BEHALF_EMBEDDER=openai           # optional: much better retrieval than the default
```

`BEHALF_PROVIDER=auto` picks Anthropic if its key is set, else OpenAI, else the
offline brain. Set it explicitly to pin one.

## Daily use

```bash
make note TEXT="batch three slipped a week, Northwind needs telling"
make curate                     # folds pending notes into ledger entries
make search Q="what blocks GA"
make chat                       # interactive: plain text captures, /ask searches
```

`note` is deliberately dumb — it appends raw text to `state/captures.jsonl` and
returns. `curate` is where the work happens: it retrieves the entries your note
touches and rewrites them, superseding rather than overwriting. Nothing is ever
destroyed; `behalf history <id>` walks the chain.

## Joining a room

Edit `config.yaml`. `me` is which agent this machine runs; `agents` is the
roster everyone shares, and list order is turn order.

```yaml
room:
  base: https://www.agentmeet.net/api/v1/<your-room-code>
  meeting: Atlas Q3 platform review
me: eng
agents:
  - key: eng
    name: Atlas-Eng
    principal: Vishnu Rao (engineering lead)
    remit: delivery risk, what is actually shippable and when
    obligation: Refuse dates the engineering entries do not support.
    scribe: true
```

Then, on your machine:

```bash
make agent          # runs the `me` agent and joins the room
make preread        # print the page once the room converges
```

Every participant runs that same command on their own machine against their own
ledger. The processes never talk to each other directly — they coordinate only
through the roster and the chatroom.

## Scaling test

`make scale AGENTS=5` starts five OS-isolated agent processes against one room
and reports wall clock, exit codes and whether the room converged. Agents past
the configured roster are synthesised from `scale_template`.

```bash
make scale AGENTS=8
cat out/scale-report.json
```

In containers, the same thing by replica:

```bash
make up AGENTS=5      # docker compose up --scale agent=5
make down             # stops and drops the state volume
```

Each replica picks its identity from its compose ordinal against the roster.

## How it works

**Ledger.** One Markdown file per fact cluster, YAML frontmatter for machines,
prose for people. Human-editable and `git diff`-able. Updating never overwrites:
the previous version is retired to `<id>@<n>` with `status: superseded` and the
chain stays walkable. `_events.jsonl` logs every mutation. See
[`ledger/README.md`](ledger/README.md).

**Retrieval.** Embedding cosine fused with BM25 by reciprocal rank. Dense alone
misses account names and entry ids; lexical alone misses paraphrase. RRF needs
no score calibration between them, which matters because the embedder is
swappable. Re-indexing is incremental — one edited file costs one embed call.

The default `hashing` embedder needs no key and no download, and its scores are
closely spaced, so it gets half a vote in the fusion and the room leans lexical.
Set `BEHALF_EMBEDDER=openai` for real semantics.

**Protocol.** Each chatroom message is prose followed by one `<state>` JSON
trailer carrying intent, proposals with evidence, concerns and a ratify flag.
Convergence is computed from trailers; an agent that omits one is abstaining.

**Stopping.** Fixed round counts waste turns on easy topics and truncate hard
ones, and plain agreement is unsafe — rooms converge fast onto wrong answers
through social reinforcement. Three conditions must hold together:

1. **Stability** — no new distinct proposal for N rounds.
2. **Scrutiny** — a challenge was raised *and* answered.
3. **Ratification** — a supermajority ratified in their latest message.

A round cap backstops all three. One agent carries a standing obligation to
challenge before it ratifies, so condition 2 is not vacuous.

## Commands

| | |
|---|---|
| `behalf note "..."` | capture an update, no structure required |
| `behalf curate` | fold pending captures into the ledger |
| `behalf chat` | interactive capture and lookup |
| `behalf search <q>` | hybrid search over the store |
| `behalf history <id>` | walk an entry's supersede chain |
| `behalf ingest` | direct write, for email/Slack adapters |
| `behalf roster` | show the room and who is in it |
| `behalf agent` | join the room as your agent |
| `behalf scale --agents N` | N process-isolated agents, with a report |
| `behalf preread` | print the current one-pager |

`make help` lists the Make targets.

## Layout

```
config.yaml          room, roster, convergence knobs
ledger/              the knowledge store (source of truth, commit this)
state/               index + capture log (derived, gitignored)
out/                 PREREAD.md, transcripts, scale reports
src/behalf/          the package
```
