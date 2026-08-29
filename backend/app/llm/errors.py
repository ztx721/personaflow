class LLMProviderError(RuntimeError):
    """A sanitized provider-boundary error safe to record in TurnLog."""

    def __init__(self, stage: str, code: str):
        super().__init__(f"{stage}:{code}")
        self.stage = stage
        self.code = code


class UnsafeGeneratorOutputError(LLMProviderError):
    def __init__(self):
        super().__init__("generator", "unsafe_output")


def error_label(stage: str, exc: Exception) -> str:
    """Return a stable label without exception text, prompts, keys, or URLs."""
    if isinstance(exc, LLMProviderError):
        return f"{stage}:{exc.code}"
    return f"{stage}:unexpected_error"
