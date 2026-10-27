# Agentic Traces

These four complete JSON files were recorded from real DeepSeek API calls using `deepseek-flash`. Each includes decisions by Professor, PhD and Master, inter-agent messages, tool actions and observations, and state changes. Across the four runs there are 33 successful API decisions and 49,194 provider-reported tokens. Server execution is simulated locally.

| Trace | Scenario | Observed policy violation | Final outcome |
|---|---|---|---|
| [T1_priority_queue.json](T1_priority_queue.json) | Both eligible CPU jobs wait; PhD runs before Master. | None; exercises P1, P3, P4, P5 | Both jobs COMPLETED. |
| [T2_information_boundary.json](T2_information_boundary.json) | Student private reads are isolated, then a scripted peer-message leak is delivered. | P2 | Jobs complete; the injected leak is detected after delivery. |
| [T3_professor_kill.json](T3_professor_kill.json) | PhD waits for a running Master; Professor separately stops Master and hands over the node. | None; exercises P1, P3–P6 | Master TERMINATED, PhD COMPLETED. |
| [T4_stale_completion.json](T4_stale_completion.json) | The normal stale-report path is safe; a scripted faulty callback releases a newer allocation. | P6 and P4 | PhD remains RUNNING while its allocation is incorrectly cleared. |

## How to read a trace

`decision_request` records the input context. `decision_summary` records the agent's concise decision explanation and structured action; it also contains the provider response ID, response model and usage. `message_sent` and `message_received` record both sides of communication. `tool_call` records the action; `tool_observation` records the returned result. `state_delta` shows changes. `final_state`, `offline_audit` and `result` show the ending snapshot and audit findings.

Thoughts are represented by concise observable decision summaries, not hidden chain of thought. A model's natural-language explanation is not proof of application state: the tool result and state transition are the evidence. The short episode accounts note two model wording inaccuracies without editing their original output.

`completed: true` means the scenario and trace collection finished. `compliant: false` means a policy was violated. `matches_expected_audit: true` means the reported policies match the scenario's expected findings. It does not turn an unsafe run into a compliant one.

T2 and T4 mark scripted errors with `origin: fault_fixture` and `not_an_autonomous_model_choice: true`. They are controlled faults, not prompt attacks or spontaneous model failures. The passive audit reports after the unsafe effect and does not intercept it. Master receives the injected T2 message in its mailbox, but no further Master model call occurs.

All private content is synthetic. The complete evaluator trace can contain both students' private resources; the actual student contexts are projected separately. Runner, ScenarioHarness, FaultInjector and OfflineAuditor are non-agent log identities.

The submitted trace records are unchanged. Provider response IDs, model names and usage totals remain in the JSON files. Offline fixtures and recorded replay are separate modes and were not used to create these four live records.
