from __future__ import annotations

from runtime.rental_agent.models import ActionDecision, AuthorityAction


_ALLOWED = {
    AuthorityAction.SEARCH,
    AuthorityAction.INGEST,
    AuthorityAction.CONTACT_DISCOVERY,
    AuthorityAction.REQUEST_MEDIA,
    AuthorityAction.COMPARE_RANK,
}


class RentalPolicy:
    mode = "market_discovery_only"

    def check(self, action: AuthorityAction) -> ActionDecision:
        if action in _ALLOWED:
            return ActionDecision(action=action, allowed=True, reason="allowed_by_market_discovery_policy")
        return ActionDecision(
            action=action,
            allowed=False,
            reason="blocked_by_market_discovery_policy",
        )

    def current(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "allowed": [action.value for action in AuthorityAction if action in _ALLOWED],
            "blocked": [action.value for action in AuthorityAction if action not in _ALLOWED],
            "do_not_volunteer": [
                "personal biography",
                "nationality",
                "business plans",
                "company details",
                "payment methods",
                "move dates",
            ],
        }
