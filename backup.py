"""타임스탬프 기반 백업 스크립트.

사용: python backup.py [메모]
  - 백업/2026-04-21_14-30/ 하위 폴더로 전체 코드 스냅샷
  - optional 메모 인자: 폴더명 뒤에 _메모 추가됨
"""

import os
import sys
import shutil
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(ROOT, "백업")
KEEP_RECENT = 5  # 최신 N개만 유지, 그보다 오래된 건 자동 삭제

# 백업할 대상 (파일·폴더)
INCLUDE = [
    "app.py",
    "kr_stocks.py",
    "requirements.txt",
    "render.yaml",
    "README.md",
    "make_icons.py",
    "backup.py",
    "analysis",
    "data",
    "routes",
    "scripts",
    "templates",
    "static",
]

# 제외할 패턴 (개별 파일 이름이나 폴더 이름)
EXCLUDE_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db"}
EXCLUDE_EXT = {".pyc", ".pyo", ".backup"}


def _should_copy(name: str) -> bool:
    if name in EXCLUDE_NAMES:
        return False
    for ext in EXCLUDE_EXT:
        if name.endswith(ext):
            return False
    return True


def _copy_tree(src: str, dst: str):
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return
    os.makedirs(dst, exist_ok=True)
    for item in os.listdir(src):
        if not _should_copy(item):
            continue
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            _copy_tree(s, d)
        else:
            shutil.copy2(s, d)


def create_backup(memo: str = "") -> str:
    # 한국 시간 기준
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    stamp = now.strftime("%Y-%m-%d_%H-%M")

    folder_name = stamp + (f"_{memo}" if memo else "")
    target = os.path.join(BACKUP_ROOT, folder_name)

    if os.path.exists(target):
        target = target + "_duplicate"
    os.makedirs(target, exist_ok=True)

    copied = 0
    for item in INCLUDE:
        src = os.path.join(ROOT, item)
        if not os.path.exists(src):
            continue
        dst = os.path.join(target, item)
        _copy_tree(src, dst)
        copied += 1

    # 메타 파일 추가
    meta_path = os.path.join(target, "_BACKUP_INFO.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"백업 일시 (KST): {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"메모: {memo if memo else '(없음)'}\n")
        f.write(f"소스 경로: {ROOT}\n")
        f.write(f"포함 항목: {len(INCLUDE)}개\n")
        try:
            import subprocess
            git_hash = subprocess.check_output(
                ["git", "log", "-1", "--format=%H"],
                cwd=ROOT, stderr=subprocess.DEVNULL
            ).decode().strip()
            f.write(f"Git 커밋: {git_hash[:12]}\n")
        except Exception:
            pass

    print(f"✓ 백업 완료: {target}")
    print(f"  항목 {copied}개 복사")

    _prune_old_backups()
    return target


def _prune_old_backups():
    """BACKUP_ROOT 안에서 최신 KEEP_RECENT개 빼고 전부 삭제."""
    if not os.path.isdir(BACKUP_ROOT):
        return
    entries = [
        (name, os.path.getmtime(os.path.join(BACKUP_ROOT, name)))
        for name in os.listdir(BACKUP_ROOT)
        if os.path.isdir(os.path.join(BACKUP_ROOT, name))
    ]
    entries.sort(key=lambda x: x[1], reverse=True)  # 최신 먼저
    for name, _ in entries[KEEP_RECENT:]:
        path = os.path.join(BACKUP_ROOT, name)
        try:
            shutil.rmtree(path)
            print(f"  🗑 오래된 백업 삭제: {name}")
        except Exception as e:
            print(f"  ⚠ 삭제 실패 {name}: {e}")


if __name__ == "__main__":
    memo = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    create_backup(memo)
