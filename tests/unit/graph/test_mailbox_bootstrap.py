"""Folder discovery: paging, nesting, and what it refuses to do.

No network: a fake Graph client answers with recorded folder payloads.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.cli.graph_mailbox_bootstrap import _permission_hint, _walk
from app.graph.errors import GraphApiError


class FakeGraph:
    """Answers folder listings and records the URLs that were requested."""

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.requested: list[tuple[str, dict[str, Any] | None]] = []

    def build_url(self, path: str) -> str:
        return f"https://graph.microsoft.com/v1.0/{path.lstrip('/')}"

    def validate_continuation_url(self, url: str) -> str:
        return url

    async def get_json(
        self, url: str, *, params: dict[str, Any] | None = None, operation: str = ""
    ) -> dict[str, Any]:
        self.requested.append((url, params))
        return self.responses[url]


def _folder(folder_id: str, name: str, *, children: int = 0, parent: str | None = None) -> dict:
    return {
        "id": folder_id,
        "displayName": name,
        "childFolderCount": children,
        "parentFolderId": parent,
    }


ROOT = "https://graph.microsoft.com/v1.0/users/licensing%40example.com/mailFolders"


async def test_child_folders_are_discovered_with_their_full_path() -> None:
    """Workflow folders usually sit under Inbox, not beside it."""
    graph = FakeGraph(
        {
            ROOT: {"value": [_folder("f1", "Inbox", children=2)]},
            f"{ROOT}/f1/childFolders": {
                "value": [
                    _folder("f2", "01_Inbox_Unprocessed", parent="f1"),
                    _folder("f3", "08_Info_Required", parent="f1"),
                ]
            },
        }
    )

    folders = await _walk(graph, "licensing@example.com")  # type: ignore[arg-type]

    assert [f["folder_path"] for f in folders] == [
        "Inbox",
        "Inbox/01_Inbox_Unprocessed",
        "Inbox/08_Info_Required",
    ]
    assert folders[1]["parent_graph_folder_id"] == "f1"


async def test_paging_follows_next_link_without_repeating_the_query() -> None:
    graph = FakeGraph(
        {
            ROOT: {"value": [_folder("f1", "Inbox")], "@odata.nextLink": f"{ROOT}?page=2"},
            f"{ROOT}?page=2": {"value": [_folder("f2", "Archive")]},
        }
    )

    folders = await _walk(graph, "licensing@example.com")  # type: ignore[arg-type]

    assert [f["display_name"] for f in folders] == ["Inbox", "Archive"]
    assert graph.requested[0][1] is not None
    assert graph.requested[1][1] is None


async def test_recursion_stops_before_walking_an_unbounded_tree() -> None:
    """A folder that claims children forever must not loop forever."""
    responses = {ROOT: {"value": [_folder("f0", "Inbox", children=1)]}}
    for depth in range(12):
        responses[f"{ROOT}/f{depth}/childFolders"] = {
            "value": [_folder(f"f{depth + 1}", f"level-{depth + 1}", children=1)]
        }
    graph = FakeGraph(responses)

    folders = await _walk(graph, "licensing@example.com")  # type: ignore[arg-type]

    assert len(folders) <= 5
    assert all("level-9" not in f["display_name"] for f in folders)


@pytest.mark.parametrize(
    ("status", "expected"),
    [(403, "Mail.Read"), (404, "does not know this mailbox"), (500, None)],
)
def test_the_two_failures_worth_explaining_get_a_next_action(
    status: int, expected: str | None
) -> None:
    hint = _permission_hint(GraphApiError(status_code=status))
    if expected is None:
        assert hint is None
    else:
        assert hint is not None and expected in hint
