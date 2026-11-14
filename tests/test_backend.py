import json
import socket
import ssl
import threading
import urllib.error
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

import pytest

from vlm_action_policy.backend import (
    InferenceRequest,
    ProviderBackend,
    ProviderConnectionError,
    ProviderHTTPError,
    ProviderResponseError,
    inference_diagnostic,
)
from vlm_action_policy.config import PolicyConfig
from vlm_action_policy.contracts import Identity, Observation

REQUEST = InferenceRequest("pick cup", Observation(Identity("ep", "e", "e:0", 0, 1),
                           (0.0,) * 8, {"main": b"png", "wrist": b"png2"}), ())
ACTIONS = {"actions": [[0, 0, 0, 0, 0, 0, -1]] * 4}


@contextmanager
def server(response, status=200):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body, self.headers["Authorization"]))
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/v1", requests
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def backend(monkeypatch, url, style="chat_completions", **extra):
    monkeypatch.setenv("VLM_API_BASE", url)
    monkeypatch.setenv("VLM_API_KEY", "unit-test-secret")
    monkeypatch.setenv("VLM_MODEL", "test-vision-model")
    monkeypatch.setenv("VLM_REASONING_EFFORT", "low")
    return ProviderBackend(PolicyConfig.from_mapping({"model": {"api_style": style, **extra}}))


def test_real_http_chat_multimodal_request(monkeypatch):
    response = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(ACTIONS)}}]}
    with server(response) as (url, requests):
        assert backend(monkeypatch, url).infer(REQUEST) == ACTIONS
        path, body, auth = requests[0]
    assert path == "/v1/chat/completions" and auth == "Bearer unit-test-secret"
    user = body["messages"][1]["content"]
    assert len([part for part in user if part["type"] == "image_url"]) == 2
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["reasoning_effort"] == "low"
    assert json.loads(user[0]["text"])["state"]["eef_x_m"] == 0


def test_real_http_responses_api(monkeypatch):
    response = {"status": "completed", "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps(ACTIONS)}]},
    ]}
    with server(response) as (url, requests):
        assert backend(monkeypatch, url, "responses").infer(REQUEST) == ACTIONS
        path, body, _ = requests[0]
    assert path == "/v1/responses"
    assert body["store"] is False
    assert body["reasoning"] == {"effort": "low"}
    assert len([part for part in body["input"][0]["content"] if part["type"] == "input_image"]) == 2


@pytest.mark.parametrize("response,label", [
    ({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}, "output_truncated"),
    ({"choices": [{"finish_reason": "stop", "message": {"refusal": "private text", "content": "{}"}}]}, "model_refusal"),
    ({"choices": [{"finish_reason": "stop", "message": {"content": "```json {} ```"}}]}, "invalid_action_json"),
    ({"choices": []}, "malformed_response"),
])
def test_malformed_refused_or_truncated_response(monkeypatch, response, label):
    with server(response) as (url, _):
        with pytest.raises(ProviderResponseError) as error:
            backend(monkeypatch, url).infer(REQUEST)
    expected = ("output_truncated; request_max_output_tokens=2048, visible_output_chars=2"
                if label == "output_truncated" else label)
    assert inference_diagnostic(error.value) == expected


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 503])
def test_provider_errors_do_not_leak_secret_or_body(monkeypatch, status):
    with server({"error": "unit-test-secret private provider body"}, status=status) as (url, _):
        with pytest.raises(ProviderHTTPError, match=f"^provider HTTP error {status}$") as error:
            backend(monkeypatch, url).infer(REQUEST)
    assert inference_diagnostic(error.value) == f"provider_http_{status}"
    assert "unit-test-secret" not in str(error.value)


@pytest.mark.parametrize("reason,label", [
    (TimeoutError("unit-test-secret timeout"), "connection_timeout"),
    (ssl.SSLError("unit-test-secret TLS"), "tls_error"),
    (socket.gaierror("unit-test-secret DNS"), "dns_error"),
    (ConnectionRefusedError("unit-test-secret refused"), "connection_failed"),
    ("unit-test-secret unknown transport", "connection_failed"),
])
@pytest.mark.parametrize("wrapped", [False, True])
def test_network_errors_are_sanitized(monkeypatch, reason, label, wrapped):
    client = backend(monkeypatch, "https://example.invalid/v1")
    error = urllib.error.URLError(reason) if wrapped else reason
    if isinstance(error, str):
        error = OSError(error)

    def fail_open(*args, **kwargs):
        raise error

    monkeypatch.setattr(client.opener, "open", fail_open)
    with pytest.raises(ProviderConnectionError) as caught:
        client.infer(REQUEST)
    assert str(caught.value) == label
    assert inference_diagnostic(caught.value) == label


