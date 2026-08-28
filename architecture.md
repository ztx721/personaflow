# PersonaFlow — 架构设计文档

> **一句话定位**：Stateful AI Character Conversation Engine — 通过 Web 与虚拟角色进行 1v1 文字聊天的技术面试 Demo。
>
> **本文档目标**：让一位开发者读完即可开始实现。每一个架构决定都附 **why**。
>
> **优先级**：简单清晰 > 正确演示 > 完备功能。这是 Demo，不是企业级系统。

---

## 0. 快速导航

| 想了解什么 | 去哪里 |
|---|---|
| 整个系统长什么样 | §2 架构总览 |
| 消息发出去后发生什么 | §8 数据流 |
| 先建什么、后建什么 | §11 开发 Phase |
| 为什么这么做、不这么做 | §12 技术决策、§13 不做的事 |
| 哪里还没想清楚 | §14 风险与待定决策 |
| 数据表长什么样 | §4 领域模型 |

---

## 1. 需求分析

### 1.1 核心能力（8 项，来自项目定义）

| # | 能力 | 需求拆解 | 对应组件 |
|---|---|---|---|
| 1 | Persona consistency | 角色身份、性格、说话方式长期一致，不因对话内容"出戏" | 人设配置 + Prompt Builder |
| 2 | Conversation state | 维护情绪、关系、话题、上下文状态，且必须可持久化 | ConversationState |
| 3 | Memory | 记住用户事实与角色产生的重要事实，后续对话能引用 | MemoryService + MemoryFact |
| 4 | Story Engine | 根据上下文平滑引导用户进入预定义剧情，而非强制跳转 | StoryEngine + Story 配置 |
| 5 | Structured LLM Output | LLM 输出必须经 Pydantic schema 校验才能进入系统 | LLM 层 + core/schemas.py |
| 6 | Multimodal Action | 满足剧情与用户意图条件后，发送**预定义**图片素材 | AssetService + catalog |
| 7 | Admin Debug | 可观察角色状态、剧情节点、planner 决策、消息 | 调试 API + 调试页 |
| 8 | Eval | 测试人格一致性、情绪响应、剧情推进、图片触发 | pytest eval 套件 |

### 1.2 用户与场景

- **主要用户**：面试官 / Demo 观众。典型演示路径：选角色 → 自由对话 → 触发剧情 → 剧情中角色引导话题 → 出现图片素材 → 打开 Admin 面板看状态和决策 → 跑一次 Eval。
- **次要用户**：开发者自己（用 Admin 面板调试）。

### 1.3 范围边界

**技术栈（已定）**：Python 3.12 / FastAPI / SQLAlchemy / Pydantic / pytest；React + TypeScript + Vite + Tailwind；SQLite（本地开发，SQLAlchemy 保证 PostgreSQL 兼容）；Docker + Docker Compose。

**明确不做**（详见 §13）：登录注册、支付、Redis/Kafka、K8s/微服务、向量库、语音、实时图片生成。

---

## 2. 架构总览

### 2.1 分层

```
┌─────────────────────────────────────────────────────────┐
│  Frontend (React + TS + Tailwind)                       │
│  ChatPage / AdminPage / (EvalPage 可选)                 │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP (REST JSON)
┌──────────────────────────▼──────────────────────────────┐
│  API 层 (FastAPI routers)      —— 薄，只做 HTTP ↔ Service │
│  sessions / roles / stories / admin / eval              │
└──────────────────────────┬──────────────────────────────┘
┌──────────────────────────▼──────────────────────────────┐
│  Core 层（无 FastAPI 依赖，纯 Python，可单测）            │
│  ConversationService（编排）                             │
│    ├─ ResponsePlanner  → LLM#1，输出 PlannerOutput       │
│    ├─ RoleGenerator    → LLM#2，输出纯文本               │
│    ├─ StoryEngine      → 剧情状态与迁移校验（不碰 LLM）    │
│    ├─ MemoryService    → 事实存取（关键词检索，无向量库）   │
│    ├─ AssetService     → asset_tag → URL                 │
│    ├─ PromptBuilder    → 模块化组装 prompt                │
│    └─ rules.py         → 纯函数：应用/夹取/校验提议        │
│  LLM 层（client + structured + mock）                    │
└──────────────────────────┬──────────────────────────────┘
                           │ SQLAlchemy
┌──────────────────────────▼──────────────────────────────┐
│  SQLite（本地）/ PostgreSQL（兼容目标）                   │
└─────────────────────────────────────────────────────────┘

配置源（不建表，只存在于磁盘）：
  config/personas/*.yaml   —— 角色人设
  config/stories/*.yaml    —— 剧情
  config/assets/catalog.yaml —— 素材目录
```

### 2.2 组件职责（单一职责）

| 组件 | 职责 | 不做什么 |
|---|---|---|
| **ConversationService** | 编排一次 turn 的全部流程；把 planner 的"提议"经规则层变成"应用"；负责持久化 | 不直接写 prompt，不直接调 LLM |
| **ResponsePlanner** | LLM#1：读上下文，产出"下一步行为计划"（结构化） | 不写最终台词，不直接改任何状态 |
| **RoleGenerator** | LLM#2：纯自然语言生成（台词） | 不做任何决策 |
| **StoryEngine** | 维护剧情节点状态；校验迁移合法性；执行节点副作用 | 不调 LLM |
| **MemoryService** | 记忆的写入与检索 | 不调 LLM |
| **AssetService** | tag→URL 解析、合法性校验 | 不负责生成图片 |
| **PromptBuilder** | 从人设/状态/剧情/记忆/对话历史拼装模块化 prompt | 不执行 LLM |
| **LLMClient / structured** | 供应商抽象、结构化输出、Pydantic 校验、重试 | 不包含业务 |
| **rules.py** | 纯函数：情绪/关系/话题/记忆/剧情的应用规则 | 无副作用 |

