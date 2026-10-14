"""The teaser and the idea behind a story (its moral) in each app language."""

from sqlalchemy import select

from app.models import AudioAsset, TeaserDraft
from app.services import morals

from .conftest import login, make_asset, make_user, make_worker
from .test_household import onboard, parent
from .test_pipeline import run_job, worker_auth

STORY = "a" * 16


def test_story_detail_has_the_teaser_in_every_language_and_the_current_morals(client, db):
    asset = make_asset(db, STORY, ready_to_publish=True, status="published", audience_age_range="All ages")
    db.scalars(select(TeaserDraft)).one().alternates = {"en-IN": {"short": "A short tale", "long": "A good story"},
                                                        "hi-IN": {"short": "", "long": ""}}
    asset.moral_translations = {"te-IN": {"text": "దయగా ఉండండి.", "by": "ai:mayura:v1", "from": "Be kind."}}
    db.commit()
    parent(client, db)
    onboard(client)
    detail = client.get(f"/api/stories/{STORY}").json()
    assert detail["teasers"] == {"te-IN": {"short": "చిన్న కథ", "long": "ఒక మంచి కథ"},
                                 "en-IN": {"short": "A short tale", "long": "A good story"}}
    assert detail["morals"] == {"en-IN": "Be kind.", "te-IN": "దయగా ఉండండి."}

    db.get(AudioAsset, STORY).moral_takeaway = "Be kind to animals."
    db.commit()
    assert client.get(f"/api/stories/{STORY}").json()["morals"] == {"en-IN": "Be kind to animals."}  # Telugu is stale


def test_moral_translations_follow_the_english_and_keep_the_editors_words(client, db):
    make_asset(db, STORY, ready_to_publish=True, status="published")
    token = make_worker(db, capabilities=["stt"])  # the Sarvam worker
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.post("/api/studio/community/refresh").json()["queued"]["translate"] == 1
    assert "translate" not in client.post("/api/studio/community/refresh").json()["queued"]  # once per text

    # The editor rewrites the moral while the first translation runs: its result is dropped, the new text gets a job.
    lease = client.post("/api/worker/lease", json={}, headers=worker_auth(token)).json()
    assert lease["type"] == "translate" and lease["inputs"]["text"] == "Be kind."
    save = client.post(f"/api/studio/review/{STORY}/save", json={"metadata": {"moralTakeaway": "Share with friends."}})
    assert save.status_code == 200, save.text
    client.post(f"/api/worker/jobs/{lease['id']}/complete", headers=worker_auth(token),
                json={"result": {"texts": {"te-IN": "దయగా ఉండండి."}, "source": "Be kind.", "model": "mayura:v1"}})
    db.expire_all()
    assert morals.morals(db.get(AudioAsset, STORY)) == {"en-IN": "Share with friends."}
    run_job(client, token, "translate", {"texts": {"te-IN": "స్నేహితులతో పంచుకోండి."}, "source": "Share with friends.",
                                         "model": "mayura:v1"})
    db.expire_all()
    assert morals.entries(db.get(AudioAsset, STORY))["te-IN"]["by"] == "ai:mayura:v1"

    # The editor corrects the Telugu. Sending it back unchanged later doesn't re-record it.
    client.post(f"/api/studio/review/{STORY}/save", json={"morals": {"te-IN": "మిత్రులతో పంచుకోండి."}})
    client.post(f"/api/studio/review/{STORY}/save", json={"morals": {"te-IN": "మిత్రులతో  పంచుకోండి."}})
    review = client.get(f"/api/studio/review/{STORY}").json()
    assert review["moralTranslations"] == {"te-IN": {"text": "మిత్రులతో పంచుకోండి.", "by": "editor:ed"}}
    db.expire_all()
    assert not morals.request(db, db.get(AudioAsset, STORY), "test")  # nothing missing