@pytest.mark.parametrize("response,label", [
    ({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}, "output_truncated"),
    ({"status": "failed", "error": "unit-test-secret"}, "response_incomplete"),
    ({"status": "completed", "output": [{"type": "message", "content": [
        {"type": "refusal", "refusal": "unit-test-secret"}]}]}, "model_refusal"),
    ({"status": "completed", "output": None}, "malformed_response"),
    ({"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": "[]"}]}]}, "invalid_action_json"),
    ([], "malformed_response"),
])
def test_responses_failures_are_sanitized(monkeypatch, response, label):
    with server(response) as (url, _):
        with pytest.raises(ProviderResponseError) as caught:
            backend(monkeypatch, url, "responses").infer(REQUEST)
    expected = "output_truncated; request_max_output_tokens=2048" if label == "output_truncated" else label
    assert inference_diagnostic(caught.value) == expected
    assert "unit-test-secret" not in str(caught.value)


@pytest.mark.parametrize("error,label", [
    (ProviderHTTPError(401), "provider_http_401"),
    (ProviderHTTPError(999), "backend_exception"),
    (ProviderHTTPError(True), "backend_exception"),
    (ProviderConnectionError("connection_timeout"), "connection_timeout"),
    (ProviderResponseError("response_too_large"), "response_too_large"),
    (ProviderResponseError("unexpected_finish_reason"), "unexpected_finish_reason"),
    (RuntimeError("unit-test-secret private provider body"), "backend_exception"),
    (ProviderResponseError("unit-test-secret"), "backend_exception"),
    (ProviderConnectionError({"private": "unit-test-secret"}), "backend_exception"),
    (ProviderResponseError(["unit-test-secret"]), "backend_exception"),
    (ProviderResponseError(), "backend_exception"),
])
def test_diagnostic_allowlist(error, label):
    assert inference_diagnostic(error) == label


@pytest.mark.parametrize("raw,label", [
    (b"not JSON unit-test-secret", "malformed_response"),
    (b"\xff", "malformed_response"),
    (b"x" * (4 * 1024 * 1024 + 1), "response_too_large"),
])
def test_invalid_or_oversized_wire_body_is_sanitized(monkeypatch, raw, label):
    client = backend(monkeypatch, "https://example.invalid/v1")
    monkeypatch.setattr(client.opener, "open", lambda *args, **kwargs: BytesIO(raw))
    with pytest.raises(ProviderResponseError) as caught:
        client.infer(REQUEST)
    assert inference_diagnostic(caught.value) == label
    assert "unit-test-secret" not in str(caught.value)


