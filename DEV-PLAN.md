# DEV-PLAN：参考生视频「一键成片」

## 读取了哪些文档

无产品文档文件（`ls *.md` 未见 PRD/需求类文件）。需求来自本次对话的澄清结果，关键决策：

- 产物：渲染完的最终 mp4 存进项目资产库，前端可在线预览 + 下载（不是只给一个裸下载链接）。
- 分辨率不一致：自动统一到 episode 内第一个 unit 的尺寸（对齐现有 `compose-video` skill 的既有做法：scale + pad，不报错、不裁切）。
- 音频范围：第一版只拼「视频 + 各 unit 的旁白配音」，不支持混入背景音乐（BGM 留到后续版本）。
- 与现有「导出剪映草稿」并存，两个按钮语义不同：「一键成片」= 自动渲染出一条可直接看的 mp4；「导出剪映草稿」= 给需要精修的用户导出可编辑工程。

## 现状核实（已确认，不重复调研）

- ffmpeg 已在生产镜像内（`Dockerfile` apt-get 安装），`lib/audio_utils.py`、`lib/thumbnail.py` 已有 `shutil.which` 探测 + 调用范式可参照。
- `agent_runtime_profile/.claude/skills/compose-video/scripts/compose_video.py` 已实现「统一分辨率（`normalize_clip`）→ 按 `transition_to_next` 分组用 xfade/acrossfade 拼接（`concatenate_with_transitions`）→ 混音（`add_background_music`）」，但只认剧本 `scenes[]`，显式拒绝 `video_units[]`。
- `ReferenceVideoUnit.transition_to_next`（`cut`/`fade`/`dissolve`，`lib/script_models.py`）已存在，目前只被 `jianying_draft_service.py` 消费导出到剪映草稿，没有任何真实渲染路径消费它。
- 每个 unit 的 `generated_assets.narration_audio` 是唯一音轨来源（`audio/segment_{id}.wav`），无独立 BGM 概念；prompt 里明确禁止视频模型自产 BGM，画面音轨可忽略或按 unit 决定是否保留。

## 模块拆解

1. **`lib/video_compose.py`（新增，共享核心）**
   把 `compose_video.py` 里 `normalize_clip` / `concatenate_final` / `concatenate_with_transitions` 这几个 ffmpeg 封装函数下沉到这里，去掉对 `scenes[]` 结构的依赖，改为接受通用片段列表：`ComposeSegment(video_path, narration_audio_path: str | None, transition_to_next: TransitionType)`。`compose_video.py` 改为调用这个共享库，避免逻辑分叉出两份实现。
   - 音画对齐策略（需在实现前定稿，默认按此写死，不做成可配置项）：以每段视频片段的时长为主轴；该段旁白比视频短则静音补齐，比视频长则截断旁白——不允许旁白反过来拉长总时长，避免最终成片时长失控、也避免和「相邻片段 xfade 转场」的时间轴对不上。
   - xfade/acrossfade 转场会让总时长略短于「各片段时长之和」（转场固有机制），成片信息里如实展示实际总时长，不做误导性文案。

2. **合成任务纳入现有 GenerationWorker 任务体系**
   新增任务 kind `reference_video_compose`（按 episode 粒度，不是按 unit）。
   - 准入：该 episode 下所有 `video_units` 必须已有 `generated_assets.video_clip`；只要有一个缺失就整体拒绝入队，返回缺失的 unit_id 列表（沿用现有批量生成「全有或全无」的既有规范，不做部分跳过）。
   - 容量：给这个任务 kind 一个独立、较小的并发上限（建议同时 1 个，ffmpeg 编码是 CPU 密集操作，不能套用图片/视频生成任务的并发档位）。
   - 执行：调用 `lib/video_compose.py`，产物写到 `presentations/episode_{episode}/final_cut.mp4`（`lib/resource_paths.py` 新增一个 pattern），完成后登记进项目 artifact manifest（关联资源 id 为该 episode，不是某个 unit，便于后续删除/GC 追踪，也便于「脚本改动使旧成片失效」时能找到并清理）。
   - 完成/失败经 `ProjectEventService` 广播，前端复用现有 SSE revision 刷新机制。

3. **新增 API**（`server/routers/reference_videos.py`）
   - `POST /projects/{project_name}/reference-videos/episodes/{episode}/compose`：校验 + 入队，返回任务信息。
   - 成片读取复用现有通用文件接口（`API.getFileUrl`），不新增下载端点。

4. **前端**
   - `EpisodeHeader.tsx`（或 `ReferenceVideoCanvas.tsx` 顶部工具栏，紧邻「批量生成视频」）新增「一键成片」按钮；未全部生成成片时禁用，title 提示缺几个。
   - 提交后按现有「入队动作层」规范走（`frontend/src/actions/generation.ts` 新增一个动作函数），占用态接入 tasks-store。
   - 完成后展示区：一个「成片预览」卡片（复用 `PresentationPlayer` 在线播放 + 下载按钮），放在 `EpisodeHeader` 附近或视频单元列表上方。
   - i18n：三语新增按钮文案、缺成片提示、任务状态文案。

## Schema / 数据结构变化

- 不改 `video_units` 结构，不新增字段。
- `lib/resource_paths.py` 新增一个 `final_cut` pattern（episode 粒度）。
- artifact manifest 新增一类「episode 级 compose 产物」的登记方式（复用现有 manifest 机制，非新表）。

## 路由清单

- `POST /api/v1/projects/{project_name}/reference-videos/episodes/{episode}/compose`（新增）
- 成片读取：复用既有 `GET /api/v1/projects/{project_name}/files/...`

## 风险点

- **CPU 资源**：容器目前单进程跑所有生成 worker，ffmpeg 编码若不设独立并发上限，可能和正在跑的 AI 生成任务抢 CPU，需要显式限流（见上）。
- **音画对齐策略是产品判断，不是纯技术细节**：上面「以视频为主轴、旁白截断/补静音」是我给的默认方案，如果和你预期不符（比如你更希望旁白优先、视频循环补齐），需要在开发前告诉我，写死之后不做成用户可调选项（第一版）。
- **分辨率对齐第一个片段**：如果 episode 第一个 unit 恰好是全片里分辨率最低的供应商生成的，其余片段会被下采样对齐，整体清晰度会被拉低到最低那个——这是你已确认接受的默认行为，仅在此处再次提示，避免上线后被当成 bug 反馈。
- **不改动 `compose-video` skill 现有行为**：下沉共享逻辑时只做「抽取函数」，不改变 `compose_video.py` 对 `scenes[]` 剧本的既有行为和其自身测试。
- **narration_audio 缺失的 unit**：允许存在（旁白交付方式为 post_production 时本来就没有 TTS 音频），此时该片段只保留原始视频自带音轨（大概率是静音，因为生成提示词已要求模型不产生背景音）。

---

📋 计划已生成，请确认：上面「音画对齐策略」（视频为主轴、旁白截断/补静音）和「合成任务并发上限设为 1」这两个技术判断是否认可；确认后我按此计划开始开发，完成后跑 `CONTRIBUTING.md` 里的全量测试闸门再出 DEV-REPORT.md。回复"确认，开始开发"后我才继续。
