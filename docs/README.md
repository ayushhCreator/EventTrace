# EventTrace — Documentation Index

## Folder Structure

```
docs/
├── phase1/     ← Active Phase 1 documents (start here)
├── phase2/     ← Future features (billing, orders, advocate portal)
└── archive/    ← Old session notes, deprecated docs
```

## Quick Links

### Strategy & Architecture (start here for big-picture decisions)
- [PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md) — **Full platform architecture**: data sources, court adapters, DB schema, jobs, notifications, scaling
- [STRATEGY_NATIONAL_EXPANSION.md](STRATEGY_NATIONAL_EXPANSION.md) — **What to build in what order**: Calcutta → Delhi → all HCs, eCourts integration phases
- [ARCHITECTURE_COURT_ADAPTER.md](ARCHITECTURE_COURT_ADAPTER.md) — **Court Adapter pattern**: how to add new courts, normalised schema, XHR research guide
- [ecourts_national_integration.md](ecourts_national_integration.md) — **eCourts technical deep dive**: CAPTCHA flow, reliability, cost analysis, all 25 HCs

### Phase 1 (current work)
- [SRS_BUSINESS.md](phase1/SRS_BUSINESS.md) — **Management SRS**: what we're building, why, pain points (non-technical)
- [TECH_SPEC.md](phase1/TECH_SPEC.md) — **Technical Spec**: how each feature works, what's pending, open questions
- [MASTER_STATUS.md](phase1/20_MASTER_STATUS.md) — Full feature checklist (built vs not built)
- [PRODUCT_STATUS.md](phase1/PRODUCT_STATUS.md) — Feature status with blockers and priority queue
- [DEPLOY.md](phase1/12_DEPLOY.md) — Deployment guide

### Phase 2 (future)
- [COMPLETE_SYSTEM_ARCHITECTURE.md](phase2/21_COMPLETE_SYSTEM_ARCHITECTURE.md) — Full architecture for billing, orders, AI layer

### Archive
- [Archive Index](archive/INDEX.md) — Old session notes and deprecated docs
