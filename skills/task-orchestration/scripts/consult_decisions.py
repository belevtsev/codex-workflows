#!/usr/bin/env python3
"""Collect independent Jev/Snap advice, then record Codex's evidence-based decision."""

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
from validate_policy import DEFAULT_POLICY, PolicyError, load_policy, read_json, require


PROVIDERS = {
    "jev": ("https://api.typesafe.ai/v1/systemone", "TYPESAFE_API_KEY"),
    "subq_snap": ("https://api.subq.ai/v1/systemone", "SUBQ_API_KEY"),
}
ERROR_CATEGORIES = {
    "missing_credential", "deadline_unavailable", "timeout", "http_error",
    "network_error", "invalid_response", "worker_error",
}


def shared_request(value):
    require(isinstance(value, dict) and set(value) == {"state", "questions"},
            "dual request requires only state and questions")
    require(isinstance(value["state"], (str, dict, list)), "invalid state type")
    jev.prepare_request(value, "jev-1.13.0")
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


def provider_worker(sender, provider, prepared, deadline_at, credential):
    """Each isolated worker owns its signal deadline and one fixed endpoint."""
    try:
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            record = unavailable(prepared, "timeout")
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


def collect(prepared, credentials, deadline_seconds, context=None, worker=None):
    """Bound startup, response transport (including partial frames), and requests."""
    records = {name: unavailable(value, "missing_credential")
               for name, value in prepared.items() if not credentials.get(name)}
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


def safe_record(record, prepared, digest):
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
    if result["status"] == "success":
        validated = jev.validate_response(record.get("result"), prepared)
        require(record.get("resolved_model") == validated["model"], "provider resolved model differs")
        result.update(resolved_model=validated["model"], result=validated, usage=validated["usage"])
    else:
        require(result["status"] == "unavailable", "invalid provider status")
        failure = record.get("error")
        require(isinstance(failure, dict) and isinstance(failure.get("category"), str) and
                failure["category"] in ERROR_CATEGORIES,
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
    for question_id in shared["questions"]:
        choices = {name: record["result"]["answers"][question_id]["choice"]
                   for name, record in providers.items() if record["status"] == "success"}
        if len(choices) == 2:
            status = "agreement" if len(set(choices.values())) == 1 else "disagreement"
        else:
            status = "partial" if choices else "unavailable"
        compared[question_id] = {"status": status, "choices": choices}
    return compared


def availability(providers):
    successes = sum(record["status"] == "success" for record in providers.values())
    return "success" if successes == 2 else "partial" if successes else "unavailable"


def make_record(shared, prepared, raw_records):
    digest = fingerprint(shared)
    providers = {}
    for name, value in prepared.items():
        try:
            providers[name] = safe_record(raw_records[name], value, digest)
        except (PolicyError, KeyError, TypeError):
            providers[name] = safe_record(unavailable(value, "invalid_response"), value, digest)
    return {"version": 1, "status": availability(providers), "request": shared,
            "request_sha256": digest, "providers": providers,
            "comparison": comparison(shared, providers),
            "final_decision": {"status": "pending", "questions": {}}}


def text_value(value):
    return isinstance(value, str) and bool(value.strip())


def text_list(value):
    return isinstance(value, list) and all(text_value(item) for item in value)


def adjudicate(record, decision):
    """Validate Codex's recorded disposition; do not infer facts or call either API."""
    require(isinstance(record, dict) and set(record) == {
        "version", "status", "request", "request_sha256", "providers", "comparison", "final_decision",
    } and type(record["version"]) is int and record["version"] == 1, "invalid consultation record")
    shared = shared_request(record["request"])
    digest = fingerprint(shared)
    require(record["request_sha256"] == digest, "shared evidence fingerprint differs")
    require(isinstance(record["providers"], dict) and set(record["providers"]) == set(PROVIDERS),
            "invalid recorded providers")
    providers = {}
    for name, stored in record["providers"].items():
        require(isinstance(stored, dict), "invalid stored provider")
        model = stored.get("requested_model")
        require(isinstance(model, str) and
                (re.fullmatch(r"jev-[0-9]+\.[0-9]+\.[0-9]+", model) if name == "jev"
                 else model == "subq-snap-preview"), "invalid stored provider model")
        require(stored.get("request_sha256") == digest, "provider evidence fingerprint differs")
        prepared = jev.prepare_request(shared, model)
        providers[name] = safe_record(dict(stored, request=prepared), prepared, digest)
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
    args = parser.parse_args(argv)
    if bool(args.adjudicate) != bool(args.decision) or (args.adjudicate and args.dry_run):
        parser.error("--decision requires --adjudicate; --dry-run is only for --request")
    try:
        if args.adjudicate:
            record = adjudicate(read_json(args.adjudicate), read_json(args.decision))
            prepared = None
        else:
            policy = load_policy(args.policy)["consultation"]
            require("providers" in policy, "policy does not configure dual consultation")
            shared = shared_request(read_json(args.request))
            prepared = {name: jev.prepare_request(shared, model) for name, model in policy["providers"].items()}
        # Reserve a private output before network access; never overwrite earlier evidence.
        descriptor = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except (PolicyError, OSError) as failure:
        detail = str(failure) if isinstance(failure, PolicyError) else "cannot create a new output file"
        print("Decision consultation validation failed: " + detail, file=sys.stderr)
        return 1
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        if prepared is not None:
            if args.dry_run:
                record = {"version": 1, "status": "dry_run", "request": shared,
                          "request_sha256": fingerprint(shared),
                          "providers": {name: {"requested_model": value["model"]} for name, value in prepared.items()},
                          "final_decision": {"status": "pending", "questions": {}}}
            else:
                credentials = {name: os.environ.get(PROVIDERS[name][1]) for name in prepared}
                raw_records = collect(prepared, credentials, policy["deadline_seconds"])
                record = make_record(shared, prepared, raw_records)
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
