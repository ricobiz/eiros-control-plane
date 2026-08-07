from runtime.rental_agent.models import AuthorityAction
from runtime.rental_agent.policy import RentalPolicy


def test_market_discovery_policy_allows_contact_but_blocks_negotiation() -> None:
    policy = RentalPolicy()
    assert policy.check(AuthorityAction.CONTACT_DISCOVERY).allowed is True
    assert policy.check(AuthorityAction.NEGOTIATE).allowed is False
    assert policy.check(AuthorityAction.SCHEDULE_VIEWING).allowed is False
    assert policy.check(AuthorityAction.SEND_MONEY).allowed is False


def test_policy_reports_market_discovery_mode() -> None:
    current = RentalPolicy().current()
    assert current["mode"] == "market_discovery_only"
    assert "nationality" in current["do_not_volunteer"]
