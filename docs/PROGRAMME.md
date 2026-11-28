# Whole-programme plan

The plan for the rest of the ASTEMIA health build: every CEDA workflow and
every ICRS module placed in a phase, with what each depends on, how it will be
accepted, its risks, and the decisions it needs. Health only; the Syntegra
education system has its own repository and plan.

Position on 28 November 2026. [STATUS.md](STATUS.md) remains the authoritative
list of what is built; [icrs-traceability.md](icrs-traceability.md) lists each
delivered requirement with the test that proves it.

## Where the build stands

### ICRS requirements

All 971 numbered requirements of the consultation, by owning module. A
requirement is **delivered** only when the build meets it as written and a
named test proves it. The 493 requirements in modules with built work were
reviewed one by one on 28 November 2026; each finding, with its reason, is in
[reviews/icrs-review-2026-11-28.jsonl](reviews/icrs-review-2026-11-28.jsonl).
Modules where nothing is built were not reviewed line by line: all of their
requirements are open.

| Code | Module or area | Requirements | Delivered | Partly built | Not built | Not reviewed (nothing built) |
|---|---|---:|---:|---:|---:|---:|
| 101 | User Tools | 152 | 0 | 48 | 104 | 0 |
| 102 | Patient Index | 50 | 9 | 23 | 18 | 0 |
| 103 | Prevention, screening and surveillance | 20 | 0 | 0 | 0 | 20 |
| 104 | Assessment | 4 | 0 | 0 | 0 | 4 |
| 105 | Integrated Care Pathways and Care Planning | 21 | 0 | 16 | 5 | 0 |
| 106 | Clinical Documentation | 17 | 0 | 6 | 11 | 0 |
| 107 | Care management | 42 | 1 | 23 | 18 | 0 |
| 108 | Scheduling | 76 | 0 | 25 | 51 | 0 |
| 109 | Electronic Booking | 50 | 0 | 0 | 0 | 50 |
| 110 | Requesting and order communications | 18 | 1 | 7 | 10 | 0 |
| 111 | Results reporting | 6 | 1 | 3 | 2 | 0 |
| 112 | Decision support | 15 | 0 | 0 | 0 | 15 |
| 113 | Prescribing and pharmacy | 71 | 0 | 0 | 0 | 71 |
| 114 | Diagnostic and Investigative Services | 10 | 0 | 1 | 9 | 0 |
| 115 | Digital Imaging and PACS | 26 | 0 | 0 | 0 | 26 |
| 116 | Document Management | 13 | 0 | 0 | 13 | 0 |
| 117 | Financial Payments to Service Providers | 5 | 0 | 0 | 0 | 5 |
| 118 | Maternity | 4 | 0 | 0 | 0 | 4 |
| 119 | Social Care | 33 | 0 | 0 | 0 | 33 |
| 120 | Dental Services | 0 | 0 | 0 | 0 | 0 |
| X1 | Context and vision | 54 | 0 | 0 | 0 | 54 |
| X2 | Platform and information governance | 49 | 6 | 24 | 19 | 0 |
| X3 | Delivery, testing, training, data conversion | 44 | 0 | 0 | 0 | 44 |
| X4 | Service levels, resilience, security, administration | 39 | 0 | 7 | 32 | 0 |
| X5 | Standards | 103 | 0 | 0 | 0 | 103 |
| X6 | National services and infrastructure | 49 | 0 | 0 | 0 | 49 |
| | **Total** | **971** | **18** | **183** | **292** | **478** |

What the numbers mean. Much more is built than is delivered: 183
requirements are partly met, because the consultation asks for more than each
slice built (for example scheduling has slots, holds, rescheduling and
attendance, but no clinic templates, waiting lists or block rescheduling).
Context paragraphs (most of X1) state no capability and will never count as
delivered; the plan treats them as background, not work.

### CEDA workflows

The 37 workflows of the CEDA (Annex A): 8 built, 10 partly built, 19 not
started.

