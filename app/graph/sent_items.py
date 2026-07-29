"""Immutable-ID sent-copy inspection."""

from app.graph.drafts import GraphDraftClient


class SentItemsClient(GraphDraftClient):
    async def inspect_immutable_message(self, mailbox: str, immutable_id: str) -> dict[str, object]:
        return await self.get(mailbox, immutable_id)
