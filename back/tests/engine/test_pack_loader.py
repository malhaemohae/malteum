import pytest

from contracts.engine_contract import Evidence
from engine.adapters.pack_source.file import FilePackSource
from engine.pack.loader import PackRejected, load_pack
from engine.pack.source import PackNotFound
from tests.engine.conftest import FIX, PACK_VERSION
from tests.engine.fakes import FakePackSource


def test_fixture_pack_loads(pack_json):
    pack = load_pack(FakePackSource(pack_json), PACK_VERSION)
    assert pack.pack_version == PACK_VERSION
    assert pack.embedding_dim == 384
    assert len(pack.items) == 9
    assert [it.code for it in pack.required_items()] == [
        "DEP-INT-001", "DEP-INT-002", "DEP-INT-003", "DEP-PRO-001", "DEP-TAX-001", "DEP-LIM-001",
    ]  # fmt: skip
    assert [it.code for it in pack.forbidden_items()] == ["DEP-BAN-001"]
    assert pack.item("DEP-DOC-001").type == "reference"
    assert pack.item("NOPE") is None


def test_items_carry_evidence_and_patterns(pack_json):
    pack = load_pack(FakePackSource(pack_json), PACK_VERSION)
    it = pack.item("DEP-INT-001")
    assert isinstance(it.evidence, Evidence)
    assert it.evidence.page == 1 and len(it.evidence.bbox) == 4
    assert ("keyword", "우대이자율") in it.l1_patterns
    assert it.plain_language


def test_file_source_reads_fixture_dir():
    pack = load_pack(FilePackSource(FIX), PACK_VERSION)
    assert pack.product_code == "ICBC-KRW-TD"


def test_missing_pack():
    with pytest.raises(PackNotFound):
        load_pack(FilePackSource(FIX), "DEP-1999.01-v1")


def test_embedding_dim_mismatch_rejected(pack_json):
    with pytest.raises(PackRejected):
        load_pack(FakePackSource(pack_json), PACK_VERSION, embedder_dim=768)
