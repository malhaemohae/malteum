from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import paths
from .compiler import approval_digest, compile_pack, compile_synthetic_pack, publish_immutable
from .pipeline import build_product_bundle, canonical_json

PINNED_DEPENDENCIES = {
    "jsonschema": "4.26.0",
    "pypdfium2": "5.13.0",
    "opendataloader-pdf": "2.3.0",
}


def _java_major(version_output: str) -> int:
    match = re.search(r'version\s+"(\d+)(?:\.(\d+))?', version_output)
    if not match:
        raise RuntimeError("Java 버전을 해석할 수 없음")
    first = int(match.group(1))
    return int(match.group(2)) if first == 1 and match.group(2) else first


def _require_java17(version_output: str) -> int:
    major = _java_major(version_output)
    if major < 17:
        raise RuntimeError(f"Java 17 이상 필요, 현재 major={major}")
    return major


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_all(repo_root: Path, output: Path, work: Path) -> dict:
    rules = paths.config_dir(repo_root) / "candidate_rules.json"
    work.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rulepack_build_", dir=work.parent) as run_dir:
        run_work = Path(run_dir)
        bundles = {
            product: build_product_bundle(repo_root, product, rules, run_work / product)
            for product in ("deposit", "loan")
        }
    for product, bundle in bundles.items():
        _write(output / f"review_{product}.json", bundle)
    queue = {
        "extraction_success": [
            item
            for bundle in bundles.values()
            for item in bundle["items"]
            if item["status"] == "evidence_verified"
        ],
        "automatic_rejection": [
            item
            for bundle in bundles.values()
            for item in bundle["items"]
            if item["status"] == "rejected"
        ],
        "review_required": [
            item
            for bundle in bundles.values()
            for item in bundle["items"]
            if item["status"] == "review_required"
        ],
    }
    _write(output / "review_queue.json", queue)
    _write(
        output / "run_manifest.json",
        {
            "parser": bundles["deposit"]["parser"],
            "sources": {
                source["doc_id"]: source
                for bundle in bundles.values()
                for source in bundle["sources"]
            },
        },
    )
    return bundles


def _strict_checks(repo_root: Path) -> dict[str, object]:
    installed = {name: importlib.metadata.version(name) for name in PINNED_DEPENDENCIES}
    mismatches = {
        name: {"expected": expected, "actual": installed[name]}
        for name, expected in PINNED_DEPENDENCIES.items()
        if installed[name] != expected
    }
    if mismatches:
        raise RuntimeError(f"고정 의존성 버전 불일치: {mismatches}")
    java = subprocess.run(
        ["java", "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if java.returncode != 0:
        raise RuntimeError("Java 실행 환경 없음")
    java_major = _require_java17(java.stdout + java.stderr)
    contracts = subprocess.run(
        [sys.executable, str(paths.contracts_dir(repo_root) / "validate.py")],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if contracts.returncode != 0:
        raise RuntimeError("contracts/validate.py 실패: " + contracts.stdout + contracts.stderr)
    return {
        "dependency_versions_exact": True,
        "java_major": java_major,
        "contracts_validate_exit_code": contracts.returncode,
    }


def verify(repo_root: Path, output: Path, strict: bool = False) -> dict:
    with (
        tempfile.TemporaryDirectory(prefix="rulepack_verify_") as first_dir,
        tempfile.TemporaryDirectory(prefix="rulepack_verify_") as second_dir,
    ):
        first = build_all(repo_root, Path(first_dir) / "artifacts", Path(first_dir) / "work")
        second = build_all(repo_root, Path(second_dir) / "artifacts", Path(second_dir) / "work")
        if canonical_json(first) != canonical_json(second):
            raise RuntimeError("결정적 재실행 불일치")
    approvals = {
        product: {
            "approved_by": "synthetic-reviewer",
            "approved_at": "2026-08-26T00:00:00Z",
            "item_codes": [code],
            "bundle_sha256": approval_digest(first[product]),
        }
        for product, code in (("deposit", "DEP-INT-002"), ("loan", "LOAN-ARR-001"))
    }
    versions = {"deposit": "DEP-2026.08-v1", "loan": "LOAN-2026.08-v1"}
    dry_run = {
        product: compile_synthetic_pack(
            repo_root, first[product], approvals[product], versions[product]
        )
        for product in approvals
    }
    for product, envelope in dry_run.items():
        _write(output / "dry_run" / f"synthetic_{product}.json", envelope)
    summary = {
        "deterministic": True,
        "dependencies": {name: importlib.metadata.version(name) for name in PINNED_DEPENDENCIES},
        "products": {product: bundle["counts"] for product, bundle in first.items()},
        "production_published": False,
        "human_approval_required": True,
        "strict": strict,
    }
    if strict:
        summary["strict_checks"] = _strict_checks(repo_root)
    _write(output / "verification_summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify", "compile", "publish"))
    parser.add_argument("--repo-root", type=Path, default=paths.find_repo_root())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    output = (args.output or paths.default_artifacts_dir(root)).resolve()
    work = paths.default_work_dir(root)

    if args.command == "build":
        result = build_all(root, output, work)
        print(canonical_json({product: bundle["counts"] for product, bundle in result.items()}))
    elif args.command == "verify":
        print(canonical_json(verify(root, output, strict=args.strict)))
    else:
        if not args.bundle or not args.approval or not args.version:
            parser.error(f"{args.command}에는 --bundle, --approval, --version이 필요함")
        pack = compile_pack(root, _read_json(args.bundle), _read_json(args.approval), args.version)
        if args.command == "compile":
            path = output / f"compiled_{args.version}.json"
            _write(path, pack)
            print(canonical_json({"status": "compiled", "path": str(path)}))
        else:
            print(
                canonical_json({"status": publish_immutable(pack, output), "version": args.version})
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
