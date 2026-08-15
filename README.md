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
./behalf who
```

`./behalf` is a launcher: on first run it creates `.venv`, installs the package
and copies `.env.example` to `.env`, then hands off. Every command below uses
it. There is nothing to activate and nothing installed globally.

It runs with no keys at all — retrieval falls back to a keyless embedder and the
agent to a scripted brain.

Prefer a real command on your PATH? Either activate the venv
(`source .venv/bin/activate`, then plain `behalf …`) or install it for your user
(`pipx install -e .`). `make <target>` also works for the common ones.

Add a model key to `.env` for real reasoning:

```bash
ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY=sk-...
BEHALF_EMBEDDER=openai           # optional, much better retrieval than the default
```

`BEHALF_PROVIDER=auto` prefers Anthropic, falls back to OpenAI, then to the
offline brain. Set it to `anthropic` or `openai` to pin one.

On OpenAI, `BEHALF_MAX_TOKENS` is a budget for **reasoning plus output** — a
reasoning model can spend most of it thinking and truncate the answer. The
default of 16000 leaves room; if you see a "response truncated" error, raise it
or drop `BEHALF_EFFORT` to `low`.

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
./behalf who
./behalf agent --persona marco --dry-run
```

## Update your store

```bash
./behalf note "batch three slipped a week, Northwind needs telling"
./behalf curate
./behalf search what blocks GA
```

`note` is deliberately dumb — it appends raw text to `state/captures.jsonl` and
returns. `curate` does the work: it retrieves the entries your note touches and
rewrites them, superseding rather than overwriting. Nothing is destroyed;
`./behalf history <id>` walks the chain.

In practice one note lands across several entries. A single "batch three
slipped" note updated `atlas-launch`, `atlas-migration` and
`northwind-escalation`, each with a recorded reason.

### Talking to your own store

`./behalf chat` is an agent wearing your persona, with your store and nothing
else. Ask it questions and it searches and reads before answering; tell it
something new and it captures that instead.

```
$ ./behalf chat
behalf · you are Vishnu Rao · brain anthropic:claude-opus-5 · store 10 entries

> when is GA and what could move it?
  · search('GA date launch timeline') ->
  · read ->
  · read ->

GA is not a booked date right now: 17 March is no longer safe after batch three
slipped on the failed rollback rehearsal, and 24 March is my judgement of
realistic [atlas-launch]. Main movers: further rollback failures, the tenant
isolation rework, and SEC-2026-11 [security-finding][atlas-migration].
```

It is bound to one persona and one store per process, the same isolation the
room runs on: it answers as you, from what *you* know, and says so plainly when
your store does not cover something rather than reaching for general knowledge.
Your colleagues' stores are invisible to it. `--persona` overrides who you are
for the session; `/raw <query>` shows unranked search hits, `/pending` lists
uncurated captures, `/quit` exits.

## Join the room

Each person, on their own machine:

```bash
./behalf agent                      # runs whoever `me` says you are
./behalf agent --persona priya      # or name it explicitly
```

To watch a three-person room on one laptop, three terminals:

```bash
./behalf agent --persona vishnu     # terminal 1, the scribe
./behalf agent --persona priya      # terminal 2
./behalf agent --persona marco      # terminal 3
```

Order does not matter — an agent waits for whoever is ahead of it in the roster.
The processes never talk to each other directly; they coordinate only through
the roster and the chatroom.

## The Google Doc

The scribe pushes the pre-read to one Google Doc and keeps rewriting that same
doc, so its URL is stable and you can leave it open in a tab.

### One-time Google setup

In the [Cloud Console](https://console.cloud.google.com), on one project:

1. Enable **both** APIs — [Google Docs API](https://console.cloud.google.com/apis/library/docs.googleapis.com)
   and [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com).
   Docs alone writes the document but **cannot share it**; you will get a 403
   naming the API to turn on.
2. Configure the OAuth consent screen (**Google Auth platform → Branding**).
   Audience **Internal** is fine for a team; **External** needs your address
   added under **Audience → Test users** or consent is refused.
3. Create an OAuth client, **Application type: Desktop app**.

Then give behalf the credentials, either way round:

```bash
GOOGLE_OAUTH_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=...
```

or drop the console's downloaded `credentials.json` in the repo root — behalf
picks it up automatically, and it is gitignored. The client id is not a secret;
the client secret is.

### First run

Consent needs a browser, so do this once on the scribe's machine before a real
session. **Pass the addresses to share with** — the doc is useless to everyone
else otherwise:

```bash
./behalf publish --share priya@example.com --share marco@example.com
```

That creates the doc, applies the formatting, shares it with those addresses
(sending them a notification), prints the URL, and caches the token at
`state/google-token.json` (mode 600). Every convergence after that rewrites the
same doc and re-shares with anyone new.

Recipients are gathered from all of: `--share` flags, any `email:` on a persona
in `config.yaml`, `google.share_with` in `config.yaml`, and `GOOGLE_SHARE_WITH`
in `.env`. If the list ends up empty, behalf says so rather than silently
publishing a doc only you can read.

### Pointing at an existing doc

Set `BEHALF_GDOC_ID` in `.env` to reuse one.

Scopes adapt to what you asked for, because per-file Drive access cannot see a
document this app did not create:

| | Docs scope | Drive scope |
|---|---|---|
| behalf creates the doc (`BEHALF_GDOC_ID` unset) | `documents` | `drive.file` — only the docs it made |
| you supply `BEHALF_GDOC_ID` | `documents` | `drive` — needed to share a doc it did not create |

If you set `BEHALF_GDOC_ID` after already consenting, the cached token is short
a scope. behalf notices and re-prompts; if you would rather avoid the broader
Drive scope, clear `BEHALF_GDOC_ID` and let it create the doc itself. To skip
Google entirely and write only `out/PREREAD.md`, pass `--no-doc`.

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
| `./behalf who` | the room, the turn order, and who you are |
| `./behalf note "..."` | capture an update, no structure required |
| `./behalf curate` | fold pending captures into your ledger |
| `./behalf chat` | agentic chat over your own store, in your voice |
| `./behalf search <q>` | hybrid search over your store |
| `./behalf history <id>` | walk an entry's supersede chain |
| `./behalf ingest` | direct write, for email/Slack adapters |
| `./behalf agent` | join the room as one person |
| `./behalf agent --dry-run` | show the resolved persona and prompt, then exit |
| `./behalf publish` | push the pre-read to the shared Google Doc |
| `./behalf preread` | print the current one-pager |

`./behalf --help` lists everything; `make help` lists the Make shortcuts.

## Layout

```
config.yaml     room, personas, convergence knobs
ledger/         your knowledge store (source of truth, commit this)
state/          index, capture log, Google token (derived, gitignored)
out/            PREREAD.md and transcripts
src/behalf/     the package
```
