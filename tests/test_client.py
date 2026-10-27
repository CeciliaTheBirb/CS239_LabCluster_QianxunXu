"""HTTP mocks only. Results here are never exported as live traces."""
import io
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from agents.client import BackendError, DeepSeekBackend, Settings, create_tls_context, load_env
from agents.deterministic import DeterministicBackend
from agents.runtime import ROLE_CLASSES
from core.schemas import fixture
from phase1.run import main, run_scenario


def envelope(decision=None):
    return {"id":"mock-response", "model":"deepseek-flash", "usage":{"total_tokens":100},
        "choices":[{"finish_reason":"stop", "message":{"content":json.dumps(decision or {"accepted":True,"message":"I accept.","summary":"Accept exact terms."}),
        "reasoning_content":"HIDDEN_REASONING_MUST_NOT_BE_RECORDED"}}]}


class Response:
    def __init__(self, payload):
        self.payload = payload if isinstance(payload,bytes) else json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,n): return self.payload[:n]


class Opener:
    def __init__(self,payload=None,exception=None,dynamic=False):
        self.payload=envelope() if payload is None else payload
        self.exception,self.dynamic,self.calls=exception,dynamic,[]
    def open(self,request,timeout):
        self.calls.append((request,timeout))
        if self.exception: raise self.exception
        if self.dynamic:
            body=json.loads(request.data)
            prompt=json.loads(body["messages"][1]["content"])
            role=next(r for r in ROLE_CLASSES if body["messages"][0]["content"].startswith("You are "+r))
            d=DeterministicBackend().choose(role,prompt["task"],prompt["context"])
            return Response(envelope(d))
        return Response(self.payload)


