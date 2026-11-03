"""Where pAIring and Matricxon update from (Admin settings > Update, Cluster > Servers and Update nodes:
"Use a different repo or branch"). Empty = as installed: a git checkout follows its own origin and branch, a
download uses the default GitHub repo. Set = that repo, e.g. a partner's private one, fetched through a separate
`update-source` remote so `origin` is never changed. The access token is one per product, apart from the repo: it
is also used to install Matricxon from a private repo (engine page) and to update a checkout whose own origin is
private. Encrypted in the database (secret_crypto), only handed to the git command or download that needs it,
never written to .git/config or shown again.
"""

import base64
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MATRICXON_DEFAULT_VERSION, MATRICXON_GITHUB_REPO, PAIRING_DEFAULT_BRANCH, PAIRING_GITHUB_REPO
from app.models import SYSTEM_OWNER_ID, AppSetting
from app.schemas.update import UpdateSourceIn, UpdateSourceOut
from app.services import secret_crypto

# (default repo, default branch) per product: app/config.py, which .env can change.
PRODUCTS = {
    "pairing": (PAIRING_GITHUB_REPO, PAIRING_DEFAULT_BRANCH),
    "matricxon": (MATRICXON_GITHUB_REPO, MATRICXON_DEFAULT_VERSION),
}
DEFAULT_BRANCH = "main"
REMOTE = "update-source"
_GITHUB_SHORT = re.compile(r"^[\w.-]+/[\w.-]+$")
_SSH = re.compile(r"^(?:ssh://)?[\w.-]+@[\w.-]+[:/][\w./~-]+$")
_BRANCH = re.compile(r"^[\w./-]+$")


class UpdateSourceError(ValueError):
    """Shown to the admin: a repo or branch that can't be used."""


_ACCESS_ERRORS = ("could not read Username", "Authentication failed", "Repository not found", "Permission denied")


def explain_git_error(message: str) -> str:
    """git's wording for a refused private repository, as something an admin can act on."""
    if any(text in message for text in _ACCESS_ERRORS):
        return (
            "The repository refused access. Check the repository name and the access token "
            "(it needs read access to this repository), or for SSH the machine's key."
        )
    if "couldn't find remote ref" in message:
        return "That branch or tag is not in the repository."
    return message


@dataclass(frozen=True)
class GitRemote:
    """A chosen repository: the URL git fetches, its branch, and an access token for a private one."""

    url: str
    branch: str
    token: str | None = None

    @property
    def github_repo(self) -> str | None:
        """owner/name on github.com, for downloads; None for another host or SSH."""
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or parsed.hostname != "github.com":
            return None
        return parsed.path.strip("/").removesuffix(".git") or None

    @property
    def ref(self) -> str:
        return f"refs/remotes/{REMOTE}/{self.branch}"

    def git_env(self) -> dict[str, str]:
        """The token as an HTTP header for this URL only, through git's environment (not argv: ps shows that)."""
        if not self.token:
            return {}
        user = "oauth2" if "gitlab" in (urlparse(self.url).hostname or "") else "x-access-token"
        basic = base64.b64encode(f"{user}:{self.token}".encode()).decode()
        return {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.{self.url}.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        }

    @staticmethod
    def header_env(url: str, token: str | None) -> dict[str, str]:
        """`token` as an HTTP header for `url` (a prefix, e.g. https://github.com/) in git's environment."""
        return GitRemote(url, DEFAULT_BRANCH, token).git_env()

    def to_request(self) -> dict:
        """The body of Matricxon's POST /api/update (../matricxon/app/update/self_update.py)."""
        return {"url": self.url, "branch": self.branch, "token": self.token}


class UpdateSourceService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def remote(self, product: str) -> GitRemote | None:
        """The chosen repository, or None to update as installed."""
        stored = await self._stored(product)
        if not stored.get("repo"):
            return None
        token = secret_crypto.decrypt(stored["token"]) if stored.get("token") else None
        return GitRemote(self.to_url(stored["repo"]), stored.get("branch") or PRODUCTS[product][1], token)

    async def token(self, product: str) -> str | None:
        """The product's access token, with or without a chosen repo."""
        stored = await self._stored(product)
        return secret_crypto.decrypt(stored["token"]) if stored.get("token") else None

    async def save_token(self, product: str, token: str | None) -> UpdateSourceOut:
        """Sets (or with None removes) the token alone, e.g. from the engine page's install form."""
        stored = await self._stored(product)
        stored["token"] = secret_crypto.encrypt(token.strip()) if token and token.strip() else None
        await self._write(product, stored)
        return await self.get(product)

    async def get(self, product: str) -> UpdateSourceOut:
        stored = await self._stored(product)
        return UpdateSourceOut(
            product=product,
            repo=stored.get("repo"),
            branch=stored.get("branch"),
            has_token=bool(stored.get("token")),
            default_repo=PRODUCTS[product][0],
            default_branch=PRODUCTS[product][1],
        )

    async def save(self, product: str, update: UpdateSourceIn) -> UpdateSourceOut:
        stored = await self._stored(product)
        repo = (update.repo or "").strip() or None
        branch = (update.branch or "").strip() or None
        default_repo, default_branch = PRODUCTS[product]
        if repo == default_repo and branch in (None, default_branch):
            repo = branch = None  # the default as shown in the form: update as installed
        if repo:
            self.to_url(repo)  # validates
        if branch and (not _BRANCH.match(branch) or branch.startswith("-")):
            raise UpdateSourceError("A branch or tag name can't contain spaces or special characters.")
        token = None if update.clear_token else stored.get("token")
        if update.token and update.token.strip():
            token = secret_crypto.encrypt(update.token.strip())
        await self._write(product, {"repo": repo, "branch": branch if repo else None, "token": token})
        return await self.get(product)

    async def _write(self, product: str, value: dict) -> None:
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, self._key(product)))
        if row is None:
            self._db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=self._key(product), value=value))
        else:
            row.value = value
        await self._db.commit()

    @staticmethod
    def to_url(repo: str) -> str:
        """owner/name (GitHub), an https URL or an SSH address; UpdateSourceError for anything else."""
        repo = repo.strip()
        if _GITHUB_SHORT.match(repo):
            return f"https://github.com/{repo}.git"
        parsed = urlparse(repo)
        if parsed.scheme == "https" and parsed.hostname:
            if parsed.username or parsed.password:
                raise UpdateSourceError("Put the access token in its own field, not in the URL.")
            return repo
        if _SSH.match(repo):
            return repo
        raise UpdateSourceError(
            "Use owner/name for GitHub, an https:// URL, or an SSH address such as git@host:owner/name.git."
        )

    async def _stored(self, product: str) -> dict:
        if product not in PRODUCTS:
            raise UpdateSourceError(f"Unknown product: {product}.")
        row = await self._db.get(AppSetting, (SYSTEM_OWNER_ID, self._key(product)))
        return dict(row.value) if row and row.value else {}

    @staticmethod
    def _key(product: str) -> str:
        return f"update_source_{product}"
