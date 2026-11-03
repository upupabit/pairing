"""Skills (models/skill.py): Admin settings > Skills, the users' private skills and a chat's skill picker."""

from pydantic import BaseModel, Field, field_validator

MAX_SKILL_CHARS = 20000


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="Other", max_length=100)
    content: str = Field(min_length=1, max_length=MAX_SKILL_CHARS)
    enabled: bool = True  # the library only: private skills are always usable by their owner

    @field_validator("name", "category")
    @classmethod
    def _stripped(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("can't be empty")
        return value


class SkillOut(BaseModel):
    id: str
    name: str
    description: str
    category: str
    content: str
    enabled: bool
    private: bool  # a user's own skill, not the shared library's
    source: str | None = None  # "fabric" when it came from the template gallery
    source_key: str | None = None


class SkillTemplateOut(BaseModel):
    """One gallery template (services/skill_templates.py); `added`: already in the library."""

    source: str
    key: str
    name: str
    description: str
    categories: list[str]
    content: str
    added: bool = False


class SkillTemplatePage(BaseModel):
    items: list[SkillTemplateOut]
    total: int
    categories: dict[str, int]  # every category with its template count, for the filter
    sources: list[dict]  # name, url, license and commit of each bundled collection


class SkillTemplateAdd(BaseModel):
    """Templates to copy into the library: by key, or a whole category."""

    keys: list[str] = Field(default_factory=list, max_length=500)
    category: str | None = None


class SkillTemplateAddResult(BaseModel):
    added: int
    already: int


class ConversationSkillsOut(BaseModel):
    chosen: list[SkillOut]
    editable: bool
    reason: str | None = None  # why not editable


class ConversationSkillsIn(BaseModel):
    skill_ids: list[str] = Field(default_factory=list, max_length=50)
