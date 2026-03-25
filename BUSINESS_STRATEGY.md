# Business Strategy — Trellis Runbook AI Co-Pilot

> Last updated: 2026-03-09

## Product Vision

A tablet-first, AI-assisted protocol execution platform for **gene and cell therapy (GCT) process development**. Scientists design manufacturing protocols as visual flowcharts, execute runs on tablets in the lab, capture data (manually, via AI image analysis, or CSV import), and export cleanly to analysis tools (GraphPad Prism, SAS, Excel). The app is not an analytics platform or a LIMS — it is the fastest path from "lab experiment" to "clean data in Prism."

## Why Gene & Cell Therapy

**The process is uniquely complex.** GCT manufacturing involves patient-specific batches (autologous CAR-T), viral vector production, plasmid prep, transfection/transduction, expansion, harvest, formulation — with strict chain-of-identity requirements. These aren't simple linear protocols. They branch, have parallel paths, and involve handoffs between roles. A graph-based protocol editor is the exact right UI for this workflow.

**The market is exploding.** ~30 approved gene/cell therapies globally as of 2025, with 2,000+ in clinical trials. The FDA approved more CGT products in the last 3 years than the previous decade combined. Every clinical program has a PD team developing the manufacturing process.

**The teams are small and underserved.** Most GCT companies are 20-200 people. PD teams are 5-15 scientists — exactly our target. They're too small for Benchling enterprise pricing ($15k+/year minimum) but too specialized for generic ELNs. Many are in paper notebooks or hacked-together Excel templates.

**The vocabulary is tight.** "We built the protocol execution tool for cell therapy PD" immediately resonates with a CAR-T scientist. "We built an ELN for biotech" does not.

**Word-of-mouth is concentrated.** The GCT community is small and interconnected. Scientists move between companies, attend the same conferences (ISCT, ASGCT), follow the same KOLs. One happy team tells three others.

## Target Market

**Beachhead**: GCT PD teams (5-15 scientists) at small/mid biotechs, currently using paper notebooks, Excel, or general-purpose tools. Not locked into Benchling.

**Expansion path** (sequential, not simultaneous):
1. Gene & cell therapy PD (beachhead)
2. Adjacent biologics PD (mAb manufacturing, vaccine development)
3. Broader process development (gene editing research, synthetic biology)
4. GMP manufacturing / tech transfer (Phase 2 — compliance layer)

---

## Go-to-Market Strategy

### Phase 1 — GCT Research Adoption (Current)

**Goal**: 50 paying GCT PD teams within 18-24 months.

**Positioning**: "The protocol execution tool built for cell therapy process development." Not "an ELN." Not "a lab notebook." A purpose-built tool for GCT PD workflows, pre-loaded with unit operations they actually use.

**What we are NOT (yet)**: A GMP-validated system, a LIMS, an analytics platform, or a replacement for Prism/SAS/JMP.

**Regulatory posture**: The existing audit trail (who did what, when, with change tracking) is sufficient for research use. No investment in 21 CFR Part 11, electronic signatures, or formal validation until Phase 2.

### Phase 2 — GMP Expansion (Revenue-Dependent)

**Trigger**: MRR > $10k AND at least one customer has signed a letter of intent for GMP capabilities at a defined annual price.

**What this adds**:
- Electronic signatures with meaning-of-signature declarations
- Witness countersigning on critical steps
- Tamper-evident audit trail (hash chaining)
- SSO / SAML / OIDC for enterprise IT requirements
- Data retention policies
- Validation documentation support (IQ/OQ/PQ)
- Formal 21 CFR Part 11 compliance certification

**Why defer**: Part 11 compliance is expensive ($50-150k+ for QA consulting, validation documentation, ongoing maintenance). It generates zero revenue in the research phase. The current data model (audit logs, permission levels, protocol versioning, approval workflows) is already the right foundation — the compliance layer adds to it rather than requiring a rewrite.

