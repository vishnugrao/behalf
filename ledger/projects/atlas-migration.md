---
id: atlas-migration
title: Tenant isolation rework is the critical path — batch three has slipped a week
kind: risk
owner: Vishnu Rao
status: active
tags:
- curated
confidence: 0.8
valid_from: '2026-08-15'
updated_at: '2026-08-15T09:06:47+00:00'
source: cli
supersedes:
- atlas-migration@1
---

Rewriting per-tenant key derivation touches the auth path for every existing
customer. Two of the four migration batches are done; the remaining two cover
the largest tenants, including Northwind.

As of 15 August, batch three has slipped by a week. The rollback rehearsal on a
60k-seat tenant — previously listed here as an unrehearsed unknown above 50k
seats — was attempted and failed twice. That is the cause of the slip (Vishnu
Rao, 15 August).

Remaining known unknown: the batch window overlaps a frozen change period for
two regulated accounts, which are still not named anywhere.

The slip has now taken 17 March with it. Vishnu's read is that 17 March is no
longer safe and 24 March is the realistic GA date — see [atlas-launch].
