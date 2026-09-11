# DEV-PLAN：ad 模式资产设计强制化 + 美食脚本调研

## 读取了哪些文档

- `PRODUCT.md`：确认「角色、场景、道具、商品资产」本就是产品文档里定义的标准生产链路一环（`源文件或商品素材 → 内容分析与项目规划 → 角色/场景/道具/商品资产 → 分集与结构化脚本 → …`），当前 ad 模式把这一步做成可选，属于对文档化流程的偏离，不是新发明一个环节。
- 本次没有新增 PRD/需求类文档；需求范围来自本轮对话内的诊断结论（探店脚本生成质量问题的两个根因）与三项已确认的范围决策：
  1. 适用范围：**全部 ad 模式项目通用规则**（不止美食）
  2. 实现层级：**agent 对话行为 + 前端资产清单向导 UI 都要加**
  3. 调研触发：**仅美食菜谱/工序类内容，默认开启**

## 背景

上一版探店脚本实际生成的视频跨 unit 不一致（厨师、铁锅、场景反复变化，出现无关人物和场景），代码调研定位到两个根因：

1. **ad 模式默认跳过资产设计**：`agent_runtime_profile/CLAUDE.ad.md:96` 把角色/场景/道具资产设计标为可选，建议轻量短片跳过；跳过后脚本正文不会出现 `@[名称]` 引用，执行期没有共享参考图可传给各 unit 的视频生成调用，每个 unit 各自"重新想象"画面。
2. **脚本文本本身缺关键工序**：这条辣子鸡脚本没有写"过油炸"这道工序，导致后续"酥脆外皮"的描述没有铺垫，且模型只能按字面生成"完整辣椒+生鸡肉同炒"。这类需要真实世界工艺知识的内容，当前生成流程里没有调研环节。

## 模块拆解

### 模块 A：ad 模式资产门禁从"可选"变"强制"（后端状态机）

**现状**：
- `lib/workflow_rules.py` 的 `_CONTENT_STEPS["ad"]`（62-77 行）不含 `asset_inventory`，`ad` 项目的这一步在 `lib/workflow_plan.py:145-146` 被 `applicable` 判定直接标 `SKIPPED`。
- `lib/workflow_state.py:481-482` `_source_inventory` 对 `mode == "ad"` 直接短路返回 `not_applicable`，因为 ad 项目没有小说/剧本源文件、没有 `compute_source_revision` 可用的源修订号概念，用的是 `project.json` 顶层 `brief` + `products[]`。
- 其余 8 处 `mode != "ad"` 短路（`workflow_state.py:1179/1325/1408/1411/1414-1423/1424-1437/1438/1457/1588/1606/1727/1751`）都建立在"ad 没有源文件、没有分集规划账本"这个既有假设上。

**架构判断（关键决策，需要你确认）**：**不直接复用现有 ASSET_INVENTORY 的"源文本修订号追踪"机制**。那套机制是为"小说源文件变了要不要重新分析资产"设计的，ad 项目没有对应的源文件revision 概念，硬套会牵连 `compute_source_revision` / `AssetInventorySourceBlocked` 等一整串不适配的分支，返工风险高。

改为新增一个 **ad 专属、更轻量的门禁检查点**（工作暂定名 `AD_ASSET_PLAN`，UI 上仍可沿用"资产分析"这类文案位置，但判定逻辑独立）：脚本生成前必须满足"`characters`/`scenes`/`props` 至少有一条，或用户已在资产清单向导里显式确认『本项目不需要额外资产』"。

**改动点**：
- `lib/workflow_rules.py`：给 `_CONTENT_STEPS["ad"]` 加回这个新 checkpoint，避免与 narration/drama 的 `ASSET_INVENTORY` 语义/流程复用产生耦合。
- `lib/workflow_state.py`：新增 ad 专属判定分支，读 `project["workflow"]["ad_asset_plan"]`（新字段：`{confirmed: bool, confirmed_at, asset_ids: [...]}）`。
- 新增一个落盘函数（`lib/asset_inventory.py` 旁边新文件，或独立模块）+ 对应 MCP 工具（`server/agent_runtime/sdk_tools/`），供 agent 在对话里调用来标记"资产清单已确认"。

**风险**：`workflow_plan.py` 的 `_current_rule_index` 依赖 rules 表里能找到 applicable 的 checkpoint 行，新 checkpoint 必须同步注册在 `workflow_rules.py`，否则会抛 `ValueError`（调研已验证这个坑真实存在）。

### 模块 B：agent 对话行为——创作前主动分析脚本要用到哪些资产

