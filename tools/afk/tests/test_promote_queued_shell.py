"""Guards how the promote-queued shell reads GitHub and routes its writes."""

import json
from collections.abc import Mapping, Sequence

from afk.promote_queued import run

ENV = {
    "AFK_APP_TOKEN": "app-token",
    "AFK_WORKFLOW_TOKEN": "workflow-token",
    "AFK_BLOCKING_TICKET": "12",
    "AFK_BOT_ID": "900",
    "GH_REPO": "owner/repo",
}

BLOCKING = {
    "data": {
        "repository": {
            "issue": {
                "blocking": {
                    "nodes": [
                        {
                            "number": 7,
                            "state": "OPEN",
                            "repository": {"nameWithOwner": "owner/repo"},
                            "parent": None,
                            "labels": {"nodes": [{"name": "afk:queued"}]},
                            "blockedBy": {"nodes": [{"state": "CLOSED"}]},
                        }
                    ]
                }
            }
        }
    }
}

COMMENT_PAGES = [
    [{"user": {"id": 900}, "body": "Queued.\n<!-- afk-command: 555 -->"}],
    [{"user": {"id": 900}, "body": "Still queued."}],
]


class GhSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, args: Sequence[str], env: Mapping[str, str]) -> str:
        self.calls.append((list(args), env["GH_TOKEN"]))
        if args[:3] == ["gh", "api", "graphql"]:
            return json.dumps(BLOCKING)
        if args[:2] == ["gh", "api"]:
            return json.dumps(COMMENT_PAGES)
        return ""


def test_reads_with_the_workflow_token_and_writes_each_planned_effect() -> None:
    gh = GhSpy()

    run(gh, ENV)

    graphql, comments, *writes = gh.calls
    assert graphql[0][:3] == ["gh", "api", "graphql"]
    assert graphql[0][-6:] == [
        "-f",
        "owner=owner",
        "-f",
        "repo=repo",
        "-F",
        "number=12",
    ]
    assert graphql[1] == "workflow-token"
    assert comments == (
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            "repos/owner/repo/issues/7/comments?per_page=100",
        ],
        "workflow-token",
    )
    assert writes == [
        (
            [
                "gh",
                "workflow",
                "run",
                "afk-run.yml",
                "-f",
                "number=7",
                "-f",
                "comment-id=555",
            ],
            "workflow-token",
        ),
        (
            [
                "gh",
                "issue",
                "edit",
                "7",
                "--remove-label",
                "afk:queued",
                "--add-label",
                "afk:in-progress",
            ],
            "app-token",
        ),
        (
            [
                "gh",
                "issue",
                "comment",
                "7",
                "--body",
                "Unblocked by #12 closing; promoted from `afk:queued` to "
                "`afk:in-progress`.",
            ],
            "app-token",
        ),
    ]


def test_a_dry_run_reads_and_reports_the_writes_it_skips() -> None:
    gh = GhSpy()

    outputs = run(gh, {**ENV, "AFK_DRY_RUN": "true"})

    assert [args[:2] for args, _ in gh.calls] == [["gh", "api"], ["gh", "api"]]
    assert [effect["type"] for effect in json.loads(outputs["effects"])] == [
        "DispatchWorkflow",
        "ReplaceLabel",
        "Comment",
    ]
