"""Stats workflow view: the admin's Simple / New choice and the page that loads the matching view."""

import pytest
from pydantic import ValidationError

from app.routers import workflow_view_admin
from app.schemas.settings import WorkflowView
from app.services import workflow_view_setting


@pytest.mark.asyncio
async def test_defaults_to_new_and_can_switch(db):
    assert (await workflow_view_admin.get_setting(db=db, _admin=None)).view == "new"
    await workflow_view_admin.set_setting(WorkflowView(view="simple"), db=db, _admin=None)
    assert (await workflow_view_admin.get_setting(db=db, _admin=None)).view == "simple"
    await workflow_view_admin.set_setting(WorkflowView(view="new"), db=db, _admin=None)
    assert await workflow_view_setting.get_workflow_view(db) == "new"


def test_rejects_unknown_views():
    with pytest.raises(ValidationError):
        WorkflowView(view="fancy")


@pytest.mark.parametrize(
    ("view", "loads", "skips"),
    [
        ("new", "workflow_diagram_cards.js", "workflow_diagram_simple.js"),
        ("simple", "workflow_diagram_simple.js", "workflow_diagram_cards.js"),
    ],
)
def test_stats_template_loads_only_the_chosen_view(view, loads, skips):
    from app.templates_env import templates

    html = templates.env.get_template("stats.html").render(
        workflow_view=view, static_version="t", app_name="pAIring", username="a", theme="midnight", hljs_theme="x"
    )
    assert loads in html and skips not in html
    assert 'data-workflow-view="simple"' in html and 'data-workflow-view="new"' in html
