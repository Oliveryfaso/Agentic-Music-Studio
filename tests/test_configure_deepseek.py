import importlib.util
import stat
import warnings
from pathlib import Path

import pytest


@pytest.mark.parametrize("kind", ["symlink", "dangling_symlink", "nonprivate"])
def test_clear_checks_parent_and_preserves_link_target(tmp_path, kind):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    secret = outside / "deepseek.env"
    secret.write_text("sk-mock-foreign-0123456789")
    secret.chmod(0o600)
    parent = tmp_path / "private"
    if kind == "nonprivate":
        parent.mkdir(mode=0o755)
        target = parent / "deepseek.env"
        target.write_bytes(secret.read_bytes())
    else:
        parent.symlink_to(
            outside if kind == "symlink" else tmp_path / "absent", target_is_directory=True
        )
        target = secret
    with pytest.raises(ValueError):
        module.clear_key(parent / "deepseek.env")
    assert secret.read_text() == "sk-mock-foreign-0123456789"
    if kind != "dangling_symlink":
        assert target.exists()


def test_clear_missing_parent_remains_idempotent(tmp_path):
    module.clear_key(tmp_path / "absent" / "deepseek.env")
    assert not (tmp_path / "absent").exists()


spec = importlib.util.spec_from_file_location(
    "configure_deepseek", Path(__file__).parents[1] / "scripts/configure_deepseek.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_private_write_replace_check_and_clear(tmp_path):
    target = tmp_path / ".env.deepseek.local"
    module.save_key(target, "sk-mock-0123456789abcdef")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_text() == "DEEPSEEK_API_KEY=sk-mock-0123456789abcdef\n"
    module.validate_file(target)
    module.save_key(target, "sk-replacement-0123456789")
    assert "mock" not in target.read_text()
    module.clear_key(target)
    assert not target.exists()
    module.clear_key(target)


def test_symlink_and_nonprivate_files_rejected(tmp_path):
    original = tmp_path / "original"
    original.write_text("keep")
    target = tmp_path / "secret"
    target.symlink_to(original)
    for action in [
        lambda: module.save_key(target, "sk-mock-0123456789abcdef"),
        lambda: module.clear_key(target),
        lambda: module.validate_file(target),
    ]:
        with pytest.raises(ValueError):
            action()
    assert original.read_text() == "keep"
    target.unlink()
    module.save_key(target, "sk-mock-0123456789abcdef")
    target.chmod(0o644)
    with pytest.raises(ValueError):
        module.validate_file(target)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "short",
        "sk-value\nLANGSMITH_TRACING=true",
        "sk-unsafe-$substitution0123456",
        " space0123456789abcd",
    ],
)
def test_invalid_keys_cannot_create_environment_lines(tmp_path, key):
    with pytest.raises(ValueError):
        module.save_key(tmp_path / "secret", key)
    assert list(tmp_path.iterdir()) == []


def test_hidden_input_and_clear_never_echo_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(module, "secret_path", lambda: tmp_path / "deepseek.env")
    monkeypatch.setattr(module.sys, "argv", ["configure_deepseek.py"])
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)
    key = "sk-mock-0123456789abcdef"
    prompts = []
    monkeypatch.setattr(module.getpass, "getpass", lambda prompt: prompts.append(prompt) or key)
    assert module.main() == 0 and prompts
    assert "NOT active yet" in capsys.readouterr().out
    monkeypatch.setattr(module.sys, "argv", ["configure_deepseek.py", "--clear"])
    assert module.main() == 0
    output = capsys.readouterr()
    assert key not in output.out + output.err
    assert not (tmp_path / "deepseek.env").exists()


def test_private_directory_required_before_key_bytes_are_written(tmp_path):
    directory = tmp_path / "nonprivate"
    directory.mkdir(mode=0o755)
    with pytest.raises(ValueError):
        module.save_key(directory / "deepseek.env", "sk-mock-0123456789abcdef")
    assert list(directory.iterdir()) == []


def test_failed_replacement_preserves_old_secret(tmp_path):
    target = tmp_path / "secret"
    module.save_key(target, "sk-mock-0123456789abcdef")
    before = target.read_bytes()
    with pytest.raises(ValueError):
        module.save_key(target, "invalid\nENV=value")
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


def test_hidden_input_failure_stops_before_echo_fallback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(module, "secret_path", lambda: tmp_path / "deepseek.env")
    monkeypatch.setattr(module.sys, "argv", ["configure_deepseek.py"])
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)

    def unsafe_fallback(prompt):
        warnings.warn("cannot disable terminal echo", module.getpass.GetPassWarning, stacklevel=2)
        pytest.fail("must stop before accepting visible input")

    monkeypatch.setattr(module.getpass, "getpass", unsafe_fallback)
    assert module.main() == 1
    assert not (tmp_path / "deepseek.env").exists()
    assert "Configuration failed" in capsys.readouterr().err
