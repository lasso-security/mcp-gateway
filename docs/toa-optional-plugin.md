# Optional TOA verify plugin (docs)

Lasso MCP Gateway is plugin-based (guardrails + tracing). Those plugins inspect
or transform live traffic. [TOA](https://github.com/Carmel-Labs-Inc/toa)
(`toa/0.1`) is different: offline delivery evidence before enable, not a
per-call guardrail.

## Suggested contribution shape

1. Docs / example CI step that runs `toa-verify` when `toa.json` is present.
2. Optional future guardrail that *fails closed* only when an operator opts in
   and supplies a path to a recent attestation (still not signing every call).

This PR ships (1) only.

```yaml
      - name: Verify tool delivery attestation
        if: hashFiles('toa.json') != ''
        run: |
          pip install "git+https://github.com/Carmel-Labs-Inc/toa.git@345f24607919b5bdf143719b9ea062543cdfe88e#subdirectory=python"
          toa-verify toa.json --require-layer functional=pass
```

Example: [`../examples/toa-after-gateway.yml`](../examples/toa-after-gateway.yml).

See also [Plugin System](../mcp_gateway/plugins/README.md).
