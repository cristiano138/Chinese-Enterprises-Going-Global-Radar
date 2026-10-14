# ComplianceRadar — Project Overview (English)

> Version: 2026-10-14 v2 (expanded scope)
> Submission deadline: **18 Oct 2026, 17:00 (Beijing Time)**
> Event: "AI+X Boundary-Breaking Hackathon" · Tmall Campus OPC Incubation Track (Zhejiang University × Tmall Campus)
> Scope principle: **An ambitious vision, a disciplined build.**

---

## 1. What the project does

### 1.1 In one sentence

A seller enters **"what I sell + where I sell it"** → the tool returns **which regulations apply, what changed recently, and what to do next** — with every conclusion linked to its official source text, verifiable with one click.

### 1.2 The essence

It turns cross-border compliance self-assessment from **hiring a lawyer for basic research (expensive, slow, opaque)** into **pressing a button and getting a checklist (fast, affordable, verifiable)**.

### 1.3 Three non-negotiable properties

| Property | What it means | Why it matters |
|---|---|---|
| **Verifiable** | Every conclusion must carry a link to the official source; no link, no output | This is the essential difference from "just asking an AI" |
| **Time-aware** | Tracks regulatory change and flags "superseded", "recently amended", "transition period" | Sellers fear most the change they never noticed |
| **Actionable** | Translates legal language into seller-side actions (e.g. "affix CE marking") | Users don't want knowledge — they want to know what to do |

---

## 2. Scope

### 2.1 Seller segments (expanded to 6)

| # | Segment | Their pain point |
|---|---|---|
| 1 | Small and mid-sized cross-border sellers | Limited budget, cannot afford counsel, cannot read the regulations themselves |
| 2 | Campus startup teams | Want to go global, have no idea where to start on compliance |
| 3 | **Domestic e-commerce sellers going overseas** | Used to domestic platform rules; overseas rules are entirely different |
| 4 | **OEM / contract manufacturers** | Know production, not regulation; lost when a buyer demands "EU-compliant" |
| 5 | **Cross-border service providers** (freight forwarders, agencies, industrial parks) | Must give compliance guidance to many clients; manual cost is prohibitive |
| 6 | **Going-global brand owners** | Operating in multiple markets; need unified change monitoring |

### 2.2 Market coverage (expanded to 6 target markets)

| Market | Regulatory framework | Data availability |
|---|---|---|
| **EU** | CE marking, GPSR, product-specific directives | Excellent (EUR-Lex official portal) |
| **US** | FDA (food/cosmetics), FCC (electronics), CPSC (consumer safety) | Good (agency sites) |
| **UK** | UKCA marking (post-Brexit standalone regime) | Good |
| **Japan** | PSE (electrical), PSC (consumer products) | Moderate |
| **Southeast Asia** (Vietnam, Indonesia) | National certification schemes | Limited |
| **Middle East** (Saudi Arabia, UAE) | SASO, ESMA certification | Limited |

### 2.3 Compliance dimensions (expanded from 1 to 6)

| # | Dimension | Content |
|---|---|---|
| 1 | **Product safety regulation** (original core) | Market access, safety standards, certification marks |
| 2 | **Tax compliance** | VAT, customs duties, tax registration |
| 3 | **Intellectual property** | Trademarks, patents, infringement risk |
| 4 | **Labelling** | Language requirements, ingredient disclosure, country of origin |
| 5 | **Customs clearance** | HS codes, certificates of origin, import licences |
| 6 | **Data compliance** | Privacy policy, GDPR, cross-border data transfer |

### 2.4 Product capabilities (from 4 modules to a full workflow)

| Stage | Capability | Before | After expansion |
|---|---|---|---|
| Look up | Regulation list query | M1 ✅ | Unified query across markets and dimensions |
| Track | Regulatory change tracking | M2 ✅ | + change subscription and alerts |
| Act | Actionable to-do list | M3 ✅ | + to-do progress management |
| Compare | Side-by-side with general AI | M4 ✅ | Retained as a trust signal |
| **Connect** | **Service-provider matching** | — | NEW: recommend testing labs, counsel, forwarders |
| **Verticalise** | **Industry-specific editions** | — | NEW: toys, electronics, textiles, beauty, food-contact |

### 2.5 The expanded picture

From a tool covering **"EU × 3 categories × 1 dimension"** to a **one-stop compliance platform spanning "6 markets × all categories × 6 dimensions × the full workflow."**

---

## 3. What is actually being built for this competition

### 3.1 Reality check

| Constraint | Value |
|---|---|
| Remaining time | **4 days** (14–18 Oct) |
| Submission deadline | 18 Oct 17:00 (internal target: submit by 12:00) |
| Team | 3 people, not full-time |
| Core bottleneck | **Data must be verified entry by entry by a human** — this cannot be compressed |

### 3.2 The real bottleneck is not code — it is verification