### 2.3 两条贯穿全系统的核心原则

**原则 A：LLM 只提议，代码才裁决（LLM proposes, code disposes）。**

LLM 的输出（planner 的结构化提议）永远是一份*提案*，不是*指令*。真正的状态变更必须经过规则层校验：

- 剧情迁移：planner 说"去 node X"，StoryEngine 校验 X 是否在当前节点的合法出边上，才迁移；
- 图片：planner 返回 `asset_tag`，AssetService 校验 tag 存在且（若有剧情限制）属于当前节点允许集，才解析 URL；
- 情绪/关系：proposal 经过枚举校验、强度阻尼、范围夹取后才写入。

> **why**：保证剧情图、状态不变量不被模型带偏；让 Admin 面板和 Eval 能看到"哪些提议被采纳、哪些被拒绝"，这让系统可解释、可测试。

**原则 B：规划与生成分离（Planner / Generator 两次 LLM 调用）。**

行为决策（情绪、剧情、记忆、图片）和台词生成是两个独立调用，分别有自己的 prompt 与 schema。

> **why**：行为决策可以与自然语言质量解耦 —— 即使台词写得一般，剧情/图片/状态控制依然正确；Eval 可以分别断言 planner 决策和台词质量；离线用 MockLLM 可以只测决策逻辑。代价是延迟和成本翻倍，对 Demo 可接受（见 §14 R2）。

---

## 3. 推荐目录结构

```
PersonaFlow/
├─ architecture.md
├─ README.md                    # 运行指南 + Demo 脚本
├─ pyproject.toml               # 后端依赖 + pytest 配置
├─ docker-compose.yml           # dev: backend + frontend
├─ .env.example                 # 所有环境变量的样板
├─ .gitignore                   # 排除 data/、node_modules/、.venv/ 等
│
├─ backend/
│  ├─ Dockerfile
│  ├─ app/
│  │  ├─ main.py                # FastAPI 应用工厂，挂路由 + CORS + 静态素材
│  │  ├─ config.py              # pydantic-settings，读环境变量
│  │  ├─ config_loader.py       # 启动时加载 personas/stories/assets YAML 并校验
│  │  ├─ db.py                  # engine + SessionLocal + Base
│  │  ├─ api/                   # ★ 薄路由层，不做业务
│  │  │  ├─ sessions.py         #   POST/GET sessions, POST messages
│  │  │  ├─ roles.py            #   GET /roles, GET /stories
│  │  │  ├─ admin.py            #   GET session debug, GET turn log
│  │  │  └─ eval.py             #   POST /eval/run（可选）
│  │  ├─ core/                  # ★ 核心逻辑，无 FastAPI 依赖，可单测
│  │  │  ├─ schemas.py          #   Pydantic：领域模型 + LLM 输出 schema（唯一事实源）
│  │  │  ├─ conversation_service.py
│  │  │  ├─ response_planner.py
│  │  │  ├─ role_generator.py
│  │  │  ├─ story_engine.py
│  │  │  ├─ memory_service.py
│  │  │  ├─ asset_service.py
│  │  │  ├─ prompt_builder.py
│  │  │  └─ rules.py            #   纯函数：情绪阻尼、关系夹取、记忆去重……
│  │  ├─ llm/
│  │  │  ├─ client.py           #   供应商抽象（Anthropic / 可扩展）
│  │  │  ├─ structured.py       #   结构化输出提取 + Pydantic 校验 + 重试/兜底
│  │  │  └─ mock.py             #   MockLLM：离线开发与测试用确定性实现
│  │  └─ models/                # SQLAlchemy ORM（表结构见 §4）
│  │     ├─ session.py  message.py  state.py
│  │     ├─ story.py    memory.py   turn_log.py
│  ├─ config/                   # ★ 配置与代码分离
│  │  ├─ personas/miko_cafe.yaml
│  │  ├─ stories/old_books_first_day.yaml
│  │  └─ assets/catalog.yaml
│  ├─ assets/                   # ★ 预定义静态图片素材（FastAPI 静态托管）
│  │  └─ miko_cafe/*.png
│  ├─ data/                     # SQLite 数据文件（gitignore，Docker volume）
│  └─ tests/
│     ├─ unit/                  #   单测：rules / prompt_builder / story_engine…
│     ├─ integration/           #   集成：一次完整 turn 的状态流转
│     └─ eval/                  #   Eval 用例 + runner（§10.4）
│
└─ frontend/
   ├─ Dockerfile                # 或 dev 模式由 vite 服务
   ├─ package.json / vite.config.ts / tsconfig.json
   ├─ tailwind.config.js / index.html
   └─ src/
      ├─ main.tsx / App.tsx
      ├─ api/client.ts          # 封装后端 REST
      ├─ types.ts               # 手工维护，与后端 schema 对齐
      ├─ pages/ChatPage.tsx
      ├─ pages/AdminPage.tsx
      └─ components/            # ChatWindow / MessageBubble /
                                # StatePanel / StoryPanel / TurnLog
```

**分层规则**：
- `api/` 只做参数校验 + 调 service + 组装响应，**不 import core 之外的业务逻辑**；
- `core/` 不 import `fastapi`，保证 pytest 直接测；
- 所有业务常量（情绪枚举、夹取边界、窗口大小）进 `core/schemas.py` 或 config，不散落各处。

---

## 4. 核心领域模型（数据表）

### 4.1 实体概览

> 命名说明：实现中以 `Conversation` / `conversations` 为统一命名（与 `/api/conversations` 一致），与文档里的 "session" 指同一概念。

