"""전사 조립. 마스킹이 과하면 판정이 망가지고, 모자라면 개인정보가 영구 저장된다."""

from server.services.stt.assembler import MASK, mask_pii, split_sentences, utterances


def test_masks_account_and_resident_and_phone():
    got = mask_pii("계좌는 110-234-567890 이고 연락처는 010-1234-5678 입니다")
    assert "110-234-567890" not in got
    assert "010-1234-5678" not in got
    assert MASK in got

    # 주민번호는 앞 6자리를 남긴다. 생년월일은 상담 맥락에서 쓰이고 뒤가 민감하다
    got = mask_pii("주민번호 900101-1234567 확인했습니다")
    assert "900101" in got and "1234567" not in got


def test_does_not_touch_amounts_or_rates():
    """⑤ 숫자 오류 감지가 대조할 값이다. 마스킹이 이걸 지우면 판정이 죽는다."""
    for text in (
        "중도해지하시면 0.5% 정도는 받으세요",
        "연 0.10% 가 적용됩니다",
        "5천만원까지 보호됩니다",
        "50,000,000원 예치하셨습니다",
        "1개월 미만은 연 0.10%",
    ):
        assert mask_pii(text) == text, f"건드리면 안 되는 값이 바뀜: {text}"


def test_splits_sentences_so_verdicts_do_not_mix():
    """한 조각에 정상 고지와 숫자 오류가 섞이면 판정 대상이 뭉갠다."""
    got = split_sentences("우대이자율은 적용이 안 됩니다. 0.5% 정도는 받으세요.")
    assert got == ["우대이자율은 적용이 안 됩니다.", "0.5% 정도는 받으세요."]


def test_single_sentence_and_empty():
    assert split_sentences("중도해지하시면") == ["중도해지하시면"]
    assert split_sentences("   ") == []


def test_utterances_masks_before_splitting():
    got = utterances("계좌는 110-234-567890 입니다. 0.5% 받으세요.")
    assert len(got) == 2
    assert MASK in got[0] and "110-234-567890" not in got[0]
    assert got[1] == "0.5% 받으세요."
