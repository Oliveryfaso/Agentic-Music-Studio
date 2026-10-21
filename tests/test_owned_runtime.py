"""Black-box ownership boundaries; fake Docker never manages host resources."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/motif_runtime_owner.mjs"
STOPPER = ROOT / "scripts/stop_motif_forge.sh"


def executable(path, source):
    path.write_text(source)
    path.chmod(0o755)


def setup(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    state = tmp_path / "state.json"
    log = tmp_path / "commands.jsonl"
    runtime = tmp_path / "runtime"
    state.write_text(json.dumps({"daemon": "test-daemon", "containers": []}))
    executable(
        bindir / "docker",
        """#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
a=sys.argv[1:];p=Path(os.environ['FAKE_DOCKER_STATE']);s=json.loads(p.read_text())
with open(os.environ['FAKE_DOCKER_LOG'],'a') as f:f.write(json.dumps(a)+'\\n')
if a[0]=='info':
 if s.get('hang_info'):
  import signal,time
  signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)
 print(s['daemon']);sys.exit(s.get('info_exit',0))
if a[0]=='ps':
 project=next(x.split('=',2)[2] for x in a if x.startswith('label=com.docker.compose.project='))
 ids=[c['Id'] for c in s['containers']
      if c['Config']['Labels']['com.docker.compose.project']==project]
 print('\\n'.join(ids));sys.exit(0)
if a[0]=='inspect':
 c=next(c for c in s['containers'] if c['Id']==a[-1]);labels=c['Config']['Labels']
 public={'Id':c['Id'],'Project':labels['com.docker.compose.project'],
         'Owner':labels['io.motif-forge.runtime-owner'],'Running':c['State']['Running']}
 print(json.dumps(public));sys.exit(0)
if a[0] in ('volume','network'):
 resources=s.get('volumes' if a[0]=='volume' else 'networks',[])
 if a[1]=='ls':
  rule=a[a.index('--filter')+1]
  matches=[r for r in resources if
   (rule.startswith('label=') and r.get('project')==rule.split('=',2)[2]) or
   (rule.startswith('name=^') and r['name']==rule[len('name=^'):-1])]
  print('\\n'.join(r['name'] for r in matches));sys.exit(0)
 if a[1]=='inspect':
  r=next(r for r in resources if r['name']==a[-1])
  fmt=a[a.index('--format')+1]
  values={'{{json .Name}}':r['name'],
   '{{json (index .Labels "com.docker.compose.project")}}':r.get('project'),
   '{{json (index .Labels "io.motif-forge.runtime-owner")}}':r['owner']}
  for token,value in values.items():fmt=fmt.replace(token,json.dumps(value))
  print(fmt);sys.exit(0)
if a[0]=='stop':
 for c in s['containers']:
  if c['Id'] in a[1:]:c['State']['Running']=False
 p.write_text(json.dumps(s));sys.exit(0)