| 实体 | 存哪里 | 说明 |
|---|---|---|
| Role（人设定义） | **config YAML**，不建表 | 定义是静态的，配置是唯一事实源 |
| Story（剧情定义） | **config YAML**，不建表 | 同上 |
| Asset（素材目录） | **config YAML**，不建表 | 同上 |
| Session | DB 表 `sessions` | 一次与某个角色的对话 |
| ConversationState | DB 表 `conversation_states` | 情绪 / 关系 / 话题 |
| StoryState | DB 表 `story_states` | 剧情运行时状态 |
| Message | DB 表 `messages` | 用户与角色消息 |
| MemoryFact | DB 表 `memory_facts` | 长期事实 |
| TurnLog | DB 表 `turn_logs` | 每次 turn 的决策快照（Admin / Eval 用） |

> **why 定义不建表**：人设/剧情是静态代码资产，改动靠 git；只有运行时状态需要 DB。避免"定义存在两份（配置 + 表）"的双源真相问题。

### 4.2 表结构

> 所有 JSON 字段用 SQLAlchemy `JSON` 类型 —— SQLite 落为 TEXT、PostgreSQL 落为 JSONB，**保持方言兼容**（技术决策 D6）。
> 所有主键用 `UUID`（`uuid4` 的字符串）—— 由代码生成，避免依赖数据库自增方言差异。

**sessions**
| 列 | 类型 | 说明 |
|---|---|---|
| id | str(uuid) PK | |
| role_id | str | 对应 persona 配置文件名 |
| story_id | str nullable | 绑定的剧情；可为空（自由对话） |
| status | str | `active`（MVP 足够） |
| created_at | datetime | |

**conversation_states**（1:1 session）
| 列 | 类型 | 说明 |
|---|---|---|
| session_id | str PK/FK | |
| emotion | str nullable | 情绪枚举值，见 §5.1 |
| emotion_intensity | int | 0–100 |
| relationship | JSON | `{axis: 0-100}`，轴由人设配置定义 |
| current_topic | str nullable | 当前话题 |
| updated_at | datetime | |

**story_states**（1:1 session，存在即剧情已激活）
| 列 | 类型 | 说明 |
|---|---|---|
| session_id | str PK/FK | |
| story_id | str | |
| current_node_id | str | |
| node_vars | JSON | 节点级变量（如已触发过的 flag），暂可空 |
| visited | JSON (list) | 已访问节点 id，用于幂等 |
| status | str | `active` / `completed` |
| updated_at | datetime | |

**messages**
| 列 | 类型 | 说明 |
|---|---|---|
| id | str(uuid) PK | |
| session_id | str FK | |
| sender | str | `user` / `character` |
| content | Text | |
| asset_tag | str nullable | 角色消息携带的图片 tag（若触发） |
| created_at | datetime | |

**memory_facts**
| 列 | 类型 | 说明 |
|---|---|---|
| id | str(uuid) PK | |
| session_id | str FK | 记忆以 session 为界（MVP，见 D11） |
| fact_type | str | `user_fact` / `character_fact` |
| content | Text | 一条事实的自然语言表述 |
| importance | int | 1–5 |
| created_at / last_used_at | datetime | last_used 用于时效排序 |

**turn_logs**（决策审计，Admin/Eval 的核心数据）
| 列 | 类型 | 说明 |
|---|---|---|
| id | str(uuid) PK | |
| session_id | str FK | |
| user_message_id | str FK | 对应触发这次 turn 的用户消息 |
| planner_output | JSON | LLM#1 的**原始**输出（校验通过与否都存） |
| applied | JSON | 规则层最终应用的决策摘要 |
| validation_errors | JSON | 结构化校验/规则拒绝的记录 |
| created_at | datetime | |

### 4.3 领域对象（Pydantic，`core/schemas.py`）

```python
# ---- 情绪枚举（全局统一，扩展只需加成员）----
class Emotion(str, Enum):
    neutral = "neutral"
    happy = "happy"
    excited = "excited"
    calm = "calm"
    sad = "sad"
    angry = "angry"
    worried = "worried"
    shy = "shy"
    embarrassed = "embarrassed"
    grateful = "grateful"

# ---- ConversationState 运行时对象（与表映射）----
class ConversationState(BaseModel):
    session_id: str
    role_id: str
    emotion: Emotion | None = None
    emotion_intensity: int = 50
    relationship: dict[str, int]        # 轴与初值来自人设配置
    current_topic: str | None = None
    updated_at: datetime
```

---

## 5. ConversationState

### 5.1 定义与设计选择

状态 = 一组**小而明确**的标量 + 窗口 + 指针：

```python
class ConversationState(BaseModel):
    session_id: str
    role_id: str
    emotion: Emotion | None            # 当前情绪（枚举）
    emotion_intensity: int             # 0-100，情绪强度
    relationship: dict[str, int]       # 关系轴 -> 数值（轴由人设定义）
    current_topic: str | None          # 当前话题（一句话，planner 提议更新）
```

**不放进状态的东西**（各有归属）：
- 完整对话历史 → `messages` 表，prompt 只取最近 N 条（`CONTEXT_WINDOW`，默认 10）；
- 剧情位置 → `StoryState`（StoryEngine 专属）；
- 长期事实 → `MemoryFact`（MemoryService 专属）；
- planner 决策 → `TurnLog`。

> **why**：状态与历史、剧情、记忆分离，各组件单一职责（§2.2）；避免一个臃肿字典被所有人改。

### 5.2 设计选择说明

