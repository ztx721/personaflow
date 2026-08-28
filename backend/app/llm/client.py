from abc import ABC, abstractmethod

from ..schemas import GeneratorContext, PlannerContext, PlannerOutput


class LLMClient(ABC):
    """LLM 供应商抽象：plan 出结构化行为提案，generate 出纯文本台词。

    Mock 实现确定性决策（测试/Eval/离线开发）；Anthropic 实现走 PromptBuilder + 结构化输出。
    """

    @abstractmethod
    def plan(self, ctx: PlannerContext) -> PlannerOutput:
        ...

    @abstractmethod
    def generate(self, ctx: GeneratorContext) -> str:
        ...
