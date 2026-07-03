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
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GITHUB_API = "https://api.github.com"
USER_AGENT = "github-weekly-wechat/2.0"


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
            dry_run=os.getenv("SEND_DRY_RUN", "false").lower() in {"1", "true", "yes", "on"},
        )


@dataclass
class Repo:
    full_name: str
    url: str
    description: str = ""
    stars: int = 0
    forks: int = 0
    topics: list[str] | None = None
    readme: str = ""


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
        topics=list(data.get("topics") or []),
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


def summarize_repo(repo: Repo, config: Config) -> str:
    fallback = fallback_summary(repo)
    if not config.ai_api_key:
        return fallback

    body = {
        "model": config.ai_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个面向中文开发者的开源项目解读助手。"
                    "优先依据 README 内容总结项目；README 信息不足时，再参考仓库描述、topics、stars 等元数据。"
                    "不要编造不存在的能力。不要输出使用方法、编程语言或 license。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请为下面的 GitHub 热门项目生成微信推送条目。"
                    "只输出两行，格式必须是：\n"
                    "介绍：一句话说明项目是什么。\n"
                    "用途功能：用 2-3 个短句说明它能解决什么问题、主要功能是什么、适合什么场景。\n\n"
                    f"仓库信息：{json.dumps(repo_payload(repo, config), ensure_ascii=False)}"
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 500,
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
        return normalize_summary(output) or fallback
    except Exception as error:
        print(f"[warn] AI summary failed for {repo.full_name}: {error}", file=sys.stderr)
        return fallback


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
        "topics": repo.topics or [],
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


def fallback_summary(repo: Repo) -> str:
    intro = strip_markdown(repo.description) or first_readme_sentence(repo.readme) or "README 中没有提供清晰的一句话描述。"
    features = extract_feature_lines(repo.readme)
    if features:
        feature_text = "；".join(features[:3])
    elif repo.topics:
        feature_text = "项目主题包括：" + "、".join(repo.topics[:5]) + "。可结合 README 进一步判断适用场景。"
    else:
        feature_text = "可从项目 README 了解主要能力和适用场景。"
    return f"介绍：{intro}\n用途功能：{feature_text}"


def first_readme_sentence(readme: str) -> str:
    for raw_line in readme.splitlines():
        line = strip_markdown(raw_line)
        if 20 <= len(line) <= 160 and not line.lower().startswith(("http", "badge", "build")):
            return line
    return ""


def extract_feature_lines(readme: str) -> list[str]:
    lines: list[str] = []
    keywords = [
        "feature",
        "features",
        "support",
        "supports",
        "fast",
        "build",
        "deploy",
        "manage",
        "generate",
        "automate",
        "agent",
        "功能",
        "特性",
        "支持",
        "生成",
        "自动",
        "部署",
        "管理",
    ]
    for raw_line in readme.splitlines():
        line = strip_markdown(raw_line.strip(" -*>\t"))
        if not line or len(line) < 12 or len(line) > 140:
            continue
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            lines.append(line)
        if len(lines) >= 5:
            break
    return lines


def normalize_summary(summary: str) -> str:
    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    kept: list[str] = []
    for line in lines:
        if line.startswith(("介绍：", "用途功能：")):
            kept.append(line)
    if len(kept) >= 2:
        return "\n".join(kept[:2])
    return summary.strip()


def strip_markdown(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"[`*_#<>|]", "", text)
    return html.unescape(text).strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def format_digest(repos: list[Repo], summaries: dict[str, str]) -> tuple[str, str]:
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    title = f"GitHub 每周热门开源项目 {today}"
    lines = [f"# {title}", "", "以下项目来自 GitHub weekly trending。", ""]

    for index, repo in enumerate(repos, start=1):
        topics = ", ".join((repo.topics or [])[:5]) or "无"
        lines.extend(
            [
                f"## {index}. {repo.full_name}",
                summaries[repo.full_name].strip(),
                "",
                f"Stars: {repo.stars:,}",
                f"Topics: {topics}",
                f"链接: {repo.url}",
                "",
            ]
        )
    return title, "\n".join(lines).strip()


def publish(title: str, content: str, config: Config) -> None:
    if config.dry_run:
        print(content)
        return

    if not config.server_chan_send_key:
        print("[warn] SERVER_CHAN_SEND_KEY is not configured. Printing digest instead.", file=sys.stderr)
        print(content)
        return

    publish_server_chan(title, content, config.server_chan_send_key)


def publish_server_chan(title: str, content: str, send_key: str) -> None:
    url = f"https://sctapi.ftqq.com/{urllib.parse.quote(send_key)}.send"
    data = urllib.parse.urlencode({"title": title, "desp": content}).encode("utf-8")
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
    selected_names = fetch_trending_repos(config)
    repos: list[Repo] = []
    summaries: dict[str, str] = {}

    for full_name in selected_names:
        print(f"[info] Processing {full_name}", file=sys.stderr)
        repo = fetch_repo(config, full_name)
        repos.append(repo)
        summaries[repo.full_name] = summarize_repo(repo, config)

    title, content = format_digest(repos, summaries)
    publish(title, content, config)


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