**Why it works**: Research scientists who adopt in Phase 1 become natural advocates for Phase 2 when their protocols move to manufacturing. The switching cost is high once protocols, data, and institutional knowledge live in the system.

---

## Acquisition Channels

### Primary: GCT Ecosystem Direct Outreach

**Conferences** (attend, demo, or poster):
- ISCT (International Society for Cell & Gene Therapy) — annual meeting, ~3,000 attendees
- ASGCT (American Society of Gene & Cell Therapy) — annual meeting, ~5,000 attendees
- CPBD (Cell & Gene Therapy Bioprocessing & Commercialization)
- BioProcess International — cell therapy track
- PDA Cell & Gene Therapy — process development focused

**Incubators & shared lab spaces** (partnership targets):
- LabCentral (Cambridge, MA) — 100+ biotech startups, many GCT
- JLABS (multiple locations) — Johnson & Johnson innovation hub
- BioLabs (multiple locations) — shared lab space for early biotechs
- Nucleate — student-run biotech accelerator at top universities
- One partnership with an incubator can seed 5-10 teams at once

**LinkedIn & community**:
- PD scientists are active on LinkedIn. Demo videos of AI image analysis + graph-based protocol design would get attention
- Cell & Gene Therapy LinkedIn groups (~15k+ members)
- BioProcess Online community
- r/biotech, r/labrats (Reddit) for awareness, not sales

**Cold outreach**:
- Target PD directors/leads at GCT companies (findable on LinkedIn)
- Message: "We built the protocol execution tool for cell therapy PD. Want to try it on your next transduction run?"
- Link to 60-second demo video showing the complete workflow (design → execute → export)

### Secondary: Content & SEO

- Blog posts on GCT PD workflow challenges
- "How to structure your CAR-T manufacturing process" (lead magnet)
- Comparison pages: "Trellis vs Benchling for cell therapy PD"
- SEO for "cell therapy protocol management," "GCT process development software"

### Tertiary: Academic Labs

- Academic GCT research labs as awareness builders and talent pipeline
- Academic tier at $49/month (team pricing, discounted)
- Students/postdocs who learn the tool bring it to their first industry job
- Good source for testimonials and case studies

---

## Pricing Strategy

### Model: Usage-Based Trial → Team-Based Subscription

No permanent free tier. No per-user pricing. Team-based flat pricing removes the friction of adding/removing users and matches how PD teams budget.

### Trial: First 3 Completed Runs (Free, No Time Limit)

Lab experiments run on weekly/biweekly cycles. A time-boxed trial may expire before a team completes a full workflow loop. Instead:

- **Free until 3 runs are completed** — guarantees they've experienced the full capture-to-export value loop
- Full Pro-tier feature access during trial including Trellis-managed AI — let them experience the full value before choosing a tier
- No credit card required
- Data preserved after trial limit — users can export or reactivate anytime
- 3 completed runs is typically 2-4 weeks of real use — enough to evaluate, not enough to freeload

### Paid Tiers

No free tier. Three paid tiers differentiated primarily by AI access and deployment model:

| Tier | Price | What's Included | AI Access | Target |
|------|-------|-----------------|-----------|--------|
| **Essentials** | $99/month | All platform features, unlimited projects, up to 10 users | BYOK — org brings their own AI API keys (OpenAI, Anthropic, Google, Ollama). All AI features work, Trellis just doesn't pay for the LLM calls | Small teams comfortable managing their own API keys, cost-conscious orgs |
| **Pro** | $299/month | Everything in Essentials + Trellis-managed AI included + white-labeling | Trellis-managed — AI works out of the box with no setup. Org can still override with their own keys per capability if preferred. Token budget included | Core PD teams who want AI to "just work" without managing API keys |
| **Enterprise** | Custom pricing | Everything in Pro + on-premise deployment + stronger SLA + platform customization + dedicated support | Trellis-managed or self-hosted LLM infrastructure, custom model selection, higher/custom rate limits | Large orgs, regulated environments, companies requiring on-prem or compliance |
| **Academic** | $49/month | Same as Essentials, .edu email required | BYOK (same as Essentials) | University research labs |

