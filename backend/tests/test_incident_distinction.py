from app.agent.orchestrator import INVESTIGATION_POLICY


def test_investigation_policy_distinguishes_timeout_and_n_plus_one():
    policy = INVESTIGATION_POLICY.lower()
    assert "downstream-timeout" in policy
    assert "502" in policy
    assert "http timeout" in policy
    assert "n+1" in policy
    assert "query volume" in policy
    assert "code diff" in policy

