---
id: security-finding
title: Pen test found a tenant-scoping gap in the export API
kind: risk
owner: vishnu
status: active
tags:
- security
- atlas
- blocker
confidence: 0.95
valid_from: '2026-08-12'
updated_at: '2026-08-12T14:02:00+00:00'
source: email
---

Third-party pen test, finding SEC-2026-11, high severity: the bulk export
endpoint authorises on the session tenant but resolves the object graph without
re-checking scope. A user in tenant A can enumerate object ids from tenant B.

No evidence of exploitation. Fix is understood and small, but it lands in the
same code path as the tenant isolation rework in [atlas-migration], so the two
have to ship together or not at all.

This is a GA blocker. It is not currently on the review agenda.
