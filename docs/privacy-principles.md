# Privacy Principles

Pro-One should treat privacy as a core part of legal access and legal safety.

People using Pro-One may eventually share sensitive legal facts, court papers, contracts, names, addresses, deadlines, business records, employment facts, housing facts, or other personal information.

The project should be designed to collect less data, store less data, and explain clearly how user information is handled.

## Core privacy standard

Pro-One should collect the least amount of user information necessary to complete a supported workflow.

The project should avoid collecting or storing sensitive legal facts unless there is a clear user benefit, a defined purpose, and appropriate safeguards.

## Data minimization

Pro-One should prefer designs that:

- avoid accounts unless they are necessary
- avoid storing legal documents by default
- avoid storing sensitive facts longer than needed
- avoid collecting information unrelated to the user's task
- allow users to complete basic workflows without unnecessary personal data
- make assumptions visible instead of silently collecting more information

## Sensitive information

Pro-One should treat the following as sensitive:

- names and addresses
- court papers
- contracts
- business records
- financial information
- employment facts
- housing facts
- family facts
- immigration facts
- medical information
- case deadlines
- correspondence with lawyers, courts, agencies, landlords, employers, customers, vendors, or opposing parties

Sensitive information should not be logged, exposed, reused, or retained without a clear reason.

## User documents

Future document-upload features should be designed carefully.

Before supporting document uploads, Pro-One should define:

- what documents are accepted
- why the document is needed
- whether the document is stored
- how long the document is retained
- whether the document is used for retrieval, drafting, or analysis
- whether the user can delete it
- whether the system may send document text to external AI providers

Until those safeguards exist, users should be warned not to upload highly sensitive documents.

## Model training

User legal facts, documents, and case information should not be used for model training without clear user consent.

The project should not hide training or data reuse in unclear language.

Users should be able to understand whether their information is used only to complete their task or for any broader purpose.

## Logs and analytics

Pro-One should avoid placing sensitive information in:

- application logs
- analytics tools
- error reports
- debugging traces
- prompt records
- model output records
- third-party monitoring tools

If logging is needed, logs should be minimized and scrubbed where possible.

## Retention

Pro-One should define retention rules before storing user data.

Retention rules should explain:

- what is stored
- why it is stored
- how long it is stored
- how users can delete it
- whether backups may keep data longer
- whether deleted data is removed from active systems

Data should not be kept indefinitely without a clear reason.

## User control

Users should have control over their information.

Future versions should aim to support:

- reviewing user-provided information
- correcting user-provided information
- deleting stored information
- exporting user-created materials
- choosing whether to save a matter or continue without saving
- seeing what sources and facts were used to generate an answer

## Third-party services

If Pro-One uses third-party AI providers, hosting providers, search services, analytics tools, or storage providers, the project should clearly identify privacy implications.

The system should avoid sending sensitive legal information to third parties unless it is necessary, disclosed, and protected.

## Public filings and private facts

Some court documents may be public, but that does not mean all related user facts should be treated as public.

Pro-One should avoid assuming that user-provided information is safe to expose simply because a legal matter may involve public filings.

## Small-business privacy

Small businesses may share sensitive information such as:

- contract terms
- customer disputes
- vendor disputes
- invoices
- settlement communications
- internal business records
- employee information

Pro-One should treat small-business legal information with the same care as personal legal information.

## Privacy by design

Privacy should be considered before building features, not added afterward.

New features should ask:

- What user information is needed?
- Can the feature work with less information?
- Does the system need to store this information?
- How will the user know what happens to the information?
- Can the user delete or export it?
- Could this information expose the user to harm if leaked?

## Guiding rule

When in doubt, Pro-One should collect less, store less, and explain more.

## External legal research privacy

CourtListener receives only legal-concept queries or base citations selected by server policy, never names, user narratives, uploaded documents or conversation state. Corpus storage contains public legal material, provenance and legal-query checkpoints, not user matters. Provider credentials stay in server environment variables; responses omit tokens, membership/account data and raw error bodies. Independent claim verification receives only a candidate, its cited evidence and relevant legal metadata. Source/filing instructions cannot change orchestration. These controls supplement, rather than replace, model-provider data review and deployment access controls. See [CourtListener](courtlistener.md).