| Workflow | Status | What exists | What is missing | Phase |
|---|---|---|---|---|
| UG01 Scheduling | Built | Slots, five-minute holds, race-safe booking, reschedule keeping the original, cancel, attendance | Clinic templates, waiting lists, block reschedule | P1 (templates) |
| UG02 Identity and consultation | Built | Explained matching, steward review, merge and unmerge, notes signed by role, corrections | Co-signature | P6 |
| UG03 Daybook tasks | Built | Owner or queue, reassignment with history, supervisors, deduplicated reminders | Delivery of reminders by message or SMS | P4 |
| UG04 Clinical correspondence | Built | Quarantine, matching with reasons, adjudication, named reviewer, versions | Malware scanning engine, protected object storage | P0 |
| UG05 Shared access and downtime | Not started | Tenant isolation only | Shared care across practices, offline mode and reconciliation | P4 |
| HS01 Primary care and prevention | Not started | | Recalls, immunisations, screening | P7 |
| HS02 Emergency and ambulance | Partly | A&E detail at admission, temporary identity and merge | Triage, ambulance pre-arrival, observations | P1 |
| HS03 Inpatient and surgical care | Not started | Admission and discharge | Beds, wards, transfers, theatre | P1 |
| HS04 Outpatient and virtual care | Built | Video and phone with identity check, failed connection rebookable | | |
| HS05 Referral and discharge | Built | Referral with the patient's history, triage, discharge with owned follow-up | Release to partners outside the tenant | P6 |
| HS06 Laboratory and pathology | Partly | Orders, results, amendments reopening review, laboratory worklist | Specimen receipt and rejection, analyser interfaces | P2 |
| HS07 Radiology and imaging | Not started | | Requests, RIS, PACS, addenda | P2 |
| HS08 Pharmacy and medication | Not started | | Prescribing, dispensing, administration | P5 |
| HS09 Blood bank and transfusion | Not started | | Units, cross-match, issue, reactions | P7 |
| HS10 Allied health and rehabilitation | Not started | | Goals with owner and review | P6 |
| HS11 Maternity, newborn and paediatric | Not started | | Pregnancy, delivery, newborn charts, guardianship | P7 |
| HS12 Long-term and specialty care | Built | Problems, care plans with immutable revisions, sessions, clashes | Pathway templates and goals | P6 |
| HS13 Mental health and safeguarding | Partly | Legal status with history, restrictive practice and independent review, concerns, advocates, access report | Tribunal and court process, restricted-note search counts and export controls | P6 |
| HS14 Dental and community | Not started | | Tooth-site procedures, home visits | P7 |
| HS15 Public health and population reporting | Not started | National-extract dictionary | Submissions, corrections, aggregate-only access | P3 |
| HS16 Patient and representative portal | Not started | | Portal, proxies, correction requests | P6 |
| HS17 Billing, insurance and reconciliation | Not started | | Charges, insurers, allocation | P8 |
| HS18 Inventory, workforce and assets | Not started | | Stock, recalls, devices, rosters | P8 |
| HS19 Records and digitisation | Partly | Inbound correspondence | Scanning batches, retention, legal holds, case-note tracking | P8 |
| HS20 Quality and management reporting | Not started | | Indicators with recorded definitions | P8 |
| SA01 Tenant provisioning | Partly | Tenant isolation everywhere, development seed | Provisioning service, key binding | P4 |
| SA02 Services and subscriptions | Partly | Service catalogue, activation per facility | Subscriptions and module entitlements | P4 |
| SA03 Support and usage | Not started | | Time-boxed support access | P4 |
| SA04 Upgrade and recovery | Not started | Migrations reverse and are checked | Backups, tenant recovery drill | P0 and P4 |
| SA05 Tenant export and offboarding | Not started | | Export with digests, legal holds | P4 |
| WF01 Registration, booking, consultation | Built | All three UAT conditions tested | | |
| WF02 Emergency and inpatient admission | Partly | Temporary identity, admission replay, emergency access expiry | Bed transfer without overlap | P1 |
| WF03 Laboratory orders and results | Partly | Orders, results, amendment, one review | HL7 ORU before ORM, replay of interface messages | P2 |
| WF04 Medication | Not started | | All | P5 |
| WF05 Imaging, theatre, transfusion | Not started | | All | P1, P2, P7 |
| WF06 Referral, discharge, community | Partly | Referral, discharge, follow-up tasks | Proxy rights, delivery to partners | P6 |
| WF07 Maternity, paediatric, specialty | Partly | Revising a completed treatment plan keeps the original | Twin births, guardianship | P7 |

## Phases

Each phase ends the same way as every slice so far: complete, tested at 100%
line coverage against MySQL 26.10 with browser and accessibility checks for
its screens, pushed with CI green, and recorded in STATUS.md and the
traceability page. A phase starts only when what it depends on is merged.

```
P0 Hardening ─┬─> P1 Inpatient core ──┬─> P3 Migration and national returns ──> Pilot go-live
              ├─> P2 Interfaces ──────┘
              └─> P4 Production identity and tenancy ─────────────────────────> Pilot go-live
P5 Medicines (waits for decision D1) ─────────────────────────────────────────> after go-live
P6 Patients and community, P7 Specialties, P8 Operations ─────────────────────> after go-live
```

P1, P2 and P4 can run in parallel after P0. P3 needs P1 and P2, because
migrated records must land in beds, encounters and results that exist.

### P0 Hardening review (next)