**Key tier differentiators**:
- **Essentials → Pro upgrade driver**: AI convenience. Essentials users get all features but must configure their own OpenAI/Anthropic/Google API keys. Pro users get Trellis-managed AI that works immediately — zero setup, no API key management, no usage monitoring on their end
- **Pro → Enterprise upgrade driver**: Deployment control and SLA. Enterprise adds on-premise installation, stronger uptime SLA, platform customization (custom branding, custom unit op libraries), and dedicated support. Required for regulated environments or companies with strict data residency requirements
- **White-labeling** (Pro & Enterprise): Org can customize the platform branding — logo, colors, custom domain. Essentials uses default Trellis branding

**Annual billing discount**: 2 months free (pay for 10, get 12). Locks in revenue and reduces churn. Pro annual = $2,990/year instead of $3,588.

**BYOK model (Essentials)**: Customer pays their AI provider directly. Trellis provides the integration layer and admin UI for configuring API keys. No AI overage billing from Trellis — the customer's own API key usage/costs are between them and their provider.

**Trellis-managed AI model (Pro)**: Trellis pays the AI provider costs and includes a monthly token budget in the subscription price. If an org exceeds their budget, they receive warnings at 80% and are prompted to either upgrade or add their own API keys at 100%.

**Why these prices work**:
- **$299/month for Pro with AI included** = $3,588/year. That's 6x cheaper than LabArchives corporate ($5,750/year for 10 users) and 4x cheaper than Benchling minimum ($15k/year)
- **$99/month Essentials** is an easy entry point — under $1,200/year, no procurement needed. Upgrade to Pro when the team tires of managing API keys
- **Under $5k/year** — falls below competitive bid threshold at most companies. A PD director can approve it
- **No per-user anxiety** — team-based pricing, not per-seat
- GCT PD teams spending $250k/year per FTE salary will not blink at $99-299/month for the whole team

### Enterprise Tier (Details)

For companies requiring on-premises deployment, custom SLA, or platform customization:

| Component | Price | Notes |
|-----------|-------|-------|
| Base platform license | $5-15k/year | On-prem deployment, updates, SLA |
| Installation & setup | $2-5k one-time | Deployment, configuration, validation on their infrastructure |
| AI (included or BYOK) | Included in license | Org can use Trellis-managed or run their own LLM infrastructure on-prem |
| Platform customization | Scoped per engagement | Custom branding, custom unit op libraries, workflow modifications |
| GMP compliance module | TBD | Phase 2, likely $20-50k/year additional |
| Dedicated support | Included | Named account manager, priority response SLA |

**Do not build on-prem packaging until a customer is ready to pay.** The stack (FastAPI + PostgreSQL + Svelte) is Docker-friendly and can be packaged when demand materializes.

### Pricing Benchmarks

| Competitor | Pricing | Notes |
|------------|---------|-------|
| eLabFTW | Free (open source, self-hosted) | Paid support: 760-6,985 EUR/year |
| LabArchives | $330-575/user/year | Add-ons for inventory, scheduling |
| Benchling | Startup plan from $15k/year (5 users); enterprise $5-7k/user/year | Heavy implementation fees ($10-20k) |
| Sapio Sciences | $100-500k+/year | Enterprise only, opaque pricing |

Trellis undercuts all paid competitors significantly while offering GCT-specific value none of them provide.

---

## Revenue Math

**Operating costs**: ~$1k/month (infrastructure, AI API for Pro tier, domain, services)
**Sustainability target**: $12.5-16.7k/month ($150-200k/year)

Blended ARPU assumption: ~60% Essentials ($99) + ~35% Pro ($299) + ~5% Enterprise ($500+ avg) = ~$185/month average

