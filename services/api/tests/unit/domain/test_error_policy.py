from motif_forge.domain.error_policy import ErrorFacts, classify_agent_error


def test_retryable_provider_error_falls_back_after_provider_owned_retries() -> None:
    decision = classify_agent_error(
        ErrorFacts(
            category="model_provider",
            code="DEEPSEEK_TIMEOUT",
            retryable=True,
            suggested_route="retry",
            repair_attempts=0,
            model_calls_remaining=1,
        )
    )

    assert decision.route == "fallback"
    assert decision.rule_id == "ERR-003"


def test_authentication_error_requires_human() -> None:
    decision = classify_agent_error(
        ErrorFacts(
            category="model_provider",
            code="DEEPSEEK_HTTP_401",
            retryable=False,
            suggested_route="human",
            repair_attempts=0,
            model_calls_remaining=1,
        )
    )

    assert decision.route == "human"
    assert decision.policy_version == "agent-error-policy.v1"
