from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings
from app.mcp_tools import safe_json_loads_arguments


SYSTEM_PROMPT = """You are a routing assistant for Cisco BDB MCP tools.
Given the user message, call exactly the MCP tool(s) that best satisfy the request.
Use the tool definitions provided. Prefer a single tool call when one tool is enough.
If required arguments are missing, infer reasonable values from context or use empty objects only when the schema allows."""


async def choose_tool_calls(
    settings: Settings,
    user_content: str,
    openai_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Returns list of {name, arguments dict} from the model."""
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    resp = await client.chat.completions.create(
        model=settings.router_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        tools=openai_tools,
        tool_choice="auto",
        temperature=0.2,
    )
    choice = resp.choices[0]
    message = choice.message
    out: list[dict[str, Any]] = []
    if not message.tool_calls:
        text = (message.content or "").strip()
        raise RuntimeError(
            "The router model did not select a tool. "
            f"Model reply (no tool_calls): {text[:500]}"
        )
    for tc in message.tool_calls:
        fn = tc.function
        args = safe_json_loads_arguments(fn.arguments or "{}")
        out.append({"name": fn.name, "arguments": args})
    return out


async def summarize_tool_results(
    settings: Settings,
    user_content: str,
    tool_results: list[dict[str, Any]],
) -> str:
    """Optional natural-language answer after tools ran."""
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    payload = json.dumps(tool_results, ensure_ascii=False)[:120000]
    resp = await client.chat.completions.create(
        model=settings.router_model,
        messages=[
            {
                "role": "system",
                "content": "Summarize the following tool results for the user in clear, concise language.",
            },
            {"role": "user", "content": f"Request:\n{user_content}\n\nTool results (JSON):\n{payload}"},
        ],
        temperature=0.3,
    )
    return (resp.choices[0].message.content or "").strip()
