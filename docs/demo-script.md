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

- `plan`: issue parsing
- `tool_call search_code`: retrieval over indexed chunks
- `tool_result search_code`: candidate files and symbols
- `tool_call read_file`: full file context
- `patch`: generated unified diff
- `tool_call apply_patch`: patch applied in sandbox workspace
- `tool_call run_tests`: Docker sandbox test execution
- `test_result`: stdout, stderr, exit code
- `final`: final summary

State clearly that hidden chain-of-thought is not shown.

## 6. Show The Result

Show:

- Diff Viewer: `return a - b` changed to `return a + b`
- Test Result Panel: passed
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
