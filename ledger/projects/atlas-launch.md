---
id: atlas-launch
title: 'Atlas GA date: 17 March no longer safe, 24 March realistic'
kind: decision
owner: Vishnu Rao
status: active
tags:
- curated
confidence: 0.8
valid_from: '2026-08-15'
updated_at: '2026-08-15T09:06:47+00:00'
source: cli
supersedes:
- atlas-launch@2
---

GA moved from 3 March to 17 March on 4 August. The trigger was the tenant
isolation rework landing two sprints later than planned, not scope creep — see
[atlas-migration].

As of 15 August that 17 March date no longer holds. Batch three has slipped a
week after the rollback rehearsal on a 60k-seat tenant failed twice, and Vishnu
Rao's position is that 17 March is no longer safe with 24 March the realistic
date. 24 March is Vishnu's judgement, not yet a booked or committed date — the
release train was booked against 17 March and the earlier "treat 17 March as
firm, no movement without a written scope cut" commitment is superseded by the
slip.

The 3 March → 17 March change was still never re-communicated to the design
partners who were told 3 March; Priya owns that message. It should now carry
the revised date rather than 17 March.
