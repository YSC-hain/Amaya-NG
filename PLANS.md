# PLANS.md — Execution Plan (ExecPlan) Template

Use this template before doing multi-step work.
The owner must approve the plan before implementation.

---

## 0) Summary
- Plan title:
- Why now:
- Success definition (1–3 bullet points):

## 1) Scope
### Goals
- G1:
- G2:

### Non-goals (explicitly not doing)
- NG1:
- NG2:

## 2) Current state (what exists today)
- Repo status:
- Constraints already decided:
- Unknowns / assumptions (must be confirmed if risky):

## 3) Proposed design
### Key concepts & terminology
- Term → meaning:

### Data / state model (if applicable)
- Files and formats:
- Source of truth:
- Derived artifacts:

### Runtime behavior (if applicable)
- Main flow:
- Edge cases:

### Prompting / tool contracts (if applicable)
- Tool list:
- Validation rules:
- “Honesty” constraints:

## 4) Phases (must be reviewable)
> Each phase ends in a working state.

### Phase 1 — (name)
**Deliverables**
- D1:
- D2:

**Acceptance criteria**
- AC1:
- AC2:

**Verification**
- How to verify quickly:
- Tests/commands (if any):

**Rollback**
- How to revert safely:

### Phase 2 — (name)
(Repeat same structure)

### Phase 3 — (name)
(Repeat same structure)

## 5) Risks & mitigations
- Risk:
  - Impact:
  - Mitigation:

## 6) Open questions for the owner (must answer before coding if blocking)
- Q1:
- Q2:

## 7) Owner approval checklist
- [ ] Goals/Non-goals match intent
- [ ] Phases are small enough to review
- [ ] Acceptance criteria are objective
- [ ] Risks are understood
- [ ] No blocked unknowns remain
