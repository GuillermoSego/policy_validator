# AWS deployment design (Part 4)

_TODO_ — one page, no code. Cover:

1. **Architecture** — API, compute and logs (e.g. API Gateway → Lambda, CloudWatch), and why.
2. **Policy documents** — where they live and how an updated policy reaches the system.
3. **Authentication and secrets** — how callers authenticate; where the OpenRouter key is stored.
4. **Cost** — rough monthly estimate at ~50,000 receipts/day, including model calls, with the math.
5. **Before production** — two or three additions (monitoring, model-outage handling, PII protection).
