"""Process-wide safeguards for API tests."""

from __future__ import annotations

import os

# Collection imports the module-global FastAPI app in several suites. Disable
# implicit SDK tracing before any of those imports can construct a client.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_API_KEY"] = ""
os.environ["LANGCHAIN_API_KEY"] = ""