| 选择 | 备选 | why |
|---|---|---|
| 分类情绪 + 强度（枚举 + 0-100） | 维度模型（valence/arousal/PAD） | 分类直观、Admin 面板好渲染、Eval 好断言；对 Demo 足够。局限见 §14 R3 |
| 关系 = 一组标量轴 | 单个熟悉度数字 / 任意 dict | 固定轴（`trust`/`affection`/`respect`，可在人设配置里增删）让状态可解释、Eval 可断言，又不写死死板 |
| 持久化到 DB，非内存 | 内存态 + 定时落盘（Redis 已排除） | 原则 #9；重启不丢；Admin 直接观察；测试可加载任意初始状态 |
| 每请求一个 DB session | 长连接全局单例 | 简单 + 避免 SQLite 写锁堆积 |

### 5.3 更新规则（`rules.py` 纯函数，全部可单测）

- **情绪**：proposal 为空 → 保持；非空 → 枚举校验，非法则拒绝（记入 TurnLog.validation_errors）；强度做**阻尼**：`new = old + clamp(proposed - old, -20, +20)`，再夹取到 `[0,100]`。
- **关系**：`relationship[axis] += delta` 后夹取 `[0,100]`；未知轴忽略并记日志。
- **话题**：proposal 非空且长度 ≤ 64 才更新，否则忽略。

---

## 6. Role Persona 配置格式（YAML）

**位置**：`backend/config/personas/<role_id>.yaml`。每个文件定义一个角色，**加角色 = 加一个数据文件，不改代码**。

```yaml
role_id: miko_cafe
display_name: 林小满
avatar: /assets/miko_cafe/avatar.png
description: 旧书店老板娘，温柔而有点害羞。   # 角色选择卡片用

# ---- 人设核心：这些字段会映射为 prompt 模块（§9）----
persona:
  identity: |
    24 岁，独自经营着一家开在巷子里的旧书店"纸页间"。
    前两年回家接手了父亲的书店，正在学着把这家店撑起来。
  personality:
    - 温柔、慢热、有点认生
    - 对书有近乎执拗的认真
    - 遇到夸奖会害羞，容易脸红
  speech_style: |
    说话轻声，语速不快，常带语气词（"唔"、"其实"）。
    不装熟，会用敬语，但熟了之后会自然随意一些。
  likes: [雨天, 旧书的味道, 读者认真翻书的样子]
  dislikes: [书被折角, 大声喧哗]
  goals: [让这家书店继续开下去, 把喜欢的书推荐给对的人]
  secrets: [书店其实快撑不下去了]   # 剧情深层信息，别让普通对话直接暴露

# ---- 初始情绪 ----
emotion:
  initial: neutral
  initial_intensity: 50

# ---- 关系轴：定义维度与初值，规则层据此夹取 ----
relationship:
  axes: {trust: 20, affection: 30, respect: 20}

# ---- 可选：绑定默认剧情（§7）----
default_story: old_books_first_day

# ---- 可选：给 LLM 看记忆时的措辞模板（默认有兜底模板）----
memory_prompt_template: |
  以下是关于这位顾客你记得的一些事（重要程度从高到低）：
  {facts}
```

> **why 模块化字段**：每个字段是独立的 prompt 块（原则 #8）。`identity/personality/speech_style` 分别是稳定的核心块，`memory_prompt_template` 单独供记忆块使用。结构化字段（likes/dislikes/goals/secrets）比一大段自由文本更稳定、更好写 Eval 断言。

---

## 7. Story 配置格式（YAML）

**位置**：`backend/config/stories/<story_id>.yaml`。剧情是一个**有向图**，节点是"场景 + 引导目标"，边是"在什么情形下自然走向下一个场景"。

```yaml
story_id: old_books_first_day
title: 旧书店的第一天
description: 第一次见面，角色引导你躲雨、聊聊你为什么会走进这家店。
entry_node: opening
trigger: on_first_message        # immediate | on_first_message（见 §14 R6）
assets_allowed: [storefront, rainy_window, shelf_cat]   # 全局允许的素材

nodes:
  opening:
    scene: |
      午后下起雨，你推开巷子里那家旧书店的木门。
    beat: |
      温柔地欢迎这位躲雨的顾客，自然地聊起店和雨，引导 TA 说说为什么进店，
      不要直接提问"剧情任务"那样生硬。
    on_enter:
      emit_asset: storefront
      record_memory:
        - text: "顾客在一个雨天第一次走进书店"
          fact_type: user_fact
          importance: 3
    transitions:
      - to: about_rain
        hint: "顾客提到下雨、天气，或者关于这家店的好奇"
      - to: book_lover
        hint: "顾客表现出对书或阅读的兴趣"

  about_rain:
    scene: 雨还下着，你站在书架旁。
    beat: 顺着雨的话题，把聊天自然引向"你平时爱看什么书"。
    transitions:
      - to: recommend_book
        hint: "顾客说出喜欢的书或类型"

  recommend_book:
    scene: 她在书架上找了一会儿。
    beat: 根据顾客的喜好推荐一本书，把书递给 TA。
    on_enter:
      emit_asset: shelf_cat
    transitions: []            # 终态：剧情完成，之后自由对话

  book_lover:
    scene: 你们聊起书来，她的眼睛亮了一些。
    beat: 顺着顾客对书的兴趣深入聊，准备推荐一本书。
    transitions:
      - to: recommend_book
        hint: "顾客愿意继续聊下去"
```

### 7.1 字段语义

