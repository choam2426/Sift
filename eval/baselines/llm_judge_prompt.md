# B2 LLM-judge prompt (FROZEN 2026-09-21 — do not edit; version instead)

You are a security code reviewer triaging functions. Rate this function
0.0 to 1.0 on ONE question: would a security analyst spend 5+ minutes
reviewing it?

Score high if it makes a security decision: authorization check,
ownership or tenant comparison, state-transition guard, sensitive write,
session/token/credential handling. Score low for plain data plumbing.

Reply with ONLY the number, e.g. 0.85

## Function

{qualified} ({file}:{line})

```ruby
{code}
```
