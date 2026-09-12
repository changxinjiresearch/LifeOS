# NextPlan Local v0.1 — Security Model

Status: **FROZEN baseline for Stage V**

## Trust boundaries

1. ChatGPT page content is untrusted input.
2. Browser-extension messages are accepted only after local pairing is introduced in Stage 4.
3. Localhost is not treated as authentication by itself.
4. Local Core is the canonical policy boundary.
5. The model/classifier can propose structured actions but cannot bypass the Action Gateway.
6. The filesystem and applications are protected resources, not implicit model context.

## Local Core network policy

- Bind to `127.0.0.1` only.
- Never bind the consumer runtime to `0.0.0.0` by default.
- Non-health endpoints require a local bearer credential.
- Stage 4 replaces bootstrap/local test credentials with one-time extension pairing and durable local credentials.

## Data policy

- User canonical state is stored locally by default.
- Do not store ChatGPT passwords, session cookies or account credentials.
- Do not scrape or persist authentication material from ChatGPT.
- Conversation capture stores only the evidence/provenance necessary for an accepted state change unless the user opts into broader history later.
- Secrets belong in OS secure storage when the desktop packaging stage is reached, not plaintext configuration files.

## Provenance policy

- User factual assertions may support a canonical write.
- Assistant text may be used for entity/context resolution but is not standalone fact authority.
- Speculation, future intent, hopes and negated completion are not completion evidence.
- Ambiguous entity resolution requires confirmation.

## Execution policy

Models never submit arbitrary shell text. They request allow-listed structured capabilities, for example:

- `artifact.open`
- `folder.open`
- `file.copy`
- `application.open`
- `notification.show`

Risk classes:

- R0 read/inspection: may auto-run within granted scope.
- R1 low-risk reversible/harmless: may auto-run depending on user policy.
- R2 consequential mutation: normally requires confirmation.
- R3 destructive/security-sensitive: explicit confirmation is mandatory; v0.1 should avoid exposing most R3 capabilities entirely.

## Verification policy

An execution request and a successful API/process return are not equivalent to a verified outcome. The execution layer records a receipt and, where possible, checks the expected postcondition before reconciliation.

## Filesystem policy

Future automatic discovery/execution is restricted to user-authorised project workspaces. Whole-disk implicit crawling is out of scope for v0.1.

## Failure policy

- Database writes use SQLite transactions and WAL mode.
- Duplicate event ids are idempotent.
- Failed projections roll back the transaction.
- Capture/extension failure must not corrupt canonical state.
- The user must be able to inspect Activity and later undo state changes with compensating events.
