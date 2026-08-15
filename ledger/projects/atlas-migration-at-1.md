---
id: atlas-migration@1
title: Tenant isolation rework is the critical path
kind: risk
owner: vishnu
status: superseded
tags:
- atlas
- engineering
- risk
confidence: 0.8
valid_from: '2026-07-29'
updated_at: '2026-08-15T09:06:47+00:00'
source: email
superseded_by: atlas-migration
---

Rewriting per-tenant key derivation touches the auth path for every existing
customer. Two of the four migration batches are done; the remaining two cover
the largest tenants, including Northwind.

Known unknowns: no rehearsal of the rollback path on a tenant above 50k seats,
and the batch window overlaps a frozen change period for two regulated
accounts.

If batch three slips, 17 March goes with it. That is the single dependency
worth watching between now and the review.