sys.exit(77)
""",
    )
    executable(
        bindir / "colima",
        '#!/usr/bin/env bash\nprintf \'["COLIMA", "%s"]\\n\' "$*" >> "$FAKE_DOCKER_LOG"\nexit 0\n',
    )
    env = {
        "LANG": "C.UTF-8",
        "TMPDIR": str(tmp_path),
        "PATH": str(bindir) + ":" + os.environ["PATH"],
        "FAKE_DOCKER_STATE": str(state),
        "FAKE_DOCKER_LOG": str(log),
        "MOTIF_FORGE_RUNTIME_DIR": str(runtime),
    }
    return runtime, state, log, env


def commands(log):
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def run(*args, env):
    return subprocess.run(
        args, env=env, cwd=ROOT, capture_output=True, text=True, timeout=12, check=False
    )


def prepare(runtime, env):
    return run(
        "node",
        str(HELPER),
        "prepare",
        str(ROOT),
        str(runtime),
        "motif-owned-test",
        env=env,
    )


def container(ident, owner, project="motif-owned-test"):
    return {
        "Id": ident * 64,
        "Config": {
            "Labels": {
                "com.docker.compose.project": project,
                "io.motif-forge.runtime-owner": owner,
            }
        },
        "State": {"Running": True},
    }


def receipt(runtime):
    return json.loads((runtime / "stack.json").read_text())


def test_stop_without_receipt_never_touches_shared_docker_or_colima(tmp_path):
    _runtime, _state, log, env = setup(tmp_path)
    result = run("bash", str(STOPPER), env=env)
    assert commands(log) == []
    assert result.returncode == 0, result.stderr


def test_prepare_writes_nonsecret_ownership_for_an_empty_project(tmp_path):
    runtime, _state, log, env = setup(tmp_path)
    result = prepare(runtime, env)
    assert result.returncode == 0, result.stderr
    r = receipt(runtime)
    assert (
        r["project_root"] == str(ROOT.resolve())
        and r["compose_project"] == "motif-owned-test"
    )
    assert r["daemon_id"] == "test-daemon" and len(r["owner"]) == 36
    assert not any(a[0] in {"stop", "compose", "COLIMA"} for a in commands(log))
    assert (runtime / "stack.json").stat().st_mode & 0o777 == 0o600


def test_prepare_refuses_to_adopt_an_existing_unrecorded_project(tmp_path):
    runtime, state, log, env = setup(tmp_path)
    state.write_text(
        json.dumps(
            {"daemon": "test-daemon", "containers": [container("a", "unmanaged")]}
        )
    )
    result = prepare(runtime, env)
    assert result.returncode != 0 and "UNOWNED" in result.stderr
    assert not (runtime / "stack.json").exists()
    assert not any(a[0] in {"stop", "compose", "COLIMA"} for a in commands(log))


def test_owned_stop_uses_exact_ids_preserves_data_and_is_repeatable(tmp_path):
    runtime, state, log, env = setup(tmp_path)
    prepared = prepare(runtime, env)
    assert prepared.returncode == 0, prepared.stderr
    owner = receipt(runtime)["owner"]
    data = runtime / "kept-project"
    data.write_text("retained")
    state.write_text(
        json.dumps(
            {
                "daemon": "test-daemon",
                "containers": [
                    container("a", owner),
                    container("b", owner),
                    container("c", "other", "unrelated-project"),
                ],
            }
        )
    )
    for _ in range(2):
        result = run("bash", str(STOPPER), env=env)
        assert result.returncode == 0, result.stderr
    assert [a for a in commands(log) if a[0] == "stop"] == [
        ["stop", "a" * 64, "b" * 64]
    ]
    assert not any(
        (a[0] in {"compose", "COLIMA", "rm", "system"})
        or (a[0] in {"volume", "network"} and a[1] not in {"ls", "inspect"})
        for a in commands(log)
    )
    assert json.loads(state.read_text())["containers"][2]["State"]["Running"]
    assert data.read_text() == "retained" and receipt(runtime)["owner"] == owner


@pytest.mark.parametrize(
    "mismatch", ["daemon", "owner", "root", "receipt-link", "directory-link"]
)
def test_identity_mismatch_never_stops_any_container(tmp_path, mismatch):
    runtime, state, log, env = setup(tmp_path)
    prepared = prepare(runtime, env)
    assert prepared.returncode == 0, prepared.stderr
    owner = receipt(runtime)["owner"]
    r = receipt(runtime)
    s = {"daemon": "test-daemon", "containers": [container("a", owner)]}
    if mismatch == "daemon":
        s["daemon"] = "another-daemon"
    if mismatch == "owner":
        s["containers"][0]["Config"]["Labels"]["io.motif-forge.runtime-owner"] = (
            "other-owner"
        )
    if mismatch == "root":
        r["project_root"] = "/unrelated/project"
    (runtime / "stack.json").write_text(json.dumps(r))
    if mismatch == "receipt-link":
        (runtime / "stack.json").rename(runtime / "target.json")
        (runtime / "stack.json").symlink_to(runtime / "target.json")
    if mismatch == "directory-link":
        actual = tmp_path / "actual"
        runtime.rename(actual)
        runtime.symlink_to(actual, target_is_directory=True)
    state.write_text(json.dumps(s))
    result = run("bash", str(STOPPER), env=env)
    assert result.returncode != 0
    assert not any(a[0] in {"stop", "compose", "COLIMA", "rm"} for a in commands(log))


def test_docker_failure_does_not_try_to_start_or_stop_a_vm(tmp_path):
    runtime, state, log, env = setup(tmp_path)
    state.write_text(
        json.dumps({"daemon": "test-daemon", "containers": [], "info_exit": 1})
    )
    result = prepare(runtime, env)
    assert result.returncode != 0
    assert not any(a[0] == "COLIMA" for a in commands(log))


def test_unresponsive_docker_is_bounded_even_when_it_ignores_term(tmp_path):
    import time

    runtime, state, _log, env = setup(tmp_path)
    state.write_text(
        json.dumps({"daemon": "test-daemon", "containers": [], "hang_info": True})
    )
    before = time.monotonic()
    result = prepare(runtime, env)
    assert result.returncode != 0 and time.monotonic() - before < 6
    assert not (runtime / "stack.json").exists()


def test_whole_set_is_verified_before_any_container_is_stopped(tmp_path):
    runtime, state, log, env = setup(tmp_path)
    assert prepare(runtime, env).returncode == 0
    owner = receipt(runtime)["owner"]
    state.write_text(
        json.dumps(
            {
                "daemon": "test-daemon",
                "containers": [container("a", owner), container("b", "foreign-owner")],
            }
        )
    )
    result = run("bash", str(STOPPER), env=env)
    assert result.returncode != 0
    assert not any(a[0] == "stop" for a in commands(log))
    inspections = [a for a in commands(log) if a[0] == "inspect"]
    assert inspections and all(
        a[1] == "--format" and ".Config.Env" not in a[2] for a in inspections
    )


def test_nonprivate_metadata_is_rejected_before_signalling_web(tmp_path):
    runtime, _state, log, env = setup(tmp_path)
    runtime.mkdir(mode=0o755)
    runtime.chmod(0o755)
    sleeper = subprocess.Popen(["sleep", "60"])
    executable(
        tmp_path / "bin/ps",
        """#!/usr/bin/env bash
