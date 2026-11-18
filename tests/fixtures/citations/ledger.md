---
pr: 140
---

## Intent

Fix stock check for regular users. Source: PR body.

## Needs your call

### D-01 · Decision · made by: agent-alone · ✅ verified
Stock check calls `availability`.
Evidence: `lib/api.dart:6` "_products.ref(path: '$productId/availability')" · session 3f9a1c2e:L812
**Status:** pending

### D-02 · Unchanged · Caching · ✅ verified
Still remote-only.
Evidence: `lib/api.dart:8` "_api.stockRef(id).get()"
**Status:** pending

### D-03 · Behavior · ✅ verified
Wrong snippet.
Evidence: `lib/api.dart:11` "_fromCache(id)"
**Status:** pending

### D-04 · Decision · made by: plan
Missing file.
Evidence: `lib/gone.dart:3` "anything"
**Status:** pending

### D-05 · Tests · ✅ verified
Elided snippet across lines.
Evidence: `lib/api.dart:5` "Ref stockRef(int productId) => … ref(path:"
**Status:** pending

### D-06 · Scope · ✅ verified
Too far away (line 1 vs snippet on line 11).
Evidence: `lib/api.dart:1` "_api.stockRef(id).get()"
**Status:** pending

### D-07 · Decision · ✅ verified
Escapes the checkout.
Evidence: `../outside.txt:1` "x"
**Status:** pending

<details><summary>Verified FYI</summary>

### D-08 · Unchanged · Navigation · ✅ verified
Evidence: `lib/api.dart:1` "class Api {"
**Status:** pending

</details>
