# NextPlan Jarvis — zero-paid-cost Cloudflare Brain adapter (P4)

**Status:** Implemented and covered by mock CI; **not deployed to a Cloudflare account**. Live inference is blocked until the account owner creates a Workers FREE account and deploys this Worker. It is NOT a complete P4 acceptance claim.

## Hard cost constraint

- Use **Cloudflare Workers Free** and **Workers AI Free allocation only**.
- Source hardcodes the open-weights Apache-2.0 Qwen3-30B-A3B-FP8 Cloudflare-hosted model (subject to model availability and Workers Free plan eligibility): `@cf/qwen/qwen3-30b-a3b-fp8` candidate. Model availability can change; inspect the current official pricing/model catalog before deploying.
- Free tier currently grants 10,000 Workers AI neurons/day. On **Workers Free**, over-limit inference is rejected, not automatically billed. On **Workers Paid**, overages can be billed. **DO NOT UPGRADE TO PAID** to work around any limit.
- This project has no paid OpenAI/Gemini/other LLM fallback, no auto-purchase, no remote GPU rental and no worker-side persistent storage.
- Basic Worker code and Workers AI binding are built for the free tier, but this README cannot certify the account owner's actual plan/billing. Confirm it yourself in Cloudflare dashboard before first inference.
- There is no guarantee a third-party free service will remain available indefinitely.

Official references:
- https://developers.cloudflare.com/workers-ai/platform/pricing/
- https://developers.cloudflare.com/workers-ai/models/qwen3-30b-a3b-fp8/
- https://developers.cloudflare.com/workers-ai/get-started/workers-wrangler/

## Architecture

```
NextPlan Web + opt-in per-turn checkbox
        |
        | HTTPS to YOUR worker (question + user-selected context)
        v
Cloudflare Worker: bearer secret + origin + size/policy gate
        |
        | env.AI.run() binding
        v
@cf/qwen/qwen3-30b-a3b-fp8, Workers AI free allocation
        |
        v
Grounded text-only response and source pointers to NextPlan
```

Browser-local encrypted knowledge remains on the user's device; only up to 8 selected snippets are submitted to the Worker on each explicitly authorized question. The session's most recent 6 already-authorized Jarvis conversation turns may also be transmitted for continuity. ChatGPT hidden memory or full chat history is **not** available.

The Worker does not keep conversations on the server and intentionally does not log questions or responses, but the inference provider's own processing and retention policies still apply. Do not submit secrets, medical records, visa papers, or other sensitive information.

## One-time account owner deployment (NO ChatGPT API key)

1. Register/sign in at https://dash.cloudflare.com/ and confirm your account is on the **Workers Free** plan. Do not enable Workers Paid or add a billing method merely to deploy this.
2. Install Node.js locally if needed. In a checkout of `LifeOS`, open `cloudflare_jarvis_free/`.
3. Run `npx wrangler login`; authenticate in the Cloudflare browser page.
4. Generate your own random secret **locally** (at least 32 characters); do not share it with ChatGPT, add it to GitHub or put it in a URL. Example on macOS/Linux: `openssl rand -hex 32`.
5. Run `npx wrangler secret put JARVIS_SHARED_TOKEN`, then paste the random secret at the Wrangler prompt.
6. Run `npx wrangler deploy` while still in `cloudflare_jarvis_free/`. Check that Wrangler reports your Worker on `https://<worker>.<account>.workers.dev`.
7. Open `https://<worker>.<account>.workers.dev/health` — `configured` must be `true`. This route never shows your secret and does not consume inference credits.
8. Open https://changxinjiresearch.github.io/LifeOS-App/jarvis.html . Fill **Free Remote Jarvis Brain** Worker URL and the same secret; click Configure. No ChatGPT/API paid key is required.
9. Unlock your browser-local memory as before, ask a question and explicitly check the Cloudflare consent box. The first request also verifies the secret.
10. Inspect Cloudflare Workers AI dashboard usage. Never upgrade if the free quota is exceeded.

The ChatGPT-side assistant currently has GitHub and Railway integrations, but **not a Cloudflare account deployment integration**. It cannot complete account registration, authenticate Wrangler, or provision the Worker without the account owner's own action.

## Security and cost guardrails

- Requests accepted only from the NextPlan Web origin, with an independent 32+ character Worker secret. CORS is not authentication; bearer authentication is mandatory.
- The Worker code never receives an OpenAI token and has no fallback AI provider.
- Remote URL is restricted in the NextPlan UI to `https://*.workers.dev`, not arbitrary untrusted domains.
- Inputs are size-limited and source entries must have known statuses. Retrieved knowledge is treated as untrusted data, not executable instructions.
- No task writes, no shell/OS tools, no spontaneous actions; model reports `executed_actions=0`.
- Automatic retry on 429/503 is intentionally disabled, preventing quota waste and loops.
- Only an opt-in user interaction sends private text to the Worker.
- The access token lives only in JS memory while the page is open; it is never committed into repository, URL parameters or `localStorage`.
- Worker uses Cloudflare's AI binding and never requires your NextPlan Railway server to host a model.

## Tests (run without touching Cloudflare billing)

```sh
node --test tests/worker.test.mjs
```

CI: `.github/workflows/jarvis-free-ai.yml`. These tests mock inference and **do not prove real Cloudflare model availability, throughput, billing configuration or live response quality**.

## Outstanding acceptance

- Account owner must complete Workers Free registration/deployment and verify plan cost.
- Real first-response test, rate-limit/quota behavior and latency measurement on deployed Worker.
- Review what source context is appropriate for third-party AI; refine selective retrieval before bulk usage.
- Browser E2E after deployment, user feedback and consistency testing.