| 字段 | 语义 | 谁消费 |
|---|---|---|
| `trigger` | 剧情何时激活：`immediate`（建会话即激活）/ `on_first_message`（第一条用户消息后进入 `entry_node`） | StoryEngine |
| `scene` | 当前场景描述（写进 prompt 的"环境"块） | PromptBuilder |
| `beat` | **引导目标**：角色此刻该温和地把话题引向哪里。这是"平滑引导不强制"的核心机制 | PromptBuilder → Planner → Generator |
| `on_enter.emit_asset` | 进入节点时发射的素材 | StoryEngine → AssetService |
| `on_enter.record_memory` | 进入节点时自动记的事实（幂等，靠 `visited`） | StoryEngine → MemoryService |
| `transitions[].to` | 允许的下一步节点 | StoryEngine 校验 |
| `transitions[].hint` | 自然语言描述"什么情形下该走这条边" | PromptBuilder → Planner |

### 7.2 StoryEngine 的三个关键行为

1. **激活**：`trigger` 满足时进入 `entry_node`，执行 `on_enter` 副作用（记记忆 / 发图）。副作用**幂等**：`visited` 里已有该节点则不重复执行。
2. **迁移校验**：planner 提议 `next_node_id` 时，只有它 ∈ 当前节点 `transitions[].to` 才迁移；否则**拒绝并记录**（进 TurnLog.validation_errors），剧情不动。→ 这就是"LLM 不直接控制业务逻辑"（原则 A）。
3. **平滑引导**：系统不强制跳转 —— planner 被提示"当前在 opening，可以自然走到 about_rain 或 book_lover"，是否走由模型根据用户当前话语判断；走错/不走都不报错，只是继续当前场景。**剧情推进是"建议 + 校验"，不是"命令 + 执行"**。

---

## 8. 消息处理数据流（完整时序）

一条用户消息 → 角色回复（含可能的图片）的全流程：

```
[前端 ChatPage]
   │  POST /api/conversations/{id}/messages   body: {"content": "..."}
   ▼
[api/conversations.py]  # 薄路由：Pydantic 校验请求体，加载 conversation
   ▼
[core/conversation_service.py]  .turn(session_id, content)
   │
   │  ┌── 1. 持久化用户 Message
   │  ├── 2. 加载 ConversationState、StoryState
   │  ├── 3. StoryEngine.maybe_activate()      # on_first_message 触发剧情
   │  ├── 4. MemoryService.retrieve(state)     # 关键词+重要性 取 top-K 事实
   │  ├── 5. PromptBuilder.build_planner(...)  # 模块化组装（§9）
   │  ├── 6. ResponsePlanner（LLM #1）
   │  │     → PlannerOutput（Pydantic 校验；失败重试 1 次 → 规则兜底，§10.3）
   │  ├── 7. 规则层逐条应用提议（rules.py 纯函数）：
   │  │     • 情绪    → 枚举校验 + 强度阻尼 + 夹取
   │  │     • 关系    → delta 夹取 0-100
   │  │     • 话题    → 非空且限长才更新
   │  │     • 剧情    → StoryEngine.validate(proposal)
   │  │                ✓ 合法边 → 迁移 + 执行 on_enter（记记忆/发图）
   │  │                ✗ 非法边 → 拒绝并记录
   │  │     • 记忆    → 去重 + 限 importance 1-5 + 每轮最多 3 条
   │  │     • 素材    → AssetService.validate(tag, 当前节点允许集) → URL
   │  ├── 8. PromptBuilder.build_generator(..., planner_intent)
   │  ├── 9. RoleGenerator（LLM #2）→ Utterance（非空、限长校验）
   │  ├── 10. 持久化角色 Message（含 asset_tag）
   │  ├── 11. 持久化 ConversationState、StoryState
   │  └── 12. 写入 TurnLog（planner 原始输出 + 应用结果 + 校验错误）
   ▼
   返回 JSON：
   {
     "message":       {"id", "content", "sender": "character", "asset_tag"},
     "asset_url":     "…/assets/miko_cafe/storefront.png" | null,
     "state_summary": {"emotion", "emotion_intensity", "relationship", "current_topic"},
     "story_node":    "opening" | null,
     "decision":      {"planner": {…}, "applied": {…}, "rejected": […]}
   }
   ▼
[前端] 渲染文本 + 可选图片 + 右侧状态面板（情绪/关系/话题/剧情）
```

**失败路径**：LLM 调用或校验整体失败 → 重试 1 次 → 兜底（返回中性的礼貌回复、状态不变），全程记入 TurnLog。**聊天的健壮性优先**：Demo 现场不能让对话挂掉。

**数据一致性**：一次 `turn()` 内所有写操作在一个 SQLAlchemy 事务里提交（`Session.commit()`），部分失败则整体回滚。

---

## 9. Prompt 组装（PromptBuilder）

> 原则 #8：**绝不维护一个巨大的 system prompt**。prompt 由模块化"块"按需拼装。

### 9.1 块清单

每个块是一个可单测的函数，输入= 相关数据，输出= 一段文本。

| 块 | 输入 | 输出内容 | 用于 |
|---|---|---|---|
| `persona_block` | persona 配置 | identity / personality / speech_style / likes / dislikes / goals | Planner + Generator |
| `state_block` | ConversationState | 当前情绪、强度、关系轴、话题 | Planner + Generator |
| `story_block` | StoryState + 当前节点 | scene + beat + 可用 transitions 的 hint（剧情未激活则为空） | Planner + Generator |
| `memory_block` | MemoryService 检索结果 | 按模板渲染的事实列表（含措辞模板，§6） | Planner + Generator |
| `recent_messages_block` | messages 最近 N 条 | 对话历史（用户/角色交替） | Planner + Generator（作为 user 侧内容） |
| `planner_intent_block` | PlannerOutput 摘要 | "本轮你决定：情绪→…，剧情→…，要发图→…"（**只给 Generator**） | Generator |
| `guidelines_block` | 配置 | 保持角色、不打破第四面墙、语气一致等稳定守则 | Planner + Generator |

### 9.2 拼装策略

