#!/usr/bin/env python3
"""Send one sanitized Choice consultation; record input but exclude authentication headers."""

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import signal
import socket
import sys
import time
import threading
from urllib import error, request

from validate_policy import DEFAULT_POLICY, PolicyError, json_value, load_policy, read_json, require, unique_mapping, validate_choice


ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MAX_RESPONSE_BYTES = 1024 * 1024
SUM_TOLERANCE = 1e-6


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, _request, _response, _code, _message, _headers, _url):
        # A redirect is unavailable advice; never send credentials to a new URL.
        return None


def open_once(outgoing, timeout):
    return request.build_opener(NoRedirect()).open(outgoing, timeout=timeout)


def prepare_request(value, model):
    require(isinstance(value, dict) and set(value) in (
        {"state", "questions"}, {"state", "questions", "model"},
    ), "invalid request fields")
    require("model" not in value or value["model"] == model, "request conflicts with pinned model")
    # Validate all state, including nested values, before serializing or sending it.
    json_value(value["state"])
    questions = value["questions"]
    require(isinstance(questions, dict) and bool(questions), "questions must be a nonempty mapping")
    require(all(isinstance(key, str) and key.strip() for key in questions), "invalid question ID")
    for question in questions.values():
        validate_choice(question)
    return {"model": model, "state": value["state"], "questions": questions}


def probability(value):
    require(type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value),
            "invalid probability or confidence")


@contextmanager
def total_deadline(seconds):
    """Bound connection and complete response reading, including slow streams."""
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def expired(_signum, _frame):
        raise TimeoutError()

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            remaining = max(0.000001, previous_timer[0] - (time.monotonic() - started))
            signal.setitimer(signal.ITIMER_REAL, remaining, previous_timer[1])


def validate_response(value, prepared):
    require(isinstance(value, dict), "response must be a mapping")
    require(value.get("model") == prepared["model"], "resolved model differs from pinned model")
    answers = value.get("answers")
    require(isinstance(answers, dict) and set(answers) == set(prepared["questions"]), "invalid answer IDs")
    validated = {}
    for question_id, question in prepared["questions"].items():
        answer = answers[question_id]
        require(isinstance(answer, dict) and answer.get("type") == "choice", "invalid answer type")
        options = question["criteria"]
        choice = answer.get("choice")
        require(isinstance(choice, str) and choice in options, "invalid chosen option")
        probabilities = answer.get("probabilities")
        require(isinstance(probabilities, dict) and set(probabilities) == set(options), "invalid probability option IDs")
        for option_probability in probabilities.values():
            probability(option_probability)
        require(math.isclose(math.fsum(probabilities.values()), 1.0, rel_tol=0, abs_tol=SUM_TOLERANCE),
                "invalid probability distribution")
        require(probabilities[choice] == max(probabilities.values()), "chosen option is not a maximum")
        confidence = answer.get("confidence")
        probability(confidence)
        validated[question_id] = {
            "type": "choice", "choice": choice, "probabilities": probabilities, "confidence": confidence,
        }
    usage = value.get("usage")
    require(isinstance(usage, dict), "invalid response usage")
    safe_usage = {}
    for field in ("input_tokens", "output_tokens"):
        tokens = usage.get(field)
        require(type(tokens) is int and tokens >= 0, "invalid token usage")
        safe_usage[field] = tokens
    # Unknown response fields have no role in a consultation and are never retained.
    return {"model": value["model"], "answers": validated, "usage": safe_usage}


def consult(prepared, deadline_seconds, credential):
    started = time.monotonic()
    record = {"request": prepared, "requested_model": prepared["model"]}
    if not credential:
        record.update(status="unavailable", error={"category": "missing_credential"}, duration_seconds=0.0)
        return record, 2
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        record.update(status="unavailable", error={"category": "deadline_unavailable"}, duration_seconds=0.0)
        return record, 2
    try:
        payload = json.dumps(prepared, allow_nan=False, separators=(",", ":")).encode("utf-8")
        outgoing = request.Request(
            ENDPOINT, data=payload, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + credential},
        )
        with total_deadline(deadline_seconds):
            with open_once(outgoing, timeout=deadline_seconds) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        require(len(body) <= MAX_RESPONSE_BYTES, "response too large")
        raw = json.loads(
            body, object_pairs_hook=unique_mapping,
            parse_constant=lambda _value: (_ for _ in ()).throw(PolicyError("nonfinite JSON number")),
        )
        result = validate_response(raw, prepared)
        record.update(status="success", resolved_model=result["model"], result=result, usage=result["usage"])
        exit_code = 0
    except error.HTTPError as failure:
        detail = {"category": "http_error"}
        if type(failure.code) is int and 100 <= failure.code <= 599:
            detail["http_status"] = failure.code
        record.update(status="unavailable", error=detail)
        exit_code = 2
    except (TimeoutError, socket.timeout):
        record.update(status="unavailable", error={"category": "timeout"})
        exit_code = 2
    except error.URLError as failure:
        category = "timeout" if isinstance(failure.reason, (TimeoutError, socket.timeout)) else "network_error"
        record.update(status="unavailable", error={"category": category})
        exit_code = 2
    except (OSError, ValueError, RecursionError) as failure:
        category = "network_error" if isinstance(failure, OSError) else "invalid_response"
        record.update(status="unavailable", error={"category": category})
        exit_code = 2
    record["duration_seconds"] = round(time.monotonic() - started, 6)
    return record, exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.policy)
        prepared = prepare_request(read_json(args.request), policy["consultation"]["model"])
        # Reserve the output before network access; never replace a previous record.
        descriptor = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except (PolicyError, OSError) as failure:
        message = str(failure) if isinstance(failure, PolicyError) else "cannot create a new output file"
        print("Consultation validation failed: " + message, file=sys.stderr)
        return 1
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        if args.dry_run:
            record = {"status": "dry_run", "request": prepared, "requested_model": prepared["model"], "duration_seconds": 0.0}
            exit_code = 0
        else:
            record, exit_code = consult(prepared, policy["consultation"]["deadline_seconds"], os.environ.get("TYPESAFE_API_KEY"))
        json.dump(record, output, indent=2, allow_nan=False)
        output.write("\n")
    print("Consultation " + record["status"])
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
