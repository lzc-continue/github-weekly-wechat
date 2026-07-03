# GitHub 每周热门开源项目微信日报

每天北京时间 09:00 获取 GitHub weekly trending 前 10 个项目，基于 README 和仓库元数据生成中文简介，然后通过 Server 酱推送到微信。

## 当前功能

- 固定推送当前 GitHub weekly trending 热门项目，不做历史去重
- 默认推送 10 个项目
- 摘要优先参考 README；README 信息不足时，再结合仓库描述和 topics 生成
- 消息内容保留项目介绍、用途功能、stars、topics 和 GitHub 链接
- 不展示使用方法、编程语言和 license
- 删除“以下项目来自 GitHub weekly trending”说明文字
- 强制每个项目和每个功能点换行，避免微信里挤成一段
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
GitHub 热门开源项目 2026-07-03

01. owner/repo
简介：一句中文简介，说明项目是什么。
功能与用途：
- 功能点一。
- 功能点二。
- 功能点三。
Stars：12,345
Topics：ai、cli、developer-tools
链接：https://github.com/owner/repo
```

## 快速开始

在 GitHub 仓库的 `Settings -> Secrets and variables -> Actions` 中配置：

Secrets：

```text
SERVER_CHAN_SEND_KEY=你的 Server 酱 SendKey
AI_API_KEY=你的 AI 服务 API key
```

Variables：

```text
AI_BASE_URL=https://api.example.com/v1
AI_MODEL=auto
PROJECT_LIMIT=10
README_CHARS=8000
SERVER_CHAN_PREVIEW_CHARS=1800
SEND_DRY_RUN=false
```

如果使用 OpenAI-compatible 中转站，`AI_BASE_URL` 通常需要带 `/v1`。

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

