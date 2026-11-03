"""services/update_source.py and its use by git_source.py / archive_source.py: updating from a chosen (e.g. a
partner's private) repository instead of the checkout's own origin."""

import shutil
import subprocess
from pathlib import Path

import pytest

from app.schemas.update import UpdateSourceIn
from app.services.archive_source import ArchiveSource
from app.services.git_source import GitSource
from app.services.source_updater import SourceUpdater, UpdateTarget
from app.services.update_process import UpdateProcess
from app.services.update_source import GitRemote, UpdateSourceError, UpdateSourceService

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(folder: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _commit(folder: Path, name: str) -> None:
    (folder / name).write_text(name)
    _git(folder, "add", name)
    _git(folder, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)


@pytest.fixture
def checkout(tmp_path):
    """(the install, a partner repository with the same history plus one private commit)."""
    upstream = tmp_path / "upstream.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(upstream))
    author = tmp_path / "author"
    _git(tmp_path, "clone", "-q", str(upstream), str(author))
    _git(author, "checkout", "-qb", "main")
    _commit(author, "README")
    _git(author, "push", "-q", "-u", "origin", "main")
    install = tmp_path / "install"
    _git(tmp_path, "clone", "-q", str(upstream), str(install))
    partner = tmp_path / "partner.git"
    _git(tmp_path, "clone", "-q", "--bare", str(upstream), str(partner))
    _commit(author, "private_feature.py")
    _git(author, "push", "-q", str(partner), "main")
    return install, partner


@needs_git
@pytest.mark.asyncio
async def test_a_checkout_updates_from_the_chosen_repository_and_origin_stays(checkout):
    install, partner = checkout
    origin = _git(install, "remote", "get-url", "origin")
    target = UpdateTarget("pAIring", install, "x/y", "main", None, frozenset())
    updater = SourceUpdater(target, remote=GitRemote(f"file://{partner}", "main"))

    status = await updater.status()
    assert status.update_available and status.behind == 1 and status.source.endswith("· main")
    events = [event async for event in updater.update_stream()]

    assert events[-1].get("done") and events[-1]["changed"]
    assert (install / "private_feature.py").exists()
    assert _git(install, "remote", "get-url", "origin") == origin


@pytest.mark.asyncio
async def test_the_token_reaches_git_only_through_its_environment(tmp_path):
    process = UpdateProcess()
    remote = GitRemote("https://github.com/partner/pairing.git", "main", token="secret-token")
    GitSource(tmp_path, process, remote)

    assert process.env["GIT_CONFIG_KEY_0"] == "http.https://github.com/partner/pairing.git.extraHeader"
    assert "secret-token" not in remote.url and remote.github_repo == "partner/pairing"


def test_downloads_need_a_github_repository():
    archive = ArchiveSource(Path("/tmp"), None, "main", frozenset(), None)
    with pytest.raises(RuntimeError, match="GitHub"):
        archive._require_github()


@pytest.mark.asyncio
async def test_saving_keeps_the_token_secret_and_an_empty_repo_goes_back_to_as_installed(db):
    service = UpdateSourceService(db)

    saved = await service.save("pairing", UpdateSourceIn(repo="partner/pairing", branch="partner", token="t0k"))
    assert saved.repo == "partner/pairing" and saved.has_token and "t0k" not in saved.model_dump_json()
    remote = await service.remote("pairing")
    assert remote == GitRemote("https://github.com/partner/pairing.git", "partner", "t0k")

    kept = await service.save("pairing", UpdateSourceIn(repo="partner/pairing", branch="partner"))
    assert kept.has_token  # an empty token field keeps the saved one

    as_installed = await service.save("pairing", UpdateSourceIn(repo=""))
    assert as_installed.repo is None and await service.remote("pairing") is None
    assert as_installed.has_token and await service.token("pairing") == "t0k"  # for a private origin

    reset = await service.save("pairing", UpdateSourceIn(repo="", clear_token=True))
    assert not reset.has_token and await service.token("pairing") is None


@pytest.mark.asyncio
async def test_the_token_alone_can_be_set_and_removed(db):
    service = UpdateSourceService(db)

    assert (await service.save_token("matricxon", "abc")).has_token and await service.token("matricxon") == "abc"
    assert not (await service.save_token("matricxon", None)).has_token


@pytest.mark.parametrize(
    "repo, url",
    [
        ("partner/matricxon", "https://github.com/partner/matricxon.git"),
        ("https://gitlab.example.com/p/m.git", "https://gitlab.example.com/p/m.git"),
        ("git@git.partner.io:p/m.git", "git@git.partner.io:p/m.git"),
    ],
)
def test_accepted_repository_forms(repo, url):
    assert UpdateSourceService.to_url(repo) == url


@pytest.mark.parametrize("repo", ["https://user:pw@github.com/p/m.git", "http://example.com/p/m.git", "not a repo"])
def test_refused_repository_forms(repo):
    with pytest.raises(UpdateSourceError):
        UpdateSourceService.to_url(repo)


@pytest.mark.asyncio
async def test_a_bad_branch_is_refused(db):
    with pytest.raises(UpdateSourceError):
        await UpdateSourceService(db).save("matricxon", UpdateSourceIn(repo="p/m", branch="a b"))


def test_git_access_errors_read_as_what_to_check():
    from app.services.update_source import explain_git_error

    assert "access token" in explain_git_error("fatal: could not read Username for 'https://github.com'")
    assert "branch or tag" in explain_git_error("fatal: couldn't find remote ref partner")
    assert explain_git_error("something else") == "something else"


@pytest.mark.asyncio
async def test_saving_the_default_shown_in_the_form_means_as_installed(db):
    from app.config import PAIRING_DEFAULT_BRANCH, PAIRING_GITHUB_REPO

    service = UpdateSourceService(db)
    saved = await service.save("pairing", UpdateSourceIn(repo=PAIRING_GITHUB_REPO, branch=PAIRING_DEFAULT_BRANCH))

    assert saved.repo is None and await service.remote("pairing") is None
    assert saved.default_repo == PAIRING_GITHUB_REPO
