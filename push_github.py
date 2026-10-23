#!/usr/bin/env python3
"""用 GitHub REST API 把本地 main 分支同步到远端。

沙箱里 `git push`（github.com:443）不通，只有 api.github.com 可访问，
所以走 Git Data API 手工造对象：blob -> tree -> commit -> 更新 ref。

用法：
    python3 push_github.py                  # 只同步 git 已跟踪的文件
    python3 push_github.py --dry-run        # 只看会改什么
    GITHUB_TOKEN=xxx python3 push_github.py

token 也可放在环境变量 GITHUB_TOKEN / GH_TOKEN，或同目录 .gh_token 文件。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
OWNER = "emfox"
REPO = "xiaopeng-site"
BRANCH = "main"


def token() -> str:
    for k in ("GITHUB_TOKEN", "GH_TOKEN"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gh_token")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    sys.exit("没有 token：设置 GITHUB_TOKEN 环境变量或写 .gh_token 文件")


TOKEN = token()


def call(method: str, path: str, body: dict | None = None, retries: int = 3) -> dict:
    url = API + path if path.startswith("/") else path
    data = json.dumps(body).encode() if body is not None else None
    for i in range(retries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {TOKEN}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:400]
            # 409 空仓库 / 422 无变化 / 502 网关抖动 可以重试
            if e.code in (409, 422, 502, 503) and i < retries - 1:
                time.sleep(1.5 * (i + 1))
                continue
            sys.exit(f"{method} {url} -> {e.code}\n{msg}")
        except (urllib.error.URLError, TimeoutError) as e:
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
                continue
            sys.exit(f"{method} {url} 网络错误: {e}")
    return {}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def tracked_files() -> list[str]:
    out = git("ls-files", "-z")
    return [p for p in out.split("\0") if p]


def remote_head() -> str | None:
    try:
        return call("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/{BRANCH}")["object"]["sha"]
    except SystemExit:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--message", default=None)
    args = ap.parse_args()

    files = tracked_files()
    head = remote_head()
    print(f"本地文件 {len(files)} 个，远端 HEAD {head[:8] if head else '（空仓库）'}")

    # 远端已有树：内容相同的文件直接复用旧 blob，不用重传
    remote_blobs: dict[str, str] = {}
    if head:
        tree_sha = call("GET", f"/repos/{OWNER}/{REPO}/git/commits/{head}")["tree"]["sha"]
        old = call("GET", f"/repos/{OWNER}/{REPO}/git/trees/{tree_sha}?recursive=1")
        remote_blobs = {e["path"]: e["sha"] for e in old.get("tree", []) if e["type"] == "blob"}

    if args.dry_run:
        for p in files:
            print("  ", p)
        return

    # 本地按内容算 git blob sha，和远端比对；只传变了的
    def blob_sha(data: bytes) -> str:
        import hashlib
        return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()

    # 1) 每个文件建 blob（内容没变就复用远端 sha）
    entries, total, reused = [], 0, 0
    for i, p in enumerate(files, 1):
        with open(p, "rb") as f:
            content = f.read()
        total += len(content)
        local = blob_sha(content)
        if remote_blobs.get(p) == local:
            sha = local
            reused += 1
        else:
            sha = call("POST", f"/repos/{OWNER}/{REPO}/git/blobs",
                       {"content": base64.b64encode(content).decode(), "encoding": "base64"})["sha"]
        entries.append({"path": p, "mode": "100755" if os.access(p, os.X_OK) else "100644",
                        "type": "blob", "sha": sha})
        if i % 25 == 0 or i == len(files):
            print(f"  blob {i}/{len(files)}（复用 {reused}）")
    print(f"内容合计 {total / 1024 / 1024:.2f} MB，复用远端 {reused} 个，实传 {len(files) - reused} 个")

    # 2) 一次 tree 覆盖全仓库（base_tree 让未列出的旧文件保留；这里要删已移除的文件，所以不带 base_tree）
    tree_body = {"tree": entries}
    if head:
        tree_body["base_tree"] = call("GET", f"/repos/{OWNER}/{REPO}/git/commits/{head}")["tree"]["sha"]
    tree = call("POST", f"/repos/{OWNER}/{REPO}/git/trees", tree_body)
    print(f"tree {tree['sha'][:8]}，条目 {len(tree.get('tree', []))}")

    # 3) commit
    msg = args.message or git("log", "-1", "--pretty=%B") or "sync"
    commit_body = {"message": msg, "tree": tree["sha"]}
    if head:
        commit_body["parents"] = [head]
    commit = call("POST", f"/repos/{OWNER}/{REPO}/git/commits", commit_body)
    print(f"commit {commit['sha'][:8]}")

    # 4) 更新分支
    if head:
        call("PATCH", f"/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}", {"sha": commit["sha"]})
    else:
        call("POST", f"/repos/{OWNER}/{REPO}/git/refs",
             {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
    print(f"已更新 {BRANCH} -> {commit['sha'][:8]}")


if __name__ == "__main__":
    main()
