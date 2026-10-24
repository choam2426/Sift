# SSA call-graph enrichment

`extract_routes` produces route units from AST registration/middleware/handler.
`extract_calls` loads the target module with `go/packages`, builds an SSA call
graph (CHA), and appends reachable functions to each route unit.

Run the AST extractor with `-depth 0` to keep the route unit compact, then enrich:

```bash
cd experiments/logic-ranker/extract_routes
go run . -root /path/to/module -out /tmp/routes -depth 0
cd ../extract_calls
GOWORK=off go run . -root /path/to/module \
  -routes /tmp/routes/routes.jsonl -out /tmp/routes-enriched/routes.jsonl \
  -max-depth 4 -max-sources 12 -max-index 400
```

Project-package functions are listed before external dependencies, and the full
call-graph index is capped so the target route stays below the 80k text limit.
The index is a decision-path aid, not a proof of reachability or vulnerability.

For a nested Go module, set `-key-prefix` and `-pkgs` for that module, e.g.:

```bash
go run . -root repo/pro -key-prefix 'pro/' -pkgs ./api ...
```

Known limit: CHA over-approximates interface dispatch and can include unrelated
implementations. Check oracle functions in the coverage gate rather than trusting
the index size.
