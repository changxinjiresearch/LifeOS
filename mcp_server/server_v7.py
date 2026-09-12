from __future__ import annotations

from . import server_v6 as v6
from .cloud_classifier_v2 import classify_turn as classify_turn_v2

# server_v6 resolves the global `classify_turn` name at request time, so replacing
# it here upgrades entity resolution without changing the installed Thin Bridge.
v6.classify_turn = classify_turn_v2

app = v6.app
mcp = v6.mcp
