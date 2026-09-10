# NextPlan Chrome Bridge (Option B)

This is the no-Business fallback bridge for NextPlan.

## Behavior

- Watches completed ChatGPT turns locally in Chrome.
- Does not send the full chat transcript to the NextPlan server.
- Uses a conservative local rule-based classifier.
- Auto-syncs only high-confidence confirmed changes.
- Ambiguous candidates are held in the extension popup for one-click confirmation.
- Writes through the existing NextPlan Event Layer; it never overwrites `state.json` directly.

## One-time setup

1. Load this folder as an unpacked extension from `chrome://extensions`.
2. Open the extension Options page.
3. Generate a browser token and save it locally.
4. Copy that same token into Railway as `NEXTPLAN_EXTENSION_TOKEN`.
5. Click **Test connection** in the extension options.

The token must never be committed to GitHub or pasted into chat.

## Default safety policy

The default automatic threshold is 88%. Questions and uncertain matches are ignored. A missed update is preferable to a wrong update.

## Known limitation

This is not a native ChatGPT MCP integration. If ChatGPT changes its page DOM, the content selector may need an update. Deterministic local rules also cannot understand every ambiguous conversation, so lower-confidence changes remain reviewable instead of being written automatically.