| Milestone | Paying Teams | MRR (at ~$185 avg) | Timeline |
|-----------|-------------|-------------------|----------|
| Covers infrastructure | 6 | $1,100 | Month 6-9 |
| Part-time sustainability | 28 | $5,200 | Month 12 |
| Full sustainability | 82 | $15,200 | Month 18-24 |
| Hire help / Phase 2 | 110+ | $20,000+ | Month 24+ |

**Note**: As the mix shifts toward Pro (teams upgrade for AI convenience), ARPU increases and the team count needed drops. At 50/50 Essentials/Pro split, ARPU is ~$199 and sustainability requires ~75 teams.

**82 paying GCT PD teams = full sustainability at launch mix.** There are 2,000+ gene/cell therapy clinical programs. Each has a PD team. 82 teams is ~4% penetration. Realistic with focused effort, and the number drops as teams upgrade to Pro.

---

## Funding Strategy

### Principle: Patient Capital, Minimal Dilution

Avoid the accelerator treadmill. YC/Techstars push for hypergrowth and Series A within 18 months — wrong cadence for a niche biotech SaaS that needs 2-3 years of patient, focused work. Instead:

### Primary: SBIR/STTR Grants (Non-Dilutive)

NIH SBIR grants are purpose-built for this situation:

| Phase | Amount | Duration | Notes |
|-------|--------|----------|-------|
| Phase I | ~$275k | 6-9 months | Feasibility/R&D. Apply under NIBIB or NCI (CAR-T is oncology) |
| Phase II | $1-2M | 2 years | Full development. Requires Phase I completion |

**Why this fits**:
- **Non-dilutive** — no equity given up, ever
- **$275k Phase I** = 18 months of runway at $150-200k/year target
- An AI-powered digital lab notebook for cell therapy PD is exactly what NIH funds
- Applications reviewed 3x/year; 6-8 months from submission to funding

**Timeline**: Submit Phase I application within first 3 months. Bridge with personal savings (6-8 months) until award decision.

### Secondary: Strategic Angels (Not VCs)

2-3 angel investors writing $25-50k checks on a SAFE note:
- **Biotech operators**: Former PD directors, CSOs, or biotech founders who understand the space
- **Value**: Their networks become your first 10 customers. Each one knows 10+ PD teams
- **Total raise**: $75-150k, minimal dilution

$75-150k from angels + $275k SBIR = 2-3 years of runway with minimal equity loss.

### Tertiary: Revenue-Based Financing (Later)

Once MRR > $5k, companies like Pipe, Capchase, or Lighter Capital advance 6-12 months of annual revenue as a loan. No equity. Pay back from revenue. Bridge from "$5k MRR" to "$15k MRR."

### What to Avoid

- **Generic accelerators** (YC, Techstars): Wrong growth cadence. Take 7% equity, push for Series A
- **Pre-PMF VC rounds**: $1-2M pre-revenue means 15-25% equity and board pressure to grow faster than the market allows
- **Biotech-specific accelerators** (IndieBio, Petri): Better fit but still push fundraising cadence. Evaluate if they have strong GCT connections, but go in with eyes open

### Projected Timeline

| Month | Revenue | Activity | Funding Source |
|-------|---------|----------|----------------|
| 0-3 | $0 | Ship MVP gaps, find GCT design partner, submit SBIR Phase I, angel outreach | Personal savings |
| 3-6 | $0-500 | Design partner live, first 2-3 trial signups, angel closes | Savings + angels ($75-150k) |
| 6-9 | $500-2k | SBIR award (if approved), 5-10 trial teams | SBIR Phase I ($275k) |
| 9-12 | $2-5k | First conference (ISCT or ASGCT), 15-20 paying teams | SBIR |
| 12-18 | $5-10k | Word of mouth, content marketing, 30-40 teams | SBIR |
| 18-24 | $10-15k | Sustainability. Evaluate Phase 2 demand. SBIR Phase II app | Revenue + SBIR remainder |
| 24+ | $15k+ | Phase 2 (GMP) if demand. Revenue-based financing if needed | Revenue-funded |

---

## Competitive Differentiators

What we have that competitors don't (or do poorly):

