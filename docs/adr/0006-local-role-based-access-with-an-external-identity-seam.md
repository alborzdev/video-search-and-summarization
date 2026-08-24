---
status: superseded by ADR-0013
---

# Local role-based access with an external identity seam

CTAILabs Vision Intelligence will initially authenticate local accounts on Thor so it works offline at tradeshows and pilot sites. Operations Analyst and System Administrator roles separate operational work from sources, rules, retention, system health, and access management. Credentials and sessions must use production-grade security, while the authentication boundary remains replaceable by OIDC or customer SSO in a future deployment.
