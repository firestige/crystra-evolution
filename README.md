# Crystra Evolution

English | [中文](README.zh-CN.md)

evolution-system is crystra-evolution's stateless Metric Result service. It
resolves an `EvaluationSelection` against Evidence, binds the owner-approved
Evaluation Catalog 2.0 review candidate, and returns a `ResolvedEvaluationContext` receipt together
with authoritative Metric Results. Compare requests contain independent left and
right selections; Evolution computes both sides and every compatible delta.

Evolution reads Facts and recorded Traces through the versioned Evidence Query
API. It does not own Evidence, persist a database, write Metric Results back, or
infer unrecorded causality. BI is its presentation client and does not calculate
published metrics.

Iteration 5 deliberately excludes Workflow editing, improvement application, AI
attribution, and the meta-recursive loop. Those remain later product scope rather
than responsibilities of this service baseline.

## Developer preview

The current candidate exposes a closed, side-effect-free compute boundary, an
exact 12-coordinate registry, pure formulas for all 12 candidate metrics, typed
Evidence/Workflow resolvers, and end-to-end SINGLE/FULL_COMPARE/PARTIAL_COMPARE
orchestration. Every successful side returns the exact 12 Metric Results and a
receipt-bound resolved read set; metric-level holes do not fail the other results.
Authoritative integer values and counts are serialized as canonical decimal strings on the JSON wire,
so browser clients retain Python integer precision beyond `2^53-1`. The `coverage` field is always
present: it contains all five fields when Evolution can establish the population and is explicit
`null` when no denominator can be established. A known empty population still uses the five-field
`NO_POPULATION` object with `raw_ratio: null`; non-applicable alerts are also explicit `null`.

The current public Fact projection still does not expose a Usage Event's native
Span identity, so call-scoped Usage inputs produce explicit missing coverage and
are never joined by Delivery identity, timestamp, arrival order, or text.
Role-template rework is instead a descriptive Delivery/template exposure: the
accepted Manifest plus recorded C30 selects the exact template, while a valid
same-Delivery `FINDING_FIX` relationship marks rework. It does not attribute
causality to the template, reviewer, or writer.

Resolution safety limits are configurable. Defaults are 500 unique Deliveries
per side, 20 pages per traversal, 100,000 Fact-plus-Trace records per side, and a
120-second side deadline. Exceeding a bound fails the side explicitly; no result
is silently truncated. The 2.0 Catalog remains a review candidate, so
**compatibility-breaking changes remain possible before publication.**

Historical Workflow enrichment resolves only the exact Package and Snapshot coordinates already recorded by Evidence, using the configured ordered public GitHub sources. The reference coordinate is `firestige/crystra-workflow-package`. A validated in-process cache is keyed by the complete Package/Workflow/Snapshot/Role content coordinate; it is never Evidence authority and never substitutes stale, compatible, latest, branch, or local checkout content. Enrichment failure remains diagnostic and cannot rewrite a Metric Result.

## Development

Python 3.13 and 3.14 are supported. Dependencies and builds are locked with
[uv](https://docs.astral.sh/uv/); local commands default to Python 3.14.

```sh
make sync    # install the exact locked environment
make format  # format Python sources and tests
make lint    # formatting, Ruff, and strict mypy
make unit    # deterministic tests without external services
make build   # build wheel and source distribution
make check   # run the non-container acceptance gate
```

## Local runtime image

Build from the superproject root because the image binds both Evolution source and the pinned Workflow
DSL 2.0 candidate checker:

```sh
docker build -f evolution-system/Dockerfile -t crystra-evolution:local .
```

The process requires `CRYSTRA_EVOLUTION_CONFIG` to name a mounted closed JSON file. Start from
`deployment/evolution.example.json`, keep one to eight public GitHub sources in the order they should
be tried, and lower the included safety limits only when needed. The file has no database or provider
credential field. Container port `8000` is private; `GET /healthz` proves only local process liveness.

## Get the source

This repository is normally consumed as a submodule of
[crystra-evolution](https://github.com/firestige/crystra-evolution):

```sh
git clone --recurse-submodules https://github.com/firestige/crystra-evolution.git
```

To clone it standalone:

```sh
git clone https://github.com/firestige/crystra-evolution.git
```

## Documentation

- [Evolution System design](https://github.com/firestige/crystra-evolution/blob/main/docs/systems/evolution/evolution-system.md)
- [Metric Catalog 2.0 review candidate](https://github.com/firestige/crystra-evolution/blob/main/docs/contracts/evaluation/metric-catalog-2-candidate.md)
- [Evidence Query Contract](https://github.com/firestige/crystra-evolution/blob/main/docs/contracts/evidence-query/evidence-query.md)

## License

[Apache-2.0](LICENSE)

Exact Workflow Package resolution can consume one qualified aggregate Crystra Workflow RC when no package-scoped release exists. It verifies the candidate receipt, metadata digest, all four asset digests, and source/contract bindings before admitting the archive. Multiple matching candidates fail closed; a package-scoped release takes precedence. This enables RC combination qualification without publishing GA.
