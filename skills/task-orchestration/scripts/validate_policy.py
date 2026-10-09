#!/usr/bin/env python3
"""Validate the coordinator's policy without changing settings or dispatching work."""

import argparse
import json
import math
from pathlib import Path
import re
import sys

import yaml


DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "model-policy.yaml"
SUBSTANTIVE_ROLES = {
    "coordinator", "coding", "testing", "planning", "architecture", "review",
    "diagnosis", "documentation", "issue_management", "pr_authoring",
}
EXECUTION_ROLES = {"commit_execution", "pr_authoring_routine", "pr_submission"}
EVIDENCE_ROLES = {"lookup", "summarization"}
PROFILE_SCOPES = {"substantive", "bounded_evidence", "bounded_execution"}
SOL_MODELS = {"gpt-6.1-sol", "gpt-6-sol"}
# Known worker capabilities in this Codex harness, not a runtime availability
# probe. None/minimal are not exposed; Luna stops at max, others support ultra.
MODEL_EFFORTS = {
    "gpt-6.1-sol": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-6-sol": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-6-astra": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-6-luna": {"low", "medium", "high", "xhigh", "max"},
}
ACTIVATION_CONDITIONS = {
    "independent_workstreams", "cross_component_change", "consequential_uncertainty",
}


class PolicyError(ValueError):
    """An input is invalid; messages contain field names, never input values."""


def require(condition, message):
    if not condition:
        raise PolicyError(message)


def unique_mapping(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate mapping key")
        value[key] = item
    return value


class PolicyLoader(yaml.SafeLoader):
    pass


def yaml_mapping(loader, node):
    loader.flatten_mapping(node)
    return unique_mapping(loader.construct_pairs(node))


PolicyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, yaml_mapping)


def read_json(path):
    try:
        return json.loads(
            Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_mapping,
            parse_constant=lambda _value: (_ for _ in ()).throw(PolicyError("nonfinite JSON number")),
        )
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise PolicyError("cannot read valid JSON input") from error


def json_value(value):
    if value is None or isinstance(value, (str, bool)):
        return
    if type(value) in (int, float):
        require(type(value) is int or math.isfinite(value), "nonfinite JSON number")
        return
    if isinstance(value, list):
        for item in value:
            json_value(item)
        return
    if isinstance(value, dict):
        require(all(isinstance(key, str) for key in value), "JSON keys must be strings")
        for item in value.values():
            json_value(item)
        return
    raise PolicyError("unsupported JSON value")


def description(value):
    require(isinstance(value, (str, dict, list)) and bool(value), "empty or invalid description")
    require(not isinstance(value, str) or bool(value.strip()), "empty or invalid description")
    json_value(value)


def validate_choice(question):
    require(isinstance(question, dict), "question must be a mapping")
    require(set(question) == {"type", "instructions", "criteria"}, "invalid Choice fields")
    require(question["type"] == "choice", "only Choice questions are supported")
    description(question["instructions"])
    criteria = question["criteria"]
    require(isinstance(criteria, dict) and len(criteria) >= 2, "Choice needs at least two options")
    require(all(isinstance(key, str) and key.strip() for key in criteria), "invalid option ID")
    for item in criteria.values():
        description(item)


def mapping(value, name, fields=None):
    require(isinstance(value, dict), name + " must be a mapping")
    if fields is not None:
        require(set(value) == set(fields), name + " has invalid fields")
    return value


def exact_integer(value, expected, name):
    require(type(value) is int and value == expected, name + " has an invalid value")


def validate_profile(profile):
    mapping(profile, "profile", {"model", "reasoning_effort", "user_requested_efforts", "scope"})
    model = profile["model"]
    require(isinstance(model, str) and model in MODEL_EFFORTS, "unknown worker model")
    effort = profile["reasoning_effort"]
    require(isinstance(effort, str) and effort in MODEL_EFFORTS[model],
            "unsupported default reasoning effort")
    require(model not in SOL_MODELS or effort != "max", "Sol max requires an explicit user request")
    efforts = profile["user_requested_efforts"]
    require(isinstance(efforts, list) and
            all(isinstance(item, str) and item in MODEL_EFFORTS[model] for item in efforts),
            "unsupported user-requested efforts")
    require(len(efforts) == len(set(efforts)), "duplicate user-requested effort")
    require(isinstance(profile["scope"], str) and profile["scope"] in PROFILE_SCOPES,
            "invalid profile scope")
    require(profile["scope"] != "substantive" or model != "gpt-6-luna",
            "substantive profiles require a non-Luna model")