```
system = persona_block + state_block + story_block + memory_block + guidelines_block
user   = recent_messages_block           # Planner
或
system = persona_block + state_block + story_block + memory_block
         + planner_intent_block + guidelines_block
user   = recent_messages_block           # Generator
```

- **稳定块在前，易变块在后**：persona/guidelines 放前，state/memory 放后。这天然兼容 prompt caching（前缀稳定才有缓存命中）——Demo 不做缓存，但留了这个结构，未来可低成本启用。
- **格式说明不进 prompt**：结构化输出的字段约束由 LLM 层的 schema 负责（§10），prompt 只描述"怎么想"，不描述"怎么输出 JSON"。
- **统一换行与分隔符**，每个块头部带明确标签（`[角色人设]` / `[当前状态]` / `[剧情节点]`…），便于模型定位也便于调试打印。

---

## 10. LLM 结构化输出与 Pydantic 校验

> 原则 #5/#10：**所有 LLM 结构化输出必须过 Pydantic**。schema 是唯一事实源，前后端/存储/测试共享。

### 10.1 LLM 输出 Schema（`core/schemas.py`）

```python
class EmotionProposal(BaseModel):
    emotion: Emotion
    intensity: int          # 0-100

class MemoryCandidate(BaseModel):
    text: str               # 一条事实
    fact_type: Literal["user_fact", "character_fact"]
    importance: int         # 1-5

class StoryProposal(BaseModel):
    next_node_id: str

class PlannerOutput(BaseModel):
    """LLM #1 的输出 = 一份『行为提案』，不是指令（原则 A）。"""
    response_intent: str                    # 给 Generator 的一句话意图
    emotion_proposal: EmotionProposal | None = None
    relationship_delta: dict[str, int] = {} # {axis: delta}
    topic_proposal: str | None = None
    asset_tag: str | None = None            # 只允许 tag，绝不允许 URL
    story_proposal: StoryProposal | None = None
    memory_candidates: list[MemoryCandidate] = []

class Utterance(BaseModel):
    """LLM #2 的输出：纯文本台词。"""
    text: str               # 校验：非空、去首尾空白、限长（如 ≤ 2000 字符）
```

**校验强度**：`PlannerOutput` 的嵌套模型用 `Literal`/`Enum` 做类型级约束；`asset_tag` 只接受字符串 tag（原则 #7 —— 就算模型想返回 URL，规则层也会因为 catalog 匹配失败而拒绝）。

### 10.2 LLM 层实现要点（`app/llm/`）

- **`client.py`**：供应商抽象，MVP 实现 Anthropic（Python SDK `anthropic`）；通过 `LLM_PROVIDER` 环境变量切换。
  - 推荐结构化输出走 SDK 原生能力：Anthropic 的 `client.messages.parse()` + `output_config`（结构化输出）可返回校验过的对象；模型默认 `claude-opus-5`（由 `LLM_MODEL` 环境变量覆盖）。*这是实现指引，实现阶段再读 SDK 文档确认 API 形态。*
  - 所有供应商的返回统一归一化成"文本 + 结构"再进业务层，业务层感知不到供应商差异。
- **`structured.py`**：对不支持原生结构化输出的供应商 / mock，走"提取 JSON → `PlannerOutput.model_validate()`"，失败则触发重试策略。
- **`mock.py`**：`MockLLM`，按规则返回确定性的 PlannerOutput / Utterance（例如：情绪跟着用户消息里的否定词变；剧情节点按固定路径推进）。**这是离线开发、CI 和 Eval 的基石**——测试从不依赖真实网络。

### 10.3 校验失败策略（确定性流程，不依赖模型心情）

1. Pydantic 校验失败 / JSON 无法解析 → **带错误信息重试 1 次**（把 ValidationError 摘要追加进提示，让模型自纠）；
2. 仍失败 → **规则兜底**：采用中性默认（情绪保持、无剧情迁移、无图片、记忆忽略），回复礼貌通用句；
3. 无论成败，**原始输出 + 错误都写进 TurnLog**，Admin 面板可见。

### 10.4 Eval（能力 #8）

**位置**：`backend/tests/eval/`。Eval 用例定义为 YAML，runner 用 pytest 驱动。

```yaml
case_id: story_asset_triggers
description: 剧情节点进入时正确发射素材
setup:
  role: miko_cafe
  story: old_books_first_day
  state: {emotion: neutral, relationship: {trust: 20, affection: 30, respect: 20}}
turns:
  - user: "我进来躲一下雨。"
assertions:
  - kind: asset              # 第一轮 on_enter 应触发 storefront
    expect: {tag: storefront}
```

| 断言 kind | 检查什么 | 实现方式 |
|---|---|---|
| `emotion` | 情绪响应是否合理 | 规则断言：最终 `emotion` / `intensity` ∈ 期望集 |
| `story` | 剧情是否推进到期望节点 | 规则断言：`StoryState.current_node_id` |
| `asset` | 图片是否正确触发（或不该触发） | 规则断言：消息 `asset_tag` |
| `relationship` | 关系轴变化方向 | 规则断言：delta 符号 |
| `persona` | 人格一致性（语义，难用规则） | **LLM-judge**（可选）：用另一个 LLM 打分 / 关键词黑名单；离线用 mock 的确定性版本 |

**Eval 跑两种模式**：
- **Mock 模式（默认，CI）**：MockLLM 驱动，完全确定性、零成本，保回归；
- **Live 模式（演示）**：真实 LLM 驱动，给人看"系统在真实模型下也工作"。

> **why YAML 定义用例**：面试官/演示者可以在不改代码的情况下加用例；用例即文档。

---

## 11. 开发 Phase

> 每个 Phase 有明确出口（AC）。**顺序是关键**：先让"核心管线"在 mock 下跑通，再接真实 LLM 和前端。

