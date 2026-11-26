"""Load the bundled Claude skills (``skills/<name>/SKILL.md``)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    body: str  # markdown without frontmatter
    path: Path

    @property
    def text(self) -> str:
        return self.path.read_text("utf-8")


_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def _skills_dir() -> Path | None:
    candidates = []
    try:
        candidates.append(Path(str(resources.files("medikeep_mcp").joinpath("skills"))))
    except (ModuleNotFoundError, TypeError):
        pass
    # Source checkout / editable install: <repo>/src/medikeep_mcp/ -> <repo>/skills
    candidates.append(Path(__file__).resolve().parents[2] / "skills")
    for c in candidates:
        if c.is_dir():
            return c
    return None


def load_skills() -> dict[str, Skill]:
    root = _skills_dir()
    skills: dict[str, Skill] = {}
    if root is None:
        return skills
    for skill_md in sorted(root.glob("*/SKILL.md")):
        raw = skill_md.read_text("utf-8")
        meta: dict[str, str] = {}
        body = raw
        m = _FRONTMATTER.match(raw)
        if m:
            body = m.group(2)
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
        name = meta.get("name") or skill_md.parent.name
        skills[name] = Skill(name, meta.get("description", ""), body.strip(), skill_md)
    return skills
