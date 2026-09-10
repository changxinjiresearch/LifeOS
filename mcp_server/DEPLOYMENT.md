# NextPlan MCP deployment runbook

## Goal

Deploy the private NextPlan MCP server as a small remote HTTPS service. The service exposes NextPlan tools to ChatGPT, writes only append-only events to `events/inbox/`, and leaves `state.json` construction to the existing serialized State Builder.

## Security model

- `NEXTPLAN_GITHUB_TOKEN` must exist only in the hosting platform secret store.
- Never commit a real token, paste it into chat, or put it in the public PWA.
- Use a fine-grained GitHub token restricted to the `changxinjiresearch/LifeOS` repository with the minimum permission required to read repository contents and create event files.
- The MCP server fails closed if no MCP access control is configured.
- `/healthz` is intentionally public and contains no private data.
- For a private endpoint, configure `NEXTPLAN_MCP_PATH_SECRET` with a long random value generated in the hosting platform. Do not reuse a password.
- `NEXTPLAN_ALLOW_INSECURE` must remain unset/false in production.

## Railway deployment

The repository root contains a `Dockerfile`, so Railway can build it directly from the GitHub repository.

1. Create a Railway project/service from the private GitHub repository `changxinjiresearch/LifeOS`, branch `main`.
2. Keep the repository root as the build root. Railway should detect the root `Dockerfile` automatically.
3. In Railway Variables, configure the variables shown in `mcp_server/.env.example`. The two important secret values are:
   - `NEXTPLAN_GITHUB_TOKEN`
   - `NEXTPLAN_MCP_PATH_SECRET`
4. Configure the Railway healthcheck path as `/healthz`.
5. Generate a public Railway domain for the service.
6. Verify `https://<railway-domain>/healthz` returns a 2xx response with `{"status":"ok","service":"NextPlan MCP"}`.
7. The private MCP endpoint is then:

   `https://<railway-domain>/<NEXTPLAN_MCP_PATH_SECRET>/mcp`

Do not publish or paste that full secret endpoint into public locations.

## ChatGPT custom app connection

When the account/workspace has full custom MCP support with write actions:

1. Enable Developer mode / custom apps in the workspace settings.
2. Create a custom app named `NextPlan`.
3. Enter the private MCP endpoint from the Railway deployment.
4. Scan/refresh tools and confirm the following tools are present:
   - `get_state`
   - `search_state`
   - `create_project`
   - `create_task`
   - `complete_task`
   - `update_milestone`
   - `update_project`
   - `set_deadline`
   - `add_note`
   - `add_resource`
5. Test reads first, then one harmless write event.
6. Verify the write creates a new file under `events/inbox/`, the State Builder succeeds, and `state.json` reflects the change.
7. Publish/enable the private app for the intended user/workspace only.

## Automatic recording behavior

The tool server itself includes the core policy in its MCP instructions. For stronger cross-chat consistency, install the accompanying NextPlan skill when the ChatGPT workspace supports Skills. The authoritative behavior remains:

- explicit new commitment -> record
- confirmed completion -> record
- confirmed status transition -> record
- confirmed deadline -> record
- explicit note/resource request -> record
- discussion / brainstorming / hypothetical / tentative plan -> do not record
- ambiguous -> ask first
- sensitive/secret content -> never store

## Acceptance test

Use brand-new chats and test at least these cases:

1. `我是不是应该申请 ANU？` -> no write.
2. `我决定申请 ANU，并开始联系导师。` -> create/update a project or task.
3. `邮件写好了。` -> do not mark sent/completed.
4. `邮件已经发给导师了。` -> complete the send task and move the relevant line to Waiting if appropriate.
5. Repeat an already-recorded task -> no duplicate.
6. Two chats create unrelated events close together -> both survive and appear in canonical state.

A build is accepted only when all six behaviors pass and no secret appears in repository history, PWA source, or logs.
