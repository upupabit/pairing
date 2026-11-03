"""Builds app/skill_templates/fabric.json (Admin settings > Skills > Template gallery) from a checkout of
Fabric (https://github.com/danielmiessler/fabric, MIT): each pattern's system.md, its description and tags.
Run again to refresh from a newer Fabric:

    git clone --depth 1 https://github.com/danielmiessler/fabric.git /tmp/fabric
    .venv/bin/python scripts/import_fabric_skills.py /tmp/fabric
"""

import json
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "app" / "skill_templates"
MAX_CHARS = 20000  # longer patterns are left out: too much for every reply's system prompt
# Fabric's "t_" patterns read the author's personal TELOS file, so they don't work as general skills.
PERSONAL_PREFIX = "t_"
# Fabric's tags as pAIring's categories; the first tag is a skill's main category.
CATEGORIES = {
    "ANALYSIS": "Analysis",
    "WRITING": "Writing",
    "DEVELOPMENT": "Development",
    "DEVOPS": "Development",
    "EXTRACT": "Extraction",
    "BUSINESS": "Business",
    "BILL": "Business",
    "CR THINKING": "Critical thinking",
    "SELF": "Personal growth",
    "WELLNESS": "Wellness",
    "SECURITY": "Security",
    "LEARNING": "Learning",
    "RESEARCH": "Research",
    "SUMMARIZE": "Summaries",
    "VISUALIZE": "Visualization",
    "VISUALIZATION": "Visualization",
    "CONVERSION": "Conversion",
    "AI": "AI",
    "REVIEW": "Review",
    "STRATEGY": "Strategy",
    "WISDOM": "Wisdom",
    "GAMING": "Gaming",
    "CREATIVITY": "Creativity",
    "CLASSIFICATION": "Analysis",
}


class FabricImporter:
    def __init__(self, checkout: Path) -> None:
        self.checkout = checkout
        self.patterns = checkout / "data" / "patterns"

    def run(self) -> dict:
        described = self._descriptions()
        skills = [s for s in (self._skill(folder, described) for folder in sorted(self.patterns.iterdir())) if s]
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.checkout, capture_output=True, text=True
        ).stdout.strip()
        return {
            "source": "fabric",
            "source_name": "Fabric",
            "url": "https://github.com/danielmiessler/fabric",
            "license": "MIT",
            "commit": commit,
            "skills": skills,
        }

    def _descriptions(self) -> dict[str, dict]:
        path = self.checkout / "scripts" / "pattern_descriptions" / "pattern_descriptions.json"
        data = json.loads(path.read_text())
        return {p["patternName"]: p for p in (data["patterns"] if isinstance(data, dict) else data)}

    def _skill(self, folder: Path, described: dict[str, dict]) -> dict | None:
        system = folder / "system.md"
        if not folder.is_dir() or not system.is_file():
            return None
        content = system.read_text(errors="replace").strip()
        if not content or len(content) > MAX_CHARS:
            return None
        if folder.name.startswith(PERSONAL_PREFIX) and "TELOS" in content:
            return None
        info = described.get(folder.name, {})
        categories = list(dict.fromkeys(CATEGORIES.get(t.upper(), "Other") for t in info.get("tags", []))) or ["Other"]
        return {
            "key": folder.name,
            "name": folder.name.replace("_", " ").strip().capitalize(),
            "description": (info.get("description") or "").strip(),
            "categories": categories,
            "content": content,
        }


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: import_fabric_skills.py <path to a Fabric checkout>")
    checkout = Path(sys.argv[1])
    catalog = FabricImporter(checkout).run()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "fabric.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n")
    (OUT_DIR / "FABRIC-LICENSE").write_text((checkout / "LICENSE").read_text())
    print(f"{len(catalog['skills'])} skills from Fabric {catalog['commit'][:12]} -> {OUT_DIR / 'fabric.json'}")


if __name__ == "__main__":
    main()
