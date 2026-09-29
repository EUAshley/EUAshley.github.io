from .base import ScriptDraft, ScriptGenerator
from .claude import ClaudeGenerator
from .template import TemplateGenerator

_GENERATORS: dict[str, ScriptGenerator] = {g.name: g for g in (TemplateGenerator(), ClaudeGenerator())}


def get(name: str = "template") -> ScriptGenerator:
    gen = _GENERATORS.get(name)
    if gen is None:
        raise ValueError(f"Unknown generator '{name}'")
    if not gen.available():
        raise ValueError(f"Generator '{name}' is not available (missing API key or package?)")
    return gen


def available() -> list[str]:
    return [n for n, g in _GENERATORS.items() if g.available()]


__all__ = ["ScriptDraft", "ScriptGenerator", "get", "available"]
