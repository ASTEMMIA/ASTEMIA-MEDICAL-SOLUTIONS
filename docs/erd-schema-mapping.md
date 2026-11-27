# AMS ERDs to the CEDA schema

How the five Visio ERDs became the MySQL 26.10 schema. The full per-entity
list is generated in [erd-inventory.md](erd-inventory.md).

| ERD file | Extracted to |
|---|---|
| `AMS_MASTER_SCHEMA_WIP_ERP.vsdx` | `src/astemia/adapters/db/erd/ams_master_schema_wip_erp.json` |
| `ZETTER_AMS_SCHEMA_ERD.vsdx` | `.../erd/zetter_ams_erd.json` |
| `PDi_AMS_SCHEMA_ERP.vsdx` | `.../erd/pdi_ams_schema_erp.json` |
| `AHIS_MASTER_ERD.vsdx` | `.../erd/ahis_master_erd.json` |
| `AE_AMS_SCHEMA_ERD.vsdx` | `.../erd/ae_ams_erd.json` |

`tools/extract_vsdx_erd.py` reads the Visio database-model store embedded in
each file (`VisDBEngrData/.../MAPInfo`), which holds every entity and field,
not just the ones drawn on the page. Each name in that store is followed by a
record tag that says whether it is an entity, a field or a primary-key field.
The extractor classifies by those tags, so it needs no hand-maintained lists
and handles fields that repeat inside the national extracts.

## Three layers

1. **Canonical** (CEDA section 3): every party, identity, directory and A&E
   entity, with the CEDA envelope (`tenant_id`, opaque UUID `id`, `version`,
   provenance, sensitivity), composite foreign keys that include `tenant_id`,
   and UTC `DATETIME(6)`.
2. **Verbatim staging** (`stg_*`, MIG-01): each ERD entity with up to 60 fields,
   field names exactly as drawn (snake_case, renamed by the naming rules below), values as raw
   `TEXT`, plus lineage: batch, source system and row key, SHA-256 row digest,
   mapping version, reconciliation status and exception owner. A unique key on
   the digest means a re-run batch adds zero duplicates (MIG-02).
3. **National extracts**: A&E transactions, Admitted Patient Care (733 fields),
   Outpatients (350), MHMDS (102), Ward Attenders and Elective Admissions.
   MySQL 26.10 rejects these as tables: even as `TEXT`, 230 columns exceed
   InnoDB's 8126-byte row limit. Their fields live in `national_extract_field`
   (position, key, label, original label, occurrence for repeating groups) and
   their rows as JSON in `stg_extract_record` (inbound) and
   `national_extract_record` (outbound returns).

## Canonical mapping

| ERD entity (all files) | Canonical table(s) |
|---|---|
| Party | `party` (supertype; patient, practitioner, organisation and alternative contact share its key) |
| Person, Patient / Service User, Person_History | `patient` |
| Person Name, Name, Name_History, Name Type | `person_name`, `name_type` |
| medicare_number, NIN (ERD nhs_number), old-style and temporary numbers, Local Patient Identifier, STG_999_COM_LPI | `patient_identifier` (unique while active per tenant, issuer and value) |
| ADDRESS, Address, Person_Address(+_History, +_Future), Alt_Cont_Address(+_History, +_Future) | `address` + `party_address` (effective-dated; address lines 1–6, state, LGA, postcode, PAF key, gazetteer) |
| ADDRESS/PARTY, Address Party | `party_address` |
| Address Type | `address_type` |
| TELECOM COMMUNICATION, Person_Telecom(+_History, +_Future), Alt_Cont_Telecom(+…) | `telecom` |
| TELECOM SERVICE PROVIDER, IT SERVICE | `service_provider` |
| PRODUCT | `it_product` |
| Disability_Code(+_History), Alt_Cont_Disability_Code(+…) | `party_disability` |
| Primary_Care(+_History, +_Future), registered doctor fields | `primary_care_registration` |
| Nominated_Pharmacy(+_History) | `nominated_pharmacy` |
| Alternative_Contact(+_History, +_Future), Contact, Person/Person | `alternative_contact` (+ its own party addresses and telecoms), `guardian_authority` |
| CONSENT, CONSENT_HISTORY | `consent` (superseding rows) |
| Duplicates | `duplicate_candidate` |
| Manage_Trans | `merge_link` |
| Transaction | `demographic_transaction` |
| ORGANISATION, ORGANISATION SITE, DEPARTMENT | `organisation`, `organisation_site`, `department` |
| ROLE PROFILE, ORGANISATION PERSON | `role_profile`, `practitioner_role` |
| HealthProfessional, Healthcare Professional | `practitioner` |
| Care Provision | `care_provision` |
| Legitmate Relationship | `legitimate_relationship` (practitioner or workgroup) |
| WORKGROUP TEAM, …MEMBERSHIP, …SERVICE | `workgroup_team`, `workgroup_team_membership`, `workgroup_team_service` |
| BUSINESS (CLINICAL) SERVICE, BUSINESS ACTION, MESSAGING CONTRACT PROPERTIES | `business_service`, `business_action`, `messaging_contract` |
| STG_010_AE_TRANSACTION, AE_TRANSACTION, LND_010_AE_MK (A&E fields) | `encounter` + `ae_attendance` |
| STG_999_COM_DIAG, STG_999_COM_CE_PROC, A&E diagnosis/investigation/treatment lists | `encounter_coding` |
| STG_999_ALL_COPY_RECIPIENT | `encounter_copy_recipient` |

