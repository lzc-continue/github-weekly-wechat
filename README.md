# GitHub 每周热门开源项目微信日报

每天北京时间 09:00 获取 GitHub weekly trending 前 10 个项目，基于 README 和仓库元数据生成中文简介，然后通过 Server 酱推送到微信。

## 当前功能

- 固定推送当前 GitHub weekly trending 热门项目，不做历史去重
- 默认推送 10 个项目
- 拉取仓库简介、stars、topics、README 和链接
- 摘要优先参考 README；README 信息不足时，再结合仓库描述和 topics 生成
- 消息内容保留项目介绍、用途功能、stars、topics 和 GitHub 链接
- 不展示使用方法、编程语言和 license
- 支持 OpenAI-compatible AI 接口，不限定只能用 OpenAI
- 支持导入 key 后自动发现可用模型，并可手动切换模型
- 通过 Server 酱推送到微信

## 消息格式

```text
# GitHub 每周热门开源项目 2026-07-03

以下项目来自 GitHub weekly trending。

## 1. owner/repo
介绍：一句话说明项目是什么。
用途功能：说明它能解决什么问题、主要功能是什么、适合什么场景。

Stars: 12,345
Topics: ai, cli, developer-tools
链接: https://github.com/owner/repo
```

## 快速开始

1. 新建一个 GitHub 仓库，把本目录内容提交进去。
2. 打开仓库的 `Settings -> Secrets and variables -> Actions`。
3. 配置 Secrets：

| 名称 | 必填 | 说明 |
| --- | --- | --- |
| `SERVER_CHAN_SEND_KEY` | 是 | Server 酱 SendKey，用于推送到微信 |
| `AI_API_KEY` | 推荐 | AI 服务的 API key |
| `OPENAI_API_KEY` | 可选 | 旧配置名，未配置 `AI_API_KEY` 时会作为备用 |

4. 配置 Variables：

| 名称 | 默认值 | 说明 |
| --- | --- | --- |
| `AI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API 地址 |
| `AI_MODEL` | `auto` | `auto` 时自动发现并选择模型；填具体模型名时手动切换 |
| `AI_MODEL_PREFERENCES` | 见 `.env.example` | 自动选模型时的优先级列表，逗号分隔 |
| `PROJECT_LIMIT` | `10` | 每次推送项目数 |
| `README_CHARS` | `8000` | 传给 AI 的 README 字符数 |
| `TRENDING_LANGUAGE` | 空 | 语言过滤，例如 `python`、`typescript`、`rust` |
| `SEND_DRY_RUN` | `false` | 为 `true` 时只打印，不推送 |

5. 进入 `Actions -> Daily GitHub Hot Projects`，手动点一次 `Run workflow` 测试。

## Server 酱

Server 酱是一个微信推送服务。脚本把消息发给 Server 酱，Server 酱再把消息转发到你的微信。

使用流程：

1. 打开 [Server 酱](https://sct.ftqq.com/)。
2. 登录并绑定微信。
3. 获取 SendKey。
4. 把 SendKey 填到 GitHub Actions Secret：`SERVER_CHAN_SEND_KEY`。

脚本调用的接口是：

```text
https://sctapi.ftqq.com/{SEND_KEY}.send
```

## AI 服务配置

本项目不强制使用 OpenAI，只要求服务兼容 `/v1/chat/completions`。如果服务也兼容 `/v1/models`，脚本可以在导入 key 后自动发现模型。

通用配置：

```text
AI_API_KEY=你的 API key
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=auto
```

当 `AI_MODEL=auto` 或留空时，脚本会请求：

```text
{AI_BASE_URL}/models
```

然后从返回的模型列表中按 `AI_MODEL_PREFERENCES` 选择最合适的模型。运行日志会打印可用模型和自动选中的模型。

如果出现多个模型，你可以手动切换：

```text
AI_MODEL=deepseek-chat
```

如果使用中转站或其他兼容服务，把 `AI_BASE_URL` 换成对应服务提供的值即可：

```text
AI_BASE_URL=https://api.example.com/v1
AI_MODEL=auto
```

如果服务不支持 `/v1/models`，脚本会回退到 `AI_MODEL_PREFERENCES` 的第一个模型，不会因此中断日报。

没有配置 AI key 时，脚本会降级为规则摘要，仍然可以推送，但文案质量会低一些。

## 本地测试

PowerShell:

```powershell
$env:SEND_DRY_RUN="true"
$env:PROJECT_LIMIT="3"
python src/main.py
```

`SEND_DRY_RUN=true` 只打印消息，不会推送。

测试自动发现模型：

```powershell
$env:AI_API_KEY="你的 key"
$env:AI_BASE_URL="https://api.openai.com/v1"
$env:AI_MODEL="auto"
$env:SEND_DRY_RUN="true"
$env:PROJECT_LIMIT="1"
python src/main.py
```

手动切换模型：

```powershell
$env:AI_MODEL="deepseek-chat"
python src/main.py
```

## 可调整方向

- 只看某个语言：设置 `TRENDING_LANGUAGE=python` 或 `typescript`
- 想换 AI 服务：改 `AI_BASE_URL` 和 `AI_API_KEY`
- 想手动换模型：改 `AI_MODEL`
- 想调整自动选模型优先级：改 `AI_MODEL_PREFERENCES`
- 想少发或多发：改 `PROJECT_LIMIT`
- 想让摘要更充分：适当调大 `README_CHARS`

## 说明

当前热门项目来源是 GitHub weekly trending 页面。它足够适合第一版日报，但不是官方 API。后续如果需要更精确的“近 7 天 star 增长排行榜”，可以升级成每日记录 star 快照，再按 7 天增量排序。

