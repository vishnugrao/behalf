---
id: atlas-migration
title: Tenant isolation rework is the critical path
kind: risk
owner: vishnu
status: active
tags:
- atlas
- engineering
- risk
confidence: 0.8
valid_from: '2026-07-29'
updated_at: '2026-08-11T16:40:00+00:00'
source: email
---

Rewriting per-tenant key derivation touches the auth path for every existing
customer. Two of the four migration batches are done; the remaining two cover
the largest tenants, including Northwind.

Known unknowns: no rehearsal of the rollback path on a tenant above 50k seats,
and the batch window overlaps a frozen change period for two regulated
accounts.

If batch three slips, 17 March goes with it. That is the single dependency
worth watching between now and the review.