Code can be accelerated by AI (roughly 80% can be produced automatically), but **regulatory accuracy must be checked by a human against the official source.** Estimated effort:

| Work item | Per entry | Entries | Total |
|---|---|---|---|
| Full verification of one regulation (official number + ELI link + OJ reference + dates + link reachability) | 8–15 min | 1 | ~10 min |
| Original scope (1 market × 3 categories × 10) | — | 30 | **~5 hours** |
| Full expansion (6 markets × 6 dimensions × 10) | — | 360 | **~60 hours** |

**60 hours over 4 days = 15 hours per day of pure verification, with zero errors allowed. That is not achievable.**

### 3.3 The competition build scope

| Dimension | Expanded vision | **What is actually built now** | Rationale |
|---|---|---|---|
| Markets | 6 | **2: EU + US** | The two markets with the most complete official data sources |
| Categories | All | **5: children's toys, electrical/electronic, textiles and apparel, beauty and personal care, food-contact materials** | Covers the highest-risk, highest-frequency categories |
| Compliance dimensions | 6 | **2: product safety regulation + labelling** | The rest shown as a roadmap |
| Seller segments | 6 | **4** | Most concentrated pain points; easiest to recruit test users |
| Capabilities | Full workflow | **Look up + Track + Act + Compare** built; "Connect" and "Verticalise" on the roadmap | The latter two are business model, not required for the demo |

### 3.4 Recalculated verification workload

| Item | Entries | Effort |
|---|---|---|
| EU × 5 categories × 8 | 40 | ~7 hours |
| US × 5 categories × 8 | 40 | ~7 hours |
| **Total** | **80** | **~14 hours** |

Spread across 15–16 Oct = **7 hours per day**; with AI pre-screening (AI flags suspicious entries, humans verify only those), this compresses to **4–5 hours per day**. That is sustainable.

### 3.5 De-scoping ladder

| Priority | What to cut | What remains |
|---|---|---|
| Step 1 | Categories 5 → 3 (drop beauty, food-contact) | Toys, electronics, textiles |
| Step 2 | Markets 2 → 1 (drop US) | EU |
| Step 3 | Dimensions 2 → 1 (drop labelling) | Product safety regulation |
| **Never cut** | — | **Source alignment (every conclusion carries an official link)** |

---

## 4. Architecture

### 4.1 The six components

| # | Component | File | Function |
|---|---|---|---|
| 1 | Crawler | `crawler.py` | Retrieves official regulation texts automatically |
| 2 | Corpus | `database.py` | Stores regulations with metadata (number, dates, official link) |
| 3 | Retriever | `retriever.py` | Retrieval-augmented: selects relevant provisions for the query |
| 4 | LLM layer | `llm.py` | Understands, classifies, summarises, translates |
| 5 | **Source alignment** ⭐ | `verify.py` | Forces every output back to its official link; no link, no output |
| 6 | Interface | `app.py` | The web page the seller uses |

### 4.2 Division of labour between AI and deterministic code

- **LLM does only four things:** understanding, classification, summarisation, translation.
- **Deterministic code does everything requiring accuracy:** crawling, URL validation, source alignment, caching, deduplication.

**Rationale:** an LLM cannot be relied upon for precision. Any step where accuracy matters must not be delegated to it.

### 4.3 Data pipeline

```
Official sources (EUR-Lex API · FDA · FCC · CPSC)
        │  deterministic code: fetch, parse, deduplicate, validate URLs, index by category
        ▼
Regulation corpus (with metadata: publication date, entry-into-force date, application date, official link)
        │  retrieval-augmented generation: match provisions to "category + market"
        ▼
LLM layer (understand → classify → summarise → translate)
        · provision screening → M1 list
        · change comparison → M2 timeline
        · legal language → actions → M3 checklist
        │  deterministic code: source alignment (every output must carry its official link)
        ▼
Web interface (deployed on ModelScope) + comparison module (M4)
```

### 4.4 Why the architecture supports expansion

| Expansion direction | Architectural support |
|---|---|
| Add a market | Data sources implemented as adapters; a new market = a new adapter |
| Add a category | Corpus indexed by category tags; a new category = a new tag |
| Add a dimension | Modules decoupled by query dimension; a new dimension = a new module |
| Add a capability | Front end composes result cards; a new capability = a new card |

This demonstrates extensibility by design, not by retrofit.

---

## 5. The four functional modules

| # | Module | Input | Output fields | Boundary handling |
|---|---|---|---|---|
| **M1** | Compliance Map | Category + market | Chinese name, official English title, official number, CELEX number, ELI link, OJ reference, entry-into-force date, whether still in force | Unsupported category/market → explicit notice |
| **M2** | Change Timeline | Category + market | Change summary, impact note, entry-into-force / application date, official link | Window limited to the last 12 months (reducible to 6) |
| **M3** | Action Checklist | Category + market | Concrete actions (e.g. "affix CE marking", "appoint an EU authorised representative"), source provision link, exportable | Only items that resolve into a concrete action |
| **M4** | Comparison Demo | One identical question | Two-column comparison: general LLM answer vs this tool | Default case: the EU toy regulation replacement |

