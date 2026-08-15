# The ledger

One Markdown file per fact cluster. YAML frontmatter for machines, prose for
people. `_events.jsonl` is the append-only audit log of every mutation.

## Frontmatter

| field | meaning |
|---|---|
| `id` | stable identifier; agents cite it as `[id]` |
| `title` | one line, readable on its own |
| `kind` | `note` `decision` `risk` `metric` `person` `customer` |
| `owner` | the human accountable for this fact |
| `status` | `active` `superseded` `draft` — only `active` is retrieved by default |
| `tags` | free-form, used for filtering |
| `confidence` | 0–1, how much weight the summary should give it |
| `valid_from` | when the fact started being true |
| `source` | `manual` `email` `slack` `calendar` `agent` |
| `supersedes` / `superseded_by` | the audit chain |

## Updating a fact

Never edit a live fact in place from code. `behalf ingest --id <id>` archives
the current version as `<id>@<n>` with `status: superseded`, writes the new
content under the stable id, and appends an event. `behalf history <id>` walks
the chain.

Editing a file by hand is fine and expected — that is the point of the format.
The index picks the change up on the next `behalf index`.
