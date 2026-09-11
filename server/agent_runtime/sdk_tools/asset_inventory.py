"""SDK MCP tool for committing an asset-inventory completion fact."""

from __future__ import annotations

import asyncio
from typing import Any

from claude_agent_sdk import tool

from lib.asset_inventory import complete_asset_inventory as complete_asset_inventory_service
from lib.asset_inventory import confirm_ad_asset_plan as confirm_ad_asset_plan_service
from server.media_tools.context import ToolContext, tool_outcome_response, tool_services
from server.tool_runtime import (
    CompleteAssetInventoryRequest,
    ConfirmAdAssetPlanRequest,
    ToolOutcome,
    ToolProblem,
    ToolRequest,
    complete_asset_inventory,
    confirm_ad_asset_plan,
)


def complete_asset_inventory_tool(ctx: ToolContext):
    @tool(
        "complete_asset_inventory",
        "原子提交分析提取出的资产和资产清单事实。工具会在项目锁内重算 source revision；"
        "与 expected_source_revision 不一致时整笔拒绝，不修改 project.json。空角色/场景/道具清单是合法结果。",
        {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["all", "files"]},
                        "files": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["kind"],
                },
                "expected_source_revision": {"type": "string"},
                "entries": {
                    "type": "object",
                    "description": (
                        "本次新增资产：{characters/scenes/props: {名称: {description, voice_style?}}}；"
                        "角色可带 derivatives: {衍生名: {description}} 登记本体之外的另一套外观"
                    ),
                },
            },
            "required": ["scope", "expected_source_revision"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            request = CompleteAssetInventoryRequest.model_validate(args)
        except ValueError as exc:
            outcome = ToolOutcome(problem=ToolProblem("invalid_request", str(exc)))
        else:
            outcome = await complete_asset_inventory(
                ToolRequest(request),
                ctx.scope,
                ctx.caller,
                tool_services(ctx),
                run_sync=asyncio.to_thread,
                complete=complete_asset_inventory_service,
            )
        return tool_outcome_response("asset_inventory", outcome)

    return _handler


def confirm_ad_asset_plan_tool(ctx: ToolContext):
    @tool(
        "confirm_ad_asset_plan",
        "确认广告/带货类项目的角色、场景、道具资产清单已经处理完毕，脚本生成前必须调用一次。"
        "该项目没有源文件修订号，不做冲突检测，只是一次性标记：要么已登记 characters/scenes/props，"
        "要么显式传 no_additional_assets=true 确认本项目不需要额外资产。",
        {
            "type": "object",
            "properties": {
                "no_additional_assets": {
                    "type": "boolean",
                    "description": "本项目除商品自身外不需要任何角色/场景/道具资产时传 true；默认 false。",
                },
            },
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            request = ConfirmAdAssetPlanRequest.model_validate(args)
        except ValueError as exc:
            outcome = ToolOutcome(problem=ToolProblem("invalid_request", str(exc)))
        else:
            outcome = await confirm_ad_asset_plan(
                ToolRequest(request),
                ctx.scope,
                ctx.caller,
                tool_services(ctx),
                run_sync=asyncio.to_thread,
                confirm=confirm_ad_asset_plan_service,
            )
        return tool_outcome_response("ad_asset_plan", outcome)

    return _handler


__all__ = ["complete_asset_inventory_tool", "confirm_ad_asset_plan_tool"]
