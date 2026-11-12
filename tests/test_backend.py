import asyncio
import json

import httpx
from test_runtime import obs

from operator_vlm_action_policy.backend import VLMClient
from operator_vlm_action_policy.contracts import PolicyConfig


def test_existing_service_contract_and_physical_schema_validation():
    async def scenario():
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            assert request.url.path == "/v1/infer:wait"
            return httpx.Response(
                200,
                json={
                    "execution_status": "succeeded",
                    "output": {
                        "json": {
                            "action_space": "eef_delta",
                            "frame": "world",
                            "actions": [[0.01, 0, 0, 0, 0, 0, -1]],
                        }
                    },
                },
            )

        cfg = PolicyConfig(instruction="pick")
        client = httpx.AsyncClient(base_url=cfg.service_url, transport=httpx.MockTransport(handler))
        backend = VLMClient(cfg, client)
        result, _ = await backend.infer(obs(), "pick", [], "act:test")
        assert result.actions[0][0] == 0.01
        request = requests[0]
        assert request["context"] == {"mode": "stateless"}
        assert (
            request["response_format"]["schema"]["properties"]["action_space"]["const"]
            == "eef_delta"
        )
        assert request["messages"][1]["content"][1]["source"]["type"] == "inline_base64"
        assert "eef_x_m" in request["messages"][1]["content"][0]["text"]
        await backend.close()

    asyncio.run(scenario())
