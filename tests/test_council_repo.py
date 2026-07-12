import os

import pytest

from roaring_kittens.db.council import get_council_transcript, save_council_run

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


async def test_save_and_get_transcript(db_session_factory):
    transcript = {"views": [{"role": "news"}], "debate": [], "proposal": {"action": "wait"}}
    async with db_session_factory() as session:
        run_id = await save_council_run(session, ticker="SBER", asked_by=42,
                                        transcript=transcript, call_id=None)
        await session.commit()
    async with db_session_factory() as session:
        loaded = await get_council_transcript(session, run_id)
        assert loaded["proposal"]["action"] == "wait"
        assert await get_council_transcript(session, run_id=None) is None
