# Feature Roadmap

Features for the Contract Intelligence Platform in two tracks:

- **Foundations (F1–F4):** capabilities the platform is missing that the novel features depend on. Not scored for novelty.
- **Novel features (1–12):** ranked by **uniqueness × impact** (each scored 1–5). Scores are judgement calls informed by a September 2026 scan of commercial contract-AI tools and recent research (sources at the end).

Bug fixes and quality improvements are tracked separately in [Bug fixes and improvements](#bug-fixes-and-improvements).

**Status (October 2026):** Feature 1, Cross-Contract Conflict Radar, has its MVP built on branch `Project1` and is in manual testing. Everything else is proposed.

Effort: **S** < 1 week, **M** 1–3 weeks, **L** 3–6 weeks, for one developer.

## Foundations

| ID | Feature | Priority | Effort | Risk | Unblocks | Status |
|---|---|---|---|---|---|---|
| F1 | Login and authentication | Before any multi-user demo or deployment | M | Medium | Production mode, 8, 11, every multi-user demo | Proposed |
| F2 | Contract library | Next | S–M | Low | 1 (pick any contract in the UI), 4, 6, 12 | Proposed |
| F3 | Full clause extraction on every upload | Next | M | Medium | Quality of 1, 2, 5, 6, 9 | Proposed |
| F4 | Review and admin console | After F1 | M | Low | Feedback data for 8; audit for compliance buyers | Proposed |

### F1. Login and authentication
- **Summary:** users sign in and every request carries a token that sets their role and tenant. HANDOVER.md names this the recommended first new feature.
- **Problem today:** production mode (`ENVIRONMENT=production`) requires a JWT, but nothing issues one, so the app cannot run in production. In development anyone can claim any role or tenant with request headers.
- **Persona:** every user; the deciding factor for any paid or shared deployment.
- **Acceptance criteria:**
  - `POST /api/auth/login` returns a token carrying `sub`, `role` and `tenant_id`; wrong credentials return 401 without saying which part was wrong.
  - A login page; every API call (including the chat stream) sends the token; a 401 returns the user to the login page; logout clears the session.
  - Tokens expire (60 minutes by default) and passwords are stored hashed, never in plain text.
  - Header-based auth stays available in development only (already enforced by `auth_mode()`).
- **Technical approach:**
  - Reuse `create_access_token` and the existing JWT validation in `backend/governance/rbac.py`; only token issuing is new.
  - Either a `(:User {email, password_hash, role, tenant_id})` node with a password-hashing library (new dependency, for example `bcrypt`), or an identity provider (Auth0, Keycloak, Azure AD) issuing the same claims. The provider route avoids storing passwords.
  - Frontend: one shared fetch wrapper that adds the `Authorization` header, replacing direct `fetch` calls in 6 files and the chat's `fetchEventSource` call.
- **Effort / risk:** M / medium (security-sensitive; needs rate limiting on login and careful token storage).
- **Monetization:** prerequisite for per-seat licensing and any multi-tenant offering.
- **Prototype plan:** `/api/auth/login` with two seeded users in two tenants (an ADMIN and a VIEWER); move the frontend onto the shared fetch wrapper; run locally with `ENVIRONMENT=production` and confirm each user sees only their tenant's contracts.

### F2. Contract library
- **Summary:** a server-side, tenant-scoped list of contracts with search and filters, and a contract picker in the UI.
- **Problem today:** the UI only knows contracts uploaded in the current browser (stored in `localStorage`). Teammates can't see each other's uploads, seeded demo contracts can't be selected, and the Conflict Radar's governing-contract field only suggests local uploads. The old contracts list API (`backend/api/contracts.py`) was removed.
- **Persona:** every user; contract managers in particular.
- **Acceptance criteria:**
  - `GET /api/contracts` returns the caller's tenant's contracts with name, type, upload date, analysis status and risk level; paginated; filterable by name and contract type.
  - A Contracts page and a reusable picker; the Intelligence page and the Conflict Radar use the picker instead of browser history.
  - Another tenant's contracts never appear (tenant filter on every query, covered by tests).
- **Technical approach:** a read-only repository query on `(:Contract {tenant_id})` ordered by `created_at`, which the existing `contract_tenant_date` index already serves; `VIEW_REPORTS` permission; keep `localStorage` only as a "recent" shortcut.
- **Effort / risk:** S–M / low.
- **Monetization:** core tier; table stakes.
- **Prototype plan:** the list endpoint first, then replace the Conflict Radar's governing-contract field with the picker so the seeded demo contracts can be selected in the UI.

### F3. Full clause extraction on every upload
- **Summary:** every upload gets LLM-based section and clause extraction with classification into the 41 CUAD clause types, not just keyword matching.
- **Problem today:** a normal upload finds clauses with regular expressions for 6 types (payment, liability cap, governing law, termination for convenience, non-compete, IP). Conflicts, financial terms and policy breaches in any other clause type are invisible to features 1, 2 and 5. The full extraction exists only behind `?enable_enhanced=true`.
- **Persona:** indirect; it raises the quality of every analysis feature.
- **Acceptance criteria:**
  - After a normal upload, clauses are classified into CUAD types with a confidence score.
  - Measured on a CUAD sample: recall and precision per clause type reported (shared harness with feature 10).
  - Upload response time does not grow; extraction runs in the background like embeddings, with its progress visible.
  - No duplicate clause nodes when both pipelines have run.
- **Technical approach:** reuse the enhanced pipeline's section and clause agents and `CUADClassifierAgent` (`backend/agents/cuad_classifier_agent.py`, 41 types) as a background step after upload; merge with or replace the regex clauses; depends on the Section/Clause ID clean-up (bug B4).
- **Effort / risk:** M / medium (LLM cost per upload; mitigate with a size limit and caching).
- **Monetization:** quality driver for every tier.
- **Prototype plan:** run the CUAD classifier in the background on `Clean_MSA.pdf` and `Clean_SOW.pdf`; compare clause counts and types before and after; re-run the Conflict Radar on the pair and compare findings.

### F4. Review and admin console
- **Summary:** screens for the features that today exist only as API: lawyer feedback and learned patterns, the audit trail, monitoring, supervisor workflows and batch analysis.
- **Problem today:** 32 API endpoints have no screen. Features 5 and 12 cover policies and the dashboard; nothing covers the rest.
- **Persona:** legal reviewers (feedback), auditors (audit trail), admins (monitoring, batch runs).
- **Acceptance criteria:**
  - Feedback: record accept / reject / modify decisions on findings and see learned patterns per clause type.
  - Audit: search the trail by contract and view error statistics; visible only to roles with `VIEW_AUDIT`.
  - Monitoring: performance, alerts and cache status; batch analysis of up to 10 contracts with progress.
  - Each screen hidden from roles that lack its permission.
- **Technical approach:** frontend only, on the existing `/api/feedback/*`, `/api/audit/*`, `/api/monitoring/*`, `/api/supervisor/*` and `/api/intelligence/contracts/batch-analyze` endpoints, using the F1 fetch wrapper and role claims.
- **Effort / risk:** M / low.
- **Monetization:** audit trail and feedback analytics support an enterprise or compliance tier.
- **Prototype plan:** the audit-trail screen first (one existing endpoint, smallest scope), then feedback, then monitoring and batch analysis.

## Novel features

### Ranking

| # | Feature | Uniqueness | Impact | Score | Effort | Risk | Group | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | Cross-Contract Conflict Radar | 5 | 5 | 25 | M–L | Med | A | **MVP built** |
| 2 | Contract Stress Test | 5 | 4 | 20 | M | Med | A | Proposed |
| 3 | Strategic Negotiation Copilot | 5 | 4 | 20 | L | High | C | Proposed |
| 4 | Amendment Time Machine | 4 | 4 | 16 | M | Low | D | Proposed |
| 5 | Explainable Policy Compiler | 4 | 4 | 16 | M–L | Med | A | Proposed |
| 6 | Regulatory Blast Radius | 4 | 4 | 16 | M | Med | C | Proposed |
| 7 | Obligation Ledger and Deadline Agent | 3 | 5 | 15 | M | Low | D | Proposed |
| 8 | Counterparty Behavior Graph | 5 | 3 | 15 | M | High | C | Proposed |
| 9 | Evidence-Backed Redlines | 3 | 4 | 12 | S–M | Low | B | Proposed |
| 10 | Trust Scorecard | 3 | 4 | 12 | S–M | Low | B | Proposed |
| 11 | Agent-to-Agent Contract Intake | 4 | 3 | 12 | S–M | Med | D | Proposed |
| 12 | Portfolio Exposure Dashboard | 2 | 4 | 8 | S | Low | D | Proposed |

### Which MVPs set the project apart

A feature's MVP qualifies when commercial tools don't offer it, it builds on assets the project already has (Neo4j graph, CUAD tools, policy engine, feedback data, MCP server), it demos well, and one developer can build it in about three weeks.

- **A. Signature differentiators (build):** 1 Conflict Radar, 2 Stress Test, 5 Policy Compiler.
- **B. Credibility multipliers (make A believable):** 10 Trust Scorecard, 9 Evidence-Backed Redlines.
- **C. Strong, but too big or data-hungry for an MVP:** 3 Negotiation Copilot, 8 Counterparty Behavior Graph, 6 Regulatory Blast Radius.
- **D. Foundations (useful, not distinctive):** 7 Obligation Ledger, 4 Amendment Time Machine, 12 Portfolio Dashboard, 11 Agent-to-Agent Intake.

**Recommended MVP set: 1 + 2 + 5 + 10** (about 7–9 developer-weeks). Together they make one demo on the sample files in `data/`:

1. Upload `Clean_MSA.pdf` and `Clean_SOW.pdf`.
2. Conflict Radar: the SOW contradicts the MSA on the liability cap and payment terms.
3. Stress Test: a 45-day supplier delay costs $X–$Y, citing the clauses that set it.
4. Policy Compiler: three playbook rules breached, each with its rule, question, answer and evidence.
5. Trust Scorecard: confidence per finding, with low-confidence items sent for human review.

### Build order

1. **§1 Conflict Radar** (MVP built).
2. **F3 Full clause extraction** and **F2 Contract library**: both directly improve the shipped Conflict Radar.
3. **§10 Trust Scorecard**, so the remaining features are measured as they are built.
4. **§5 Policy Compiler**, then **§2 Stress Test**.
5. **F1 Login** before any multi-user demo or deployment; **F4 console** after it.

### Feature details

Every feature lists the same nine fields: summary, novelty, persona, acceptance criteria, technical approach, effort, risk, monetization and prototype plan.

#### 1. Cross-Contract Conflict Radar — MVP built
- **Summary:** finds contradictions inside related contracts, such as a SOW that contradicts its MSA or clashing exclusivity or pricing promises to the same party, showing both clauses, the conflict type, severity and a suggested fix.
- **Novelty:** LLMs alone miss subtle conflicts and flag false ones (CLAUSE benchmark, 2026), and published tools such as LegalWiz check one document at a time. Letting the contract graph choose candidate clause pairs and the LLM judge them is rare.
- **Persona:** in-house counsel or a contract manager handling master agreements with many work orders.
- **Acceptance criteria:** contracts can be linked parent → child (MSA → SOW); a check returns conflicts with type, both clause texts and severity; ≥ 70% recall and ≥ 60% precision on planted conflicts; under 60 s per contract pair.
- **Technical approach:** `(:Contract)-[:GOVERNED_BY]->(:Contract)`; candidate pairs are same-type clauses or clauses with cosine similarity ≥ 0.80, capped at 25 per check; the LLM judges each pair and a skeptical second pass verifies it; confirmed findings stored as `(:Clause)-[:CONFLICTS_WITH]->(:Clause)`.
- **Effort:** M–L.
- **Risk:** medium; false positives, reduced by the verification pass and by showing evidence rather than verdicts.
- **Monetization:** premium "Portfolio" tier, or an add-on priced per checked contract family.
- **Prototype plan:** `Clean_MSA.pdf` and `Clean_SOW.pdf` with 10 hand-planted conflicts; script first, then API, then UI panel.
- **What shipped (MVP):**
  - API: `PUT /api/intelligence/contracts/{id}/governing-contract`, `POST` and `GET /api/intelligence/contracts/{id}/conflicts`.
  - Results are saved atomically and tenant-scoped; partial failures and the pair cap are reported, never hidden.
  - Automated, idempotent schema migration at startup (`backend/migrations/runner.py`); seed data with planted conflicts (`python -m backend.migrations.runner seed`).
  - UI panel on the Intelligence page; 41 unit and BDD-style tests.
- **Known limitations (MVP):**
  - The seed data has no clause embeddings, so only same-type pairing is exercised by the demo and the offline tests; similarity-based pairing (≥ 0.80) runs only on real uploads.
  - Pairing depends on extracted clauses: a normal upload recognises only 6 clause types until F3 ships.
  - If the governing contract is re-linked while a check is running, the stored conflict count can differ from the stored conflicts; this is logged as a warning.
  - Conflicts within a single contract and suggested links are not in the MVP (planned for v1).
  - The UI can only select contracts uploaded in the same browser until F2 ships; the API works with any contract.

#### 2. Contract Stress Test
- **Summary:** "what if" scenarios such as "the supplier is 45 days late", "we terminate in year 2" or "a data breach costs $2M", priced from the contract's own liability caps, service credits, penalties and termination fees.
- **Novelty:** contract tools flag risky clauses but don't calculate what a scenario would cost; this turns risk scores into money amounts.
- **Persona:** CFO, finance partner or procurement lead.
- **Acceptance criteria:** financial terms (caps, credits, fees, notice periods) extracted with their source clauses; 5 built-in scenarios plus custom ones; results show the exposure range and calculation steps citing clauses; within 10% of a lawyer's hand calculation on 8 of 10 test contracts.
- **Technical approach:** the LLM extracts terms into a typed schema (extending `intelligence_tools.py`); a deterministic Python calculator does the maths, never the LLM; the LLM only turns a free-text scenario into parameters; terms stored as `(:FinancialTerm)` nodes for reuse by feature 12.
- **Effort:** M.
- **Risk:** medium; contract wording varies, so the calculator answers "not determinable" rather than guess.
- **Monetization:** CFO add-on; strong sales demo.
- **Prototype plan:** three term types (liability cap, service credits, termination fee) and two scenarios on the four sample contracts, in a notebook first, then as an endpoint.

#### 3. Strategic Negotiation Copilot
- **Summary:** takes in the other side's redlines and applies the playbook's preferred and fallback positions with an explicit priority model: concede low-value points to win high-value ones, escalate anything outside the playbook, and draft replies.
- **Novelty:** a May 2026 paper found LLM negotiators understand what the other side wants but don't use it strategically; deals drift to the opening offers. An explicit priority model targets exactly that weakness.
- **Persona:** contract manager or sales-legal team working through many deals.
- **Acceptance criteria:** reads a redlined DOCX or a before/after PDF pair; maps each change to a playbook rule; proposes accept, counter or escalate with a reason; keeps more weighted value on our priorities than an LLM-only baseline in simulated negotiations; every escalation goes to a human.
- **Technical approach:** priority weights and fallback levels added to each `PolicyRule`; the LLM classifies each change, a solver (greedy knapsack or OR-Tools) picks the concession set, the LLM writes counter-language; every decision logged to the feedback API (feeds feature 8).
- **Effort:** L.
- **Risk:** high; legal liability requires human approval on everything, and quality depends on the playbook.
- **Monetization:** core of a "Negotiation" tier, priced per seat.
- **Prototype plan:** NDA only with a 10-rule playbook; a simulated counterparty (another LLM) plays 20 negotiations with and without the solver.

#### 4. Amendment Time Machine
- **Summary:** links amendments, renewals and replaced versions to the original contract and shows the terms in force on any date, clause by clause, each citing the document that set it.
- **Novelty:** the terms in force today are spread across several amendments; a version graph answers "what applies now?" without anyone reading them all.
- **Persona:** contract manager or auditor.
- **Acceptance criteria:** an uploaded amendment is linked to its original (manual confirmation is fine); "terms as of" any date; every term cites its source document.
- **Technical approach:** `AMENDS` and `SUPERSEDES` relationships with effective dates; the LLM maps each amendment clause to the original clause as replace, add or delete; the "as of" view is a Cypher query taking the latest effective version up to the chosen date.
- **Effort:** M.
- **Risk:** low.
- **Monetization:** core tier; drives retention.
- **Prototype plan:** write two amendments for `Salesforce_MSA.pdf` and build a timeline view.

#### 5. Explainable Policy Compiler
- **Summary:** compiles policy playbooks into typed rules plus small, targeted extraction questions; the LLM answers the questions and a deterministic rule checker decides compliance.
- **Novelty:** follows PolicyGuard (2026). Today's policy check asks the LLM for an overall judgement, which is opaque and can change between runs; compiled rules are traceable, testable and the same every run.
- **Persona:** compliance officer or legal ops.
- **Acceptance criteria:** each policy compiles to rules you can view and edit; each result shows rule → question → answer → evidence; the same contract always gives the same result; each rule can have its own tests.
- **Technical approach:** extend `PolicyWorkflowOrchestrator` to output a small rule language (JSON logic); a checker service; a rule editor UI, which also gives the nine policy endpoints a screen.
- **Effort:** M–L.
- **Risk:** medium; some policies can't be expressed as rules, so they fall back to the LLM and are labelled.
- **Monetization:** compliance tier with audit-ready reports.
- **Prototype plan:** compile `data/Contract_Policy_Playbook.pdf` and compare results with the current checker on the four sample contracts.

#### 6. Regulatory Blast Radius
- **Summary:** when a regulation or internal policy changes, find every affected contract and clause, rank them by exposure and draft remediation redlines in bulk.
- **Novelty:** tools either monitor regulations or review contracts; few connect the two into one portfolio-wide query.
- **Persona:** compliance officer or general counsel.
- **Acceptance criteria:** entering a change produces a ranked list of affected contracts with clauses and a draft redline each; ≥ 80% of affected contracts found on a seeded test set.
- **Technical approach:** split the regulation into requirements; match clauses by embedding similarity plus CUAD type; reuse the redline generator; run as a batch job on `/batch-analyze`.
- **Effort:** M.
- **Risk:** medium; depends on matching quality and needs a sizeable portfolio to show value.
- **Monetization:** compliance-tier add-on.
- **Prototype plan:** one scenario, such as a new data-transfer rule, run against the sample contracts plus 20 contracts from `research/import-graph`.

#### 7. Obligation Ledger and Deadline Agent
- **Summary:** extracts every obligation and date (renewals, notice periods, payments, SLAs) into a ledger; a scheduled agent sends alerts ahead of deadlines, with a calendar export.
- **Novelty:** low, since commercial tools have it; impact is high because it is the platform's most obvious gap.
- **Persona:** contract manager, or the business owner responsible for a contract.
- **Acceptance criteria:** ≥ 90% of dates found on the test set; alerts at 90, 30 and 7 days; `.ics` calendar export; a "what we owe this month" view.
- **Technical approach:** `(:Obligation {due, owner, type})` nodes, an APScheduler job, email or webhook notifications; its term extraction is shared with feature 2.
- **Effort:** M.
- **Risk:** low.
- **Monetization:** core tier; expected by buyers.
- **Prototype plan:** extract dates from the four sample PDFs into a list view.

#### 8. Counterparty Behavior Graph
- **Summary:** learns from past negotiations and lawyer decisions what each counterparty usually accepts and resists, predicts a proposed clause's chance of acceptance and suggests the fallback most likely to land.
- **Novelty:** high; it uses the organization's own deal history, which no outside tool has.
- **Persona:** deal desk or sales-legal team.
- **Acceptance criteria:** a profile per counterparty (accepted and resisted clause types); an acceptance likelihood per redline; predictions beat chance after 50+ decisions.
- **Technical approach:** counterparty features added to `feedback_learning_system.py`; a simple logistic model per clause type; industry-wide averages as the cold-start fallback.
- **Effort:** M.
- **Risk:** high; needs plenty of history, and each tenant's data must stay separate.
- **Monetization:** enterprise tier.
- **Prototype plan:** a synthetic history of 200 decisions to validate the approach.

#### 9. Evidence-Backed Redlines
- **Summary:** each suggested redline cites clauses the organization already approved and signed, with how often similar language was accepted.
- **Novelty:** medium; turns "the AI suggests" into "you agreed to this language in 12 signed deals".
- **Persona:** legal reviewer.
- **Acceptance criteria:** ≥ 80% of redlines include 1–3 portfolio citations with a similarity score; clicking a citation opens the source.
- **Technical approach:** reuse the MCP tool `search_prior_approved_clauses` inside `RedlineGenerator`.
- **Effort:** S–M.
- **Risk:** low.
- **Monetization:** core tier.
- **Prototype plan:** upload the sample contracts first so there is history to cite.

#### 10. Trust Scorecard
- **Summary:** each finding shows calibrated confidence, benchmarked on public datasets (CUAD, ContractNLI); low-confidence findings say "needs human review" instead of guessing.
- **Novelty:** medium; honest uncertainty is rare in legal AI and makes a strong capstone point.
- **Persona:** a risk-averse general counsel, or capstone reviewers.
- **Acceptance criteria:** a benchmark script reports precision and recall per clause type; expected calibration error below 0.1; a confidence badge per finding in the UI.
- **Technical approach:** an evaluation harness under `research/benchmark/`; self-consistency sampling to estimate confidence; a per-type threshold for when to abstain. Shared with F3's quality measurement.
- **Effort:** S–M.
- **Risk:** low.
- **Monetization:** builds trust; supports enterprise sales.
- **Prototype plan:** 50 CUAD contracts and 5 clause types.

#### 11. Agent-to-Agent Contract Intake
- **Summary:** MCP tools such as `submit_contract`, `get_review` and `propose_redline` so external AI agents can send contracts in and get reviews back; a human approves anything that leaves the system.
- **Novelty:** medium-high; matches the 2026 trend of agents negotiating over MCP, and the MCP server already exists.
- **Persona:** procurement or sales-ops teams automating contract intake.
- **Acceptance criteria:** an external client submits a contract and receives a review; every outgoing redline needs approval; every action is written to the audit log.
- **Technical approach:** extend `backend/mcp_server.py` with write tools, keep `MCP_TENANT_ID` pinning, add an approval queue. Requires F1 first, because the server would accept writes.
- **Effort:** S–M.
- **Risk:** medium; accepting writes from outside raises security questions.
- **Monetization:** API usage pricing.
- **Prototype plan:** demo with Claude Desktop as the external agent.

#### 12. Portfolio Exposure Dashboard
- **Summary:** a portfolio-wide view: how many contracts have uncapped liability, single-supplier concentration, governing-law mix and the risk trend over time.
- **Novelty:** low, but cheap, and it gives the unused dashboard and batch endpoints a screen.
- **Persona:** general counsel or CFO.
- **Acceptance criteria:** six portfolio charts; filters by contract type and counterparty; drill-down to individual contracts.
- **Technical approach:** Cypher aggregations behind the existing `/api/intelligence/dashboard/summary`, plus frontend charts.
- **Effort:** S.
- **Risk:** low.
- **Monetization:** core tier.
- **Prototype plan:** one page on the existing summary endpoint.

### Top three: roadmap and validation

#### 1. Cross-Contract Conflict Radar
| Stage | Scope |
|---|---|
| MVP (built) | Manual MSA → SOW link; same-type and high-similarity pairs; two-pass judgement; side-by-side panel |
| v1 | Suggested links, conflicts inside a single contract, severity scoring, one-click fix redlines |
| v2 | Portfolio-wide scan on every upload, amendments included (after feature 4) |

**Two-week validation.** Hypothesis: graph-selected pairs plus verification find more planted conflicts, with fewer false alarms, than one prompt over both whole documents. Set-up: `Clean_MSA`/`Clean_SOW` plus 9 CUAD pairs, 30 planted conflicts across 6 types, both approaches scored. Success: recall ≥ 70%, precision ≥ 60%, 15+ points better than the baseline; reviewers rate ≥ 70% of flags useful. Week 1: dataset and baseline. Week 2: pipeline, scoring, reviewer ratings.

#### 2. Contract Stress Test
| Stage | Scope |
|---|---|
| MVP | Liability cap, service credits, termination fee; 2 scenarios; calculation steps with cited clauses |
| v1 | 10 term types, free-text scenarios, "not determinable" handling, PDF report |
| v2 | Portfolio totals (feeds 12), currency and inflation inputs, alerts with the obligation ledger |

**Two-week validation.** Hypothesis: computed exposure matches a lawyer's calculation, and finance users prefer it to a risk score. Set-up: 10 contracts × 3 scenarios hand-calculated; 5 finance users compare risk score vs stress test. Success: ≥ 80% within 10%; 4 of 5 users prefer it and decide faster. Week 1: extraction schema and hand-calculated answers. Week 2: calculator, scoring, user sessions.

#### 3. Strategic Negotiation Copilot
| Stage | Scope |
|---|---|
| MVP | NDA only, 10 weighted rules, accept / counter / escalate per change with draft wording |
| v1 | MSA and DPA, concession solver, DOCX replies with tracked changes, feedback logging |
| v2 | Counterparty profiles (feature 8), approved agent-to-agent negotiation over MCP (feature 11) |

**Two-week validation.** Hypothesis: an explicit priority solver keeps more weighted value than an LLM alone without lowering the deal rate. Set-up: a simulated counterparty with hidden priorities, 20 NDA negotiations per variant, a lawyer blind-reviews 10 reply sets. Success: +15% weighted value, deal rate no worse, ≥ 70% of replies "would send with minor edits". Week 1: playbook weights, simulator, baseline runs. Week 2: solver, comparison runs, blind review.

## Bug fixes and improvements

Fixes and quality work, kept out of the feature ranking because they repair or harden existing behaviour rather than add capabilities. Sources: HANDOVER.md §10 and issues found while building and testing the Conflict Radar.

### Fixed

| ID | Issue | Fix |
|---|---|---|
| — | Uploads failed on Windows: the temp folder defaulted to `/tmp`, which doesn't exist there (`[Errno 2] No such file or directory`) | Default is now the OS temp folder; `UPLOAD_TMP_DIR` still overrides it. Regression test in `test_uploads.py` (October 2026). |

### Open bugs

| ID | Issue | Impact | Suggested fix | Effort |
|---|---|---|---|---|
| B1 | The live agent panel (`workflow_tracker`) is one object for the whole server | Users see whichever analysis ran most recently, possibly another tenant's | Key workflow status by request correlation id and tenant | S |
| B2 | Output guard runs after streaming | An answer blocked for non-PII reasons is visible briefly before the `retract` event removes it | Buffer the answer until the guard passes, or guard sentence by sentence | M |
| B3 | Content validation flags many real contracts as having issues | Noisy warnings in logs; reduces trust in validation | Review the rules in `ContentValidationService` against the sample contracts | S |
| B4 | Section and Clause nodes use either `id` or `section_id`/`clause_id`, depending on the pipeline | Every query needs `coalesce(...)`; duplicates when both pipelines run; blocks F3 | Migrate to one id property with an idempotent migration through `backend/migrations/runner.py` | M |
| B5 | Linking to a missing contract returns "Contract X or Y not found" | The message doesn't say which contract is missing | Check each contract separately before linking | S |

### Improvements

| ID | Improvement | Why | Effort |
|---|---|---|---|
| I1 | Planner uses the user's actual request or the contract type instead of a fixed query | It always picks the same analysis strategy today | S |
| I2 | Replace the Gemini-based "Llama Guard" check with a real Llama Guard model (optional) | Today it is Gemini prompted with the Llama Guard categories | M |

### Engineering health

| ID | Item | Effort |
|---|---|---|
| E1 | Fix the 26 remaining ESLint errors (mostly `no-explicit-any`) | S |
| E2 | Update or retire the legacy live-service scripts in `tests/`; replace `tests/test.pdf`, which is not a real PDF | S–M |
| E3 | Add a frontend test framework (for example Vitest) so UI behaviour can be tested directly | S |
| E4 | Optionally move the Given/When/Then scenario tests to `pytest-bdd` with `.feature` files | S |
| E5 | Resolve the 15 npm security advisories in frontend dependencies, testing the build after each upgrade | S |
| E6 | Fix the CSS minifier warning from `grid-cols-[1fr_auto]` in `frontend/src/components/shared/ui/card.tsx` | S |
| E7 | Document the Conflict Radar in `HANDOVER.md` (API changes §9, layout §4, commands §7) and `README.md`: its three endpoints, the automatic migration runner, and the `seed` / `unseed` commands | S |
| E8 | Move the index parts of the 7 older migration scripts in `backend/migrations/` into the automatic runner, leaving out the sample-data inserts, so every schema change applies on deploy | S–M |
| E9 | Add a seed use case with clause embeddings so similarity-based Conflict Radar pairing is exercised by the demo and by tests | S |
| E10 | Local configuration: `.env` points `PHOENIX_COLLECTOR_ENDPOINT` at the Docker-only `phoenix:6006`, so tracing must be turned off when running outside Docker; `.env` sets both `GOOGLE_API_KEY` and `GEMINI_API_KEY`, which logs a warning on every start; the dev machine runs Node 24 while CI uses Node 22 | S |

### Operations

| ID | Item | Recommendation |
|---|---|---|
| O1 | The free Neo4j Aura tier pauses an instance after about 3 days without activity; the app then reports "Could not connect" and `/api/health` shows the database as degraded. It happened twice during development. | For demos and reviews, use a paid Aura tier or the local Neo4j in `docker-compose.yml`, and check `/api/health` before presenting. Resume a paused instance at console.neo4j.io. |

## Sources
- Sirion, AI in CLM 2026 — https://www.sirion.ai/library/contract-insights/ai-contract-lifecycle-management/
- PwC, Agentic AI and CLM — https://www.pwc.com/us/en/services/consulting/supply-chain-operations/future-of-contract-lifecycle-management.html
- Icertis, State of AI in Contracting 2026 — https://www.icertis.com/research/blog/ai-in-contracting/
- Sirion, Renewal and expiration management — https://www.sirion.ai/library/contract-insights/contract-renewal-and-expiration-management-with-ai/
- Ironclad, Obligation tracking — https://ironcladapp.com/resources/articles/contract-obligation-tracking
- Sirion, Playbook-driven redlining benchmarks — https://www.sirion.ai/library/contract-insights/ai-redlining-benchmarks-legal-ops-playbook/
- Counterparty Modeling is Not Strategy (arXiv 2605.16575) — https://arxiv.org/abs/2605.16575
- PolicyGuard (arXiv 2606.32004) — https://arxiv.org/abs/2606.32004
- CLAUSE discrepancy benchmark (EACL 2026 Findings) — https://aclanthology.org/2026.findings-eacl.305.pdf
- ComplianceNLP (arXiv 2604.23585) — https://arxiv.org/pdf/2604.23585
- ACORD clause retrieval (arXiv 2501.06582) — https://arxiv.org/pdf/2501.06582
