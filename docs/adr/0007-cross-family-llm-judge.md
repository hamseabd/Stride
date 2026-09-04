# 0007. Cross-Family LLM Judge

Date: 2026-06-28 · Status: Accepted

## Context

Automated evals require grading—does the agent's reply meet criteria? An LLM grading its own family (Sonnet grading Sonnet responses) exhibits self-preference bias. Models favor outputs they would produce themselves, overrating coherence and underrating factual errors in sibling outputs. This bias undermines eval reliability for production coaching.

## Decision

L2 judges (complex reasoning, multi-criteria grading) run on Amazon Nova Pro via Bedrock, a different model family than Sonnet. The judge follows a critique-then-verdict pattern: first articulate the criteria and find evidence, then render a binary pass/fail. L1 checks remain deterministic and free—regex, length, jargon scanning, schema validation.

## Consequences

Bedrock permissions must be granted in CI. This was missed for 60 nightly eval runs until v2.3. Judge prompts are versioned alongside test fixtures; changes to scoring criteria require ADR review and fixture updates.

Cross-family evaluation adds latency to the eval suite but eliminates the bias. Each eval turn invokes Nova Pro once, at ~$0.003 per call. This cost is acceptable for pre-release validation and regression detection. The judge's verdict feeds into the gate: fails halt the PR, passes advance to merge.
