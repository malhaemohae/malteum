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

# 값은 허용 표기 묶음이다. 한 패키지가 플랫폼마다 다른 문자열로 같은 빌드를
# 부르는 경우가 있어 하나로 못박으면 그 플랫폼에서 늘 실패한다.
PINNED_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "jsonschema": ("4.26.0",),
    "pypdfium2": ("5.13.0",),
    "opendataloader-pdf": ("2.3.0",),
    # 임베딩 벡터가 팩에 묶이므로 이 셋이 바뀌면 같은 항목도 다른 벡터가 된다.
    "sentence-transformers": ("5.1.2",),
    # macOS 휠에는 로컬 버전 접미사(`+cpu`)가 없다. 둘 다 같은 CPU 빌드라
    # 벡터가 달라지지 않는다. `uv.lock` 이 darwin 에만 접미사 없는 것을 준다.
    "torch": ("2.9.1+cpu", "2.9.1"),
    "transformers": ("4.57.6",),
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


def _products(repo_root: Path) -> list[str]:
    """상품 목록의 진실 원천은 `config/products.json` 이다.

    코드에 박아 두면 상품을 늘릴 때 설정과 코드를 둘 다 고쳐야 하고, 한쪽만
    고치면 조용히 빠진다 (2026-08-30).
    """
    doc = _read_json(paths.config_dir(repo_root) / "products.json")
    return sorted(doc)


def build_all(repo_root: Path, output: Path, work: Path) -> dict:
    rules = paths.config_dir(repo_root) / "candidate_rules.json"
    work.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rulepack_build_", dir=work.parent) as run_dir:
        run_work = Path(run_dir)
        bundles = {
            product: build_product_bundle(repo_root, product, rules, run_work / product)
            for product in _products(repo_root)
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
            # parser 는 상품이 아니라 실행 단위의 속성이라 아무 번들에서 꺼내도 같다.
            # 상품 이름을 박으면 상품 이름이 바뀔 때 여기서만 KeyError 로 죽는다.
            "parser": next(iter(bundles.values()))["parser"],
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
        name: {"allowed": list(allowed), "actual": installed[name]}
        for name, allowed in PINNED_DEPENDENCIES.items()
        if installed[name] not in allowed
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
        "dependency_versions_pinned": True,
        "java_major": java_major,
        "contracts_validate_exit_code": contracts.returncode,
    }


def _synthetic_version(bundle: dict) -> str:
    r"""dry-run 팩 버전. 계약이 `^[A-Z]{3,4}-\d{4}\.\d{2}-v\d+$` 를 강제한다.

    접두어는 항목 코드에서 딴다. 상품이 늘어도 코드를 안 고치게 하려는 것이고,
    이 버전은 검증 전용이라 운영 발행물이 되지 못한다.
    """
    code = bundle["items"][0]["code"]
    prefix = code.split("-", 1)[0]
    return f"{prefix}-2026.08-v1"


def verify(repo_root: Path, output: Path, strict: bool = False) -> dict:
    with (
        tempfile.TemporaryDirectory(prefix="rulepack_verify_") as first_dir,
        tempfile.TemporaryDirectory(prefix="rulepack_verify_") as second_dir,
    ):
        first = build_all(repo_root, Path(first_dir) / "artifacts", Path(first_dir) / "work")
        second = build_all(repo_root, Path(second_dir) / "artifacts", Path(second_dir) / "work")
        if canonical_json(first) != canonical_json(second):
            raise RuntimeError("결정적 재실행 불일치")
    # 검증용 항목은 번들에서 고른다. 코드에 박으면 그 항목이 폐기·보류로 바뀔 때
    # dry-run 이 통째로 실패하고, 원인이 계약이 아니라 이 목록이 낡은 것이 된다.
    dry_run = {}
    for product, bundle in first.items():
        codes = [item["code"] for item in bundle["items"] if item["status"] == "evidence_verified"]
        if not codes:
            raise RuntimeError(f"{product}: 근거 검증을 통과한 항목이 없어 dry-run 을 못 만듦")
        approval = {
            "approved_by": "synthetic-reviewer",
            "approved_at": "2026-08-26T00:00:00Z",
            "item_codes": [codes[0]],
            "bundle_sha256": approval_digest(bundle),
        }
        dry_run[product] = compile_synthetic_pack(
            repo_root, bundle, approval, _synthetic_version(bundle)
        )
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


def build_parser() -> argparse.ArgumentParser:
    """인자 정의. 문서가 적은 사용법이 실제로 파싱되는지 테스트가 이걸로 확인한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify", "compile", "publish"))
    parser.add_argument("--repo-root", type=Path, default=paths.find_repo_root())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
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
