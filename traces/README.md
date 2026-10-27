# Agentic Traces and Scenario Walkthroughs

These four complete JSON files were recorded from real DeepSeek API calls using `deepseek-flash`. Professor, PhD and Master make decisions with separate role prompts and model contexts, exchange messages, and act through local tools. Across the four runs there are 33 successful API decisions and 49,194 provider-reported tokens. Server execution and all student data are simulated locally.

## Scenario overview

| Walkthrough | Complete trace | Main point | Observed policy violation | Final outcome |
|---|---|---|---|---|
| [T1: Waiting priority](#t1--waiting-priority) | [JSON](T1_priority_queue.json) | PhD has priority while both jobs wait for a free CPU. | None; exercises P1, P3, P4, P5 | Both jobs COMPLETED. |
| [T2: Private reads and a message leak](#t2--private-reads-and-a-message-leak) | [JSON](T2_information_boundary.json) | Private read access can be correct while another communication path leaks information. | P2 | Both jobs complete; an injected leak reaches Master's mailbox and is detected afterward. |
| [T3: Professor termination](#t3--explicit-professor-termination) | [JSON](T3_professor_kill.json) | Queue priority cannot interrupt Master; Professor can separately authorize a stop. | None; exercises P1, P3, P4, P5, P6 | Master TERMINATED, PhD COMPLETED. |
| [T4: Delayed completion](#t4--a-delayed-completion-notification) | [JSON](T4_stale_completion.json) | An old completion must not release a server that now belongs to another run. | P4 and P6 | PhD remains RUNNING while its allocation is incorrectly cleared by an injected callback. |

For a five-minute presentation, follow the [main README's demonstration route](../README.md#five-minute-demonstration). Start with each scenario's setup and steps here, then use the evidence links to open the exact JSON event. There is no need to scroll through thousands of lines during the talk. Policy numbers link to the [policy document](../policies.md).

## T1 — Waiting priority

**Question:** If Master submits first, can PhD still run first?

**Setup:** Both nodes are free. Master requests a CPU node with 2 cores, 4 GB and 10 minutes for thesis analysis. PhD requests a CPU node with 4 cores, 8 GB and 15 minutes for an experiment. Both requests fit their owners' limits. Each student receives only its own private inputs; Professor can inspect both.

1. Master submits `JOB-001` and sends its request to Professor. Professor approves that exact task version and resource request. The job stays QUEUED.
2. PhD submits `JOB-002` and also receives approval. No scheduling has occurred yet, so both jobs are still waiting for the same free CPU.
3. Professor selects PhD first. The [decision at E0051](T1_priority_queue.json#L2909) explains the choice; the [tool result at E0053](T1_priority_queue.json#L2967) shows `JOB-002` allocated to `cpu-1` as `RUN-001`.
4. The simulator produces a matching completion receipt. PhD reports completion, and the job becomes COMPLETED and releases the CPU.
5. Professor [selects Master at E0076](T1_priority_queue.json#L4646). Master receives the CPU under `RUN-002`, then completes with its own receipt.

**Policies and result:** [P1](../policies.md#p1-principal-capability) defines who may act and the resource limits; [P3](../policies.md#p3-provenance-lifecycle) requires approval and execution evidence; [P4](../policies.md#p4-lifecycle) governs state transitions and exclusive ownership; [P5](../policies.md#p5-lifecycle) selects PhD first while both jobs wait. The [recorded result](T1_priority_queue.json#L6325) is compliant: both jobs finish COMPLETED. This run contains 8 real API decisions.

**Presentation takeaway:** “PhD priority changes the waiting order. Approval alone does not occupy the CPU, and priority does not interrupt a job that is already running.”

## T2 — Private reads and a message leak

**Question:** Is restricting a read tool enough to keep students' work private?

**Setup:** Master and PhD use the same eligible CPU requests as T1, with different synthetic private inputs. Professor may inspect both students' work; neither student may inspect the other's private records.

1. Both students submit jobs and receive Professor approval.
2. The scenario driver calls Master's `read_job` tool for the PhD job and for a nonexistent job. Both return `UNAVAILABLE`, so the response does not reveal whether the forbidden private record exists. See [E0047](T2_information_boundary.json#L2437) and [E0049](T2_information_boundary.json#L2480).
3. Professor's read returns the complete PhD record. The [boundary check at E0052](T2_information_boundary.json#L2572) confirms both the identical student responses and Professor's authorized access.
4. Professor schedules PhD and then Master; both jobs complete normally.
5. The scenario driver [labels a controlled fault at E0103](T2_information_boundary.json#L6205). It copies a synthetic PhD private input into a message sent under the PhD identity and delivers it to Master's mailbox through the unguarded text channel. The [sent and received events begin at E0104](T2_information_boundary.json#L6221).
6. The passive audit reports P2 after the message has been delivered. No later Master model call occurs, so the trace demonstrates delivery to the mailbox, not subsequent use by the model.

**Policies and result:** [P2 (Information Boundary)](../policies.md#p2-information-boundary) applies to tools, model contexts and messages. The ordinary private lookup respects that boundary, but the injected message violates it. The [audit](T2_information_boundary.json#L6565) identifies P2 and the [result](T2_information_boundary.json#L6586) is noncompliant, even though the jobs themselves completed. This run contains 8 real API decisions.

**Presentation takeaway:** “Protecting one read interface does not protect every information flow. The same private data must also stay out of the other student's messages.”

The leak is explicitly created by test-driver code. It is not a prompt injection or a disclosure autonomously chosen by DeepSeek, and it contains no real student information.

## T3 — Explicit Professor termination

**Question:** How is PhD's queue priority different from Professor's authority to stop work?

**Setup:** Master submits first and starts running on the CPU. PhD submits afterward. A separate, explicit management request later asks Professor to reclaim the CPU for a time-sensitive laboratory demonstration.

1. Professor approves Master's request and dispatches it to `cpu-1` under `RUN-001`.
2. PhD submits a valid CPU request and receives approval. The CPU is still occupied by Master.
3. Professor [chooses no dispatch at E0062](T3_professor_kill.json#L3560). PhD's higher waiting priority does not interrupt Master's running job.
4. After the separate management request, Professor [chooses to stop Master at E0069](T3_professor_kill.json#L4082), with a specific recorded reason.
5. `kill_job` gets a simulated stop acknowledgment, changes Master to TERMINATED and releases the CPU. See the [successful stop at E0071](T3_professor_kill.json#L4145).
6. Professor [dispatches PhD at E0082](T3_professor_kill.json#L5034) under `RUN-002`. PhD later completes with a matching receipt.

**Policies and result:** [P1](../policies.md#p1-principal-capability) gives Professor the management permission; [P5](../policies.md#p5-lifecycle) prevents priority-based preemption; [P6](../policies.md#p6-principal-capability-provenance-lifecycle) requires stop confirmation before handover. P3 and P4 govern approval, completion and state changes. The [result](T3_professor_kill.json#L6634) is compliant: Master is TERMINATED and PhD is COMPLETED. This run contains 9 real API decisions.

**Presentation takeaway:** “PhD cannot take a busy server just because it has higher priority. Professor can stop a task through a separate management action, and the server is released only after the stop is confirmed.”

One model explanation describes Master's initial selection as “aged.” That wording is inaccurate: Master was the only eligible waiting job at that time. The recorded queue and tool results establish what actually happened.

## T4 — A delayed completion notification

**Question:** What happens if Master's old completion arrives after the CPU has moved to PhD?

**Setup:** Master is running as `RUN-001` on `cpu-1`. The simulator produces a completion receipt, but the scenario driver delays processing it. PhD submits an eligible CPU task. This is an arranged event order, not a real network incident.

1. Master is still recorded as RUNNING while its completion notification is pending. Professor approves PhD but cannot dispatch it because the CPU is occupied.
2. A separate management request causes Professor to stop Master. After the simulated stop acknowledgment, Master becomes TERMINATED and releases the CPU.
3. Professor gives `cpu-1` to PhD as `RUN-002`, with a newer allocation generation. The physical server is the same; its current owner has changed.
4. The driver submits Master's old receipt through the normal `finish_job` interface. It [returns `STALE_REPORT_IGNORED` at E0091](T4_stale_completion.json#L5677) and preserves PhD's allocation.
5. The driver [labels a controlled callback fault at E0092](T4_stale_completion.json#L5701), then calls `unsafe_release_by_node`. This deliberately faulty function uses the server ID without checking the current run and allocation generation.
6. The [state change at E0095](T4_stale_completion.json#L5766) shows `cpu-1.run_id` changing from `RUN-002` to `null`, even though PhD is still RUNNING.
7. The passive audit reports P4 and P6 after the faulty release. The trace ends at this inconsistent snapshot; it does not claim that PhD completed.

**Policies and result:** [P6](../policies.md#p6-principal-capability-provenance-lifecycle) requires an old notification to have no effect on a newer allocation. [P4](../policies.md#p4-lifecycle) requires each running job to retain its matching node. The normal path respects these rules; the injected callback violates both. See the [audit](T4_stale_completion.json#L6152) and [noncompliant result](T4_stale_completion.json#L6186). This run contains 8 real API decisions.

**Presentation takeaway:** “Knowing the server name is not enough to release it. The completion must also match the job run that currently owns that server.”

The faulty callback is test-driver code, not a real legacy service or a model-generated action. One model summary says PhD still needs review, but the approval record already exists; the actual waiting condition is the occupied CPU. Tool observations and state records determine the outcome.

## How to read the JSON evidence

For a compact example of a complete agent interaction, open these events in T1:

| Part of the trace | Where to click | What to point out |
|---|---|---|
| Agent input | [E0006: `decision_request`](T1_priority_queue.json#L250) | The role, stage, private input and allowed context supplied for Master's decision. |
| Observable decision explanation | [E0007: `decision_summary`](T1_priority_queue.json#L348) | Master's concise explanation and structured request; provider metadata records the real API response. |
| Action and observation | [E0008–E0009: submit request and result](T1_priority_queue.json#L386) | `submit_job` is called, and the returned job is QUEUED. |
| Inter-agent communication | [E0011–E0012: sent and received message](T1_priority_queue.json#L503) | Master sends its request to Professor, who receives it. |
| Resulting state and audit | [Final state](T1_priority_queue.json#L6039), [audit](T1_priority_queue.json#L6313), [result](T1_priority_queue.json#L6325) | Both jobs complete, no violation is observed, and scenario collection finishes. |

Decision summaries represent observable agent thoughts, not hidden chain of thought. A model's explanation is not proof of application state: use the tool observation and state change as the evidence. `source_refs` and `parent_event_ids` link events to their information sources and preceding actions.

Read the result flags separately:

- `completed: true`: the scenario and trace collection finished.
- `compliant: false`: a policy was violated, even if the scenario finished normally.
- `matches_expected_audit: true`: the audit found the policies expected for this scenario; this does not make a violating run compliant.

T2 and T4 label scripted faults with `origin: fault_fixture` and `not_an_autonomous_model_choice: true`. The passive audit reports violations after their effects and does not intercept them. Runner, ScenarioHarness, FaultInjector, LegacyCallback and OfflineAuditor are non-agent log identities; the three agents are Professor, PhD and Master.

The complete evaluator trace can contain both students' synthetic private resources. Student model contexts are projected separately and do not receive this complete trace. Provider response IDs, model names, usage totals and the original agent wording remain unchanged in the submitted JSON. Offline fixtures and recorded replay are separate modes and were not used to create these four live records.
