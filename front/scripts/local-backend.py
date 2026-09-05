"""Run the existing backend against the local Docker DB, without changing backend files.

Use back/.venv/Scripts/python.exe front/scripts/local-backend.py from the repo root.
Optional: --seed, --env-file <team env>, --secret-file <shared age identity>.
Decryption reuses tools/envsecret.py and saves only inside front/ (gitignored).
Never generates replacement identities or overwrites an existing env/pack/volume.
"""

import argparse
import importlib.util
import os
import secrets
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

FRONT = Path(__file__).resolve().parents[1]
ROOT = FRONT.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-port", type=int, default=15432)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--docs-dir", type=Path, default=ROOT / "assets/03_규정문서")
    parser.add_argument("--env-file", type=Path, default=FRONT / ".env.backend.local")
    parser.add_argument("--secret-file", type=Path)
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    if not (1 <= args.db_port <= 65535 and 1 <= args.port <= 65535):
        parser.error("Ports must be between 1 and 65535")
    if not args.docs_dir.is_dir():
        parser.error("The supplied documents directory does not exist")
    if args.secret_file:
        if not args.secret_file.is_file():
            parser.error("The supplied age identity file does not exist")
        target = FRONT / ".env.backend.local"
        if target.exists():
            parser.error(
                "front/.env.backend.local already exists; it will not be overwritten"
            )
        spec = importlib.util.spec_from_file_location(
            "team_envsecret", ROOT / "tools/envsecret.py"
        )
        utility = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(utility)
        utility.ENV = target
        utility.SECRET = args.secret_file.resolve()
        utility.cmd_decrypt(utility._pyrage(), argparse.Namespace(force=False))
        args.env_file = target
    if args.env_file.is_file():
        load_dotenv(args.env_file, override=True)
        print("Loaded backend configuration (values are not logged)", flush=True)
    elif args.env_file != FRONT / ".env.backend.local":
        parser.error("The supplied env file does not exist")

    # Local override is deliberate: never migrate/seed a production DSN from a team env.
    env = dict(os.environ)
    env.update(
        {
            "PYTHONUTF8": "1",
            "POSTGRES_USER": "app",
            "POSTGRES_PASSWORD": "app",
            "POSTGRES_DB": "app",
            "POSTGRES_PORT": f"127.0.0.1:{args.db_port}",
            "APP_DATABASE_URL": f"postgresql+psycopg://app:app@127.0.0.1:{args.db_port}/app",
            "APP_PACK_DIR": str(ROOT / "back/contracts/fixtures"),
            "APP_DOCS_DIR": str(args.docs_dir.resolve()),
            "APP_EXTRACTION_DIR": str(ROOT / "assets/extraction"),
            "APP_UPLOAD_DIR": str(FRONT / ".local/uploads"),
        }
    )
    if not env.get("APP_ADMIN_TOKEN"):
        token_path = FRONT / ".admin-token"
        if not token_path.exists():
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(32))
        env["APP_ADMIN_TOKEN"] = token_path.read_text(encoding="utf-8").strip()
        if not env["APP_ADMIN_TOKEN"]:
            parser.error("front/.admin-token is empty; supply a valid APP_ADMIN_TOKEN")
        print(
            "Local administrator token: front/.admin-token (value not logged)",
            flush=True,
        )
    services = ["db"]
    if env.get("APP_STT_PROVIDER") == "openai_file":
        env.setdefault("APP_DIARIZATION_URL", "ws://127.0.0.1:8300/ws")
        services.append("diarization")
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "-f",
            "front/compose.local.yaml",
            "up",
            "-d",
            "--wait",
            *services,
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "back",
        env=env,
        check=True,
    )
    if args.seed:
        subprocess.run(
            [sys.executable, "scripts/load_pack.py", "--unsigned"],
            cwd=ROOT / "back",
            env=env,
            check=True,
        )
    missing = [
        name
        for name in ("APP_STT_API_KEY", "APP_LLM_MODEL", "APP_ADMIN_TOKEN")
        if not env.get(name)
    ]
    if missing:
        print("Configuration not supplied: " + ", ".join(missing), flush=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        cwd=ROOT / "back",
        env=env,
        check=True,
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
