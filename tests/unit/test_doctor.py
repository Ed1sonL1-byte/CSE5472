from seedbridge.doctor import tool_environment


def test_ambient_compiler_overrides_cannot_change_pinned_build(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PROFILE", "unexpected")
    monkeypatch.setenv("FOUNDRY_OPTIMIZER", "true")
    monkeypatch.setenv("FOUNDRY_EVM_VERSION", "cancun")
    monkeypatch.setenv("DAPP_REMAPPINGS", "unexpected")
    monkeypatch.setenv("HALMOS_FFI", "true")
    env = tool_environment()
    assert env["FOUNDRY_PROFILE"] == "default"
    assert env["FOUNDRY_OPTIMIZER"] == "false"
    assert env["FOUNDRY_EVM_VERSION"] == "shanghai"
    assert "DAPP_REMAPPINGS" not in env
    assert "HALMOS_FFI" not in env
