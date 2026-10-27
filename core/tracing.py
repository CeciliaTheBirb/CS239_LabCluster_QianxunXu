"""Persistent causal trace; private synthetic contexts are evaluator-only."""
from copy import deepcopy
from datetime import datetime, timezone
import json


class Trace:
    def __init__(self, store):
        self.store, self.events = store, []
        self.completed_tools = {}

    def add(self, actor, kind, inputs=None, outputs=None, parents=(), source_refs=(), visibility="PUBLIC", origin="application"):
        # A consumer depends on the returned observation, not only an earlier request.
        parents = list(dict.fromkeys([*parents, *[self.completed_tools[p] for p in parents if p in self.completed_tools]]))
        event = {"seq": len(self.events)+1, "event_id": f"E{len(self.events)+1:04d}",
            "actor": actor, "kind": kind, "inputs": deepcopy(inputs or {}), "outputs": deepcopy(outputs or {}),
            "parent_event_ids": list(parents), "source_refs": list(source_refs), "visibility": visibility,
            "origin": origin, "timestamp": datetime.now(timezone.utc).isoformat()}
        self.events.append(event)
        with self.store.db:
            self.store.db.execute("INSERT INTO events VALUES (?,?)", (event["seq"], json.dumps(event)))
        return event["event_id"]

    def tool(self, actor, name, args, fn, parents=(), sources=(), visibility="PUBLIC", origin="application"):
        action = self.add(actor, "tool_call", {"tool": name, "arguments": args}, parents=parents,
                          source_refs=sources, visibility=visibility, origin=origin)
        before = self.store.snapshot()
        try:
            result = fn(action)
        except Exception as exc:
            self.add(actor, "tool_observation", {"tool": name}, {"error_type": type(exc).__name__},
                     parents=[action], source_refs=sources, visibility=visibility, origin=origin)
            raise
        after = self.store.snapshot()
        observation = self.add(actor, "tool_observation", {"tool": name}, {"result": result}, parents=[action],
                               source_refs=sources, visibility=visibility, origin=origin)
        self.completed_tools[action] = observation
        if before != after:
            changes = {key: {"before": before[key], "after": after[key]} for key in before if before[key] != after[key]}
            self.add(actor, "state_delta", {"tool": name}, changes, parents=[action],
                     visibility="EVALUATOR_PRIVATE", origin=origin)
        return result, action
