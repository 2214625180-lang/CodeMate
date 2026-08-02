# CodeMate Demo Script

## 1. Start The Stack

```bash
docker compose up --build
```

Open:

```text
http://localhost:3000
```

## 2. Index A Demo Repository

Use a small repository with:

- `src/math.js`
- `test/math.test.js`
- a failing `add` implementation that returns `a - b`

Submit the Git URL on the repositories page.

Wait for:

```text
indexed
```

Point out:

- file count
- chunk count
- language summary

## 3. Code Q&A

Open:

```text
/repos/<repo_id>/chat
```

Ask:

```text
add 函数在哪里？
```

Show:

- streamed answer
- citation card
- file path and line numbers
- code snippet after clicking citation

## 4. Bug Fix Agent

Open:

```text
/repos/<repo_id>/fix
```

Input:

```text
add function test fails: expected 5 but received -1
```

Test command:

```text
npm test
```

Start the run.

## 5. Explain The Timeline

Walk through the visible events:

- `inspection`: repository and test-command inspection
- `baseline_test_result`: pre-patch failure reproduction
- `agent_plan`: the model's schema-validated next action and remaining budget
- `tool_call search_code` / `find_symbol`: shown when the issue needs discovery; an issue with an explicit path may go directly to `read_file`
- `tool_result`: candidate files, symbols, or bounded file content
- `agent_observation`: evidence summary, action path, and no-progress counter
- `agent_guardrail`: only appears when a duplicate, invalid, over-budget, or unauthorized action is rejected
- `patch`: generated unified diff
- `tool_call apply_patch`: patch applied in sandbox workspace
- `targeted_test_result`: post-patch target test evidence
- `regression_test_result`: regression-suite evidence
- `verification`: strict terminal verdict and all three evidence phases
- `final`: final summary

State clearly that hidden chain-of-thought is not shown.

## 6. Show The Result

Show:

- Diff Viewer: `return a - b` changed to `return a + b`
- Test Result Panel: `verified_success` with baseline, targeted, and regression evidence
- final summary

Submit feedback:

```text
accepted
```

## 7. Evaluation

Prepare:

```bash
cp scripts/eval_cases.example.json scripts/eval_cases.json
```

Fill in the indexed `repo_id`, then run:

```bash
python3 scripts/evaluate_retrieval.py --cases scripts/eval_cases.json
python3 scripts/evaluate_fix.py --cases scripts/eval_cases.json
```

Discuss:

- Recall@5
- Fix Success Rate
- Avg Tool Calls
- Avg Latency
