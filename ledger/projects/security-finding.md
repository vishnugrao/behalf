---
id: security-finding
title: Pen test found a tenant-scoping gap in the export API
kind: risk
owner: Vishnu Rao
status: active
tags:
- atlas
- blocker
- curated
- security
confidence: 0.8
valid_from: '2026-08-15'
updated_at: '2026-08-15T10:21:36+00:00'
source: cli
supersedes:
- security-finding@1
---

Third-party penetration test finding SEC-2026-11 identified a high-severity tenant-scoping gap in the bulk export endpoint: the endpoint authorised on the session tenant but resolved the object graph without re-checking scope, allowing a user in tenant A to enumerate object IDs from tenant B.

There is still no evidence of exploitation.

The fix for SEC-2026-11 was originally understood to be small but coupled to the tenant isolation rework described in [atlas-migration], with an expectation that the two would ship together or not at all.

As of 15 August 2026, per Vishnu Rao, the SEC-2026-11 fix has been merged and has passed the penetration test re-test. The finding is now treated as closed and is no longer a GA blocker.
