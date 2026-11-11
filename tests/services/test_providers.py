import json

import httpx
import pytest
import respx

from ranobe.core.errors import (
    AuthFailed,
    ContentRefused,
    OutputTruncated,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    Transient,
)
from ranobe.services.providers import ChatRequest, ProviderRegistry

KEY = "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKE123"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


@pytest.fixture
async def registry():
    reg = ProviderRegistry()
    yield reg
    await reg.aclose()


def ok(content='{"segments": []}', finish="stop"):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


REQ = ChatRequest(model="gemini-2.5-flash", system="sys", user="usr")


@respx.mock
async def test_chat_success_sends_json_mode_and_bearer(registry):
    route = respx.post(GEMINI).mock(return_value=ok())
    resp = await registry.get("gemini").chat(REQ, KEY)
    assert resp.text == '{"segments": []}' and resp.input_tokens == 10
    sent = route.calls.last.request
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(sent.content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "sys"}


@respx.mock
async def test_openrouter_does_not_force_json_mode(registry):
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(return_value=ok())
    await registry.get("openrouter").chat(REQ, "sk-or-xxxxxxxxxxxxxxxxxxxx")
    assert "response_format" not in json.loads(route.calls.last.request.content)


GEMINI_RPM_429 = [
    {
        "error": {
            "code": 429,
            "message": "Resource has been exhausted. Quota exceeded for metric "
            "generate_content_free_tier_requests, limit: 10, per minute",
            "status": "RESOURCE_EXHAUSTED",
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}],
        }
    }
]
GEMINI_DAY_429 = [
    {
        "error": {
            "code": 429,
            "message": "Quota exceeded for quota metric 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'",
            "status": "RESOURCE_EXHAUSTED",
        }
    }
]


@pytest.mark.parametrize(
    ("status", "body", "headers", "expected"),
    [
        (429, GEMINI_RPM_429, {}, RateLimited),
        (429, {"error": {"message": "slow down"}}, {"retry-after": "12"}, RateLimited),
        (429, GEMINI_DAY_429, {}, QuotaExhausted),
        (429, {"error": {"code": "insufficient_quota", "message": "x"}}, {}, QuotaExhausted),
        (402, {"error": {"message": "Insufficient Balance"}}, {}, QuotaExhausted),
        (401, {"error": {"message": "bad key"}}, {}, AuthFailed),
        (
            400,
            [{"error": {"message": "API key not valid. Please pass a valid API key."}}],
            {},
            AuthFailed,
        ),
        (404, {"error": {"message": "model not found"}}, {}, AuthFailed),
        (500, "oops", {}, Transient),
        (503, {"error": {"message": "overloaded"}}, {}, Transient),
        (400, {"error": {"message": "request blocked by safety settings"}}, {}, ContentRefused),
        (400, {"error": {"message": "something else"}}, {}, ProviderError),
    ],
)
@respx.mock
async def test_error_classification(registry, status, body, headers, expected):
    content = body if isinstance(body, str) else json.dumps(body)
    respx.post(GEMINI).mock(return_value=httpx.Response(status, text=content, headers=headers))
    with pytest.raises(expected) as info:
        await registry.get("gemini").chat(REQ, KEY)
    assert type(info.value) is expected
    assert KEY not in str(info.value)


@respx.mock
async def test_retry_after_values(registry):
    respx.post(GEMINI).mock(return_value=httpx.Response(429, json=GEMINI_RPM_429))
    with pytest.raises(RateLimited) as info:
        await registry.get("gemini").chat(REQ, KEY)
    assert info.value.retry_after == 37.0


@respx.mock
async def test_gemini_daily_quota_resets_at_0800_utc(registry):
    respx.post(GEMINI).mock(return_value=httpx.Response(429, json=GEMINI_DAY_429))
    with pytest.raises(QuotaExhausted) as info:
        await registry.get("gemini").chat(REQ, KEY)
    assert info.value.reset_at.hour == 8


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (ok(finish="length"), OutputTruncated),
        (ok(finish="content_filter"), ContentRefused),
        (ok(content=""), ContentRefused),
        (httpx.Response(200, json={"choices": []}), ContentRefused),
    ],
)
@respx.mock
async def test_bad_success_responses(registry, response, expected):
    respx.post(GEMINI).mock(return_value=response)
    with pytest.raises(expected):
        await registry.get("gemini").chat(REQ, KEY)


@respx.mock
async def test_network_errors_are_transient(registry):
    respx.post(GEMINI).mock(side_effect=httpx.ConnectTimeout("t"))
    with pytest.raises(Transient):
        await registry.get("gemini").chat(REQ, KEY)
    respx.post(GEMINI).mock(side_effect=httpx.ConnectError("c"))
    with pytest.raises(Transient):
        await registry.get("gemini").chat(REQ, KEY)


@respx.mock
async def test_list_models(registry):
    respx.get("https://api.groq.com/openai/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]})
    )
    assert await registry.get("groq").list_models("gsk_x") == ["a", "b"]


def test_unknown_provider():
    with pytest.raises(KeyError):
        ProviderRegistry().get("nope")