1. **GCT-specific unit op library** — Pre-loaded with viral vector production, cell expansion, transfection, harvest, formulation, fill/finish. New users get a template that's 80% of their actual workflow on day one. No generic ELN does this
2. **Visual graph-based protocol design** — Unique among ELNs. Protocols as flowcharts with swimlanes for role-based parallel paths. Scientists think in process flows, not documents
3. **AI-powered image analysis** — Take a photo of an instrument reading, AI extracts the value. No competitor offers this natively. Available on all tiers (Essentials with BYOK, Pro/Enterprise with Trellis-managed AI included)
4. **Full offline field mode** — Encrypted offline sessions with background sync. Critical for labs with unreliable connectivity or cleanroom environments. Most competitors require constant internet
5. **Copy-on-write run execution** — Protocols are templates; runs are snapshots with deviation tracking. Clean separation of design vs execution
6. **Tablet-first design** — Purpose-built for lab use on tablets with gloves. Not a desktop app crammed onto a small screen
7. **Price** — $299/month for a full team vs $15k+/year for Benchling. Accessible without enterprise procurement

## What We Deliberately Don't Build

- **In-app analytics / SPC charts** — Scientists use Prism, SAS, JMP for analysis. Build a mediocre duplicate of those and you waste dev time. Instead, make the export pipeline excellent
- **LIMS functionality** — Inventory, reagent tracking, sample management is a different product category. Stay focused
- **Real-time collaboration** — CRDTs/OT for concurrent editing is an architectural rabbit hole. Not needed for research teams where one person owns a protocol at a time
- **Predictive analytics / ML** — Premature. Requires data accumulation and data science expertise
- **Native mobile app** — PWA covers tablet/mobile use. Native apps double the maintenance burden for a solo dev

---

## GCT-Specific Product Strategy

### Pre-Loaded Unit Operations Library

Ship with GCT-specific unit operations so new users see their workflow immediately:

**Upstream Processing**
- Plasmid DNA preparation
- Viral vector production (lentiviral, AAV, retroviral)
- Cell thaw & revival
- Cell seeding & expansion
- Transfection / transduction
- Media exchange
- Cell harvest

**Downstream Processing**
- Clarification (centrifugation, filtration)
- Chromatography (affinity, ion exchange)
- Tangential flow filtration (TFF)
- Buffer exchange / diafiltration
- Sterile filtration

**Formulation & Fill**
- Formulation & excipient addition
- Fill/finish
- Cryopreservation
- Visual inspection

**Quality Control (in-process)**
- Cell count & viability (Vi-CELL, Countess)
- Flow cytometry sampling
- pH / DO / metabolite measurement
- Endotoxin testing (LAL)
- Sterility sampling
- Potency assay sampling

**Common Parameters** (pre-configured in param schemas):
- Cell density (cells/mL), viability (%), VCD, TCD
- MOI (multiplicity of infection), transduction efficiency (%)
- pH, dissolved oxygen (%), temperature (C)
- Titer (TU/mL, vg/mL, pfu/mL)
- Recovery (%), purity (%)
- Volume (mL, L), flow rate (mL/min)

### Sample Protocol Templates

Pre-load 2-3 complete protocol templates:
1. **CAR-T manufacturing** — T-cell isolation → activation → transduction → expansion → harvest → formulation → cryo
2. **Lentiviral vector production** — Plasmid prep → cell seeding → transfection → harvest → clarification → chromatography → TFF → formulation
3. **AAV vector production** — Similar to lenti but with different downstream steps

These let new users explore a populated editor immediately (critical for onboarding and trial conversion).

---

## Data Security & Privacy

### Where Data Lives

- **SaaS**: Hosted on [TBD — AWS / Hetzner / Fly.io]. US-based servers
- **Images**: Cloud storage (S3-compatible). Encrypted at rest (AES-256)
- **Database**: PostgreSQL with encryption at rest. Daily automated backups with 30-day retention
- **In transit**: TLS 1.3 for all connections
- **Multi-tenant isolation**: Org-scoped queries at the application layer. Each org's data is logically isolated by `organization_id` foreign keys. No cross-org data access

