"""Guards which tickets and specs a closed blocking ticket promotes or refuses."""

from dataclasses import dataclass
from typing import Any

import pytest

from afk.effects import Comment, DispatchWorkflow, EditLabels
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


def make_response(*tickets: Blocked) -> dict[str, Any]:
    nodes = [ticket.node() for ticket in tickets]
    return {"data": {"repository": {"issue": {"blocking": {"nodes": nodes}}}}}


class TestSelect:
    @pytest.mark.parametrize(
        ("ticket", "selection"),
        [
            pytest.param(
                Blocked(7, labels=("afk:queued",), parent=3),
                [Refusal(number=7, parent=3)],
                id="refuses a queued child ticket",
            ),
            pytest.param(
                Blocked(7, labels=("afk:queued",), parent=3, blocked_by=("OPEN",)),
                [Refusal(number=7, parent=3)],
                id="refuses a queued child ticket that is still blocked",
            ),
            pytest.param(
                Blocked(7, labels=("afk:queued",), blocked_by=("CLOSED", "CLOSED")),
                [Promotion(number=7)],
                id="promotes a queued ticket whose blocking tickets are all closed",
            ),
            pytest.param(
                Blocked(7, parent=3, parent_labels=("afk:queued",)),
                [Promotion(number=3)],
                id="promotes the queued spec of an unblocked child ticket",
            ),
            pytest.param(
                Blocked(7, labels=("afk:queued",), blocked_by=("CLOSED", "OPEN")),
                [],
                id="skips a queued ticket that another ticket still blocks",
            ),
            pytest.param(
                Blocked(7, labels=("afk:queued", "afk:in-progress")),
                [],
                id="skips a queued ticket that is in progress",
            ),
            pytest.param(
                Blocked(7, labels=("ready-for-agent",)),
                [],
                id="skips a ticket that is not queued",
            ),
            pytest.param(
                Blocked(7, labels=("afk:queued",), state="CLOSED"),
                [],
                id="skips a closed ticket",
            ),
            pytest.param(
                Blocked(7, labels=("afk:queued",), repository="owner/other"),
                [],
                id="skips a ticket in another repository",
            ),
            pytest.param(
                Blocked(
                    7, parent=3, parent_labels=("afk:queued",), blocked_by=("OPEN",)
                ),
                [],
                id="skips the queued spec of a child ticket that is still blocked",
            ),
            pytest.param(
                Blocked(7, parent=3, parent_labels=("afk:queued", "afk:in-progress")),
                [],
                id="skips a queued spec that is in progress",
            ),
        ],
    )
    def test_selects_one_blocked_ticket(
        self, ticket: Blocked, selection: list[Promotion | Refusal]
    ) -> None:
        assert select(make_response(ticket), REPOSITORY) == selection

    def test_promotes_a_spec_once_when_several_of_its_child_tickets_unblock(
        self,
    ) -> None:
        spec = ("afk:queued",)
        tickets = (
            Blocked(8, parent=3, parent_labels=spec),
            Blocked(7, parent=3, parent_labels=spec),
        )

        assert select(make_response(*tickets), REPOSITORY) == [Promotion(number=3)]

    def test_orders_the_selection_by_number(self) -> None:
        tickets = (
            Blocked(9, labels=("afk:queued",)),
            Blocked(4, labels=("afk:queued",)),
        )

        assert select(make_response(*tickets), REPOSITORY) == [
            Promotion(number=4),
            Promotion(number=9),
        ]


class TestPlan:
    def test_plans_a_refusal_as_blocked_with_a_comment_that_names_the_spec(
        self,
    ) -> None:
        effects = plan([Refusal(number=7, parent=3)], {}, blocking_ticket=12)

        assert effects == [
            EditLabels(number=7, add=("afk:blocked",), remove=("afk:queued",)),
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
            EditLabels(number=7, add=("afk:in-progress",), remove=("afk:queued",)),
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


def make_comment(user_id: int, body: str) -> dict[str, Any]:
    return {"user": {"id": user_id}, "body": body}


class TestCommandId:
    @pytest.mark.parametrize(
        ("pages", "expected"),
        [
            pytest.param(
                [
                    [
                        make_comment(BOT_ID, "Queued.\n<!-- afk-command: 111 -->"),
                        make_comment(
                            BOT_ID, "Queued again.\n<!-- afk-command: 222 -->"
                        ),
                        make_comment(BOT_ID, "Promoted."),
                    ]
                ],
                "222",
                id="finds the command in the App's latest queued comment",
            ),
            pytest.param(
                [
                    [make_comment(BOT_ID, "Queued.\n<!-- afk-command: 111 -->")],
                    [make_comment(BOT_ID, "Queued again.\n<!-- afk-command: 222 -->")],
                ],
                "222",
                id="finds the command on the latest page",
            ),
            pytest.param(
                [
                    [
                        make_comment(BOT_ID, "<!-- afk-command: 111 -->"),
                        make_comment(1, "<!-- afk-command: 333 -->"),
                    ]
                ],
                "111",
                id="ignores a command marker that another user wrote",
            ),
            pytest.param(
                [
                    [
                        make_comment(BOT_ID, "<!-- afk-command: 111 -->"),
                        make_comment(BOT_ID, "<!-- afk-command:  -->"),
                    ]
                ],
                None,
                id="finds no command when the latest marker is empty",
            ),
            pytest.param(
                [[make_comment(BOT_ID, "Queued.")]],
                None,
                id="finds no command without a marker",
            ),
        ],
    )
    def test_finds_the_command_id(
        self, pages: list[list[dict[str, Any]]], expected: str | None
    ) -> None:
        assert command_id(pages, BOT_ID) == expected
