from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from typing import Any


GITHUB_API = "https://api.github.com"
USER_AGENT = "github-weekly-wechat/2.1"


@dataclass(frozen=True)
class Config:
    github_token: str
    ai_api_key: str
    ai_base_url: str
    ai_model: str
    ai_model_preferences: list[str]
    server_chan_send_key: str
    trending_language: str
    project_limit: int
    readme_chars: int
    server_chan_preview_chars: int
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            github_token=os.getenv("GITHUB_TOKEN", "").strip(),
            ai_api_key=(os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip(),
            ai_base_url=(os.getenv("AI_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").strip(),
            ai_model=(os.getenv("AI_MODEL") or os.getenv("OPENAI_MODEL") or "auto").strip(),
            ai_model_preferences=parse_list(
                os.getenv("AI_MODEL_PREFERENCES")
                or "gpt-4.1-mini,gpt-4.1,gpt-4o-mini,gpt-4o,deepseek-chat,qwen-plus,qwen-turbo,glm-4-flash,moonshot-v1-8k"
            ),
            server_chan_send_key=os.getenv("SERVER_CHAN_SEND_KEY", "").strip(),
            trending_language=os.getenv("TRENDING_LANGUAGE", "").strip(),
            project_limit=parse_int("PROJECT_LIMIT", 10, minimum=1, maximum=30),
            readme_chars=parse_int("README_CHARS", 8000, minimum=800, maximum=30000),
            server_chan_preview_chars=parse_int("SERVER_CHAN_PREVIEW_CHARS", 1800, minimum=200, maximum=4000),
            dry_run=os.getenv("SEND_DRY_RUN", "false").lower() in {"1", "true", "yes", "on"},
        )


@dataclass
class Repo:
    full_name: str
    url: str
    description: str = ""
    stars: int = 0
    forks: int = 0
    readme: str = ""


@dataclass
class Summary:
    intro: str
    features: list[str]


class TrendingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_article = False
        self.in_repo_heading = False
        self.repos: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "article":
            self.in_article = "Box-row" in (attr.get("class") or "")
        if self.in_article and tag == "h2":
            self.in_repo_heading = True
        if self.in_article and self.in_repo_heading and tag == "a":
            full_name = normalize_repo_path(attr.get("href") or "")
            if full_name and full_name not in self.repos:
                self.repos.append(full_name)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self.in_repo_heading = False
        if tag == "article":
            self.in_article = False


def parse_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_repo_path(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) == 2 and all(part not in {".", ".."} for part in parts):
        return f"{parts[0]}/{parts[1]}"
    return ""


def request_text(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 30,
) -> str:
    req_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    data = None
    req_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    text = request_text(url, method=method, headers=req_headers, data=data, timeout=timeout)
    return json.loads(text)


def github_headers(config: Config, *, raw: bool = False) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if config.github_token:
        headers["Authorization"] = f"Bearer {config.github_token}"
    return headers


def fetch_trending_repos(config: Config) -> list[str]:
    language = urllib.parse.quote(config.trending_language.strip("/"))
    url = f"https://github.com/trending/{language}?since=weekly" if language else "https://github.com/trending?since=weekly"
    page = request_text(url)
    parser = TrendingParser()
    parser.feed(page)
    if not parser.repos:
        raise RuntimeError("No repositories found on GitHub Trending. The page layout may have changed.")
    return parser.repos[: config.project_limit]


def fetch_repo(config: Config, full_name: str) -> Repo:
    data = request_json(f"{GITHUB_API}/repos/{full_name}", headers=github_headers(config))
    repo = Repo(
        full_name=full_name,
        url=data.get("html_url", f"https://github.com/{full_name}"),
        description=data.get("description") or "",
        stars=int(data.get("stargazers_count") or 0),
        forks=int(data.get("forks_count") or 0),
    )
    repo.readme = fetch_readme(config, full_name)
    return repo


def fetch_readme(config: Config, full_name: str) -> str:
    try:
        return request_text(
            f"{GITHUB_API}/repos/{full_name}/readme",
            headers=github_headers(config, raw=True),
            timeout=20,
        )
    except urllib.error.HTTPError as error:
        if error.code in {403, 404}:
            return ""
        raise


def summarize_repo(repo: Repo, config: Config) -> Summary:
    if not config.ai_api_key:
        return fallback_summary(repo, ai_configured=False)

    body = {
        "model": config.ai_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个面向中文开发者的开源项目解读助手。"
                    "必须用简体中文输出，除项目名、专有名词、URL、命令名外，不要保留英文句子。"
                    "必须先从 README 中寻找项目介绍、功能特性、用途场景和目标用户。"
                    "只有 README 为空或没有可用信息时，才根据仓库名、仓库描述、链接等信息谨慎分析总结。"
                    "如果仓库描述或 README 是英文，要先理解后改写成自然中文。"
                    "不要编造不存在的能力。不要输出使用方法、编程语言或 license。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请为下面 GitHub 热门项目生成微信消息内容。"
                    "只返回 JSON，不要 Markdown，不要代码块。格式："
                    '{"intro":"一句中文简介，说明项目是什么","features":["中文功能点1","中文功能点2","中文功能点3"]}'
                    "要求 intro 和 features 都优先依据 readme_excerpt；features 每个点独立成句，最多 3 个，每个不超过 45 个汉字。"
                    "如果 readme_excerpt 没有功能信息，再自行分析项目可能的用途，但要保持谨慎。"
                    f"\n\n仓库信息：{json.dumps(repo_payload(repo, config), ensure_ascii=False)}"
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 700,
    }

    try:
        response = request_json(
            chat_completions_url(config.ai_base_url),
            method="POST",
            headers={"Authorization": f"Bearer {config.ai_api_key}"},
            body=body,
            timeout=60,
        )
        output = extract_chat_completion_text(response).strip()
        summary = parse_ai_summary(output)
        if summary:
            return summary
        print(f"[warn] AI summary returned invalid JSON for {repo.full_name}", file=sys.stderr)
        return fallback_summary(repo, ai_configured=True)
    except Exception as error:
        print(f"[warn] AI summary failed for {repo.full_name}: {error}", file=sys.stderr)
        return fallback_summary(repo, ai_configured=True)


def parse_ai_summary(output: str) -> Summary | None:
    cleaned = output.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    intro = clean_inline_text(str(payload.get("intro") or ""))
    raw_features = payload.get("features") or []
    if not isinstance(raw_features, list):
        raw_features = [str(raw_features)]
    features = [clean_inline_text(str(item)) for item in raw_features if clean_inline_text(str(item))]
    if not intro:
        return None
    return Summary(intro=intro, features=features[:3] or ["可结合 README 进一步了解项目能力和适用场景。"])


def resolve_ai_model(config: Config) -> Config:
    if not config.ai_api_key:
        return config

    manual_model = config.ai_model and config.ai_model.lower() not in {"auto", "detect"}
    if manual_model:
        print(f"[info] Using configured AI model: {config.ai_model}", file=sys.stderr)
        return config

    try:
        models = fetch_ai_models(config)
    except Exception as error:
        fallback = config.ai_model_preferences[0] if config.ai_model_preferences else "gpt-4.1-mini"
        print(f"[warn] AI model discovery failed: {error}. Falling back to {fallback}", file=sys.stderr)
        return replace(config, ai_model=fallback)

    if not models:
        fallback = config.ai_model_preferences[0] if config.ai_model_preferences else "gpt-4.1-mini"
        print(f"[warn] AI model discovery returned no models. Falling back to {fallback}", file=sys.stderr)
        return replace(config, ai_model=fallback)

    selected = select_ai_model(models, config.ai_model_preferences)
    print(f"[info] Available AI models: {', '.join(models[:20])}", file=sys.stderr)
    if len(models) > 20:
        print(f"[info] ...and {len(models) - 20} more models", file=sys.stderr)
    print(f"[info] Auto-selected AI model: {selected}", file=sys.stderr)
    return replace(config, ai_model=selected)


def fetch_ai_models(config: Config) -> list[str]:
    response = request_json(
        models_url(config.ai_base_url),
        method="GET",
        headers={"Authorization": f"Bearer {config.ai_api_key}"},
        timeout=30,
    )
    raw_models = response.get("data") if isinstance(response, dict) else response
    if not isinstance(raw_models, list):
        return []

    models: list[str] = []
    for item in raw_models:
        model_id = item.get("id") if isinstance(item, dict) else item
        if isinstance(model_id, str) and model_id and is_chat_like_model(model_id):
            models.append(model_id)
    return sorted(set(models), key=models.index)


def select_ai_model(models: list[str], preferences: list[str]) -> str:
    exact = {model.lower(): model for model in models}
    for preferred in preferences:
        match = exact.get(preferred.lower())
        if match:
            return match
    for preferred in preferences:
        preferred_lower = preferred.lower()
        for model in models:
            if preferred_lower in model.lower():
                return model
    return models[0]


def is_chat_like_model(model_id: str) -> bool:
    lowered = model_id.lower()
    blocked = ["embedding", "embed", "rerank", "moderation", "whisper", "tts", "dall-e", "image", "audio"]
    return not any(term in lowered for term in blocked)


def repo_payload(repo: Repo, config: Config) -> dict[str, Any]:
    return {
        "full_name": repo.full_name,
        "description": repo.description,
        "stars": repo.stars,
        "forks": repo.forks,
        "url": repo.url,
        "readme_excerpt": truncate(repo.readme, config.readme_chars),
    }


def chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def models_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/models"):
        return normalized
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    return f"{normalized}/models"


def extract_chat_completion_text(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else ""


def fallback_summary(repo: Repo, *, ai_configured: bool) -> Summary:
    readme_intro = extract_intro_line(repo.readme)
    description = clean_inline_text(repo.description)

    if readme_intro:
        intro = readme_intro
    elif description and not looks_mostly_english(description):
        intro = description
    else:
        intro = f"{repo.full_name} 是一个本周受到关注的开源项目。"

    features = extract_feature_lines(repo.readme)
    if not features:
        if description and not looks_mostly_english(description):
            features = [f"围绕项目简介提供相关能力：{shorten_sentence(description, 34)}。"]
        else:
            features = [
                "README 中未提取到明确功能点。",
                "已改用规则摘要，建议查看运行日志确认 AI 接口是否调用成功。"
                if ai_configured
                else "建议配置 AI key 以生成更准确的中文功能用途解读。",
            ]
    return Summary(intro=intro, features=features[:3])


def extract_intro_line(readme: str) -> str:
    for raw_line in readme.splitlines():
        line = clean_inline_text(strip_markdown(raw_line.strip()))
        if not is_meaningful_readme_line(line):
            continue
        if looks_mostly_english(line):
            continue
        return shorten_sentence(line, 70)
    return ""


def extract_feature_lines(readme: str) -> list[str]:
    lines: list[str] = []
    keywords = [
        "功能",
        "特性",
        "支持",
        "生成",
        "自动",
        "部署",
        "管理",
        "feature",
        "support",
        "build",
        "deploy",
        "manage",
        "generate",
        "automate",
        "agent",
    ]
    for raw_line in readme.splitlines():
        line = clean_inline_text(strip_markdown(raw_line.strip(" -*>\t")))
        if not is_meaningful_readme_line(line) or len(line) > 90 or looks_mostly_english(line):
            continue
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            lines.append(shorten_sentence(line, 70))
        if len(lines) >= 5:
            break
    return lines


def is_meaningful_readme_line(line: str) -> bool:
    if not line or len(line) < 12:
        return False
    lowered = line.lower()
    if not contains_cjk(line):
        return False
    if re.fullmatch(r"[\d\s/.,:;|()a-zA-Z-]+", line):
        return False
    if lowered.startswith(("http://", "https://", "badge", "npm ", "pip ", "docker ")):
        return False
    if any(token in lowered for token in ["shields.io", "github.com/", "img.shields", "license", "stars"]):
        return False
    return True


def shorten_sentence(text: str, max_chars: int) -> str:
    text = clean_inline_text(text)
    if len(text) <= max_chars:
        return text.rstrip("。；，,;")
    return text[:max_chars].rstrip("。；，,;") + "..."


def looks_mostly_english(text: str) -> bool:
    if not text:
        return False
    letters = sum(1 for char in text if char.isascii() and char.isalpha())
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    if cjk == 0 and letters > 3:
        return True
    return letters > 20 and letters > cjk * 2


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def clean_inline_text(text: str) -> str:
    text = strip_markdown(text)
    text = text.replace("�", "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+\?\s+", " ", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\?(?=\s*[\u4e00-\u9fff])", "", text)
    text = text.replace("； ", "；").replace("。 ", "。")
    return text.strip(" -:\t\r\n")


def strip_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[`*_#<>|]", "", text)
    return html.unescape(text).strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def format_digest(repos: list[Repo], summaries: dict[str, Summary]) -> tuple[str, str, str]:
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    title = f"GitHub 每周热门开源项目 {today}"
    sections: list[str] = []

    for index, repo in enumerate(repos, start=1):
        summary = summaries[repo.full_name]
        sections.extend(
            [
                f"## {index}. {repo.full_name}",
                "",
                f"**简介：** {summary.intro}",
                "",
                "**功能与用途：**",
                *[f"- {feature}" for feature in summary.features[:3]],
                "",
                f"**Stars：** {repo.stars:,}",
                "",
                f"**链接：** {repo.url}",
                "",
            ]
        )

    content = "\n".join(sections).strip()
    preview = build_preview(repos, summaries)
    return title, content, preview


def build_preview(repos: list[Repo], summaries: dict[str, Summary]) -> str:
    lines = []
    for index, repo in enumerate(repos, start=1):
        summary = summaries[repo.full_name]
        lines.append(f"{index}. {repo.full_name}：{summary.intro}")
    return "\n".join(lines)


def publish(title: str, content: str, preview: str, config: Config) -> None:
    if config.dry_run:
        print(content)
        return

    if not config.server_chan_send_key:
        print("[warn] SERVER_CHAN_SEND_KEY is not configured. Printing digest instead.", file=sys.stderr)
        print(content)
        return

    publish_server_chan(title, content, truncate(preview, config.server_chan_preview_chars), config.server_chan_send_key)


def publish_server_chan(title: str, content: str, preview: str, send_key: str) -> None:
    url = f"https://sctapi.ftqq.com/{urllib.parse.quote(send_key)}.send"
    data = urllib.parse.urlencode({"title": title, "desp": content, "short": preview}).encode("utf-8")
    text = request_text(
        url,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        timeout=30,
    )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {"raw": text}
    code = payload.get("code")
    if code not in {0, "0", None}:
        raise RuntimeError(f"Server Chan push failed: {payload}")


def main() -> None:
    config = resolve_ai_model(Config.from_env())
    print_ai_config_status(config)
    selected_names = fetch_trending_repos(config)
    repos: list[Repo] = []
    summaries: dict[str, Summary] = {}

    for full_name in selected_names:
        print(f"[info] Processing {full_name}", file=sys.stderr)
        repo = fetch_repo(config, full_name)
        repos.append(repo)
        summaries[repo.full_name] = summarize_repo(repo, config)

    title, content, preview = format_digest(repos, summaries)
    publish(title, content, preview, config)


def print_ai_config_status(config: Config) -> None:
    key_status = "configured" if config.ai_api_key else "missing"
    print(
        f"[info] AI config: key={key_status}, base_url={config.ai_base_url}, model={config.ai_model}",
        file=sys.stderr,
    )


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    configure_stdio()
    try:
        main()
    except Exception as exc:
        wrapped = "\n".join(textwrap.wrap(str(exc), width=100)) or repr(exc)
        print(f"[error] {wrapped}", file=sys.stderr)
        raise