def referenced_profile(profiles, name):
    require(isinstance(name, str) and name in profiles, "invalid profile reference")
    return profiles[name]


def role_scopes(role):
    if role in EXECUTION_ROLES:
        return {"bounded_execution", "substantive"}
    if role in EVIDENCE_ROLES:
        return {"bounded_evidence", "substantive"}
    return {"substantive"}


def resolve_worker(policy, role, requested_effort=None):
    """Resolve a worker from a loaded policy without mutating its defaults.

    requested_effort represents an explicit user request, not an automatic
    escalation. An override must be permitted by the selected profile.
    """
    require(isinstance(role, str) and bool(role.strip()), "invalid role name")
    roles = mapping(policy.get("roles"), "roles")
    profiles = mapping(policy.get("profiles"), "profiles")
    name = roles.get(role, policy.get("unknown_role_profile"))
    profile = referenced_profile(profiles, name)
    validate_profile(profile)
    require(profile["scope"] in (role_scopes(role) if role in roles else {"substantive"}),
            "invalid role routing")
    effort = profile["reasoning_effort"]
    if requested_effort is not None:
        require(isinstance(requested_effort, str) and requested_effort in MODEL_EFFORTS[profile["model"]],
                "unsupported requested reasoning effort")
        require(requested_effort == effort or requested_effort in profile["user_requested_efforts"],
                "requested reasoning effort is not permitted")
        effort = requested_effort
    return {"model": profile["model"], "reasoning_effort": effort}


