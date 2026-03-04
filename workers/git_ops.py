"""Git 操作：clone/pull Hugo site repo，寫入文章後 push。"""

import logging
import subprocess
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def run_git(*args: str, cwd: Path | None = None) -> str:
    """執行 git 指令，回傳 stdout。"""
    env = None
    if config.SSH_KEY_PATH:
        env = {
            "GIT_SSH_COMMAND": f"ssh -i {config.SSH_KEY_PATH} -o StrictHostKeyChecking=no"
        }

    cmd = ["git"] + list(args)
    logger.info(f"執行：{' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if result.returncode != 0:
        logger.error(f"git 指令失敗：{result.stderr}")
        raise RuntimeError(f"git {args[0]} 失敗：{result.stderr}")
    return result.stdout.strip()


def ensure_repo() -> Path:
    """確保 Hugo site repo 存在並是最新狀態。回傳 repo 路徑。"""
    repo_dir = config.HUGO_SITE_DIR

    if not repo_dir.exists():
        logger.info(f"Clone repo 到 {repo_dir}")
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        run_git("clone", config.HUGO_SITE_REPO, str(repo_dir))
    else:
        logger.info(f"Pull 最新變更：{repo_dir}")
        run_git("pull", "--rebase", cwd=repo_dir)

    return repo_dir


def publish_post(md_path: Path, pub_date_str: str) -> None:
    """將產生的 Markdown 文章推送到 Hugo site repo。

    Args:
        md_path: 產生的 .md 檔案路徑
        pub_date_str: 日期字串（用於 commit message，如 2026-03-02）
    """
    repo_dir = ensure_repo()
    posts_dir = repo_dir / "content" / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)

    # 複製文章到 repo
    dest = posts_dir / md_path.name
    dest.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    logger.info(f"文章已複製到 {dest}")

    # git add + commit + push
    run_git("add", f"content/posts/{md_path.name}", cwd=repo_dir)

    # 檢查是否有變更
    status = run_git("status", "--porcelain", cwd=repo_dir)
    if not status:
        logger.info("沒有變更需要 commit")
        return

    run_git(
        "commit",
        "-m", f"feat: add tagesschau {pub_date_str}",
        cwd=repo_dir,
    )
    run_git("push", cwd=repo_dir)
    logger.info("文章已推送到遠端 repo")
