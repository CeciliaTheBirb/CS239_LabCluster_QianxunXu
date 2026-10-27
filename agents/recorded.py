"""Offline replay of recorded decisions, with exact prompt-context matching.

This backend makes NO API calls and must never be presented as a fresh live run.
"""
from copy import deepcopy
import hashlib
import json

from core.schemas import ApplicationError, validate_decision


class RecordedBackend:
    name = "recorded_replay"

    def __init__(self, path):
        raw = path.read_bytes()
        trace = json.loads(raw)
        if trace["backend"] != "deepseek" or not trace["result"]["completed"]:
            raise ApplicationError("Replay requires a completed original DeepSeek trace.")
        self.model = trace["model"]
        self.source_trace_sha256 = hashlib.sha256(raw).hexdigest()
        self.source_run_id = trace["run_id"]
        self.scenario = trace["scenario_id"]
        self.requests = [e for e in trace["events"] if e["kind"] == "decision_request"]
        self.decisions = [e for e in trace["events"] if e["kind"] == "decision_summary"]
        if len(self.requests) != len(self.decisions):
            raise ApplicationError("Incomplete recorded decisions.")
        self.position = 0
        self.last_metadata = {}

    def choose(self, role, stage, context, instructions=""):
        if self.position >= len(self.decisions):
            raise ApplicationError("Recorded decisions exhausted; no fixture/API fallback.")
        request, answer = self.requests[self.position], self.decisions[self.position]
        if (request["actor"] != role or request["inputs"]["stage"] != stage
                or request["inputs"]["context"] != context):
            raise ApplicationError("Recorded role/stage/context differs; replay refused.")
        decision = deepcopy(answer["outputs"]["decision"])
        validate_decision(stage, decision, context)
        self.position += 1
        self.last_metadata = {"origin": "recorded_live_replay", "new_api_call": False,
                              "source_trace_sha256": self.source_trace_sha256,
                              "source_run_id": self.source_run_id,
                              "original_response": deepcopy(answer["outputs"]["backend_metadata"])}
        return decision

    def statistics(self):
        return {"requests_attempted": 0, "successful_decisions": 0, "provider_reported_tokens": 0,
                "replayed_decisions": self.position, "recorded_decisions": len(self.decisions)}
