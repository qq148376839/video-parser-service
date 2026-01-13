"""
M3U8 KEY处理工具

当m3u8内容中包含 #EXT-X-KEY 时：
- 解析并规范化URI（相对路径转绝对URL）
- 下载key文件到本地缓存目录（data/m3u8_cache），并按项目规则重命名
- 将m3u8中的URI改写为本服务可访问的key地址
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urljoin

from utils.logger import logger


_KEY_TAG_PREFIX = "#EXT-X-KEY"
_URI_RE = re.compile(r'URI=(?P<q>["\'])(?P<uri>[^"\']+)(?P=q)')


def _project_root() -> Path:
    return Path(__file__).parent.parent


def get_key_cache_dir() -> Path:
    """
    key缓存目录（与m3u8缓存同目录，便于统一清理）
    """
    cache_dir = _project_root() / "data" / "m3u8_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def compute_key_id(key_url: str) -> str:
    """
    计算key文件ID（稳定、可复用）
    """
    return hashlib.md5(key_url.encode("utf-8")).hexdigest()[:16]


def key_filename(key_id: str) -> str:
    """
    按项目规则生成key文件名
    """
    return f"key_{key_id}.key"


def build_local_key_url(api_base_url: str, key_id: str) -> str:
    """
    构建返回给播放器的key访问URL
    复用既有 m3u8 下载接口：/api/v1/m3u8/{file_id}
    """
    base = (api_base_url or "").rstrip("/")
    return f"{base}/api/v1/m3u8/{key_filename(key_id)}"


def _normalize_key_uri(uri: str, m3u8_url_for_base: str) -> str:
    """
    将KEY的URI规范化为绝对URL
    """
    if not uri:
        return uri
    # m3u8里的URI可能是相对路径或 //example.com/xxx.key
    if uri.startswith(("http://", "https://")):
        return uri
    return urljoin(m3u8_url_for_base, uri)


def download_key_if_needed(session, key_url: str, dest_path: Path, timeout: int = 15) -> bool:
    """
    下载key文件（若已存在则跳过）
    """
    try:
        if dest_path.exists() and dest_path.is_file() and dest_path.stat().st_size > 0:
            return True

        resp = session.get(key_url, timeout=timeout)
        resp.raise_for_status()
        content = resp.content or b""
        if not content:
            logger.warning(f"KEY下载为空内容: {key_url}")
            return False

        dest_path.write_bytes(content)
        logger.info(f"KEY已缓存: {dest_path.name} (大小: {len(content)} 字节)")
        return True
    except Exception as e:
        logger.warning(f"KEY下载失败: {key_url} -> {dest_path.name}, err={e}")
        return False


def rewrite_m3u8_key_uris(
    m3u8_content: str,
    m3u8_url_for_base: str,
    api_base_url: str,
    session,
) -> Tuple[str, int]:
    """
    扫描并处理m3u8中的 #EXT-X-KEY，将URI改写为本服务地址，并确保key已被缓存。

    Returns:
        (rewritten_content, rewritten_count)
    """
    if not m3u8_content or _KEY_TAG_PREFIX not in m3u8_content:
        return m3u8_content, 0

    cache_dir = get_key_cache_dir()

    rewritten = 0
    out_lines = []
    for line in m3u8_content.split("\n"):
        line_stripped = line.strip()
        if not line_stripped.startswith(_KEY_TAG_PREFIX):
            out_lines.append(line)
            continue

        m = _URI_RE.search(line)
        if not m:
            out_lines.append(line)
            continue

        original_uri = m.group("uri")
        normalized_key_url = _normalize_key_uri(original_uri, m3u8_url_for_base)
        key_id = compute_key_id(normalized_key_url)
        local_url = build_local_key_url(api_base_url, key_id)

        # 下载key到缓存目录
        dest = cache_dir / key_filename(key_id)
        ok = download_key_if_needed(session=session, key_url=normalized_key_url, dest_path=dest)
        if not ok:
            # 下载失败：保持原URI不改写（避免返回一个404的本地URL）
            out_lines.append(line)
            continue

        # 改写URI，保持原引号风格
        q = m.group("q")
        new_line = _URI_RE.sub(f'URI={q}{local_url}{q}', line, count=1)
        out_lines.append(new_line)
        rewritten += 1

    if rewritten > 0:
        logger.info(f"M3U8 KEY处理: 已改写 {rewritten} 个KEY URI为本地接口")

    return "\n".join(out_lines), rewritten

