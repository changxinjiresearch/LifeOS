# NextPlan Search / Command Palette v1

## Goal

Provide one fast entry point for locating NextPlan state and navigating the application without manually opening every section.

## Search coverage

Unified search covers:

- projects
- tasks / milestones
- notes
- resources
- deadlines
- calendar events
- recent state-history events

Supported filters include `kind:`, `type:`, `status:`, `area:` and `project:`. Plain text is matched across names, descriptions, next actions, IDs and linked project names.

## Command palette

`Cmd/Ctrl + K` opens the palette. Commands beginning with `>` navigate directly to Home, Projects, Tasks, Calendar, Weekly Review, Notes, Resources or Analytics. Search results retain their entity type and contextual subtitle so the user can distinguish similarly named items.

## Cloud endpoint

Authenticated Thin Bridge clients can request `POST /extension/search` with `query` and optional `limit`. Search is read-only and never mutates canonical state.

## Safety

Search returns only material already present in canonical NextPlan state. It does not inspect external repositories or connected services unless those locations were explicitly stored as safe resource pointers.
