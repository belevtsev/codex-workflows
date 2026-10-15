#!/usr/bin/env python3
"""Collect independent adviser judgments, then record Codex's evidence-based decision."""

import sys

# Installed skills are immutable; importing a helper must not create cache files.
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import math
import multiprocessing
from multiprocessing.connection import wait
import os
from pathlib import Path
import re
import signal
import threading
import time

import consult_jev as jev
import consult_openai as openai
from validate_policy import DEFAULT_POLICY, PolicyError, load_policy, read_json, require


PAIR_PROVIDERS = {
    "jev": ("https://api.typesafe.ai/v1/systemone", "TYPESAFE_API_KEY"),
    "subq_snap": ("https://api.subq.ai/v1/systemone", "SUBQ_API_KEY"),
}
OPTIONAL_PROVIDERS = {
    "openai_decisions": (openai.ENDPOINT, "OPENAI_API_KEY"),
}
PROVIDERS = dict(PAIR_PROVIDERS, **OPTIONAL_PROVIDERS)
ERROR_CATEGORIES = {
    "missing_credential", "deadline_unavailable", "timeout", "http_error",
    "network_error", "invalid_response", "worker_error",
}
DISABLED_REASONS = {"missing_credential", "excluded"}


def shared_request(value):
    require(isinstance(value, dict) and set(value) == {"state", "questions"},
            "shared request requires only state and questions")
    require(isinstance(value["state"], (str, dict, list)), "invalid state type")
    jev.prepare_request(value, "jev-1.14.0")
    require(all(len(key) <= 100 for key in value["questions"]), "question ID exceeds the shared limit")
    require(all(len(question["criteria"]) <= 255 for question in value["questions"].values()),
            "Choice exceeds the shared option limit")
    return value


