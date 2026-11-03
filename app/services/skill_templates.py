"""The Template gallery of Admin settings > Skills: skill templates bundled in app/skill_templates/*.json (built by
scripts/import_fabric_skills.py; each file names its source, license and commit). Read once, kept in memory."""

import json
from functools import lru_cache
from pathlib import Path

from app.schemas.skill import SkillTemplateOut

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "skill_templates"


class SkillTemplates:
    def __init__(self, folder: Path = TEMPLATES_DIR) -> None:
        self._folder = folder

    @lru_cache(maxsize=1)  # noqa: B019 - one shared instance below; the files don't change while running
    def _catalogs(self) -> tuple[dict, ...]:
        return tuple(json.loads(path.read_text()) for path in sorted(self._folder.glob("*.json")))

    def sources(self) -> list[dict]:
        keys = ("source", "source_name", "url", "license", "commit")
        return [{k: catalog.get(k) for k in keys} for catalog in self._catalogs()]

    def all(self) -> list[SkillTemplateOut]:
        return [
            SkillTemplateOut(source=catalog["source"], **template)
            for catalog in self._catalogs()
            for template in catalog["skills"]
        ]

    def get(self, source: str, key: str) -> SkillTemplateOut | None:
        return next((t for t in self.all() if t.source == source and t.key == key), None)

    def search(self, query: str = "", category: str | None = None) -> list[SkillTemplateOut]:
        """Matches name, description and content; name matches first, then description, then content. A category
        narrows it."""
        words = query.lower().split()
        found = []
        for template in self.all():
            if category and category not in template.categories:
                continue
            fields = (template.name.lower(), template.description.lower(), template.content.lower())
            rank = next((i for i, text in enumerate(fields) if all(w in text for w in words)), None)
            if rank is None and all(any(w in text for text in fields) for w in words):
                rank = len(fields)
            if rank is not None:
                found.append((rank, template.name, template))
        return [t for *_, t in sorted(found, key=lambda f: (f[0], f[1]))]

    def categories(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for template in self.all():
            for name in template.categories:
                counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items()))


skill_templates = SkillTemplates()