class ClientTests(unittest.TestCase):
    def backend(self,payload=None,exception=None,dynamic=False,**kwargs):
        b=DeepSeekBackend(Settings(api_key="test-key-never-real",**kwargs))
        b.opener=Opener(payload,exception,dynamic)
        return b

    def test_env_is_literal_and_process_variables_take_precedence(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{},clear=True):
            path=Path(d)/".env"
            path.write_text('DEEPSEEK_API_KEY="literal-$(never-executed)"\nDEEPSEEK_MODEL=deepseek-flash\n')
            self.assertEqual(load_env(path)["DEEPSEEK_API_KEY"],"literal-$(never-executed)")
            os.environ["DEEPSEEK_MODEL"]="override-model"
            settings=Settings.from_env(path)
            self.assertEqual(settings.model,"override-model")
            self.assertNotIn(settings.api_key,repr(settings))

    def test_missing_credentials_no_fallback(self):
        with patch.dict(os.environ,{},clear=True), tempfile.TemporaryDirectory() as d, patch("sys.stderr",new_callable=io.StringIO) as output:
            self.assertEqual(main(["--env-file",str(Path(d)/"missing")]),2)
            self.assertIn("DEEPSEEK_API_KEY",output.getvalue())

    def test_configuration_rejects_bad_limits_and_insecure_url(self):
        for kwargs in ({"timeout":float("nan")},{"timeout":0},{"max_tokens":1},{"max_calls":0},{"base_url":"http://api.deepseek.com"}):
            with self.subTest(config=kwargs),self.assertRaises(BackendError):
                Settings(api_key="test",**kwargs).validate()

    def test_request_is_bounded_json_and_hidden_reasoning_ignored(self):
        b=self.backend()
        d=b.choose("Master","accept",{},"You are Master.")
        request,timeout=b.opener.calls[0]
        body=json.loads(request.data)
        self.assertEqual(body["response_format"],{"type":"json_object"})
        self.assertEqual(body["thinking"],{"type":"disabled"})
        self.assertEqual(body["max_tokens"],1800)
        self.assertEqual(timeout,30)
        self.assertTrue(d["accepted"])
        self.assertNotIn("test-key-never-real",json.dumps(body))
        self.assertNotIn("HIDDEN_REASONING",json.dumps(b.last_metadata))

    def test_http_failures_no_retry_or_raw_body_leak(self):
        for code in (400,401,402,403,404,422,500,503):
            error=HTTPError("https://api.deepseek.com",code,"private-error-body",{},io.BytesIO(b"test-key-never-real"))
            b=self.backend(exception=error)
            with self.subTest(code=code),self.assertRaises(BackendError) as caught:
                b.choose("Master","accept",{},"You are Master.")
            self.assertIn(str(code),str(caught.exception))
            self.assertNotIn("private-error-body",str(caught.exception))
            self.assertEqual(len(b.opener.calls),1)

    def test_rate_limit_retry_is_once_and_budgeted(self):
        error = lambda: HTTPError("https://api.deepseek.com",429,"limited",{},io.BytesIO(b"private body"))
        b=self.backend()
        b.opener.open=Mock(side_effect=[error(),Response(envelope())])
        with patch("agents.client.time.sleep"):
            self.assertTrue(b.choose("Master","accept",{},"You are Master.")["accepted"])
        self.assertEqual(b.calls,2)
        self.assertEqual(b.last_metadata["http_retries"],[{"status":429,"request_index":2}])
        b=self.backend()
        b.opener.open=Mock(side_effect=[error(),error()])
        with patch("agents.client.time.sleep"),self.assertRaisesRegex(BackendError,"429"):
            b.choose("Master","accept",{},"You are Master.")
        self.assertEqual(b.opener.open.call_count,2)
        b=self.backend(max_calls=1)
        b.opener.open=Mock(side_effect=error())
        with self.assertRaisesRegex(BackendError,"429"):
            b.choose("Master","accept",{},"You are Master.")
        self.assertEqual(b.opener.open.call_count,1)

    def test_transport_errors_distinguish_certificates_dns_and_timeout(self):
        for cause,hint in ((socket.gaierror(8,"sensitive"),"DNS"),(ssl.SSLCertVerificationError(1,"sensitive"),"certificate"),
                           (TimeoutError("sensitive"),"timed out"),(OSError("sensitive"),"connection failed")):
            b=self.backend(exception=URLError(cause))
            with self.assertRaisesRegex(BackendError,hint) as caught:
                b.choose("Master","accept",{},"You are Master.")
            self.assertNotIn("sensitive",str(caught.exception))

    def test_malformed_responses_and_strict_boolean(self):
        for payload in (b"not json",[],{"choices":[None]},envelope({"accepted":"false","message":"x","summary":"y"})):
            b=self.backend(payload)
            with self.subTest(kind=type(payload)),self.assertRaises(BackendError):
                b.choose("Master","accept",{},"You are Master.")

    def test_failed_decision_usage_is_still_accounted(self):
        payload=envelope()
        payload["choices"][0]["finish_reason"]="length"
        b=self.backend(payload)
        with self.assertRaisesRegex(BackendError,"truncated"):
            b.choose("Master","accept",{},"You are Master.")
        self.assertEqual(b.statistics()["provider_reported_tokens"],100)
        self.assertEqual(b.statistics()["successful_decisions"],0)
        self.assertEqual(b.last_metadata["finish_reason"],"length")

    def test_schema_diagnostic_redacts_key(self):
        b=self.backend(envelope({"accepted":"test-key-never-real","message":"x","summary":"y"}))
        with self.assertRaises(BackendError):
            b.choose("Master","accept",{},"You are Master.")
        self.assertNotIn("test-key-never-real",json.dumps(b.last_metadata))
        self.assertIn("REDACTED_API_KEY",json.dumps(b.last_metadata))

    def test_missing_summary_has_one_recorded_schema_repair(self):
        invalid={"accepted":True,"message":"I accept."}
        b=self.backend()
        b.opener.open=Mock(side_effect=[Response(envelope(invalid)),Response(envelope())])
        self.assertTrue(b.choose("Master","accept",{},"You are Master.")["accepted"])
        repair=b.last_metadata["schema_repair"]
        self.assertEqual(json.loads(repair["repair_input"]["previous_invalid_final_output"]),invalid)
        self.assertIn('summary',repair['repair_input']['instruction'])
        self.assertEqual(b.calls,2)
        self.assertEqual(b.successful_calls,1)
        self.assertEqual(b.reported_tokens,200)

    def test_schema_repair_never_repeats_or_exceeds_budget(self):
        invalid={"accepted":True,"message":"I accept."}
        b=self.backend(envelope(invalid))
        with self.assertRaises(BackendError):
            b.choose("Master","accept",{},"You are Master.")
        self.assertEqual(len(b.opener.calls),2)
        self.assertIn('schema_repair',b.last_metadata)
        b=self.backend(envelope(invalid),max_calls=1)
        with self.assertRaisesRegex(BackendError,"budget"):
            b.choose("Master","accept",{},"You are Master.")
        self.assertEqual(len(b.opener.calls),1)

    def test_local_budget_stops_before_request(self):
        b=self.backend(max_calls=1)
        b.choose("Master","accept",{},"You are Master.")
        with self.assertRaisesRegex(BackendError,"budget"):
            b.choose("Master","accept",{},"You are Master.")
        self.assertEqual(len(b.opener.calls),1)
        b=self.backend(total_token_budget=1000)
        with self.assertRaisesRegex(BackendError,"budget"):
            b.choose("Master","accept",{"big":"x"*4000},"You are Master.")
        self.assertEqual(len(b.opener.calls),0)

    def test_model_discovery(self):
        b=self.backend({"data":[{"id":"deepseek-flash"}]})
        self.assertTrue(b.check_models()["configured_model_available"])
        b=self.backend({"data":[{"id":"other"}]})
        with self.assertRaises(BackendError): b.check_models()

    def test_default_ca_fallback_remains_secure(self):
        ctx=create_tls_context()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)
        empty,system=Mock(),Mock()
        empty.get_ca_certs.return_value=[]
        with patch.dict(os.environ,{},clear=True),patch("agents.client.sys.platform","darwin"), \
                patch("agents.client.Path.is_file",return_value=True),patch("agents.client.ssl.create_default_context",side_effect=[empty,system]) as fn:
            self.assertIs(create_tls_context(),system)
            self.assertEqual(fn.call_args.kwargs,{"cafile":"/etc/ssl/cert.pem"})

    def test_explicit_ca_path_is_respected(self):
        empty=Mock();empty.get_ca_certs.return_value=[]
        with patch.dict(os.environ,{"SSL_CERT_FILE":"/custom/cert.pem"},clear=True), \
                patch("agents.client.ssl.create_default_context",return_value=empty) as fn:
            self.assertIs(create_tls_context(),empty)
            self.assertEqual(fn.call_count,1)

    def test_whole_workflow_through_mocked_http(self):
        backend=self.backend(dynamic=True)
        t=run_scenario("T1_priority_queue",backend)
        self.assertTrue(t["result"]["compliant"])
        self.assertEqual(len(backend.opener.calls),backend.successful_calls)
        self.assertNotIn("HIDDEN_REASONING",json.dumps(t))
        self.assertNotIn("test-key-never-real",json.dumps(t))
        # Never exported: mocked transport is not genuine API evidence.

    def test_duplicate_decision_keys_never_become_an_application_decision(self):
        payload = envelope()
        payload['choices'][0]['message']['content'] = '{"accepted":false,"accepted":true,"message":"x","summary":"y"}'
        backend = self.backend(payload)
        with self.assertRaises(BackendError):
            backend.choose('Master', 'accept', {}, 'You are Master.')
        self.assertEqual(backend.successful_calls, 0)
        self.assertEqual(len(backend.opener.calls), 2)  # One bounded repair, then stop.

    def test_over_budget_response_is_not_counted_as_success(self):
        payload = envelope()
        payload['usage']['total_tokens'] = 20000
        backend = self.backend(payload, total_token_budget=10000)
        with self.assertRaisesRegex(BackendError, 'Provider-reported token budget'):
            backend.choose('Master', 'accept', {}, 'You are Master.')
        self.assertEqual(backend.successful_calls, 0)
        self.assertEqual(backend.reported_tokens, 20000)

    def test_required_summary_is_first_in_output_protocol(self):
        backend = self.backend()
        backend.choose('Master', 'accept', {}, 'You are Master.')
        body = json.loads(backend.opener.calls[0][0].data)
        prompt = json.loads(body['messages'][1]['content'])
        self.assertEqual(next(iter(prompt['output_schema'])), 'summary')
        self.assertIn('including control', body['messages'][0]['content'])
