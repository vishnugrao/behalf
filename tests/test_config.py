import importlib
import sys


def reload_config(monkeypatch, tmp_path, contents: str):
    (tmp_path / ".env").write_text(contents)
    monkeypatch.chdir(tmp_path)
    for name in [m for m in sys.modules if m.startswith("behalf")]:
        del sys.modules[name]
    return importlib.import_module("behalf.config")


def test_dotenv_reaches_the_dataclass_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BEHALF_PROVIDER", raising=False)
    mod = reload_config(monkeypatch, tmp_path, "ANTHROPIC_API_KEY=sk-ant-test\n")
    assert mod.CONFIG.anthropic_api_key == "sk-ant-test"
    assert mod.CONFIG.resolve_provider() == "anthropic"


def test_real_environment_beats_dotenv(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    mod = reload_config(monkeypatch, tmp_path, "ANTHROPIC_API_KEY=sk-ant-from-file\n")
    assert mod.CONFIG.anthropic_api_key == "sk-ant-from-env"


def test_openai_is_used_when_only_its_key_is_present(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("BEHALF_PROVIDER", raising=False)
    mod = reload_config(monkeypatch, tmp_path, "OPENAI_API_KEY=sk-openai\n")
    assert mod.CONFIG.resolve_provider() == "openai"


def test_no_keys_falls_back_to_scripted(monkeypatch, tmp_path):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BEHALF_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    mod = reload_config(monkeypatch, tmp_path, "")
    assert mod.CONFIG.resolve_provider() == "scripted"
