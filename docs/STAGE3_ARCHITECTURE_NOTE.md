# Stage III architecture note

The local Chrome extension remains a thin transport/UI bridge. Stage III external-action logic belongs cloud-side and behind provider APIs/connectors. Browser scraping is a fallback, not the default integration strategy.

The agent loop must remain separate from canonical state mutation: plans and external signals are provisional until verified action results are reconciled through the event layer.
