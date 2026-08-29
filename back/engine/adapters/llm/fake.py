"""테스트용 L3. 발화 텍스트 → JudgeDecision 스크립트. 없는 발화는 빈 결정(잠정 판정 유지)."""

from __future__ import annotations

from contracts.engine_contract import JudgeDecision, JudgePrompt


class ScriptedLlmJudge:
    def __init__(self, script: dict[str, JudgeDecision] | None = None) -> None:
        self.script = dict(script or {})
        self.prompts: list[JudgePrompt] = []

    def decide(self, prompt: JudgePrompt) -> JudgeDecision:
        """정확히 같은 발화가 우선, 없으면 스크립트 키가 발화에 포함되는 것."""
        self.prompts.append(prompt)
        text = prompt.utterance_text
        if text in self.script:
            return self.script[text]
        for key, decision in self.script.items():
            if key in text:
                return decision
        return JudgeDecision()
