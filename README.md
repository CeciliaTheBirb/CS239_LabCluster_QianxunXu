# CS239_LabCluster_QianxunXu

LabCluster is a three-agent prototype for a simulated laboratory server cluster. Professor manages requests and may stop either student's job. PhD can request CPU or GPU and has higher default waiting priority; Master can request CPU only. Students cannot inspect each other's private work, while Professor may inspect both.

```mermaid
stateDiagram-v2
    [*] --> QUEUED: Submit
    QUEUED --> RUNNING: Approval and successful allocation
    QUEUED --> TERMINATED: Reject or cancel
    RUNNING --> COMPLETED: Verified completion
    RUNNING --> TERMINATED: Confirmed stop
```

## Setup and examples

Use Python 3.10 or newer. All runtime and test dependencies are in the standard library. Run commands from the directory containing `phase1/`; no cluster account or GPU is needed.

For a free offline example:

```bash
python3 -m phase1.run --scenario T1_priority_queue --backend deterministic
```

For real DeepSeek agent calls:

```bash
cp .env.example .env
```

Set `DEEPSEEK_API_KEY` to your own key and `DEEPSEEK_MODEL` to an available model, then run:

```bash
python3 -m phase1.run --scenario T1_priority_queue --backend deepseek
```

DeepSeek is the only external service needed for live LLM mode. Offline mode needs neither credentials nor network access. Keep `.env` private. Live calls consume provider credit and do not silently fall back to offline decisions.

Replace `--scenario T1_priority_queue` with `--all` to run all four scenarios. Each invocation writes a new JSON/Markdown trace and local state records under `runtime/runs/`. These generated outputs are ignored by Git. The four selected genuine traces are already in `traces/`.

The model calls are real; server execution is simulated locally. T2 and T4 contain explicitly labeled scripted faults, with passive detection after effects. No safety-enforcing framework is used.

## Tests

The tests are automatic checks of application behavior. `test_cluster.py` has 23 checks for permissions, private access, scheduling, job states, completion evidence and the four scenarios. `test_client.py` has 20 checks using simulated provider responses to verify the model client's request handling and failures. All 43 tests run offline, require no API key and consume no API credit.

```bash
python3 -m unittest discover -s tests -v
```

Run them before a demo and after changing the program; they are not a prerequisite for every application run. `OK` means the checked behavior matched expectations, including the audit detecting the deliberately injected faults. It does not mean every path prevents policy violations, and these test responses are not the submitted genuine DeepSeek traces. The application command above is the running-agent demonstration.

In the whole-application archive, tests are alongside `src/`; enter `src/` and run `python3 -m unittest discover -s ../tests -v`. Test descriptions are included with that archive.

## Project artifacts

- [requirements.md](requirements.md): what the application does and must never do.
- [policies.md](policies.md): detailed permissions, resource capabilities, prerequisites, ordering and information boundaries.
- [traces/README.md](traces/README.md): step-by-step scenarios, policy connections and direct links to evidence in four complete agentic traces.
- `agents/`, `core/`, `fixtures/`, `phase1/`: the application source and synthetic inputs.

The separate requirements archive contains the app/tool descriptions, exact agent prompts and episode files requested by the submission template. The scenario walkthroughs are also integrated into `traces/README.md` so they can be presented directly from GitHub.
