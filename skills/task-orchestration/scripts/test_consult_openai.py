"""Offline Decisions wire, validation, and transport checks; no external requests."""

import copy
import io
import json
import os
import socket
import threading
import time
import unittest
from unittest import mock
from urllib import error

import consult_jev as jev
import consult_openai as openai
from test_consult_decisions import Response, sample_request
from validate_policy import PolicyError


def wire_result(prepared, refusals=()):
    return {
        "model": openai.MODEL,
        "answers": [
            {"name": name, "type": "refusal"} if name in refusals else
            {"name": name, "type": "choice", "choice": "supported", "confidence": 0.7,
             "probabilities": [{"value": option, "probability": float(option == "supported")}
                               for option in question["criteria"]]}
            for name, question in prepared["questions"].items()
        ],
        "usage": {"input_tokens": 23, "output_tokens": 0, "total_tokens": 23,
                  "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
    }


class OpenAIDecisionsTests(unittest.TestCase):
    def setUp(self):
        self.shared = sample_request()
        self.shared["questions"]["other"] = copy.deepcopy(self.shared["questions"]["claim"])
        self.prepared = openai.prepare_request(self.shared)

    def test_mapping_preserves_evidence_and_verbatim_questions(self):
        self.shared["state"] = {"z": [True, None, 1], "a": "quoted \"text\""}
        self.shared["questions"]["claim"]["instructions"] = "  Inspect the source.\nUse the actual evidence.  "
        prepared = openai.prepare_request(self.shared)
        body = openai.request_body(prepared)
        self.assertEqual(set(body), {"model", "input", "questions"})
        self.assertEqual(body["model"], "gpt-6-luna")
        self.assertEqual(body["input"], '{"a":"quoted \\"text\\"","z":[true,null,1]}')
        self.assertEqual(body["questions"][0]["name"], "claim")
        self.assertEqual(body["questions"][0]["instructions"], self.shared["questions"]["claim"]["instructions"])
        self.assertEqual(body["questions"][0]["choices"], [
            {"value": key, "description": value}
            for key, value in sorted(self.shared["questions"]["claim"]["criteria"].items())])
        reversed_state = dict(reversed(list(self.shared["state"].items())))
        self.assertEqual(body, openai.request_body(openai.prepare_request(dict(self.shared, state=reversed_state))))
        self.assertEqual(openai.request_body(openai.prepare_request(dict(self.shared, state="text")))["input"],
                         '"text"')

    def test_fixed_requested_and_documented_returned_model(self):
        for model in ("gpt-6-astra", "gpt-6-luna-unknown-snapshot", "", None):
            with self.subTest(model=model), self.assertRaises(PolicyError):
                openai.prepare_request(self.shared, model)
            result = wire_result(self.prepared)
            result["model"] = model
            with self.subTest(returned=model), self.assertRaises(PolicyError):
                openai.validate_response(result, self.prepared)
        result = openai.validate_response(wire_result(self.prepared), self.prepared)
        self.assertEqual(result["model"], openai.MODEL)
        self.assertEqual(result["usage"]["input_tokens"], 23)

    def test_partial_refusals_preserve_other_answers_and_all_refused(self):
        for refusals, expected in (((), "success"), (("claim",), "partial"), (("claim", "other"), "refusal")):
            result = openai.validate_response(wire_result(self.prepared, refusals), self.prepared)
            self.assertEqual(openai.response_status(result), expected)
            for name in refusals:
                self.assertEqual(result["answers"][name], {"type": "refusal"})
            if expected == "partial":
                self.assertEqual(result["answers"]["other"]["choice"], "supported")
            self.assertEqual(openai.validate_result(result, self.prepared), result)

    def test_choice_does_not_require_an_undocumented_argmax(self):
        result = wire_result(self.prepared)
        answer = result["answers"][0]
        answer["probabilities"] = [{"value": "supported", "probability": 0.3},
                                   {"value": "contradicted", "probability": 0.7},
                                   {"value": "insufficient_evidence", "probability": 0}]
        self.assertEqual(openai.validate_response(result, self.prepared)["answers"]["claim"]["choice"], "supported")

    def test_rejects_missing_duplicate_extra_and_mistyped_names(self):
        for mutate in (
            lambda value: value["answers"].pop(),
            lambda value: value["answers"].append(copy.deepcopy(value["answers"][0])),
            lambda value: value["answers"][0].update(name="other"),
            lambda value: value["answers"][0].update(name="unexpected"),
            lambda value: value["answers"][0].update(name=None),
            lambda value: value["answers"][0].update(name=[]),
            lambda value: value.update(answers={}),
            lambda value: value["answers"][0].update(type="predicate"),
            lambda value: value["answers"][0].update(choice=True),
        ):
            result = wire_result(self.prepared)
            mutate(result)
            with self.subTest(mutate=mutate), self.assertRaises(PolicyError):
                openai.validate_response(result, self.prepared)
        # Names identify questions independently of response order.
        result = wire_result(self.prepared)
        result["answers"].reverse()
        self.assertEqual(set(openai.validate_response(result, self.prepared)["answers"]), {"claim", "other"})

    def test_rejects_invalid_distributions_and_confidence(self):
        for mutate in (
            lambda answer: answer.update(probabilities={"supported": 1}),
            lambda answer: answer["probabilities"].pop(),
            lambda answer: answer["probabilities"][0].update(value=True),
            lambda answer: answer["probabilities"][0].update(value="unexpected"),
            lambda answer: answer["probabilities"][0].update(value=answer["probabilities"][1]["value"]),
            lambda answer: answer["probabilities"][0].update(probability=0.5),
            lambda answer: answer["probabilities"][0].update(probability=True),
            lambda answer: answer["probabilities"][0].update(probability=-0.1),
            lambda answer: answer["probabilities"][0].update(probability=1.1),
            lambda answer: answer["probabilities"][0].update(probability=float("nan")),
            lambda answer: answer["probabilities"][0].update(probability=float("inf")),
            lambda answer: answer.update(confidence=float("nan")),
            lambda answer: answer.update(confidence=10 ** 1000),
            lambda answer: answer.update(confidence=False),
        ):
            result = wire_result(self.prepared)
            mutate(result["answers"][0])
            with self.subTest(mutate=mutate), self.assertRaises(PolicyError):
                openai.validate_response(result, self.prepared)

    def test_rejects_malformed_usage_even_for_all_refused(self):
        for mutate in (
            lambda usage: usage.pop("input_tokens"),
            lambda usage: usage.update(input_tokens=True),
            lambda usage: usage.update(output_tokens=-1),
            lambda usage: usage.update(total_tokens=0.5),
            lambda usage: usage.update(input_tokens_details=None),
            lambda usage: usage["input_tokens_details"].update(cached_tokens=float("nan")),
            lambda usage: usage["output_tokens_details"].update(reasoning_tokens="0"),
        ):
            result = wire_result(self.prepared, ("claim", "other"))
            mutate(result["usage"])
            with self.subTest(mutate=mutate), self.assertRaises(PolicyError):
                openai.validate_response(result, self.prepared)

    def test_provider_limits_do_not_rewrite_nontext_instructions(self):
        for kind in ("count", "instructions", "description", "length"):
            shared = sample_request()
            if kind == "count":
                shared["questions"] = {str(index): shared["questions"]["claim"] for index in range(201)}
            elif kind == "instructions":
                shared["questions"]["claim"]["instructions"] = {"policy": "keep intact"}
            elif kind == "description":
                shared["questions"]["claim"]["criteria"]["supported"] = ["keep intact"]
            else:
                shared["questions"]["claim"]["instructions"] = "x" * (openai.MAX_TEXT + 1)
            prepared = openai.prepare_request(shared)
            self.assertFalse(openai.request_supported(prepared))
            with mock.patch.object(jev, "open_once", side_effect=AssertionError("must not call")):
                record, code = openai.consult(prepared, 30, "fake-openai")
            self.assertEqual(code, 2)
            self.assertEqual(record["error"], {"category": "unsupported_request"})
        shared["questions"] = {str(index): sample_request()["questions"]["claim"] for index in range(200)}
        self.assertTrue(openai.request_supported(openai.prepare_request(shared)))

    def test_transport_uses_fixed_endpoint_and_only_explicit_credential(self):
        seen = []

        def open_fixture(outgoing, timeout):
            seen.append(outgoing)
            self.assertEqual(outgoing.full_url, "https://api.openai.com/v1/decisions")
            self.assertEqual(outgoing.get_method(), "POST")
            self.assertEqual(outgoing.get_header("Authorization"), "Bearer fake-openai")
            self.assertEqual(json.loads(outgoing.data), openai.request_body(self.prepared))
            self.assertEqual(timeout, 3)
            return Response(json.dumps(wire_result(self.prepared, ("claim",))).encode())

        environment = {"TYPESAFE_API_KEY": "fake-jev", "SUBQ_API_KEY": "fake-snap", "OPENAI_API_KEY": "not-used"}
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(jev, "open_once", side_effect=open_fixture):
            before = dict(os.environ)
            record, code = openai.consult(self.prepared, 3, "fake-openai")
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(len(seen), 1)
        self.assertEqual(record["status"], "partial")
        self.assertEqual(code, 2)
        for secret in (*environment.values(), "fake-openai"):
            self.assertNotIn(secret, json.dumps(record))

    def test_errors_are_single_attempt_sanitized_and_responses_bounded(self):
        cases = (
            (error.HTTPError(openai.ENDPOINT, 429, "fake-secret", {}, None), "http_error"),
            (error.URLError("fake-secret"), "network_error"),
            (socket.timeout("fake-secret"), "timeout"),
            (Response(b"x" * (jev.MAX_RESPONSE_BYTES + 1)), "invalid_response"),
            (Response(b'{"model":"x","model":"y"}'), "invalid_response"),
        )
        for response, category in cases:
            options = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
            with self.subTest(category=category), mock.patch.object(jev, "open_once", **options) as transport:
                record, code = openai.consult(self.prepared, 3, "fake-secret")
            self.assertEqual(transport.call_count, 1)
            self.assertEqual(record["error"]["category"], category)
            self.assertEqual(code, 2)
            self.assertNotIn("fake-secret", json.dumps(record))

    def test_missing_credential_and_non_main_thread_never_call(self):
        with mock.patch.object(jev, "open_once", side_effect=AssertionError("must not call")):
            record, _ = openai.consult(self.prepared, 3, None)
            self.assertEqual(record["error"]["category"], "missing_credential")
            result = []
            thread = threading.Thread(target=lambda: result.append(openai.consult(self.prepared, 3, "fake")))
            thread.start()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result[0][0]["error"]["category"], "deadline_unavailable")

    def test_full_response_read_is_bounded_and_redirects_are_rejected(self):
        class SlowResponse(Response):
            def read(self, *_args):
                time.sleep(3)
                return super().read()

        started = time.monotonic()
        with mock.patch.object(jev, "open_once", return_value=SlowResponse(b"{}")):
            record, _ = openai.consult(self.prepared, 0.05, "fake")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(record["error"]["category"], "timeout")
        self.assertIsNone(jev.NoRedirect().redirect_request(None, None, 302, "moved", {}, "https://elsewhere"))


if __name__ == "__main__":
    unittest.main()
