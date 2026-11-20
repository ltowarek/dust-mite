"""Guards which tickets and specs a closed blocking ticket promotes or refuses."""

from dataclasses import dataclass
from typing import Any

from afk.effects import Comment, DispatchWorkflow, ReplaceLabel
from afk.promote_queued import Promotion, Refusal, command_id, plan, select

REPOSITORY = "owner/repo"


@dataclass(frozen=True)
class Blocked:
    number: int
    labels: tuple[str, ...] = ()
    state: str = "OPEN"
    repository: str = REPOSITORY
    parent: int | None = None
    parent_labels: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()

    def node(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "state": self.state,
            "repository": {"nameWithOwner": self.repository},
            "parent": None
            if self.parent is None
            else {
                "number": self.parent,
                "labels": {"nodes": [{"name": n} for n in self.parent_labels]},
            },
            "labels": {"nodes": [{"name": n} for n in self.labels]},
            "blockedBy": {"nodes": [{"state": s} for s in self.blocked_by]},
        }


def response(*tickets: Blocked) -> dict[str, Any]:
    nodes = [ticket.node() for ticket in tickets]
    return {"data": {"repository": {"issue": {"blocking": {"nodes": nodes}}}}}


class TestSelect:
    def test_refuses_a_queued_child_ticket(self) -> None:
        selection = select(
            response(Blocked(7, labels=("afk:queued",), parent=3)), REPOSITORY
        )

        assert selection == [Refusal(number=7, parent=3)]

    def test_refuses_a_queued_child_ticket_that_is_still_blocked(self) -> None:
        ticket = Blocked(7, labels=("afk:queued",), parent=3, blocked_by=("OPEN",))

        assert select(response(ticket), REPOSITORY) == [Refusal(number=7, parent=3)]

    def test_promotes_a_queued_ticket_whose_blocking_tickets_are_all_closed(
        self,
    ) -> None:
        ticket = Blocked(7, labels=("afk:queued",), blocked_by=("CLOSED", "CLOSED"))

        assert select(response(ticket), REPOSITORY) == [Promotion(number=7)]

    def test_skips_a_queued_ticket_that_another_ticket_still_blocks(self) -> None:
        ticket = Blocked(7, labels=("afk:queued",), blocked_by=("CLOSED", "OPEN"))

        assert select(response(ticket), REPOSITORY) == []

    def test_skips_a_queued_ticket_that_is_in_progress(self) -> None:
        ticket = Blocked(7, labels=("afk:queued", "afk:in-progress"))

        assert select(response(ticket), REPOSITORY) == []

    def test_skips_a_ticket_that_is_not_queued(self) -> None:
        assert (
            select(response(Blocked(7, labels=("ready-for-agent",))), REPOSITORY) == []
        )

    def test_skips_a_closed_ticket(self) -> None:
        ticket = Blocked(7, labels=("afk:queued",), state="CLOSED")

        assert select(response(ticket), REPOSITORY) == []

    def test_skips_a_ticket_in_another_repository(self) -> None:
        ticket = Blocked(7, labels=("afk:queued",), repository="owner/other")

        assert select(response(ticket), REPOSITORY) == []

    def test_promotes_the_queued_spec_of_an_unblocked_child_ticket(self) -> None:
        ticket = Blocked(7, parent=3, parent_labels=("afk:queued",))

        assert select(response(ticket), REPOSITORY) == [Promotion(number=3)]

    def test_skips_the_queued_spec_of_a_child_ticket_that_is_still_blocked(
        self,
    ) -> None:
        ticket = Blocked(
            7, parent=3, parent_labels=("afk:queued",), blocked_by=("OPEN",)
        )

        assert select(response(ticket), REPOSITORY) == []

    def test_skips_a_queued_spec_that_is_in_progress(self) -> None:
        ticket = Blocked(7, parent=3, parent_labels=("afk:queued", "afk:in-progress"))

        assert select(response(ticket), REPOSITORY) == []

    def test_promotes_a_spec_once_when_several_of_its_child_tickets_unblock(
        self,
    ) -> None:
        spec = ("afk:queued",)
        tickets = (
            Blocked(8, parent=3, parent_labels=spec),
            Blocked(7, parent=3, parent_labels=spec),
        )

        assert select(response(*tickets), REPOSITORY) == [Promotion(number=3)]

    def test_orders_the_selection_by_number(self) -> None:
        tickets = (
            Blocked(9, labels=("afk:queued",)),
            Blocked(4, labels=("afk:queued",)),
        )

        assert select(response(*tickets), REPOSITORY) == [
            Promotion(number=4),
            Promotion(number=9),
        ]


class TestPlan:
    def test_plans_a_refusal_as_blocked_with_a_comment_that_names_the_spec(
        self,
    ) -> None:
        effects = plan([Refusal(number=7, parent=3)], {}, blocking_ticket=12)

        assert effects == [
            ReplaceLabel(number=7, remove="afk:queued", add="afk:blocked"),
            Comment(
                number=7,
                body="Refused to promote: this ticket is a child ticket of #3. Child "
                "tickets run only through their spec; comment `/afk implement` on #3 "
                "instead.",
            ),
        ]

    def test_plans_a_promotion_as_a_dispatch_before_its_label_and_comment(self) -> None:
        effects = plan([Promotion(number=7)], {7: "555"}, blocking_ticket=12)

        assert effects == [
            DispatchWorkflow(
                workflow="afk-run.yml", inputs={"number": "7", "comment-id": "555"}
            ),
            ReplaceLabel(number=7, remove="afk:queued", add="afk:in-progress"),
            Comment(
                number=7,
                body="Unblocked by #12 closing; promoted from `afk:queued` to "
                "`afk:in-progress`.",
            ),
        ]

    def test_plans_a_dispatch_without_a_command_when_none_queued_the_ticket(
        self,
    ) -> None:
        effects = plan([Promotion(number=7)], {7: None}, blocking_ticket=12)

        assert effects[0] == DispatchWorkflow(
            workflow="afk-run.yml", inputs={"number": "7"}
        )

    def test_plans_nothing_for_an_empty_selection(self) -> None:
        assert plan([], {}, blocking_ticket=12) == []


BOT_ID = 900


def comment(user_id: int, body: str) -> dict[str, Any]:
    return {"user": {"id": user_id}, "body": body}


class TestCommandId:
    def test_finds_the_command_in_the_apps_latest_queued_comment(self) -> None:
        comments = [
            comment(BOT_ID, "Queued.\n<!-- afk-command: 111 -->"),
            comment(BOT_ID, "Queued again.\n<!-- afk-command: 222 -->"),
            comment(BOT_ID, "Promoted."),
        ]

        assert command_id(comments, BOT_ID) == "222"

    def test_ignores_a_command_marker_that_another_user_wrote(self) -> None:
        comments = [
            comment(BOT_ID, "<!-- afk-command: 111 -->"),
            comment(1, "<!-- afk-command: 333 -->"),
        ]

        assert command_id(comments, BOT_ID) == "111"

    def test_finds_no_command_when_the_latest_marker_is_empty(self) -> None:
        comments = [
            comment(BOT_ID, "<!-- afk-command: 111 -->"),
            comment(BOT_ID, "<!-- afk-command:  -->"),
        ]

        assert command_id(comments, BOT_ID) is None

    def test_finds_no_command_without_a_marker(self) -> None:
        assert command_id([comment(BOT_ID, "Queued.")], BOT_ID) is None
