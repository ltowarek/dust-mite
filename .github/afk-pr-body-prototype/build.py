"""PROTOTYPE, throwaway: render each variant through GitHub's Markdown API into one viewer page."""

import json
import pathlib
import subprocess

HERE = pathlib.Path(__file__).parent

PRS = {
    "212": {
        "title": "Shut the streamer down cleanly on SIGTERM and SIGINT",
        "stats": "+187 −24 · 10 files",
        "labels": [],
        "context": "A controller change with no DUT run. Variants B–E pretend an AFK run wrote it.",
    },
    "183": {
        "title": "Stream Camera frames closer to the camera's rate",
        "stats": "+30 −8 · 4 files",
        "labels": ["needs-car"],
        "context": "A car firmware change that needs the car to confirm. The real PR came from an interactive session at the desk; variants B–E pretend an AFK run wrote it and a car agent session then did the DUT run.",
    },
}

VARIANTS = {
    "a-actual": ("A", "As merged", "The body the real PR carried, for comparison."),
    "b-pr-skill": ("B", "Vanilla /pr", "Matt's released template filled as written: Summary, Evidence, Merge Danger. Nothing added."),
    "c-pr-plus": ("C", "/pr + review aids", "Adds Read first, Worth understanding, a DUT run section, the repo's one-way doors and Undo."),
    "d-calls-first": ("D", "Calls first", "Opens with what the agent decided that the ticket didn't, then what isn't tested; shape and evidence fold away."),
    "e-four-lines": ("E", "Four lines", "Changed, verified, could break, safe to merge. Everything else folds away."),
    "f-agreed": ("F", "Agreed so far", "Vanilla /pr plus the agreed parts: Not in the ticket, a Worth understanding section of folded items, the DUT run inside Evidence, and the YAML's Closes line and run link."),
}


def render(markdown: str) -> str:
    return subprocess.run(
        ["gh", "api", "markdown", "-f", "mode=gfm", "-f", "context=ltowarek/dust-mite", "-f", f"text={markdown}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


data = {
    "prs": PRS,
    "variants": [{"id": k, "key": v[0], "name": v[1], "note": v[2]} for k, v in VARIANTS.items()],
    "bodies": {
        pr: {variant: render((HERE / f"pr-{pr}" / f"{variant}.md").read_text()) for variant in VARIANTS} for pr in PRS
    },
}
template = (HERE / "viewer.template.html").read_text()
(HERE / "index.html").write_text(template.replace("/*DATA*/null", json.dumps(data).replace("</", "<\\/")))
print("wrote", HERE / "index.html")