- **Scope:** threat model and security review of every endpoint; tenant
  isolation proved by a test for every resource; concurrency of every write
  path; load test against NFR-02 (chart read p95 at most 2 seconds);
  integrity of the audit trail; malware scanning and protected object storage
  for correspondence (UG04); backup and restore of one tenant (SA04 first half).
- **ICRS:** X2, X4 (partly).
- **Depends on:** nothing.
- **Acceptance:** each finding fixed with a test that failed before the fix;
  a load report with the p95 measured; no endpoint returns another tenant's
  data; a tenant restored from backup in an isolated database matches its
  record counts and digests.
- **Risks:** findings may need schema changes (expand-first migrations only).

### P1 Inpatient core

- **Scope:** wards, beds and occupancy; transfers that close the old
  occupancy; theatre lists, sessions and cancellations that release capacity
  and flag the linked plan; clinic templates and waiting lists (108);
  triage and ambulance pre-arrival for A&E (HS02).
- **Workflows:** HS03, HS02, WF02, WF05 (theatre part), UG01 (templates).
- **ICRS:** 107, 108 (bed management, theatres, waiting lists).
- **Depends on:** P0.
- **Acceptance (CEDA):** transfer closes the old occupancy; a cancelled
  operation releases theatre capacity and flags the inpatient plan; an
  overlapping bed transfer is refused (UAT WF02); scheduling across an
  unavailable asset is refused (UAT WF05).
- **Risks:** bed and theatre rules differ by site; agree them with the pilot
  hospital before building (decision D7).

### P2 Interfaces and diagnostics

- **Scope:** HL7 v2 interface engine (ADT, ORM, ORU) with replay safety;
  FHIR R4 read API for partners; specimen receipt and rejection with
  recollection (HS06, API-04); radiology requests, RIS, PACS viewer
  integration and signed addenda (HS07); terminology validation of codes.
- **Workflows:** HS06, HS07, WF03, WF05 (imaging part).
- **ICRS:** 110, 111, 114, 115, X5 (messaging standards).
- **Depends on:** P0.
- **Acceptance (CEDA):** a result delivered before its order is reconciled
  once the order arrives; every input replayed creates nothing twice (UAT
  WF03); a rejected sample creates a recollection request; a study with
  conflicting identity stays off the chart; an addendum keeps the original
  report; PACS access for another patient is refused (UAT WF05).
- **Risks:** partner systems and their message specifications (decisions D3,
  D4); test analysers and a PACS are needed for integration testing.

### P3 Data migration and national returns

- **Scope:** loaders from the legacy systems into the 66 staging tables
  already in the schema, reconciliation reports, cut-over rehearsal
  (MIG-01 to MIG-03); national returns (APC, outpatients, A&E, mental
  health) from the extract dictionary, with corrections that name the version
  they supersede (HS15).
- **ICRS:** X3 (data conversion), X6, HS15.
- **Depends on:** P1 and P2.
- **Acceptance:** a re-run batch adds no duplicates (already tested for
  staging); every migrated record reconciles by count and checksum to its
  source; a corrected return identifies the superseded version and recipient;
  an aggregate recipient cannot reach patient-level detail.
- **Risks:** source data quality and unknown legacy schemas (decision D5);
  migration windows at the pilot site.

### P4 Production identity, tenancy and resilience

- **Scope:** production identity provider (OpenID Connect) with MFA and
  step-up, including for emergency access; key management; write-once audit
  storage; tenant provisioning, subscriptions and entitlements, time-boxed
  support access, export and offboarding (SA01 to SA05); downtime mode and
  reconciliation (UG05); delivery of Daybook reminders by message and SMS.
- **Workflows:** SA01 to SA05, UG05, UG03 (delivery).
- **ICRS:** X2 (remaining), X4 (resilience), X6 (national identity services).
- **Depends on:** P0.
- **Acceptance (CEDA):** a retried provisioning creates one tenant; a failed
  key binding leaves the tenant inactive; support access expires and its
  history is reviewable; one tenant is recovered in isolation with others
  untouched; an export validates by digest and count; offline attendance
  reconciles against appointments.
- **Risks:** the identity provider and NIN verification depend on outside
  services (decision D2); hosting and recovery objectives (decision D6).

**Pilot go-live** needs P0 to P4. Everything after go-live is ordered by
decision D8.

### P5 Medicines

- **Scope:** prescribing (inpatient, outpatient, to take out), dispensing,
  administration with recorded omissions, pharmacy stock, electronic
  transmission of prescriptions, drug-interaction and allergy checking (112).
