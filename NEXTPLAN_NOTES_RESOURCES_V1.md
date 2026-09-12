# NextPlan Notes / Resources Integration v1

## Separation of concerns

- Task / milestone: an action to execute.
- Note: non-sensitive information or an idea worth retaining, without implying action.
- Resource: a safe pointer to a document, repository, webpage or other location. NextPlan stores the pointer and high-level metadata, not sensitive file contents.

## Note fields

Required: `id`, `title`. Supported metadata: `body`, `category`, `project_id`, `tags`, `at`, `updated_at`.

## Resource fields

Required: `id`, `title`, `location`. Supported metadata: `type`, `description`, `project_id`, `tags`, `at`, `updated_at`.

## Conversation writes

The cloud classifier can recognize explicit note-save instructions and explicit resource-save instructions. A resource write requires an actual location/link; the classifier must never invent a resource location. Notes and resources may be linked to a resolved project.

## Lifecycle

Canonical event types support add, update and remove for both notes and resources. All writes remain append-only at the event layer and are materialized by the state builder.

## Privacy

Do not store credentials, tokens, bank details, identity numbers, medical records or sensitive document contents. Store only safe high-level text and resource pointers.
