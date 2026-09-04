#!/usr/bin/env python3
"""루트 .env 를 age 로 암호화해 저장소에 두고(.env.age), 필요한 사람만 푼다.

    python tools/envsecret.py decrypt            .env.age → .env      (팀원이 처음 받을 때)
    python tools/envsecret.py encrypt            .env    → .env.age   (값을 바꾼 뒤)
    python tools/envsecret.py keygen             새 개인키 .secret 발급 + 공개키 출력
    python tools/envsecret.py add-key age1...    수신자 추가(deploy/env.recipients) 뒤 다시 암호화
    python tools/envsecret.py keys               수신자 목록

개인키는 루트 `.secret`(age 개인키 파일, gitignore) 또는 환경변수 `MALTEUM_AGE_KEY`(파일 내용
그대로)에서 읽는다. Jenkins 는 후자다. 수신자(공개키) 목록은 `deploy/env.recipients` 에 있고
커밋된다 — 누가 풀 수 있는지가 저장소에 남는다.

age 구현은 pyrage(PyPI, 윈도우·맥·리눅스 휠)를 쓰고 없으면 이 파이썬으로 설치를 시도한다.
age CLI 와 같은 형식이라 `age -d -i .secret .env.age` 로도 풀린다.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
ENV_AGE = ROOT / ".env.age"
SECRET = ROOT / ".secret"
RECIPIENTS = ROOT / "deploy" / "env.recipients"
KEY_ENV = "MALTEUM_AGE_KEY"


def _pyrage():
    try:
        import pyrage
    except ImportError:
        print("pyrage 가 없어 설치합니다 (pip install pyrage) …", file=sys.stderr)
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", "pyrage"]
        if not _in_venv():
            cmd.insert(4, "--user")
        try:
            subprocess.run(cmd, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            sys.exit(
                "pyrage 설치 실패. 직접 설치하세요: `python -m pip install pyrage` "
                "(윈도우는 python.org 파이썬 3.9+ 권장). 또는 age CLI: "
                "`age -d -i .secret .env.age > .env`"
            )
        import pyrage
    return pyrage


def _in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _identity(pyrage):
    raw = os.environ.get(KEY_ENV)
    if not raw and SECRET.exists():
        raw = SECRET.read_text(encoding="utf-8")
    if not raw:
        sys.exit(
            f"개인키가 없습니다. {SECRET.name} 파일(공유받은 것)을 레포 루트에 두거나 {KEY_ENV} 를 주세요."
        )
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("AGE-SECRET-KEY-"):
            return pyrage.x25519.Identity.from_str(line)
    sys.exit("개인키 형식이 아닙니다 (AGE-SECRET-KEY- 로 시작하는 줄이 없음)")


def _recipients(pyrage):
    if not RECIPIENTS.exists():
        sys.exit(
            f"{RECIPIENTS.relative_to(ROOT)} 가 없습니다. 먼저 `keygen` 으로 만드세요."
        )
    keys = [
        line.split("#", 1)[0].strip()
        for line in RECIPIENTS.read_text(encoding="utf-8").splitlines()
    ]
    keys = [k for k in keys if k]
    if not keys:
        sys.exit("수신자 목록이 비어 있습니다")
    return [pyrage.x25519.Recipient.from_str(k) for k in keys], keys


def _write_private(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    if os.name != "nt":
        os.chmod(path, 0o600)


def cmd_encrypt(pyrage, _args) -> None:
    if not ENV.exists():
        sys.exit(".env 가 없습니다")
    recipients, keys = _recipients(pyrage)
    ENV_AGE.write_bytes(pyrage.encrypt(ENV.read_bytes(), recipients))
    print(f".env → {ENV_AGE.name} (수신자 {len(keys)}명). 커밋하세요.")


def cmd_decrypt(pyrage, args) -> None:
    if not ENV_AGE.exists():
        sys.exit(f"{ENV_AGE.name} 가 없습니다")
    if ENV.exists() and not args.force:
        sys.exit(".env 가 이미 있습니다. 덮어쓰려면 --force")
    _write_private(ENV, pyrage.decrypt(ENV_AGE.read_bytes(), [_identity(pyrage)]))
    print(f"{ENV_AGE.name} → .env")


def cmd_keygen(pyrage, args) -> None:
    if SECRET.exists() and not args.force:
        sys.exit(
            f"{SECRET.name} 가 이미 있습니다. 새로 만들려면 --force (기존 키로 푼 사람은 못 풀게 됩니다)"
        )
    ident = pyrage.x25519.Identity.generate()
    pub = str(ident.to_public())
    _write_private(SECRET, f"# public key: {pub}\n{ident}\n".encode())
    RECIPIENTS.parent.mkdir(parents=True, exist_ok=True)
    with RECIPIENTS.open("a", encoding="utf-8") as f:
        f.write(f"{pub}  # {args.label or 'keygen'}\n")
    print(f"{SECRET.name} 발급. 공개키(수신자 목록에 추가됨): {pub}")
    print("개인키 파일은 저장소에 올리지 말고 Bitwarden 같은 곳으로 공유하세요.")


def cmd_add_key(pyrage, args) -> None:
    pyrage.x25519.Recipient.from_str(args.public_key)  # 형식 검사
    RECIPIENTS.parent.mkdir(parents=True, exist_ok=True)
    with RECIPIENTS.open("a", encoding="utf-8") as f:
        f.write(f"{args.public_key}  # {args.label or 'added'}\n")
    print(f"수신자 추가: {args.public_key}")
    if ENV.exists():
        cmd_encrypt(pyrage, args)
    else:
        print(".env 가 없어 다시 암호화하지 않았습니다. 푼 뒤 `encrypt` 를 돌리세요.")


def cmd_keys(_pyrage, _args) -> None:
    print(RECIPIENTS.read_text(encoding="utf-8") if RECIPIENTS.exists() else "(없음)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("encrypt")
    d = sub.add_parser("decrypt")
    d.add_argument("--force", action="store_true", help="기존 .env 를 덮어쓴다")
    k = sub.add_parser("keygen")
    k.add_argument("--label", help="수신자 목록에 남길 이름")
    k.add_argument("--force", action="store_true")
    a = sub.add_parser("add-key")
    a.add_argument("public_key", help="age1... 공개키")
    a.add_argument("--label")
    sub.add_parser("keys")
    args = p.parse_args(argv)
    pyrage = _pyrage()
    {
        "encrypt": cmd_encrypt,
        "decrypt": cmd_decrypt,
        "keygen": cmd_keygen,
        "add-key": cmd_add_key,
        "keys": cmd_keys,
    }[args.cmd](pyrage, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