`_History` and `_Future` tables are not copied: each canonical row carries
`effective_from`/`effective_to`, so past, current and future versions are rows
of one table.

## Deliberately not carried into the canonical schema

| ERD field | Why | Where it lives instead |
|---|---|---|
| Password, Logon Name, Registered Smart Card Number, Forti Token ID | Credentials belong in the identity provider (CEDA 7, SEC controls) | Identity provider; `membership.subject` links the login |
| shared_secret | Same | Identity provider |
| Age | Derived from date of birth | Computed on read |
| Demographic copies on CONSENT and Contact (names, address lines, DOB) | Duplicates of the patient record | Read from `patient`, `person_name`, `address` |
| `*_PSEUD` columns | Pseudonymised values are produced for secondary use (CEDA 7.3), not stored beside the real value | Warehouse pseudonymisation |

All of these remain in the `stg_*` tables, because staging must hold source
rows exactly as received. Access to staging is restricted to the migration role.

## Naming rules for NHS terms

As instructed, with no exceptions:

* **The NHS number and NHS ID become NIN** (Nigerian National
  Identification Number), because they name a person's national identifier:
  `nhs_number` becomes `nin`, `NHS_NUMBER_STATUS_IND` becomes `NIN_STATUS_IND`,
  "Previous NHS Number" becomes "Previous NIN". NHAIS (the registration system)
  becomes NIMC, the NIN issuer.
* **Every other NHS becomes Astemia Medical Solutions:** "NHS Status" becomes
  "Astemia Medical Solutions Status" (`astemia_medical_solutions_status`),
  "Date of NHS Exit" becomes "Date of Astemia Medical Solutions Exit", and the
  business clinical service's "NHS BS Code / Name" becomes "Astemia Medical
  Solutions BS Code / Name". Directory and organisation names follow it too,
  for example "Astemia Medical Solutions Greater Glasgow and Clyde".

Migration 0007 renamed the affected staging columns in place, so staged values
are kept. The extract dictionary keeps the original label in `source_label`
for lineage. The canonical issuer is `NG-NIN` (11 digits); the old UK issuer
and its check-digit rule were removed.

## GP renamed to medical doctor

As instructed, GP (general practitioner) is named **medical doctor**, the term
the ZETTER ERD already uses:

* `Registered GP Number` becomes `registered_medical_doctor_number`.
* `GP_CODE` becomes `MEDICAL_DOCTOR_CODE`.
* `ORG_CODE_GP` becomes `ORG_CODE_MEDICAL_DOCTOR`.
* Catalogue service D36-07 is **Medical doctor out of hours**.

The AHIS GP columns in `stg_patient_service_user` merge into the existing
ZETTER medical doctor columns (migration 0005). The CDS suffix `VGP`
(variant grouping) is not a GP field and is unchanged. The extract dictionary
keeps the original label in `source_label`.

The rule has no exceptions. The Astemia Medical Solutions Greater Glasgow and
Clyde directory listings are renamed too:
"GP Service" becomes "Medical Doctor Service", "GP Out of Hours" becomes
"Medical Doctor Out of Hours", and "Out of Hours GP Service" becomes "Out of
Hours Medical Doctor Service" (migration 0006, including tenant search
aliases), and "Shops in NHSGGC" became "Shops in Astemia Medical Solutions"
(migrations 0007 and 0008). Only the listing URLs keep the old letters, because
they are the publisher's own web addresses and changing them would break the
links.

## Decisions for the data architect

1. **Name and address type values.** The ERDs define the tables but not their
   values. Migration 0002 seeds proposed defaults (usual, preferred, maiden,
   alias, previous; home, correspondence, temporary, work, billing, site).

## Decided

* **medicare_number is retired in favour of the NIN** (23 November 2026).
  New registrations cannot bind a Medicare number (`422 medicare_number_retired`).
  Migrated Medicare numbers are kept as `previous` identifiers that never hold
  the active binding, so legacy records can still be matched. Migration 0003
  maps the national-extract identifier fields (MEDICARE Number, MEDICARE_ID,
  their status indicators and pseudonyms) to the NIN. Fields naming the
  Medicare programme (service agreements, Medicare sites) are unchanged.
  Staging keeps the source column names.
* **All service catalogue groups D01-D50 are in pilot scope** (23 November
  2026), including the ASTEMIA extension groups D37-D50. Each service is
  still activated per facility under CAT-05.
* **Mother's and father's names are kept** (23 November 2026). They are
  stored on `patient` for identity verification only. They are not returned
  in the chart and never written to audit records or events.
