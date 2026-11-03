"""services/server_facts.py, servers_check.py and this_server_settings.py: the multi-server checklist and
editing this server's .env."""

import pytest

from app.models import Server
from app.schemas.servers import ThisServerUpdate
from app.services import servers_check as check_module
from app.services.server_facts import MARKER_FILE, ServerFacts, secret_fingerprint
from app.services.server_registry import ServerRegistry
from app.services.servers_check import ServersCheck
from app.services.this_server_settings import ThisServerSettingsError, ThisServerSettingsService


class _NoNetworkDisk:
    def is_shared(self, _path) -> bool:
        return False


def _facts(tmp_path, name: str) -> ServerFacts:
    folder = tmp_path / name
    return ServerFacts(folders={"KNOWLEDGE_DIR": folder}, probe=_NoNetworkDisk())


def _report(facts: ServerFacts, secret: str = "fp", secret_set: bool = True) -> dict:
    return {**facts.report(), "secret": secret, "secret_set": secret_set}


async def _online(db, server_id: str, details: dict) -> None:
    await ServerRegistry(server_id=server_id).heartbeat(db, details)


async def _checks(db, facts: ServerFacts, monkeypatch) -> dict:
    monkeypatch.setattr(check_module, "shared_database", lambda _db: True)
    monkeypatch.setattr(check_module, "SHARED_FOLDERS", {"KNOWLEDGE_DIR": None})
    result = await ServersCheck(facts=facts).run(db)
    return {c.id: c for c in result.checks}


def test_the_secret_fingerprint_matches_only_for_the_same_key():
    assert secret_fingerprint("a" * 40) == secret_fingerprint("a" * 40)
    assert secret_fingerprint("a" * 40) != secret_fingerprint("b" * 40)


@pytest.mark.asyncio
async def test_one_shared_folder_passes_and_a_local_copy_fails(db, tmp_path, monkeypatch):
    leader = _facts(tmp_path, "shared")
    await leader.refresh_markers(db)
    await _online(db, "a:1", _report(leader))
    await _online(db, "b:1", _report(_facts(tmp_path, "shared")))
    assert (await _checks(db, leader, monkeypatch))["KNOWLEDGE_DIR"].ok is True

    await _online(db, "c:1", _report(_facts(tmp_path, "local-copy")))
    check = (await _checks(db, leader, monkeypatch))["KNOWLEDGE_DIR"]
    assert check.ok is False and "c:1" in check.detail


@pytest.mark.asyncio
async def test_a_stale_marker_from_an_old_leader_no_longer_counts(db, tmp_path, monkeypatch):
    leader = _facts(tmp_path, "shared")
    await leader.refresh_markers(db)
    old = tmp_path / "old-local"
    old.mkdir()
    (old / MARKER_FILE).write_text((tmp_path / "shared" / MARKER_FILE).read_text())
    leader.MARKER_SECONDS = 0
    await leader.refresh_markers(db)
    await leader.refresh_markers(db)  # the copied id is now two rounds old

    await _online(db, "b:1", _report(_facts(tmp_path, "old-local")))
    assert (await _checks(db, leader, monkeypatch))["KNOWLEDGE_DIR"].ok is False


@pytest.mark.asyncio
async def test_different_or_missing_secret_keys_fail(db, tmp_path, monkeypatch):
    facts = _facts(tmp_path, "shared")
    await _online(db, "a:1", _report(facts, secret="one"))
    await _online(db, "b:1", _report(facts, secret="two"))
    assert (await _checks(db, facts, monkeypatch))["secret_key"].ok is False

    await _online(db, "b:1", _report(facts, secret="one", secret_set=False))
    check = (await _checks(db, facts, monkeypatch))["secret_key"]
    assert check.ok is False and "b:1" in check.detail


@pytest.mark.asyncio
async def test_offline_servers_are_not_checked(db, tmp_path, monkeypatch):
    facts = _facts(tmp_path, "shared")
    await _online(db, "a:1", _report(facts, secret="one"))
    db.add(Server(server_id="gone:1", version="1", is_primary=True, last_seen=0, details=_report(facts, secret="x")))
    await db.commit()

    assert (await _checks(db, facts, monkeypatch))["secret_key"].ok is True


def test_saving_this_server_writes_only_its_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("APP_PORT=8000\n")
    service = ThisServerSettingsService(env_path=env, folders={"KNOWLEDGE_DIR": tmp_path / "k"})

    info = service.save(ThisServerUpdate(folders={"KNOWLEDGE_DIR": str(tmp_path / "shared/k")}, secret_key="s" * 40))

    text = env.read_text()
    assert (
        "APP_PORT=8000" in text
        and f"KNOWLEDGE_DIR={tmp_path / 'shared/k'}" in text
        and "SECRET_KEY=" + "s" * 40 in text
    )
    assert info.restart_needed and info.secret_saved
    assert (tmp_path / "shared/k").is_dir()


def test_a_relative_folder_is_refused(tmp_path):
    service = ThisServerSettingsService(env_path=tmp_path / ".env", folders={"KNOWLEDGE_DIR": tmp_path / "k"})

    with pytest.raises(ThisServerSettingsError):
        service.save(ThisServerUpdate(folders={"KNOWLEDGE_DIR": "relative/k"}))
    assert not (tmp_path / ".env").exists()
