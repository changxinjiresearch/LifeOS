from __future__ import annotations

from . import server_v11 as v11
from . import server_v6 as v6
from .cloud_classifier_v6 import classify_turn as classify_turn_v6

# Stage IV keeps the proven Stage III production app and replaces only the cloud
# turn classifier. server_v6 resolves this module global at request time, so the
# existing /extension/classify endpoint immediately uses the Stage IV classifier.
v6.classify_turn = classify_turn_v6

app = v11.app
mcp = v11.mcp