| Phase | 内容 | 交付物 / 验收标准（AC） |
|---|---|---|
| **P0 脚手架** | 目录结构、`pyproject.toml`、FastAPI 空应用、Vite+Tailwind 空应用、`docker-compose.yml`（dev）、`.env.example` | `docker compose up` 后 8000 与 5173 均可访问 |
| **P1 数据层** | SQLAlchemy 全部模型、`db.py`、启动 `create_all()`、SQLite 文件 + volume | 单测通过：建 session/state/message 并回读 |
| **P2 配置层** | `config_loader.py`：加载 personas/stories/catalog，Pydantic 校验，启动失败快速报错 | 加载全部配置；坏 YAML 报清晰错误 |
| **P3 LLM 层** | `client.py` + `mock.py` + `structured.py`（含重试/兜底） | Mock 返回合法 PlannerOutput；非法 JSON → 重试 → 兜底 |
| **P4 核心管线** | PromptBuilder 全部块 + planner/generator + rules + StoryEngine + MemoryService + AssetService + `conversation_service.turn()` | **MockLLM 集成测试跑通一次完整 turn**，状态/剧情/记忆/图片正确持久化 |
| **P5 API + Admin** | 全部路由 + debug/turn-log 接口 + 素材静态托管 | curl 全流程；`GET /sessions/{id}/debug` 返回可读状态与最近决策 |
| **P6 前端** | ChatPage（角色选择、消息流、图片显示、状态面板）+ AdminPage（状态/剧情/决策/记忆） | 浏览器完成"对话→剧情→图片→看 Admin"完整演示 |
| **P7 Eval 与测试** | pytest 单元+集成全量；eval 用例 + runner + 报告；可选 `/eval/run` API | `pytest` 全绿；eval 报告覆盖 4 类断言 |
| **P8 演示打磨** | Demo 角色/剧情/素材内容精修、README 演示脚本、（可选）Admin 剧情跳转控件、（可选）流式打字效果 | 按 README 的 demo 脚本能完整走一遍 |

> **stretch（都不承诺）**：Admin 剧情跳转（`POST /admin/sessions/{id}/story/jump`，演示剧情分支很方便）、WebSocket 流式、single-call 快路径（§14 R2）。

---

## 12. 核心技术决策及理由

| # | 决策 | 备选 | why |
|---|---|---|---|
| D1 | **Planner / Generator 两次 LLM 调用** | 一次调用同时返回文本+决策 | 严格贯彻原则 #5/#6：行为决策与 NLG 解耦，各自可测、可评估；代价是延迟/成本翻倍，Demo 可接受（§14 R2 留后门） |
| D2 | **LLM 提议 → 代码裁决（规则层）** | 让 LLM 直接改状态 | 原则 #3；防模型破坏剧情图与状态不变量；让 Admin/Eval 可解释"哪些提议被采纳/拒绝" |
| D3 | **结构化输出 = 供应商原生结构化输出 + Pydantic 校验** | 纯文本 JSON 自由解析 | 原则 #10；schema 是唯一事实源；失败有明确的重试/兜底路径 |
| D4 | **状态持久化 SQLite（非内存）** | 内存态；Redis（已排除） | 原则 #9；重启不丢、Admin 可观察、测试可加载任意初始态 |
| D5 | **配置与代码分离（YAML + 启动时 Pydantic 校验）** | 人设/剧情写死代码 | 原则 #1/#2；加角色=加数据文件；坏配置启动即报错而不是运行中炸 |
| D6 | **定义不建表，DB 只存运行时状态** | 人设/剧情也落库 | 避免双源真相；定义随 git 走 |
| D7 | **同步 SQLAlchemy 2.0 + FastAPI `def` 端点** | async SQLAlchemy | 单一用户 Demo，同步最简单；async+sync 混用易出 bug；未来可平滑迁移 |
| D8 | **`create_all()`，不用 Alembic** | Alembic 迁移 | MVP schema 小且稳定；迁移工具是负担；schema 开始演进再引入 |
| D9 | **图片 = 本地静态目录 + catalog（tag→URL）** | 外部对象存储 / 实时生成（已排除） | 原则 #7；简单、可审计；LLM 永远只回 tag |
| D10 | **记忆检索 = 关键词重叠 + importance + 时效** | 向量数据库（已排除） | 数据量小，关键词足够；向量检索是后续增强点，不阻塞 MVP |
| D11 | **记忆/状态以 session 为界，无全局用户档案** | 跨会话用户档案 | 无登录体系；MVP 每会话独立记忆；跨会话记忆留给未来 |
| D12 | **MVP 用 REST POST，非 WebSocket 流式** | WebSocket/SSE 打字机效果 | 流式主要提升演示观感，属打磨；P8 可选加 |
| D13 | **LLM 供应商可插拔（Mock 默认 + Anthropic 可选）** | 绑定单一供应商 | Mock 让开发/CI/Eval 全离线确定性；演示换真实模型只需环境变量 |
| D14 | **情绪 = 分类枚举 + 强度（0-100）** | 维度模型（valence/arousal） | 直观、好渲染、好断言；Demo 深度足够（§14 R3 记录局限） |
| D15 | **剧情 = 有向图 + 引导目标（beat），迁移靠 LLM 提议 + 规则校验** | 完全规则化触发；完全由 LLM 自由推进 | 前者死板难写；后者不可控。折中：**平滑引导 + 合法边校验**正是"Story Engine"的意义 |

---

## 13. MVP 明确不做的事

来自需求约束 + D 决策，逐条列出以免后续方向漂移：