### Data Ownership

- Customer owns all their data. Full export available at any time (CSV, Excel, JSON)
- On account cancellation: data preserved for 90 days, then permanently deleted. Customer can request immediate deletion
- We do not sell, share, or use customer data for AI training

### If We Go Out of Business

- 90-day notice to all customers
- Full data export provided
- Open-source the core platform if commercially viable (considered, not promised)

### SOC 2 / Formal Certification

Not pursuing in Phase 1. Will evaluate when enterprise customers require it (typically $30-50k for initial audit). The current security posture (encrypted storage, TLS, logical isolation, audit trail) is sufficient for research use.

---

## Churn Prevention

### Usage Monitoring

- Track weekly active users per team, runs completed per month, exports per month
- Flag "at risk" accounts: teams with declining usage over 2+ weeks
- Automated email when a team hasn't logged in for 7 days: "Your team hasn't run an experiment this week. Need help?"

### Retention Tactics

- **Annual billing discount**: 2 months free. Locks in revenue, reduces churn trigger points
- **Export presets as lock-in**: Once a team has configured their Prism export template, switching tools means reconfiguring. Stickiness through workflow, not data hostage
- **Regular check-ins**: Monthly email to paying teams: "Here's what you accomplished this month" with run counts, data captured, AI analyses used
- **Feature request tracking**: When a customer asks for something you build later, email them: "You asked for X — we built it"

### Win-Back

- Churned customers keep their data for 90 days
- At day 30 and day 60: email with what's new since they left
- Offer 1 free month to return

---

## Competitive Response Scenarios

| Scenario | Response |
|----------|----------|
| Benchling releases a free tier for small teams | Differentiate on GCT specificity and offline. Benchling's free tier will be limited and generic. We're purpose-built |
| eLabFTW adds AI features | Our AI is tightly integrated (image → parameter extraction → run data). Bolted-on AI in an open-source tool won't match the workflow integration |
| LabArchives adds graph-based protocols | They're a document-based notebook. Adding a graph editor is a fundamental architecture change — it would take them years. Our graph editor is the core, not an add-on |
| New GCT-specific competitor appears | Move fast. First-mover advantage in a niche is strong. Deepen GCT templates, lock in design partners, build community |
| A customer demands features we don't have | Evaluate honestly. If it's on the roadmap, share the timeline. If it's out of scope, say so. Don't promise features you can't build as a solo dev |

---

## MVP Feature Priorities (Research Phase)

Features ranked by impact on GCT PD team adoption, accounting for solo-dev constraints:

### Must Ship (blocks adoption)
1. **Undo/redo in protocol editor** — Basic usability expectation for any editor
2. **Better export pipeline** — Export presets, clipboard copy, Prism-friendly formatting. Core value prop
3. **Full-text search** — Critical once teams have 20+ protocols and runs
4. **Commenting system** — Researchers collaborate constantly; discussions need to live in the app
5. **GCT unit ops library & templates** — Pre-loaded with cell therapy operations and 2-3 sample protocols. This is the "built for you" moment

### Should Ship Before Launch
6. **Barcode/QR scanning** — Immediate lab workflow value, relatively quick to build
7. **Instrument data import (CSV)** — Eliminates manual transcription from instrument exports
8. **Onboarding / guided tour** — First-run experience matters for trial conversion. Sample CAR-T protocol walkthrough
9. **Cloud storage for images** — Required for production SaaS deployment

### Nice to Have (Post-Launch)
10. **Voice-to-text** — Hands-free data entry for gloved scientists. Differentiator for marketing
11. **Protocol version diff view** — Useful but not blocking anyone
12. **Dark mode** — Requested, not a dealbreaker

### Deferred to Phase 2 (GMP)
- Electronic signatures / 21 CFR Part 11
- Witness countersigning
- Tamper-evident audit trail (hash chaining)
- SSO / SAML / OIDC
- Data retention policies
- Validation documentation (IQ/OQ/PQ)
- Self-hosted deployment package

