# 任务台账：ad 模式资产设计强制化 + 美食脚本调研

来源：DEV-PLAN.md（2026-09-10 确认）。本文件是进度唯一真相，每个交付单元完成后回写状态，不凭对话记忆判断进度。

## 交付顺序

A → B → D → C，一个周期一个单元，完成即验证、提交，再进下一个。

---

## 单元 A：ad 模式资产门禁从"可选"变"强制"（后端状态机）

- 状态：已完成（2026-09-10）
- 实际方案（比原计划更省改动）：没有新增 `AD_ASSET_PLAN` checkpoint/state 字面量，而是复用现有的
  `"asset_inventory"` step id 与 `"ASSET_INVENTORY"` checkpoint（`lib/workflow_rules.py` 把它加回
  `_CONTENT_STEPS["ad"]`），只是 ad 模式下这个 checkpoint 走一条独立的计算分支
  （`WorkflowStateService._ad_asset_plan_status`，读 `project["workflow"]["ad_asset_plan"]`），完全不
  触碰 narration/drama 用的 `_source_inventory`/`compute_source_revision`。好处：零新增
  `WorkflowStateName`/前端 step 字面量、零新增 `step_*` i18n key，`artifacts["asset_inventory"]` 这个既
  有响应字段直接复用。
- 产出：
  - `lib/workflow_rules.py`：`_CONTENT_STEPS["ad"]` 加回 `"asset_inventory"`
  - `lib/workflow_state.py`：新增 `WorkflowActionType.CONFIRM_AD_ASSET_PLAN`、
    `_ad_asset_plan_status` 辅助方法、`_SharedWorkflowFacts.ad_asset_plan` 字段、`_get_status` 里
    SELLING_POINTS 之后、FINAL_SCRIPT 之前插入的门禁判断
  - `lib/asset_inventory.py`：新增 `confirm_ad_asset_plan()` + `AdAssetPlanConfirmation`（一次性确认，
    无 source-revision 冲突检测；未登记任何角色/场景/道具时必须传 `no_additional_assets=true` 才能确认）
  - `server/tool_runtime.py`：新增 `ConfirmAdAssetPlanRequest/Result` + `confirm_ad_asset_plan` 编排函数
  - `server/agent_runtime/sdk_tools/asset_inventory.py` + `__init__.py`：注册内嵌 agent 可调用的
    `confirm_ad_asset_plan` MCP 工具（含 `MIGRATION_BLOCKED_TOOL_IDS` 登记）
  - `server/remote_mcp.py`：注册对外 MCP 的 `confirm_ad_asset_plan` 工具
  - `agent_runtime_profile/.claude/references/workflow-plan.md`：补充 `confirm_ad_asset_plan` 动作行
  - 前端：`frontend/src/types/workflow.ts` 的 `WORKFLOW_ACTION_TYPES` 加入该动作；
    `frontend/src/i18n/{zh,en,vi}/workflow.ts` 补 `action_confirm_ad_asset_plan`；
    `frontend/src/i18n/{zh,en,vi}/dashboard.ts` 补 `tool_name_confirm_ad_asset_plan`
  - 测试：`tests/integration/lib/test_workflow_state.py`（`_make_project` 加
    `confirm_ad_asset_plan` 开关 + 4 个新/改测试）、`tests/integration/lib/test_project_migration_blocking.py`、
    `tests/integration/lib/project_migrations/test_project_migration_v7_v8.py` 三处既有 ad 项目
    fixture 补上确认标记，避免这次改动误伤既有回归覆盖
- 验收标准（已核实）：
  - 未确认资产清单的 ad 项目，`workflow_state` 返回 `state="ASSET_INVENTORY"`，
    `next_action.type="confirm_ad_asset_plan"`，`workflow_plan` 不抛错 ✅
  - 确认后门禁放行，直达 `FINAL_SCRIPT`，后续状态机路径不变 ✅
  - `uv run python -m pytest -n 4 --dist loadfile`：12036 passed（全量，含新增用例）✅
  - `uv run ruff check . / ruff format . / basedpyright --warnings / lint-imports / deptry`：全部无问题 ✅
  - `(cd frontend && pnpm check)`：183 test files / 2150 tests 全过 ✅
  - `uv run python scripts/audit_tests.py --check`：0 处违规 ✅
  - `uv run python scripts/lint_agent_runtime_profile.py`：通过 ✅
- 已知限制（记录，不在本单元内处理）：`ad_asset_plan` 一旦确认不会因为后续新增角色/场景/道具而失效，
  没有 narration/drama 那种 source-revision 漂移检测；如果需要"资产变了要重新确认"，需要另开工作量评估。
- 依赖：无

## 单元 B：agent 对话行为——创作前主动分析所需资产

- 状态：已完成（2026-09-10）
- 产出：
  - `agent_runtime_profile/CLAUDE.ad.md`：「资产设计（可选）」改写为「资产设计（必经）」，加入具体判断逻辑——
    分析 brief/卖点里会反复出现的角色/场景/道具，逐条确认；确实不需要时要求显式调用
    `confirm_ad_asset_plan({"no_additional_assets": true})`
  - `agent_runtime_profile/.claude/skills/video-workflow/SKILL.ad.md`：
    - `next_action.type` 路由表加入 `confirm_ad_asset_plan → 步骤 4`
    - 步骤 4 拆成两个分支（`confirm_ad_asset_plan` 必经确认 / `generate_asset_sheets` 出图），明确
      "这一步不确认，计划不会推进到步骤 5"
- 验收标准（已核实）：
  - `uv run python -m pytest tests/unit/lib/test_video_workflow_prompt.py tests/integration/agent_runtime_profile/`：55 passed ✅
  - `uv run python scripts/lint_agent_runtime_profile.py`：通过 ✅
  - `uv run ruff check .`：通过 ✅
  - `uv run python -m pytest -n 4 --dist loadfile`：12037 passed，无回归 ✅
- 依赖：单元 A（MCP 工具已在单元 A 落地）

## 单元 D：美食脚本调研（仅食物类目默认开启）

- 状态：待开始
- 产出：
  - `server/agent_runtime/session_manager.py` `DEFAULT_ALLOWED_TOOLS` 加入 `WebSearch`
  - `agent_runtime_profile/.claude/skills/video-workflow/SKILL.ad.md` 步骤 5 前插入美食类目调研分支
  - `agent_runtime_profile/CLAUDE.ad.md` 补充规则说明
- 验收标准：非美食类目行为不变；美食类目生成剧本前有调研动作的文档依据
- 依赖：无（可与 B 并行，但按序做）

## 单元 C：前端资产清单向导 UI

- 状态：待开始
- 产出：
  - `AdInitCanvas` 提交后，若 `ad_asset_plan.confirmed` 未标记，插入资产清单确认步骤
  - 复用 `frontend/src/components/canvas/lorebook/` 现成卡片列表 + 新增表单模式
  - 调用单元 A 新增的确认接口
- 验收标准：`(cd frontend && pnpm check)` 通过；新增 i18n key 全语言同步；手动/自动化验证走一遍创建项目→资产清单确认流程
- 依赖：单元 A（需要接口已存在）

---

## 硬停止记录

（如遇同一问题连续 2 次未修好、或撞上 CLAUDE.md 第四节"必须停下"清单，记录在此并停下问用户）

无
