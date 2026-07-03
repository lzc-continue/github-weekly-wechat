# GitHub 每周热门开源项目微信日报

每天北京时间 09:00 获取 GitHub weekly trending 前 10 个项目，基于 README 和仓库元数据生成中文简介，然后通过 Server 酱推送到微信。

## 当前功能

- 固定推送当前 GitHub weekly trending 热门项目，不做历史去重
- 默认推送 10 个项目
- 摘要优先参考 README；README 信息不足时，再结合仓库描述和仓库名谨慎分析
- 消息内容保留项目介绍、用途功能、stars 和 GitHub 链接
- 不展示使用方法、编程语言和 license
- 不包含额外来源说明文字
- 强制每个项目和每个功能点换行，功能与用途会输出更详细的 4 条说明
- 要求 AI 将英文描述翻译成中文
- 通过 Server 酱发送时同时传 `short` 预览，改善微信卡片直接展示
- 支持 OpenAI-compatible AI 接口，不限定只能用 OpenAI

## 微信直接显示说明

Server 酱的部分微信通道会把长正文放到详情页里，微信消息卡片只展示标题和简短摘要。这个行为由推送通道决定，脚本无法完全控制。

本项目已经做了两件事来改善：

- `desp`：保存完整正文，点详情时排版清晰
- `short`：发送一段摘要预览，尽量让微信卡片直接显示更多内容

如果你希望完整 10 个项目都不点详情、直接在聊天窗口里展开显示，需要后续改为企业微信应用文本消息直发，并按长度拆成多条消息。

## 消息格式

```text
## 1. owner/repo

**简介：** 一句中文简介，说明项目是什么。

**功能与用途：**
- 说明项目提供的核心能力，以及它主要解决哪类开发或使用问题。
- 说明项目适合的典型场景，例如自动化、数据处理、前端构建或团队协作。
- 说明 README 中提到的重要特性，并解释这些特性对使用者有什么价值。
- 说明项目和同类工具相比更值得关注的地方，避免只罗列关键词。

**Stars：** 12,345

**链接：** https://github.com/owner/repo
```

## 快速开始

在 GitHub 仓库的 `Settings -> Secrets and variables -> Actions` 中配置：

Secrets：

```text
SERVER_CHAN_SEND_KEY=你的 Server 酱 SendKey
AI_API_KEY=你的 AI 服务 API key
AI_BACKUP_API_KEY=备用 AI 服务 API key，可选
```

Variables：

```text
AI_BASE_URL=https://api.example.com/v1
AI_MODEL=auto
PROJECT_LIMIT=10
README_CHARS=8000
FEATURE_POINT_COUNT=4
FEATURE_POINT_MAX_CHARS=90
SERVER_CHAN_PREVIEW_CHARS=1800
SEND_DRY_RUN=false
```

如果使用 OpenAI-compatible 中转站，`AI_BASE_URL` 通常需要带 `/v1`。例如：

```text
AI_BASE_URL=https://api.aisz.mom/v1
```

如果日志里出现 `Response ... was not JSON` 或 `Expecting value: line 1 column 1`，通常说明接口地址填到了网页地址或根地址，请先检查 `/v1` 是否正确。

功能与用途的详细程度可以用这两个变量调整：

```text
FEATURE_POINT_COUNT=4
FEATURE_POINT_MAX_CHARS=90
```

想更详细可以改成 `FEATURE_POINT_COUNT=5`、`FEATURE_POINT_MAX_CHARS=120`；如果微信里显得太长，再调回默认值。

## AI 服务配置

`AI_MODEL=auto` 时，脚本会请求：

```text
{AI_BASE_URL}/models
```

然后从返回的模型列表中按 `AI_MODEL_PREFERENCES` 自动选择。你也可以手动指定：

```text
AI_MODEL=deepseek-chat
```

没有配置 AI key 时，脚本会降级为规则摘要，但英文翻译和内容质量会明显差一些。

## AI 保障机制

脚本不会因为 AI key 突然失效就中断当天推送，会按下面顺序处理：

1. 先使用 `AI_API_KEY` 生成中文摘要
2. 如果主 key 调用失败，自动尝试 `AI_BACKUP_API_KEY`
3. 如果配置了 `AI_BACKUP_API_KEYS`，会按英文逗号分隔的顺序继续尝试多个备用 key
4. 如果所有 AI key 都失败，仍会发送规则摘要，并在 GitHub Actions 日志里记录失败原因

建议至少配置一个备用 key：

```text
AI_BACKUP_API_KEY=你的备用 key
```

如果你有多个备用 key，可以配置：

```text
AI_BACKUP_API_KEYS=备用key1,备用key2,备用key3
```

日志里会看到类似：

```text
[warn] AI summary failed for owner/repo; key #1: HTTP Error 401: Unauthorized | key #2: ...
```

这里的 `key #1` 是主 key，`key #2` 开始是备用 key。日志不会打印真实 key。

## 本地测试

PowerShell:

```powershell
$env:SEND_DRY_RUN="true"
$env:PROJECT_LIMIT="3"
python src/main.py
```

测试 AI 摘要：

```powershell
$env:AI_API_KEY="你的 key"
$env:AI_BASE_URL="https://api.example.com/v1"
$env:AI_MODEL="auto"
$env:SEND_DRY_RUN="true"
$env:PROJECT_LIMIT="1"
python src/main.py
```

