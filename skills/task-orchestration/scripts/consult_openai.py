"""One-shot OpenAI Decisions adapter; authentication never enters retained evidence."""

import json
import math
import signal
import socket
import threading
import time
from urllib import error, request

import consult_jev as jev
from validate_policy import PolicyError, require, unique_mapping


ENDPOINT = "https://api.openai.com/v1/decisions"
MODEL = "gpt-6-luna"
MAX_QUESTIONS = 200
MAX_TEXT = 1048576
MAX_INPUT = 10485760


def prepare_request(shared, model=MODEL):
    require(model == MODEL, "invalid OpenAI Decisions model")
    return jev.prepare_request(shared, model)


def request_supported(prepared):
    """Provider limits must never invalidate other advisers' supported evidence."""
    if not 1 <= len(prepared["questions"]) <= MAX_QUESTIONS:
        return False
    if len(json.dumps(prepared["state"], sort_keys=True, allow_nan=False,
                      separators=(",", ":"))) > MAX_INPUT:
        return False
    for question in prepared["questions"].values():
        if not isinstance(question["instructions"], str) or len(question["instructions"]) > MAX_TEXT:
            return False
        if not all(isinstance(value, str) and len(value) <= MAX_TEXT
                   for value in question["criteria"].values()):
            return False
    return True


def request_body(prepared):
    require(prepared["model"] == MODEL, "invalid OpenAI Decisions model")
    require(request_supported(prepared), "unsupported OpenAI Decisions request")
    return {
        "model": MODEL,
        "input": json.dumps(prepared["state"], sort_keys=True, allow_nan=False,
                            separators=(",", ":")),
        "questions": [
            {"type": "choice", "name": name, "instructions": question["instructions"],
             "choices": [{"value": option, "description": description}
                         for option, description in sorted(question["criteria"].items())]}
            for name, question in sorted(prepared["questions"].items())
        ],
    }


def validate_usage(usage):
    require(isinstance(usage, dict), "invalid response usage")
    result = {}
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        tokens = usage.get(field)
        require(type(tokens) is int and tokens >= 0, "invalid token usage")
        result[field] = tokens
    for field, fields in (("input_tokens_details", ("cached_tokens", "cache_write_tokens")),
                          ("output_tokens_details", ("reasoning_tokens",))):
        detail = usage.get(field)
        require(isinstance(detail, dict), "invalid token usage details")
        result[field] = {}
        for name in fields:
            tokens = detail.get(name)
            require(type(tokens) is int and tokens >= 0, "invalid token usage")
            result[field][name] = tokens
    return result


def validate_response(value, prepared):
    require(isinstance(value, dict), "response must be a mapping")
    model = value.get("model")
    # Only this model is documented for Decisions. A future snapshot ID needs a
    # documented mapping before it can enter an independently recorded judgment.
    require(model == MODEL, "resolved model differs from supported Decisions model")
    answers = value.get("answers")
    require(isinstance(answers, list) and len(answers) == len(prepared["questions"]),
            "invalid answer IDs")
    validated = {}
    for answer in answers:
        require(isinstance(answer, dict), "invalid answer type")
        name = answer.get("name")
        require(isinstance(name, str) and name in prepared["questions"] and name not in validated,
                "invalid answer IDs")
        kind = answer.get("type")
        if kind == "refusal":
            validated[name] = {"type": "refusal"}
            continue
        require(kind == "choice", "invalid answer type")
        options = prepared["questions"][name]["criteria"]
        choice = answer.get("choice")
        require(isinstance(choice, str) and choice in options, "invalid chosen option")
        probabilities = answer.get("probabilities")
        require(isinstance(probabilities, list) and len(probabilities) == len(options),
                "invalid probability option IDs")
        distribution = {}
        for item in probabilities:
            require(isinstance(item, dict), "invalid probability option IDs")
            option = item.get("value")
            require(isinstance(option, str) and option in options and option not in distribution,
                    "invalid probability option IDs")
            probability = item.get("probability")
            jev.probability(probability)
            distribution[option] = probability
        require(math.isclose(math.fsum(distribution.values()), 1.0, rel_tol=0,
                             abs_tol=jev.SUM_TOLERANCE), "invalid probability distribution")
        confidence = answer.get("confidence")
        jev.probability(confidence)
        # Decisions does not document a choice-is-argmax invariant.
        validated[name] = {"type": "choice", "choice": choice,
                           "probabilities": distribution, "confidence": confidence}
    return {"model": model, "answers": validated, "usage": validate_usage(value.get("usage"))}


def validate_result(value, prepared):
    """Revalidate the retained normalized result during offline adjudication."""
    require(isinstance(value, dict), "response must be a mapping")
    answers = value.get("answers")
    require(isinstance(answers, dict) and set(answers) == set(prepared["questions"]),
            "invalid answer IDs")
    wire = []
    for name, answer in answers.items():
        require(isinstance(answer, dict), "invalid answer type")
        item = dict(answer, name=name)
        if item.get("type") == "choice":
            probabilities = item.get("probabilities")
            require(isinstance(probabilities, dict), "invalid probability option IDs")
            item["probabilities"] = [{"value": option, "probability": probability}
                                     for option, probability in probabilities.items()]
        wire.append(item)
    return validate_response(dict(value, answers=wire), prepared)


def response_status(result):
    choices = sum(answer["type"] == "choice" for answer in result["answers"].values())
    return "success" if choices == len(result["answers"]) else "partial" if choices else "refusal"


def consult(prepared, deadline_seconds, credential):
    """Use only the explicitly supplied OpenAI credential and the fixed endpoint."""
    started = time.monotonic()
    record = {"request": prepared, "requested_model": prepared["model"]}
    if not credential:
        record.update(status="unavailable", error={"category": "missing_credential"}, duration_seconds=0.0)
        return record, 2
    if not request_supported(prepared):
        record.update(status="unavailable", error={"category": "unsupported_request"}, duration_seconds=0.0)
        return record, 2
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        record.update(status="unavailable", error={"category": "deadline_unavailable"}, duration_seconds=0.0)
        return record, 2
    try:
        with jev.total_deadline(deadline_seconds):
            payload = json.dumps(request_body(prepared), allow_nan=False,
                                 separators=(",", ":")).encode("utf-8")
            outgoing = request.Request(
                ENDPOINT, data=payload, method="POST",
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + credential},
            )
            with jev.open_once(outgoing, timeout=deadline_seconds) as response:
                body = response.read(jev.MAX_RESPONSE_BYTES + 1)
            require(len(body) <= jev.MAX_RESPONSE_BYTES, "response too large")
            raw = json.loads(
                body, object_pairs_hook=unique_mapping,
                parse_constant=lambda _value: (_ for _ in ()).throw(PolicyError("nonfinite JSON number")),
            )
            result = validate_response(raw, prepared)
        status = response_status(result)
        record.update(status=status, resolved_model=result["model"], result=result, usage=result["usage"])
        exit_code = 0 if status == "success" else 2
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