---

## 6. The worked example (our strongest evidence)

### 6.1 The facts

The EU toy safety regime has changed:

- **Regulation (EU) 2025/2509** was adopted on 26 Nov 2025
- It **entered into force on 1 Jan 2026**
- It will **fully replace Directive 2009/48/EC** from **1 Aug 2030**
- Directive 2009/48/EC had been in place for more than a decade

### 6.2 Why this example matters

It proves two things at once:

1. **Regulatory change is a real, recurring pain point** — a toy seller who has exported for years must now know the rulebook has been replaced.
2. **A general-purpose LLM is very likely to be wrong** — its training data still points to the old Directive 2009/48/EC. It will answer confidently, cite no source, and give an outdated answer.

### 6.3 How we use it

- Set as the **default example in the M4 comparison demo**
- Written into the **user pain point** section of the submission material

---

## 7. Verification and evaluation

| Item | Method | Target |
|---|---|---|
| Test set | 15 questions (12 substantive + 3 edge cases) with reference answers and official sources | 15 complete |
| Controlled experiment | Same questions to a general LLM and to this tool; manual comparison | All 15 compared |
| Metric 1 | Regulatory entry accuracy | Reported as measured |
| Metric 2 | Source verifiability rate | **≥95%** |
| Metric 3 | Hallucinated entries | Reported as measured |
| User testing | 2–3 real users (cross-border sellers / law or international business students), remote, ~20 min each | ≥2 complete the full flow |
| Edge cases | Unrelated category, unsupported market, dead source link | All three handled with a clear notice |

**Honesty principle:** anything not actually tested is labelled "not tested" in the material. No estimated values are presented as measured results.

---

## 8. Business model

### 8.1 Tiering

| Tier | Content | Price |
|---|---|---|
| Free | Query 1 market × 1 category | ¥0 (acquisition) |
| Professional | Multi-market, multi-category queries + change alerts + to-do management | ¥99–299 / month |
| Enterprise | Batch queries + service-provider matching + dedicated compliance advisor | Custom |
| Service-provider | White-label embedding (freight forwarders, agencies, industrial parks) | Annual licence |

### 8.2 Fit with the incubation track

The competition track offers OPC incubation resources (free premises, workstations, company registration services, Alibaba-ecosystem resources). A compliance tool for going-global sellers is a natural complement to an e-commerce ecosystem.

### 8.3 Why the expanded scope is itself a competitive advantage

Judges favour **"mature projects and a clear path to deployment."** A tool limited to the EU and three categories has an obvious ceiling. A project that has already reasoned from 1 market to 6, and from regulation lookup to service-provider matching, demonstrates **extensible architecture and commercial judgement**.

**The strategy is therefore: build a small, solid product; draw a large, credible roadmap.**

---

## 9. Three critical dependencies

| Blocker | Consequence if unresolved | Checkpoint |
|---|---|---|
| Platform API token + data-source validation | The build cannot start | 14 Oct |
| Corpus verification complete | Evaluation cannot run; material has no measured data | 15 Oct, end of day |
| Deployment live | Submission package incomplete; loss of eligibility | 16 Oct, night |

---

## 10. Scope red lines

**Explicitly out of scope for this build:** user registration and login, subscription push, multi-market multilingual UI, mobile app, paid features, admin back office, AI chatbot.

Rationale: the build window is 5 days. **Every added feature trades "deliverable" for "undeliverable."**

---

## 11. AI usage principles

| Principle | Explanation |
|---|---|
| **AI executes, humans judge** | Coding, drafting and template generation go to AI; regulatory accuracy, scope decisions and acceptance testing remain human |
| **Give AI full context** | AI knows nothing about this project by default; background, constraints, boundaries and acceptance criteria must be supplied together |
| **Treat all AI output as unverified** | Every factual item — regulation number, date, figure — must be checked. The more fluent the output, the more it needs checking |
| **Use AI as a control group** | Have AI play the "unassisted general model" and measure its errors — those errors are the evidence of this product's value |

---

## 12. Reference documents

| Document | Content |
|---|---|
| `项目定位_扩大版.md` | Full scope, business model, architectural extensibility (Chinese) |
| `AI全流程执行手册.md` | Seven-step execution guide with AI prompt templates (Chinese) |
| `语料核对表.xlsx` | Corpus verification workbook, 18 columns with validation rules |
| `EUR-Lex官方来源判定指南.md` | How to determine what counts as an official source (Chinese) |
| `AI设计大赛参赛方案.md` | Five-day sprint checklist (Chinese) |