@pytest.mark.parametrize("style", ["chat_completions", "responses"])
def test_truncation_reports_only_budget_usage_and_visible_length(monkeypatch, style):
    private_text = "unit-test-secret private model output"
    if style == "responses":
        response = {
            "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
            "usage": {"input_tokens": 1200, "output_tokens": 8192,
                      "output_tokens_details": {"reasoning_tokens": 8180},
                      "private": private_text},
            "output": [
                {"type": "reasoning", "summary": [{"text": private_text}]},
                {"type": "message", "content": [{"type": "output_text", "text": private_text}]},
            ],
        }
    else:
        response = {
            "choices": [{"finish_reason": "length", "message": {
                "content": private_text, "reasoning_content": private_text}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 8192,
                      "completion_tokens_details": {"reasoning_tokens": 8180},
                      "private": private_text},
        }
    with server(response) as (url, requests):
        with pytest.raises(ProviderResponseError) as caught:
            backend(monkeypatch, url, style, max_output_tokens=8192).infer(REQUEST)
    diagnostic = inference_diagnostic(caught.value)
    assert diagnostic == (
        "output_truncated; request_max_output_tokens=8192, input_tokens=1200, "
        f"output_tokens=8192, reasoning_tokens=8180, visible_output_chars={len(private_text)}"
    )
    budget_key = "max_output_tokens" if style == "responses" else "max_completion_tokens"
    assert requests[0][1][budget_key] == 8192
    assert str(caught.value) == "output_truncated"
    assert private_text not in diagnostic


@pytest.mark.parametrize("style", ["chat_completions", "responses"])
@pytest.mark.parametrize("usage", [None, "unit-test-secret", [], {
    "prompt_tokens": True, "completion_tokens": "unit-test-secret",
    "completion_tokens_details": {"reasoning_tokens": -1},
    "input_tokens": {}, "output_tokens": 10**100,
    "output_tokens_details": {"reasoning_tokens": ["unit-test-secret"]},
}])
def test_invalid_usage_never_masks_truncation_or_leaks_text(monkeypatch, style, usage):
    if style == "responses":
        response = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
    else:
        response = {"choices": [{"finish_reason": "length", "message": {"content": None}}]}
    response["usage"] = usage
    client = backend(monkeypatch, "https://example.invalid/v1", style, max_output_tokens=8192)
    monkeypatch.setattr(client.opener, "open", lambda *args, **kwargs: BytesIO(json.dumps(response).encode()))
    with pytest.raises(ProviderResponseError) as caught:
        client.infer(REQUEST)
    assert inference_diagnostic(caught.value) == "output_truncated; request_max_output_tokens=8192"


def test_truncation_statistic_allowlist_ignores_invalid_values_and_unknown_fields():
    error = ProviderResponseError("output_truncated", statistics={
        "request_max_output_tokens": 8192, "input_tokens": True,
        "output_tokens": "unit-test-secret", "reasoning_tokens": -1,
        "visible_output_chars": 0, "provider_body": "unit-test-secret",
    })
    assert inference_diagnostic(error) == (
        "output_truncated; request_max_output_tokens=8192, visible_output_chars=0"
    )
    error.statistics = "unit-test-secret"
    assert inference_diagnostic(error) == "output_truncated"


def test_plugin_exception_subclasses_are_not_trusted():
    class PluginError(ProviderResponseError):
        pass

    assert inference_diagnostic(PluginError("model_refusal")) == "backend_exception"


def test_plain_json_provider_option(monkeypatch):
    client = backend(monkeypatch, "https://example.invalid/v1", structured_output=False)
    assert "response_format" not in client.payload(REQUEST)


@pytest.mark.parametrize("style", ["chat_completions", "responses"])
@pytest.mark.parametrize("truncated", [False, True])
def test_response_metadata_is_logged_without_private_content(monkeypatch, capsys, style, truncated):
    private = "unit-test-secret private text"
    content = "" if truncated else json.dumps(ACTIONS)
    usage = {"reasoning_tokens": 8000 if truncated else 100}
    if style == "responses":
        response = {
            "model": "served-vision-model",
            "status": "incomplete" if truncated else "completed",
            "incomplete_details": {"reason": "max_output_tokens"} if truncated else None,
            "usage": {"input_tokens": 1200, "output_tokens": 8192 if truncated else 200,
                      "output_tokens_details": usage},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": content}]},
                       {"type": "reasoning", "summary": [{"text": private}]}],
        }
    else:
        response = {
            "model": "served-vision-model",
            "choices": [{"finish_reason": "length" if truncated else "stop", "message": {
                "content": content, "reasoning_content": private}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 8192 if truncated else 200,
                      "completion_tokens_details": usage},
        }
    client = backend(monkeypatch, "https://example.invalid/v1", style, max_output_tokens=8192)
    monkeypatch.setattr(client.opener, "open", lambda *args, **kwargs: BytesIO(json.dumps(response).encode()))
    if truncated:
        with pytest.raises(ProviderResponseError):
            client.infer(REQUEST)
    else:
        assert client.infer(REQUEST) == ACTIONS
    captured = capsys.readouterr()
    assert private not in captured.err
    assert REQUEST.instruction not in captured.err
    assert content == "" or content not in captured.err
    diagnostic = json.loads(captured.err.split("[vlm_provider] ", 1)[1])
    assert diagnostic["request_model"] == "test-vision-model"
    assert diagnostic["response_model"] == "served-vision-model"
    assert diagnostic["request_reasoning_effort"] == "low"
    assert diagnostic["request_max_output_tokens"] == 8192
    assert diagnostic["request_token_parameter"] == (
        "max_output_tokens" if style == "responses" else "max_completion_tokens")
    assert diagnostic["output_tokens"] == (8192 if truncated else 200)
    assert diagnostic["reasoning_tokens"] == (8000 if truncated else 100)
    assert diagnostic["visible_output_chars"] == len(content)
    if style == "chat_completions":
        assert diagnostic["finish_reason"] == ("length" if truncated else "stop")
        assert diagnostic["content_is_empty"] is truncated
    else:
        assert diagnostic["response_status"] == ("incomplete" if truncated else "completed")


def test_response_metadata_redacts_sensitive_identifiers_and_unknown_usage(monkeypatch, capsys):
    client = backend(monkeypatch, "https://example.invalid/v1")
    response = {
        "model": "unit-test-secret",
        "choices": [{"finish_reason": "unit-test-secret", "message": {
            "content": None, "reasoning_content": "unit-test-secret"}}],
        "usage": {"completion_tokens": "unit-test-secret",
                  "completion_tokens_details": {"reasoning_tokens": True}},
    }
    client._log_response_diagnostic(response, {"model": "https://private.example/key", "max_completion_tokens": 8192})
    captured = capsys.readouterr()
    assert "unit-test-secret" not in captured.err
    assert "private.example" not in captured.err
    diagnostic = json.loads(captured.err.split("[vlm_provider] ", 1)[1])
    assert diagnostic["request_model"] == diagnostic["response_model"] == "[redacted]"
    assert diagnostic["finish_reason"] == "other"
    assert diagnostic["request_reasoning_effort"] is None
    assert diagnostic["output_tokens"] is diagnostic["reasoning_tokens"] is None
    assert diagnostic["visible_output_chars"] is None
    assert diagnostic["content_is_empty"] is True


def test_missing_model_environment_fails_startup(monkeypatch):

    monkeypatch.delenv("VLM_MODEL", raising=False)
    with pytest.raises(ValueError):
        ProviderBackend(PolicyConfig())
