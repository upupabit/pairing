"""alembic a3c5e7b9d1f2 (skills): the "skill" note slot goes; an unedited Skill note is removed, an edited one stays
as a regular note, and no note is left pinned as a skill."""

import sqlite3

from alembic.config import Config

from alembic import command
from app.config import BASE_DIR


def _config(url: str) -> Config:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_skill_notes_move_out_of_the_note_slots(tmp_path):
    path = tmp_path / "old.db"
    cfg = _config(f"sqlite:///{path}")
    command.upgrade(cfg, "f6c2e8a4b1d7")
    con = sqlite3.connect(path)
    con.execute(
        "INSERT INTO users (id, username, password_hash, role, status) VALUES ('u1', 'dana', 'x', 'user', 'active')"
    )
    con.execute("INSERT INTO conversations (id, owner_id, title, model) VALUES ('c1', 'u1', 't', 'm')")
    notes = [
        ("n1", "Skill", "Writing, summarizing, brainstorming, general Q&A.", "skill"),  # the starter text
        ("n2", "Skill", "Review my Python like a senior engineer.", "skill"),  # edited
        ("n3", "Persona", "Friendly.", "persona"),
        ("n4", "My note", "Pinned as a skill", None),
    ]
    con.executemany("INSERT INTO notes (id, owner_id, title, content, default_type) VALUES (?, 'u1', ?, ?, ?)", notes)
    con.executemany(
        "INSERT INTO note_pins (id, note_id, conversation_id, pin_type) VALUES (?, ?, 'c1', ?)",
        [("p1", "n1", "skill"), ("p2", "n4", "skill"), ("p3", "n3", "persona")],
    )
    con.commit()
    con.close()

    command.upgrade(cfg, "head")

    con = sqlite3.connect(path)
    rows = {r[0]: r[1] for r in con.execute("SELECT id, default_type FROM notes")}
    assert rows == {"n2": None, "n3": "persona", "n4": None}  # n1 gone; the edited one kept, now a plain note
    assert [r[0] for r in con.execute("SELECT pin_type FROM note_pins")] == ["persona"]
    assert con.execute("SELECT count(*) FROM skills").fetchone() == (0,)
    con.close()
