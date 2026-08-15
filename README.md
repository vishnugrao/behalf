# behalf

Your own context store, and an agent that speaks **as you** in a shared room.

Everyone on the team runs this on their own laptop with their own persona and
their own knowledge store. You update your store from the CLI whenever you have
something. Your agent joins the shared chatroom, argues from what you know, and
the room converges on a **one-page pre-read** that lands in a shared Google Doc.

```
  you ──note──▶ capture log ──curate──▶ your ledger ──▶ hybrid retrieval
                                                              │
                                                        your agent ──┐
                                                                     ├──▶ chatroom ──▶ Google Doc
   your colleagues, same loop on their own laptops ────────────────┘
```

One process runs **one person**. Three people in the room means three launches,
on three machines — or three terminals if you are testing alone.

## Setup

```bash
git clone <this repo> && cd behalf
make setup
```

That creates a venv, installs `behalf`, copies `.env.example` to `.env`, and
indexes the sample ledger. It runs with no keys at all — retrieval falls back to
a keyless embedder and the agent to a scripted brain.

Add a model key to `.env` for real reasoning:

```bash
ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY=sk-...
BEHALF_EMBEDDER=openai           # optional, much better retrieval than the default
```

`BEHALF_PROVIDER=auto` prefers Anthropic, falls back to OpenAI, then to the
offline brain. Set it explicitly to pin one.

## Be someone

Open `config.yaml`. `personas` is the roster everyone shares — same list on every
machine, because list order is turn order and each agent needs to know who it is
waiting on. `me` is who *this* laptop is.

```yaml
me: vishnu

personas:
  - key: vishnu
    person: Vishnu Rao
    role: engineering lead
    email: vishnu@example.com
    remit: delivery risk, what is actually shippable and when
    obligation: Refuse dates your own entries do not support.
    scribe: true
```

`scribe: true` marks the one person whose agent writes the Google Doc when the
room converges. Check what you look like before joining:

```bash
behalf who
behalf agent --persona marco --dry-run
```

## Update your store

```bash
make note TEXT="batch three slipped a week, Northwind needs telling"
make curate
make search Q="what blocks GA"
make chat
```

`note` is deliberately dumb — it appends raw text to `state/captures.jsonl` and
returns. `curate` does the work: it retrieves the entries your note touches and
rewrites them, superseding rather than overwriting. Nothing is destroyed;
`behalf history <id>` walks the chain.

In practice one note lands across several entries. A single "batch three
slipped" note updated `atlas-launch`, `atlas-migration` and
`northwind-escalation`, each with a recorded reason.

## Join the room

Each person, on their own machine:

```bash
behalf agent                      # runs whoever `me` says you are
behalf agent --persona priya      # or name it explicitly
```

To watch a three-person room on one laptop, three terminals:

```bash
behalf agent --persona vishnu     # terminal 1, the scribe
behalf agent --persona priya      # terminal 2
behalf agent --persona marco      # terminal 3
```

Order does not matter — an agent waits for whoever is ahead of it in the roster.
The processes never talk to each other directly; they coordinate only through
the roster and the chatroom.

## The Google Doc

The scribe pushes the pre-read to one Google Doc and keeps updating that same
doc, so its URL is stable and you can leave it open.

**One-time Google setup.** In the [Cloud Console](https://console.cloud.google.com):
enable the **Google Docs API** and the **Google Drive API**, then create an
OAuth client of type **Desktop app**. Put both halves in `.env`:

```bash
GOOGLE_OAUTH_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=...
```

The client id is not a secret; the client secret is. `.env` is gitignored —
keep it that way.

**First run.** The first publish opens your browser for consent, then caches the
token at `state/google-token.json` (mode 600). Do this once on the scribe's
machine before a real session:

```bash
behalf publish --share teammate@example.com
```

That creates the doc, prints its URL, and shares it. After that, every
convergence rewrites the same doc in place. Add recipients any time:

```bash
behalf agent --share priya@example.com --share marco@example.com
```

Anyone with an `email:` in `config.yaml` is shared automatically, as is anything
under `google.share_with`. To point at an existing doc instead of creating one,
set `BEHALF_GDOC_ID` in `.env`. To skip Google entirely and write only
`out/PREREAD.md`, pass `--no-doc`.

Scopes requested are `documents` and `drive.file` — `drive.file` only grants
access to files this app created, not the rest of your Drive.

## Containers

One container is one person, same as one process:

```bash
make up PERSONA=priya
docker compose run --rm cli search launch date
```

`state/` is bind-mounted, so the OAuth token you created on the host is reused.
Do the browser consent on the host first — a container has nowhere to open it.

## How it works

**Ledger.** One Markdown file per fact cluster, YAML frontmatter for machines,
prose for people. Human-editable and `git diff`-able. Updating never overwrites:
the previous version is retired to `<id>@<n>` with `status: superseded` and the
chain stays walkable. `_events.jsonl` logs every mutation. See
[`ledger/README.md`](ledger/README.md).

**Retrieval.** Embedding cosine fused with BM25 by reciprocal rank. Dense alone
misses account names and entry ids; lexical alone misses paraphrase. Each agent
retrieves against a standing query (its remit) unioned with the live
conversation, so evidence it cited a moment ago does not vanish next turn.

The default `hashing` embedder needs no key and no download, and its scores sit
close together, so it gets half a vote in the fusion and the room leans lexical.
Set `BEHALF_EMBEDDER=openai` for real semantics.

**Protocol.** Each message is prose followed by one `<state>` JSON trailer
carrying intent, proposals with evidence, concerns and a ratify flag.
Convergence is computed from trailers; an agent that omits one is abstaining.

**Stopping.** Fixed round counts waste turns on easy topics and truncate hard
ones, and plain agreement is unsafe — rooms converge fast onto wrong answers
through social reinforcement. Three conditions must hold together:

1. **Stability** — no new distinct proposal for N rounds.
2. **Scrutiny** — a challenge was raised *and* answered.
3. **Ratification** — a supermajority ratified in their latest message.

A round cap backstops all three, and a page published on the cap says so and
names who did not ratify. One persona carries a standing obligation to object
before ratifying, so condition 2 is never vacuous.

## Commands

| | |
|---|---|
| `behalf who` | the room, the turn order, and who you are |
| `behalf note "..."` | capture an update, no structure required |
| `behalf curate` | fold pending captures into your ledger |
| `behalf chat` | interactive capture and lookup |
| `behalf search <q>` | hybrid search over your store |
| `behalf history <id>` | walk an entry's supersede chain |
| `behalf ingest` | direct write, for email/Slack adapters |
| `behalf agent` | join the room as one person |
| `behalf agent --dry-run` | show the resolved persona and prompt, then exit |
| `behalf publish` | push the pre-read to the shared Google Doc |
| `behalf preread` | print the current one-pager |

`make help` lists the Make targets.

## Layout

```
config.yaml     room, personas, convergence knobs
ledger/         your knowledge store (source of truth, commit this)
state/          index, capture log, Google token (derived, gitignored)
out/            PREREAD.md and transcripts
src/behalf/     the package
```