1. 登录注册、多用户、鉴权（Admin 面板仅限本地/dev 使用）
2. 支付 / 计费
3. Redis、Kafka、消息队列
4. Kubernetes、微服务、服务发现
5. Vector Database / 向量检索（记忆用关键词）
6. Voice / 语音输入输出
7. 实时图片生成（图片全部为预定义素材）
8. WebSocket / SSE 流式聊天（MVP 用 REST POST）
9. 单会话多角色同时对话（1v1 固定）
10. 跨会话记忆 / 全局用户档案（记忆以 session 为界）
11. 模型微调 / 自定义模型部署
12. 数据库迁移工具（用 `create_all()`）
13. i18n / 多语言
14. Admin 接口的访问控制（Demo 本地使用，不加认证）
15. 对抗性提示注入防护（仅一条"保持角色"守则，见 §14 R11）
16. 大规模会话 / 消息数据清理策略（单机 Demo 数据量小，注明即可）

---

## 14. 风险、歧义与需要提前决定的问题

按"对开发影响"排序，标注**建议决策**与**最晚决策时间**。

| # | 问题/风险 | 影响 | 建议决策 | 最晚决策时点 |
|---|---|---|---|---|
| R1 | **LLM 供应商与 API key**：现场演示必须有可用的 key；测试不能依赖网络 | 高 | 默认 Anthropic + `claude-opus-5`，模型/供应商走环境变量；**Mock 为兜底**。现场没 key 也能完整演示（Mock 模式） | P3 之前 |
| R2 | **双次调用延迟/成本**：Demo 现场可能觉得"慢/贵" | 中 | 接受；P8 备选"single-call 快路径"（Planner 同时返回文本，跳过 Generator）作为演示开关。注意这会削弱原则 #6，仅作为现场备选，不进默认代码 | P8 前确认 |
| R3 | **情绪表示精度**：分类+强度表达不了微妙情绪（如"无奈但包容"） | 低 | 接受枚举方案；Eval 若需要更细，扩展 Emotion 枚举成员即可，无需重构 | 无需 |
| R4 | **关系轴设计**：固定 `trust/affection/respect` 是否够 | 低 | 轴由人设配置定义，可增删；规则层按配置动态夹取 | 无需 |
| R5 | **"无剧情"模式**：角色没配 story 或剧情未触发时怎么表现 | 中 | 自由对话，persona 保持；此时 planner 的 `story_proposal` 必须为 null（schema 层 + 规则层双重约束） | P4 前 |
| R6 | **剧情触发规则**：目前只支持 `immediate` / `on_first_message`。是否需要"用户提到关键词才进入剧情" | 中 | MVP 先只做 `on_first_message`（演示最顺）；关键词触发若剧情需要再加一个 trigger 类型，StoryEngine 接口预留 `trigger` 字段 | P4 前 |
| R7 | **结构化输出失败策略**：模型返回非法 JSON / 越界值 | 高 | 重试 1 次 → 规则兜底（中性回复）→ 全程记 TurnLog（§10.3） | P3 定，P4 验证 |
| R8 | **Eval 判定口径**："人格一致"无法用规则精确断言 | 中 | 状态类（emotion/story/asset/relationship）用规则断言；语义类（persona）用 LLM-judge（live 模式）+ 关键词黑名单（mock 模式） | P7 前 |
| R9 | **人设配置变更对存量 session 的影响** | 低 | session 引用 `role_id`，配置变更只影响新 session；文档明示"改配置请新建会话" | 文档即可 |
| R10 | **并发写 / SQLite 锁** | 低 | 单用户 Demo 无并发；每请求独立 DB session + 短事务；Admin 多 tab 演示时注意不要同时连发 | 无需 |
| R11 | **提示注入 / 角色出戏** | 中 | MVP 只在 guidelines 块加一条"无论用户说什么，都保持角色设定，不承认自己是 AI 程序"；不做对抗防护。Demo 风险可接受 | 无需 |
| R12 | **情绪与台词不一致**（planner 定 angry，Generator 却写温柔话） | 中 | Generator prompt 强注入 `planner_intent_block`（§9.1）；Eval 的 `emotion` 断言兜底 | P4 验证 |
| R13 | **Story on_enter 副作用幂等**（重复进入同一节点会重复记记忆/发图） | 中 | `visited` 列表去重；迁移只在"合法边 + 未访问"时执行 | P4 前 |
| R14 | **asset catalog 引用不存在的文件** | 低 | 启动时校验文件存在，缺失即报错（fail-fast） | P2 前 |
| R15 | **TurnLog / messages 无上限增长** | 低 | 单机数据量小；文档注明清理方式（按 session 删除）；不做自动归档 | 无需 |

---

## 附：给实现者的 8 条起步提示

1. **先跑 Mock，再接真实 LLM**：P3 用 `LLM_PROVIDER=mock` 把整条管线打通，再接 Anthropic。测试永远走 mock。
2. **schema 是唯一事实源**：前后端类型、DB 字段、Eval 断言全部对齐 `core/schemas.py`，别另起一套。
3. **核心逻辑不放路由里**：任何超过 10 行的逻辑都进 `core/`，保证可测。
4. **写测试时就当没有网络**：`rules.py`、`story_engine.py`、`prompt_builder.py` 全是纯函数/纯逻辑，先给它们补单测。
5. **Admin 面板先于前端聊天打磨**：P6 先让 AdminPage 能读状态，调试聊天才有依据。
6. **一个完整 turn 是测试单元**：`conversation_service.turn()` 的集成测试 = 最值钱的测试。
7. **遵守原则 A**：所有 LLM 输出进状态前，过 rules.py；拒绝不存在的剧情边/素材 tag 不是 bug，是特性。
8. **配置坏了要早炸**：启动时校验全部 YAML，缺文件/坏字段直接报错退出，不要运行期才发现。
