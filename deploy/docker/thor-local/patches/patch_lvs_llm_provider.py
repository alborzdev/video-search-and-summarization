"""Add provider-aware vLLM request options to the released LVS runtime."""

from pathlib import Path
import sysconfig


module = (
    Path(sysconfig.get_paths()["purelib"])
    / "vss_ctx_rag"
    / "tools"
    / "llm"
    / "llm_handler.py"
)
source = module.read_text()


def replace_once(old: str, new: str) -> None:
    global source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one LVS patch marker, found {count}: {old!r}")
    source = source.replace(old, new, 1)


replace_once(
    "    seed: Optional[int] = Field(default=None)\n",
    "    seed: Optional[int] = Field(default=None)\n"
    "    provider: str = Field(default=\"openai\")\n"
    "    enable_thinking: Optional[bool] = Field(default=None)\n",
)

replace_once(
    '        llm_params = {\n            "temperature": self.config.params.temperature,\n        }\n',
    '        llm_params = {\n            "temperature": self.config.params.temperature,\n        }\n'
    '        provider = (self.config.params.provider or "openai").strip().lower()\n'
    '        if provider not in {"nim", "openai", "vllm"}:\n'
    '            raise ValueError(f"Unsupported LVS LLM provider: {provider}")\n'
    '        if provider == "vllm" and self.config.params.enable_thinking is not None:\n'
    '            llm_params["extra_body"] = {\n'
    '                "chat_template_kwargs": {\n'
    '                    "enable_thinking": self.config.params.enable_thinking\n'
    '                }\n'
    '            }\n',
)

module.write_text(source)
Path(__file__).unlink()