case "$*" in
  *lstart=*) echo owned-test-start;;
  *command=*) echo 'npm run dev:web';;
  *) echo S;;
esac
""",
    )
    (runtime / "web.pid").write_text(f"{sleeper.pid}\n{ROOT}\nowned-test-start\n")
    try:
        result = run("bash", str(STOPPER), env=env)
        assert sleeper.poll() is None, (
            "untrusted metadata must never authorize a signal"
        )
        assert result.returncode != 0
        assert commands(log) == []
    finally:
        if sleeper.poll() is None:
            sleeper.terminate()
        sleeper.wait(timeout=5)


@pytest.mark.parametrize("kind", ["volumes", "networks"])
@pytest.mark.parametrize("labelled", [True, False])
def test_prepare_refuses_orphaned_persistent_resource_without_container(
    tmp_path, kind, labelled
):
    runtime, state, log, env = setup(tmp_path)
    resource = {
        "name": "motif-owned-test"
        + ("_motif_forge_postgres" if kind == "volumes" else "_default"),
        "project": "motif-owned-test" if labelled else None,
        "owner": "unmanaged",
    }
    state.write_text(
        json.dumps({"daemon": "test-daemon", "containers": [], kind: [resource]})
    )
    result = prepare(runtime, env)
    assert result.returncode != 0 and "UNOWNED" in result.stderr
    assert not (runtime / "stack.json").exists()
    assert not any(
        call[0] in {"stop", "compose", "COLIMA", "rm"} for call in commands(log)
    )


def test_recorded_persistent_resources_restart_with_original_owner(tmp_path):
    runtime, state, _log, env = setup(tmp_path)
    assert prepare(runtime, env).returncode == 0
    original = receipt(runtime)
    state.write_text(
        json.dumps(
            {
                "daemon": "test-daemon",
                "containers": [],
                "volumes": [
                    {
                        "name": "motif-owned-test_motif_forge_postgres",
                        "project": "motif-owned-test",
                        "owner": original["owner"],
                    }
                ],
                "networks": [
                    {
                        "name": "motif-owned-test_default",
                        "project": "motif-owned-test",
                        "owner": original["owner"],
                    }
                ],
            }
        )
    )
    assert prepare(runtime, env).returncode == 0
    assert receipt(runtime) == original


@pytest.mark.parametrize("kind", ["volumes", "networks"])
def test_recorded_project_refuses_foreign_persistent_owner(tmp_path, kind):
    runtime, state, log, env = setup(tmp_path)
    assert prepare(runtime, env).returncode == 0
    resource = {
        "name": "motif-owned-test"
        + ("_motif_forge_postgres" if kind == "volumes" else "_default"),
        "project": "motif-owned-test",
        "owner": "foreign-owner",
    }
    state.write_text(
        json.dumps({"daemon": "test-daemon", "containers": [], kind: [resource]})
    )
    result = prepare(runtime, env)
    assert result.returncode != 0 and "UNOWNED_RESOURCE" in result.stderr
    assert not any(
        call[0] in {"stop", "compose", "COLIMA", "rm"} for call in commands(log)
    )


def test_operation_lock_survives_helper_exit_and_recovers_on_holder_exit(tmp_path):
    runtime, _state, _log, env = setup(tmp_path)
    runtime.mkdir(mode=0o700)
    lock = runtime / "operation.lock"
    lock.touch(mode=0o600)
    helper = ROOT / "scripts/motif_runtime_lock.py"
    hold = 'exec 9<> "$1"; python3 "$2" acquire "$1" || exit $?; printf "locked\\n"; read -r finish'
    holder = subprocess.Popen(
        ["bash", "-c", hold, "bash", str(lock), str(helper)],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    contender = [
        "bash",
        "-c",
        'exec 9<> "$1"; python3 "$2" acquire "$1"',
        "bash",
        str(lock),
        str(helper),
    ]
    try:
        assert holder.stdout.readline().strip() == "locked"
        busy = run(*contender, env=env)
        assert busy.returncode == 75 and "RUNTIME_OPERATION_BUSY" in busy.stderr
    finally:
        holder.terminate()
        holder.wait(timeout=5)
    assert lock.exists()
    assert run(*contender, env=env).returncode == 0


def test_managed_persistent_resource_names_match_compose_contract():
    import yaml

    document = yaml.safe_load((ROOT / "compose.yaml").read_text())
    owner = {"io.motif-forge.runtime-owner": "${MOTIF_FORGE_RUNTIME_OWNER:-unmanaged}"}
    assert document["volumes"] == {"motif_forge_postgres": {"labels": owner}}
    assert document["networks"] == {"default": {"labels": owner}}