---

## Design Partner Strategy

One deeply engaged GCT team is worth more than 20 casual users.

**Ideal design partner profile**:
- 5-10 person PD team at a cell therapy or viral vector company
- Currently using paper/Excel (not already locked into Benchling)
- Working on an active program (not between projects)
- Willing to give weekly feedback
- Located near a biotech hub (Boston, SF Bay Area, San Diego, RTP) or very responsive remote

**Where to find them**:
- LabCentral, JLABS, or BioLabs resident companies
- ISCT/ASGCT conference contacts
- LinkedIn outreach to PD directors at pre-clinical or Phase I GCT companies
- Nucleate (student biotech org) — connected to university spinouts

**What you offer**: Free access for 12 months, direct line to the developer, features built around their workflow, their unit ops added to the default library.

**What they give you**: Real usage data, pain point discovery, testimonials, case study, and introductions to other teams. This is the most valuable asset for selling to the next 50 teams.

---

## Key Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Can't find GCT design partner | High | Cast wide: incubators, conferences, LinkedIn. Offer extraordinary terms. This is the single most important milestone |
| No one converts after trial | High | Usage-based trial (3 runs) ensures they've experienced full value. Monitor where users drop off. Iterate on onboarding |
| SBIR not awarded | Medium | Angels as backup. Can resubmit next cycle (3x/year). Reduce personal burn rate if needed |
| AI costs exceed revenue per Pro team | Medium | Pro tier includes token budget — monitor per-org AI spend. Essentials tier has zero AI cost to Trellis (BYOK). Adjust Pro token budget or pricing if margins compress |
| GCT funding downturn | Medium | GCT is cyclically funded. Maintain generic architecture so expansion to adjacent verticals (mAb, vaccine) is just a template change, not a rebuild |
| Competitor ships similar features | Low | Move fast on GCT specificity. Deep niche beats broad features. First-mover advantage in a tight community |
| Solo dev burnout | High | Prioritize ruthlessly. One feature at a time. Don't build Phase 2 during Phase 1. Take weekends off. The SBIR runway gives permission to be patient |
| Enterprise customer wants GMP before ready | Low | Quote a timeline and a price. If they're serious, their deposit funds the development. Don't build on spec |
| Data breach / security incident | High | Encrypt at rest and in transit. Regular backups. Don't store more than needed. Have an incident response plan before launch, even if it's a simple one |

---

## Market Context

### ELN Market Size
- **Global**: ~$700M (2024), growing to $1B+ by 2030 at 7.3% CAGR
- **Pharma/biotech segment**: 47% of market (~$329M)
- **Cloud/SaaS**: 81% of deployments

### GCT Market
- **2,000+** gene/cell therapy clinical programs worldwide
- **~30** approved GCT products globally (growing rapidly)
- **Each program** has a PD team of 5-15 scientists
- **99%** of biotech companies are SMEs (under 500 employees)

### Adoption Gap
- **~70%** of labs still use paper notebooks as primary record-keeping
- **Only ~30%** have adopted ELNs
- **Top barriers**: Cost, UX problems, device accessibility, institutional inertia
- **This is our opportunity**: The 70% on paper are not comparing ELNs — they need a reason to switch from paper. GCT-specific templates and AI image analysis are that reason

### Funding Environment
- **$21-26B** in biotech VC raised in 2024
- Average biotech burn rate: ~$20k/employee/month
- GCT companies are well-funded (large Series A/B rounds common)
- Tool budgets are embedded in R&D spend — a $3,600/year subscription is noise in a $5M+ annual burn rate

### SaaS Benchmarks
- **Trial-to-paid conversion**: 18-25% average for B2B SaaS (opt-in, no credit card)
- **Annual churn**: 3-5% for niche B2B SaaS with high switching costs
- **At 20% conversion**: 250 trial teams → 50 paying teams (sustainability target)