def load_policy(path=DEFAULT_POLICY):
    path = Path(path)
    try:
        policy = yaml.load(path.read_text(encoding="utf-8"), Loader=PolicyLoader)
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, RecursionError) as error:
        raise PolicyError("cannot read valid policy YAML") from error
    mapping(policy, "policy")
    exact_integer(policy.get("version"), 2, "policy version")
    mapping(policy, "policy", {
        "version", "activation", "profiles", "effort_policy", "effort_guidance", "roles", "lookup_boundary", "unknown_role_profile",
        "fixed_specialists", "fallbacks", "consultation", "publication",
    })
    activation = mapping(policy["activation"], "activation", {"any_of", "bypass"})
    conditions = activation["any_of"]
    require(isinstance(conditions, list) and bool(conditions) and
            all(isinstance(item, str) and item in ACTIVATION_CONDITIONS for item in conditions),
            "invalid activation conditions")
    require(len(conditions) == len(set(conditions)), "duplicate activation condition")
    require(activation["bypass"] == "small_edits_and_direct_factual_answers", "invalid activation bypass")
    profiles = mapping(policy["profiles"], "profiles")
    require({"sol", "luna", "luna_execution"} <= set(profiles), "missing required profile")
    for name, profile in profiles.items():
        require(isinstance(name, str) and bool(name.strip()), "invalid profile name")
        validate_profile(profile)
    effort_policy = mapping(policy["effort_policy"], "effort_policy", {
        "default_substantive", "max_for_sol", "configured_max_profiles", "automatic_escalation",
    })
    require(effort_policy["max_for_sol"] == "explicit_user_request", "invalid Sol max rule")
    configured_max = effort_policy["configured_max_profiles"]
    require(isinstance(configured_max, list) and
            all(isinstance(name, str) and name in profiles for name in configured_max),
            "invalid configured max profiles")
    require(len(configured_max) == len(set(configured_max)), "duplicate configured max profile")
    require(set(configured_max) == {
        name for name, profile in profiles.items() if profile["reasoning_effort"] == "max"
    }, "invalid configured max profiles")
    require(effort_policy["automatic_escalation"] is False, "automatic effort escalation must be disabled")
    effort_guidance = mapping(policy["effort_guidance"], "effort_guidance", {"ultra", "max", "comparison"})
    for guidance in effort_guidance.values():
        require(isinstance(guidance, str) and bool(guidance.strip()), "effort guidance must be nonempty text")
    roles = mapping(policy["roles"], "roles")
    require(SUBSTANTIVE_ROLES | EXECUTION_ROLES | EVIDENCE_ROLES <= set(roles), "missing required role")
    for role, name in roles.items():
        require(isinstance(role, str) and role.strip(), "invalid role name")
        profile = referenced_profile(profiles, name)
        require(profile["scope"] in role_scopes(role), "invalid role routing")
    require(effort_policy["default_substantive"] == profiles[roles["coordinator"]]["reasoning_effort"],
            "substantive default must match coordinator effort")
    require(referenced_profile(profiles, policy["unknown_role_profile"])["scope"] == "substantive",
            "unknown-role fallback must be substantive")
    require(policy["lookup_boundary"] == "bounded_read_only_evidence_without_consequential_conclusions",
            "invalid lookup boundary")
    specialists = mapping(policy["fixed_specialists"], "fixed_specialists", {"context_explorer"})
    specialist = mapping(specialists["context_explorer"], "context_explorer", {"respect_runtime_model", "scope"})
    require(specialist["respect_runtime_model"] is True, "fixed specialist must respect runtime model")
    require(specialist["scope"] == "evidence_gathering_only", "invalid fixed-specialist scope")
    fallbacks = mapping(policy["fallbacks"], "fallbacks", {
        "luna_unavailable", "sol_unavailable", "jev_unavailable_or_inconclusive",
    })
    require(referenced_profile(profiles, fallbacks["luna_unavailable"])["scope"] == "substantive",
            "worker fallback must be substantive")
    require(fallbacks["sol_unavailable"] == "compatible_coordinator_or_report_blocker" and
            fallbacks["jev_unavailable_or_inconclusive"] ==
            "continue_with_source_evidence_and_conservative_routing", "invalid fallback routing")
    consultation = mapping(policy["consultation"], "consultation", {
        "model", "deadline_seconds", "attempts_per_evidence_batch", "automatic_retries", "questions",
        "ownership", "reuse", "sharing",
    })
    require(isinstance(consultation["model"], str) and
            re.fullmatch(r"jev-[0-9]+\.[0-9]+\.[0-9]+", consultation["model"]),
            "consultation model must be an exact versioned Jev ID")
    exact_integer(consultation["deadline_seconds"], 30, "consultation deadline")
    exact_integer(consultation["attempts_per_evidence_batch"], 1, "consultation attempts")
    require(consultation["automatic_retries"] is False, "automatic retries must be disabled")
    require(consultation["ownership"] == "task_coordinator", "invalid consultation owner")
    require(consultation["reuse"] == "unchanged_evidence_decisions_question_meaning_and_model", "invalid reuse rule")
    require(consultation["sharing"] == "minimal_evidence_within_task_authorization", "invalid sharing rule")
    reference = consultation["questions"]
    require(isinstance(reference, str) and bool(reference.strip()), "invalid question reference")
    relative = Path(reference)
    require(not relative.is_absolute(), "question reference must be relative")
    resolved = (path.parent / relative).resolve()
    require(path.parent.resolve() in resolved.parents, "question reference escapes skill directory")
    questions = read_json(resolved)
    mapping(questions, "question reference")
    exact_integer(questions.get("version"), 1, "question reference version")
    templates = mapping(questions.get("questions"), "question templates")
    require(bool(templates), "question templates are empty")
    require(all(isinstance(key, str) and key.strip() for key in templates), "invalid question ID")
    for question in templates.values():
        validate_choice(question)
    publication = mapping(policy["publication"], "publication", {
        "authority", "analysis_output", "refresh_before_write", "readback_after_write", "uncertain_outcome",
    })
    require(publication["authority"] == "user_request_and_carried_authorization", "invalid publication authority")
    require(publication["analysis_output"] == "draft", "invalid analysis output")
    require(publication["refresh_before_write"] is True and publication["readback_after_write"] is True,
            "publication checks must be enabled")
    require(publication["uncertain_outcome"] == "reconcile_before_retry", "invalid uncertain-outcome rule")
    return policy


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args(argv)
    try:
        load_policy(args.policy)
    except PolicyError as error:
        print("Invalid policy: " + str(error), file=sys.stderr)
        return 1
    print("Policy valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