- `agent_runtime_profile/CLAUDE.ad.md:96`：把"资产设计(可选)……轻量短片可跳过"改为强制步骤，加入判断逻辑——agent 分析 `brief`/卖点里提到的人物、场景、道具，逐条列给用户确认是否需要提供参考图/文字描述。
- `agent_runtime_profile/.claude/skills/video-workflow/SKILL.ad.md` 步骤 4：从"依赖用户主动定义"改为 agent 主动触发的必经步骤，明确"资产清单未确认前不得进入步骤 5（生成剧本）"。

### 模块 C：前端资产清单向导 UI

- 现状：`AdInitCanvas.tsx` 是项目创建后的一次性表单（商品名/描述/图片/brief），提交后走纯 REST 接口，不经过 agent；之后切回常规 `OverviewCanvas`，资产管理另有独立路由（`characters`/`scenes`/`props`/`products`，对应 `frontend/src/components/canvas/lorebook/` 下的 `CharactersPage`/`ScenesPage`/`PropsPage`/`ProductsPage` + `*Card.tsx`/`AddCharacterForm.tsx` 等现成 CRUD UI）。
- 改动：`AdInitCanvas` 提交完成后，若 `ad_asset_plan.confirmed` 未标记，插入一个"资产清单确认"步骤/弹窗，复用 `lorebook` 目录现成的卡片列表 + 新增表单模式（`ProductsPage`/`ProductCard` 与 ad 场景最贴近）。清单可以由 agent 对话建议回填，也支持用户手动增删；确认后调用模块 A 新增的接口，写 `ad_asset_plan.confirmed = true`。

### 模块 D：美食脚本调研（仅食物类目默认开启）

- 现状：内嵌 agent 工具白名单 `server/agent_runtime/session_manager.py:319-334`（`DEFAULT_ALLOWED_TOOLS`）里有 `WebFetch`，**没有 `WebSearch`**；`agent_runtime_profile/` 下没有任何联网检索类 skill；`SKILL.ad.md` 生成剧本（步骤 5）之前没有调研钩子，唯一"落笔前收集信息"的环节是步骤 3 卖点起草，信息完全来自项目内已有数据。
- 改动：
  1. `session_manager.py` 的 `DEFAULT_ALLOWED_TOOLS` 加入 `WebSearch`。
  2. `SKILL.ad.md` 步骤 5 前插入条件分支：当 brief/卖点识别为"美食/菜谱/烹饪工序"相关内容时，先用 `WebSearch` 查这道菜的标准制作流程，把关键工序（如"过油炸"）作为素材传给 `generate-script`，要求脚本 unit 必须覆盖完整工序链条。
  3. `CLAUDE.ad.md` 对应段落补充规则说明。

**⚠️ 需要你决策的点**：`DEFAULT_ALLOWED_TOOLS` 目前是 session 级别的全局白名单，调研没有发现按 `content_mode` 细分工具集的现成机制。也就是说"仅美食默认开启"这个范围决策，落到工具权限层面**做不到只让美食类目的 agent 能用 WebSearch**——要么全局放开（所有创作类型的内嵌 agent 都能联网搜索，靠 prompt 指令约束"只在美食场景调用"，不是硬限制），要么这次不碰全局白名单、退化成"agent 尝试用 WebFetch 抓取一个由用户给定/搜索引擎已知的菜谱页面 URL"（改动小很多，但达不到"自主调研"的效果）。这一点需要你在下面选一个。

## 风险点（汇总）

1. 模块 A 改的是核心工作流状态机表，出错会导致所有 ad 项目的 `workflow_plan` 计算异常；需要补充针对"ad 强制资产门禁"的回归测试用例。
2. 新 checkpoint（`AD_ASSET_PLAN`）涉及界面文案，需要按项目规范同步 `CONTEXT.md` 术语定义 + 全语言 i18n key，并过 `test_i18n_consistency.py`。
3. WebSearch 白名单放开的影响面（见模块 D 决策点）。
4. 模块 C 的具体挂载路由（`AdInitCanvas` 之后插入的确切时机/是否弹窗还是内嵌步骤）需要在开工后现场核对 `StudioCanvasRouter.tsx` 的路由跳转逻辑再定稿，本计划先给方向。

## 建议的交付节奏

范围较大，建议按模块拆成 4 个可独立验证的交付单元（A → B → D → C，或 A/B 并行、C/D 并行），完成一个验证一个再进下一个，不一次性全上。

---

## 📋 请确认以下问题后回复"确认，开始开发"：

1. **模块 A 的架构判断**——不复用现有 ASSET_INVENTORY 的源修订号机制，新增一个 ad 专属轻量门禁（`AD_ASSET_PLAN`）——是否同意？
2. **模块 D 的 WebSearch 决策**——全局放开 WebSearch 工具（所有创作类型可用，靠 prompt 约束仅美食场景触发），还是这次先不碰全局白名单、改用更弱的 WebFetch 方案？
3. **交付节奏**——是否同意按 A→B→D→C 分批交付、每批验证后再继续？