- **Workflows:** HS08, WF04.
- **ICRS:** 113, 112.
- **Depends on:** P0, P4, and decision D1.
- **Acceptance (CEDA):** cancelling an undispensed repeat prevents supply; a
  recorded omission is distinct from a missing entry; racing a dispense with a
  cancellation gives one consistent balance and no duplicate stock movement.
- **Risks:** the highest clinical-safety risk in the programme; needs a
  clinical safety officer's sign-off.

### P6 Patients, community and pathways

- **Scope:** patient and representative portal with proxies and correction
  requests (HS16); release of referrals and summaries to partners outside the
  tenant (HS05, WF06); pathway templates and goals (HS10, HS12); mental health
  tribunal and court process, restricted-note search and export controls
  (HS13); co-signature (UG02); electronic booking (109); social care (119).
- **Workflows:** HS16, HS10, WF06, and the rest of HS05, HS12, HS13.
- **ICRS:** 105, 106, 109, 119, 101 (communication tools).
- **Depends on:** P4.
- **Acceptance (CEDA):** an expired proxy loses access to messages and
  documents; a correction request routes to the record owner and keeps the
  original; each active goal shows its owner and review date.

### P7 Specialties

- **Scope:** primary care, recalls and immunisations (HS01, 103); transfusion
  (HS09); maternity, newborn and paediatric care with guardianship (HS11,
  118); dental and community visits (HS14); assessments (104).
- **Workflows:** HS01, HS09, HS11, HS14, WF05 (transfusion), WF07.
- **Depends on:** P1, P6.
- **Acceptance (CEDA):** a completed vaccination closes its recall; a unit
  reserved for another patient cannot be issued; a twin delivery creates two
  newborn charts; a change of guardianship ends the former guardian's access.

### P8 Operations and reporting

- **Scope:** billing and insurers (HS17, 117); inventory, recalls, devices and
  workforce (HS18); scanning, retention, legal holds and case-note tracking
  (HS19, 116); quality indicators with recorded definitions (HS20); reporting
  tools (101).
- **Depends on:** P3, P4.
- **Acceptance (CEDA):** replaying a completed visit cannot charge twice; a
  scan batch with missing pages cannot be verified; a held object survives
  disposal; an indicator recomputes for a closed period.

## Risks

| ID | Risk | Effect | Mitigation | Owner |
|---|---|---|---|---|
| R1 | No approved medication list or formulary | P5 cannot start | Decision D1; keep P5 after go-live | Programme owner |
| R2 | Identity provider and NIN verification depend on outside services | Go-live delayed | Choose the provider early (D2); keep development sign-in out of production (enforced) | Programme owner |
| R3 | Interface partners (laboratory analysers, PACS) not available for testing | P2 slips | Agree partners and specifications (D3, D4); build against recorded message samples first | Integration lead |
| R4 | Legacy data quality and unknown source schemas | P3 slips; wrong records migrated | Profile the sources first (D5); reconcile every batch by count and checksum | Data lead |
| R5 | Chart performance under load not yet measured | NFR-02 missed in the pilot | P0 load test before more features | Engineering |
| R6 | Data protection and mental health legislation | Legal exposure | Review against Nigerian data protection law and mental health legislation before go-live; record decisions in the CEDA | Information governance |
| R7 | Backups and recovery untested | Data loss | P0 restore drill; P4 recovery objectives (D6) | Operations |
| R8 | Staff training and adoption | Low use; workarounds | Pilot with named champions; training material from the browser test journeys | Pilot lead |
| R9 | Scope: 478 requirements in modules with nothing built | Plan too large for the pilot | Decision D8 on what follows go-live | Programme owner |

## Decisions needed

| ID | Decision | Needed before |
|---|---|---|
| D1 | The approved medication list and formulary source | P5 |
| D2 | The production identity provider, MFA method, and NIN verification route | P4 |
| D3 | Which laboratory systems connect first, and whether HL7 v2 or FHIR comes first for each | P2 |
| D4 | The PACS and imaging standard (for example DICOMweb) | P2 |
| D5 | Which legacy systems are migrated, and the cut-over approach | P3 |
| D6 | Hosting region, backup frequency and recovery objectives (RPO and RTO) | P4 |
| D7 | Bed, ward and theatre rules for the pilot hospital | P1 |
| D8 | The order of P5 to P8 after go-live, and which modules are out of scope (for example 120 has no requirements; 119 social care may be a separate service) | Go-live |

## Keeping the plan true

- A requirement moves to delivered only in `src/astemia/icrs/data/modules.json`
  with the test that proves it; `tests/unit/test_icrs_traceability.py` fails
  if that test does not exist, and the traceability page is regenerated.
- Each phase updates STATUS.md, this plan's tables and, where a rule changes,
  the CEDA with a new revision.
- The line-by-line review is repeated when a phase completes, for the modules
  it touched.
