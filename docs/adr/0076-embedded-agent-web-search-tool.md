---
status: accepted
---

# 内嵌 Agent 加入 WebSearch 工具

美食/探店类脚本生成质量差的一个根因是脚本本身缺少真实菜谱工序（如「过油炸」），导致视频生成模型只能按字面臆造画面。修这个问题需要内嵌 agent 在写脚本前能自主查证菜品的标准制作流程，而不是只依赖项目内已有信息。

ADR 0069 把内嵌 agent 的允许工具定为 `WebFetch` 加入、`WebSearch` 不加入——当时的场景是自定义供应商端点适配，agent 只需要读一个已知 URL 的文档，WebFetch 够用。这次场景不同：agent 需要在没有具体网址的情况下自主查一道菜怎么做，WebFetch 做不到「发现」，只能「读取」。决定把 `WebSearch` 加入 `SessionManager.DEFAULT_ALLOWED_TOOLS`（`server/agent_runtime/session_manager.py`），全局放开——不按 `content_mode` 细分工具白名单，靠 `agent_runtime_profile/.claude/skills/video-workflow/SKILL.ad.md` 的 prompt 指令把实际触发场景约束在「美食/菜谱/烹饪工序」类内容。

`WebSearch` 是 Anthropic 服务端工具，执行方式与 `WebFetch`/`Bash curl` 不同：它不经过本机 sandbox 的 `allowedDomains` 网络策略（ADR 0069 那套「网络已放开到 `*`」的风险接受逻辑不覆盖它），搜索本身在 Anthropic 侧执行，结果作为文本回填进同一轮对话——对最终用户和调用方都是同一次请求内自动完成，不需要额外的会话或人工中转。按 [Anthropic 官方定价](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)，每 1000 次搜索 $10，另加返回内容的正常 token 费用；这笔费用计入该内嵌 agent 所用的同一个 Anthropic 账号。

## Consequences

- 所有 `content_mode`（narration/drama/ad）的内嵌 agent 都获得 WebSearch 能力，不止美食类；非美食场景是否触发完全靠 prompt 指令约束，没有硬性工具级限制——指令写得不到位可能导致意外触发搜索产生额外费用。
- 依赖用户的 Anthropic 账号在 Claude Console 未关闭 Web Search 组织级开关；关闭时相关请求会以 400 失败，而不是静默降级。
- 搜索结果内容以文本形式进入 agent 上下文，与 WebFetch 已有的 prompt injection 暴露面同级（供应商页面能塞进恶意指令的问题本就存在），这里不构成新增的信任边界扩大，只是新增一个同级的内容来源。
- 不修改 sandbox 的 `network` 配置（`allowedDomains`/`allowLocalBinding` 维持 ADR 0069 现状）；`WebSearch` 由 Anthropic 侧执行，本就不受这层沙箱网络策略约束。