def fingerprint(value):
    body = json.dumps(value, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def unavailable(prepared, category, duration=0.0):
    return {"request": prepared, "requested_model": prepared["model"],
            "status": "unavailable", "error": {"category": category},
            "duration_seconds": duration}


def disabled(prepared, reason):
    return {"request": prepared, "requested_model": prepared["model"],
            "status": "disabled", "reason": reason, "duration_seconds": 0.0}


def provider_worker(sender, provider, prepared, deadline_at, credential):
    """Each isolated worker owns its signal deadline and one fixed endpoint."""
    try:
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            record = unavailable(prepared, "timeout")
        elif provider == "openai_decisions":
            record, _ = openai.consult(prepared, remaining, credential)
        else:
            jev.ENDPOINT = PROVIDERS[provider][0]
            record, _ = jev.consult(prepared, remaining, credential)
        sender.send(record)
    except Exception:
        # Do not retain exception messages: transports can include credentials.
        try:
            sender.send(unavailable(prepared, "worker_error"))
        except (OSError, EOFError):
            pass
    finally:
        sender.close()


def stop_worker(process):
    if process.pid is None:
        return
    process.join(timeout=0.1)
    if process.is_alive():
        process.terminate()
        process.join(timeout=0.1)
    if process.is_alive():
        process.kill()
        process.join(timeout=0.1)
    if not process.is_alive():
        process.close()


def collect(prepared, credentials, deadline_seconds, context=None, worker=None, disabled_providers=None,
            required_providers=None):
    """Bound startup, response transport (including partial frames), and requests."""
    disabled_providers = disabled_providers or {}
    required_providers = set(prepared) if required_providers is None else set(required_providers)
    require(required_providers <= set(prepared) and
            set(disabled_providers) <= set(prepared) - required_providers,
            "required provider cannot be disabled")
    records = {}
    for name, value in prepared.items():
        if name in disabled_providers:
            records[name] = disabled(value, disabled_providers[name])
        elif not credentials.get(name):
            records[name] = unavailable(value, "missing_credential")
        elif name == "openai_decisions" and not openai.request_supported(value):
            records[name] = unavailable(value, "unsupported_request")
    active = [name for name in prepared if name not in records]
    if not active:
        return records
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        records.update({name: unavailable(prepared[name], "deadline_unavailable") for name in active})
        return records
    context = context or multiprocessing.get_context("spawn")
    started = time.monotonic()
    deadline_at = started + deadline_seconds
    receivers, processes = {}, []
    try:
        with jev.total_deadline(deadline_seconds):
            for name in active:
                receiver, sender = context.Pipe(duplex=False)
                receivers[receiver] = name
                process = context.Process(target=worker or provider_worker,
                                          args=(sender, name, prepared[name], deadline_at, credentials[name]))
                processes.append(process)
                try:
                    process.start()
                except TimeoutError:
                    raise
                except (OSError, RuntimeError, ValueError):
                    records[name] = unavailable(prepared[name], "worker_error")
                    receivers.pop(receiver)
                    receiver.close()
                finally:
                    sender.close()
            while receivers:
                ready = wait(list(receivers), timeout=max(0, deadline_at - time.monotonic()))
                if not ready:
                    break
                for receiver in ready:
                    name = receivers[receiver]
                    try:
                        # Drain the pipe before joining; large records exceed pipe capacity.
                        records[name] = receiver.recv()
                    except TimeoutError:
                        raise
                    except (OSError, EOFError):
                        records[name] = unavailable(prepared[name], "worker_error")
                    receivers.pop(receiver)
                    receiver.close()
    except TimeoutError:
        pass
    except (OSError, RuntimeError, ValueError):
        for name in active:
            if name not in records:
                records[name] = unavailable(prepared[name], "worker_error")
    finally:
        for receiver in receivers:
            receiver.close()
        for process in processes:
            stop_worker(process)
    elapsed = round(time.monotonic() - started, 6)
    for name in active:
        if name not in records:
            records[name] = unavailable(prepared[name], "timeout", elapsed)
    return records


def safe_record(record, prepared, digest, provider=None, allow_disabled=False):
    require(isinstance(record, dict), "invalid provider record")
    require(record.get("requested_model") == prepared["model"], "provider requested model differs")
    require(record.get("request") == prepared, "provider evidence differs from shared request")
    duration = record.get("duration_seconds")
    try:
        finite_duration = type(duration) in (int, float) and math.isfinite(duration)
    except OverflowError:
        finite_duration = False
    require(finite_duration and duration >= 0,
            "invalid provider duration")
    result = {"status": record.get("status"), "requested_model": prepared["model"],
              "request_sha256": digest, "duration_seconds": duration}
    is_openai = provider == "openai_decisions"
    if result["status"] == "disabled":
        require(allow_disabled and is_openai and isinstance(record.get("reason"), str) and
                record["reason"] in DISABLED_REASONS and duration == 0,
                "invalid disabled provider")
        result["reason"] = record["reason"]
    elif result["status"] == "success" or (is_openai and result["status"] in ("partial", "refusal")):
        validated = (openai.validate_result(record.get("result"), prepared) if is_openai else
                     jev.validate_response(record.get("result"), prepared))
        if is_openai:
            require(result["status"] == openai.response_status(validated), "provider status differs from answers")
        require(record.get("resolved_model") == validated["model"], "provider resolved model differs")
        result.update(resolved_model=validated["model"], result=validated, usage=validated["usage"])
    else:
        require(result["status"] == "unavailable", "invalid provider status")
        failure = record.get("error")
        require(isinstance(failure, dict) and isinstance(failure.get("category"), str) and
                failure["category"] in (ERROR_CATEGORIES | ({"unsupported_request"} if is_openai else set())),
                "invalid provider failure")
        detail = {"category": failure["category"]}
        if detail["category"] == "http_error":
            code = failure.get("http_status")
            require(type(code) is int and 100 <= code <= 599, "invalid HTTP status")
            detail["http_status"] = code
        result["error"] = detail
    return result


def comparison(shared, providers):
    compared = {}
    enabled = {name for name, record in providers.items() if record["status"] != "disabled"}
    extended = "openai_decisions" in providers
    for question_id in shared["questions"]:
        choices, missing = {}, {}
        for name, record in providers.items():
            status = record["status"]
            if status in ("success", "partial", "refusal"):
                answer = record["result"]["answers"][question_id]
                if answer["type"] == "choice":
                    choices[name] = answer["choice"]
                else:
                    missing[name] = "refusal"
            else:
                missing[name] = status
        if choices and len(choices) == len(enabled):
            status = "agreement" if len(set(choices.values())) == 1 else "disagreement"
        else:
            status = "partial" if choices else "unavailable"
        compared[question_id] = {"status": status, "choices": choices}
        if extended:
            compared[question_id]["missing"] = missing
    return compared


def availability(providers):
    enabled = [record for record in providers.values() if record["status"] != "disabled"]
    if enabled and all(record["status"] == "success" for record in enabled):
        return "success"
    return "partial" if any(record["status"] in ("success", "partial") for record in enabled) else "unavailable"


def make_record(shared, prepared, raw_records, version=None):
    if version is None:
        version = 3 if "openai_decisions" in prepared else 1
    require(type(version) is int and version in (1, 2, 3), "invalid consultation record version")
    expected = set(PAIR_PROVIDERS) if version == 1 else set(PROVIDERS)
    require(set(prepared) == expected, "invalid prepared providers")
    digest = fingerprint(shared)
    providers = {}
    for name, value in prepared.items():
        try:
            providers[name] = safe_record(raw_records[name], value, digest, name, allow_disabled=version == 2)
        except (PolicyError, KeyError, TypeError):
            providers[name] = safe_record(unavailable(value, "invalid_response"), value, digest, name)
    return {"version": version,
            "status": availability(providers), "request": shared,
            "request_sha256": digest, "providers": providers,
            "comparison": comparison(shared, providers),
            "final_decision": {"status": "pending", "questions": {}}}


def text_value(value):
    return isinstance(value, str) and bool(value.strip())


def text_list(value):
    return isinstance(value, list) and all(text_value(item) for item in value)


def adjudicate(record, decision):
    """Validate Codex's recorded disposition without hosted requests or voting."""
    require(isinstance(record, dict) and set(record) == {
        "version", "status", "request", "request_sha256", "providers", "comparison", "final_decision",
    } and type(record["version"]) is int and record["version"] in (1, 2, 3), "invalid consultation record")
    shared = shared_request(record["request"])
    digest = fingerprint(shared)
    require(record["request_sha256"] == digest, "shared evidence fingerprint differs")
    expected_providers = set(PAIR_PROVIDERS) if record["version"] == 1 else set(PROVIDERS)
    require(isinstance(record["providers"], dict) and set(record["providers"]) == expected_providers,
            "invalid recorded providers")
    providers = {}
    for name, stored in record["providers"].items():
        require(isinstance(stored, dict), "invalid stored provider")
        model = stored.get("requested_model")
        require(isinstance(model, str) and
                (re.fullmatch(r"jev-[0-9]+\.[0-9]+\.[0-9]+", model) if name == "jev"
                 else model == (openai.MODEL if name == "openai_decisions" else "subq-snap-preview")),
                "invalid stored provider model")
        require(stored.get("request_sha256") == digest, "provider evidence fingerprint differs")
        prepared = (openai.prepare_request(shared, model) if name == "openai_decisions" else
                    jev.prepare_request(shared, model))
        providers[name] = safe_record(dict(stored, request=prepared), prepared, digest, name,
                                      allow_disabled=record["version"] == 2)
        require(providers[name] == stored, "stored provider contains inconsistent fields")
    compared = comparison(shared, providers)
    require(record["comparison"] == compared and record["status"] == availability(providers),
            "recorded comparison differs from provider answers")
    require(record["final_decision"] == {"status": "pending", "questions": {}},
            "consultation already has a decision")
    require(isinstance(decision, dict) and set(decision) == {"questions"}, "invalid decision fields")
    questions = decision["questions"]
    require(isinstance(questions, dict) and set(questions) == set(shared["questions"]),
            "decision must cover every question")
    for question_id, item in questions.items():
        require(isinstance(item, dict) and set(item) == {
            "status", "choice", "reason", "evidence", "verification", "rejected_judgments",
        }, "invalid decision item")
        require(item["status"] in ("resolved", "unresolved"), "invalid decision status")
        require(text_value(item["reason"]), "decision needs a reason")
        require(text_list(item["evidence"]) and text_list(item["verification"]),
                "invalid decision references")
        rejected = item["rejected_judgments"]
        require(isinstance(rejected, dict) and all(text_value(reason) for reason in rejected.values()),
                "invalid rejected judgment reasons")
        if item["status"] == "resolved":
            require(isinstance(item["choice"], str) and item["choice"] in shared["questions"][question_id]["criteria"],
                    "decision choice is not an allowed option")
            require(item["choice"] != "insufficient_evidence", "insufficient evidence remains unresolved")
            require(bool(item["evidence"]) and bool(item["verification"]),
                    "resolved decision needs evidence and verification")
            expected = {name for name, choice in compared[question_id]["choices"].items()
                        if choice != item["choice"]}
            require(set(rejected) == expected, "decision must explain each rejected provider judgment")
        else:
            require(item["choice"] is None and not rejected, "unresolved decision must not choose or reject")
    final = dict(record)
    final["final_decision"] = {
        "status": "resolved" if all(item["status"] == "resolved" for item in questions.values()) else "unresolved",
        "questions": questions,
    }
    return final


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--request", type=Path)
    action.add_argument("--adjudicate", type=Path)
    parser.add_argument("--decision", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--dry-run", action="store_true")
    openai_flags = parser.add_mutually_exclusive_group()
    openai_flags.add_argument("--with-openai", dest="use_openai", action="store_const", const=True,
                             help="explicitly include OpenAI; required policies already include it")
    openai_flags.add_argument("--without-openai", dest="use_openai", action="store_const", const=False,
                             help="exclude OpenAI only under historical optional policies")
    args = parser.parse_args(argv)
    if bool(args.adjudicate) != bool(args.decision) or (args.adjudicate and
                                                     (args.dry_run or args.use_openai is not None)):
        parser.error("--decision requires --adjudicate; --dry-run and OpenAI flags are only for --request")
    try:
        if args.adjudicate:
            record = adjudicate(read_json(args.adjudicate), read_json(args.decision))
            prepared = None
        else:
            policy = load_policy(args.policy)["consultation"]
            require("providers" in policy, "policy does not configure adviser consultation")
            required_providers = set(policy["providers"])
            required_openai = "openai_decisions" in required_providers
            require(not (required_openai and args.use_openai is False),
                    "required OpenAI adviser cannot be disabled")
            require(args.use_openai is None or required_openai or "optional_providers" in policy,
                    "policy does not configure the OpenAI adviser")
            version = 3 if required_openai else 2 if "optional_providers" in policy else 1
            shared = shared_request(read_json(args.request))
            prepared = {name: (openai.prepare_request(shared, model) if name == "openai_decisions" else
                               jev.prepare_request(shared, model)) for name, model in policy["providers"].items()}
            prepared.update({name: openai.prepare_request(shared, model)
                             for name, model in policy.get("optional_providers", {}).items()})
            credentials = {name: os.environ.get(PROVIDERS[name][1]) for name in prepared}
            disabled_providers = {}
            if "openai_decisions" in prepared and not required_openai:
                if args.use_openai is False:
                    disabled_providers["openai_decisions"] = "excluded"
                elif args.use_openai is None and not credentials["openai_decisions"]:
                    disabled_providers["openai_decisions"] = "missing_credential"
        # Reserve a private output before network access; never overwrite earlier evidence.
        descriptor = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except (PolicyError, OSError) as failure:
        detail = str(failure) if isinstance(failure, PolicyError) else "cannot create a new output file"
        print("Decision consultation validation failed: " + detail, file=sys.stderr)
        return 1
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        if prepared is not None:
            if args.dry_run:
                previews = {name: {"requested_model": value["model"]} for name, value in prepared.items()}
                if "openai_decisions" in prepared:
                    previews["openai_decisions"]["status"] = "dry_run"
                    if "openai_decisions" in disabled_providers:
                        previews["openai_decisions"].update(
                            status="disabled", reason=disabled_providers["openai_decisions"])
                record = {"version": version,
                          "status": "dry_run", "request": shared,
                          "request_sha256": fingerprint(shared),
                          "providers": previews,
                          "final_decision": {"status": "pending", "questions": {}}}
            else:
                raw_records = collect(prepared, credentials, policy["deadline_seconds"],
                                      disabled_providers=disabled_providers, required_providers=required_providers)
                record = make_record(shared, prepared, raw_records, version=version)
        json.dump(record, output, indent=2, allow_nan=False)
        output.write("\n")
    if args.adjudicate:
        status = record["final_decision"]["status"]
        print("Codex decision " + status)
        return 0 if status == "resolved" else 2
    print("Decision consultation " + record["status"] + "; Codex decision pending")
    return 0 if record["status"] in ("success", "dry_run") else 2


if __name__ == "__main__":
    sys.exit(main())
