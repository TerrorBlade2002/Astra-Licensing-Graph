import json
import uuid

import httpx
import pytest

from app.ai.base import ClassificationModelInput
from app.ai.openai_provider import OpenAIClassificationProvider
from app.classification.deterministic import ClassificationInput, DeterministicClassifier
from tests.conftest import make_test_settings


def settings():
    return make_test_settings(
        "postgresql+asyncpg://astra:astra_local_dev@localhost:5442/astra_licensing_test",
        AI_CLASSIFICATION_ENABLED=True,
        AI_EXTERNAL_PROVIDER_APPROVED=True,
        AI_DATA_POLICY_ACKNOWLEDGED=True,
        OPENAI_API_KEY="synthetic-test-key",
        OPENAI_MODEL="synthetic-model",
    )


@pytest.mark.asyncio
async def test_openai_adapter_sends_minimized_strict_non_stored_request() -> None:
    output = (
        DeterministicClassifier()
        .classify(ClassificationInput(subject="General", body="No action is requested."))
        .output
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
        assert "tools" not in body and "background" not in body
        assert "[REDACTED_SSN]" in body["input"][1]["content"][0]["text"]
        return httpx.Response(
            200,
            json={
                "id": "resp_synthetic",
                "status": "completed",
                "output_text": output.model_dump_json(),
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIClassificationProvider(settings(), client)
    result = await provider.classify(
        ClassificationModelInput(
            subject="SSN 123-45-6789", sanitized_current_body="No action.", deterministic_hints={}
        ),
        "ClassificationOutputV1",
        "v1",
        uuid.uuid4(),
    )
    assert result.provider_request_id == "resp_synthetic"
    assert result.total_tokens == 30
    await client.aclose()


def test_openai_adapter_fails_closed_without_approval() -> None:
    with pytest.raises(ValueError, match="approved"):
        OpenAIClassificationProvider(
            make_test_settings(
                "postgresql+asyncpg://astra:astra_local_dev@localhost:5442/astra_licensing_test"
            )
        )
