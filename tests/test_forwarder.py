import asyncio
from types import SimpleNamespace as NS

import pytest
from telethon import errors, types

from apexbot.forwarder import MessageMapStore, copy_message, invite_hash_from_link


class FakeClient:
    def __init__(self, fail=None):
        self.sent, self.fail, self.next_id = [], list(fail or []), 100

    async def _send(self, kind, dest, payload, **kw):
        if self.fail:
            raise self.fail.pop(0)
        self.next_id += 1
        self.sent.append((kind, payload, kw.get("reply_to")))
        return NS(id=self.next_id)

    async def send_message(self, dest, text, **kw): return await self._send("text", dest, text, **kw)
    async def send_file(self, dest, media, **kw): return await self._send("file", dest, media, **kw)


def msg(mid, text="salom", media=None, reply_to=None, noforwards=False):
    return NS(id=mid, message=text, entities=None, media=media, noforwards=noforwards,
              reply_to=NS(reply_to_msg_id=reply_to) if reply_to else None)


def run(coro): return asyncio.run(coro)


@pytest.fixture
def store(tmp_path):
    s = MessageMapStore(tmp_path / "m.sqlite3"); yield s; s.close()


def test_invite_hash():
    assert invite_hash_from_link("https://t.me/+AbC-12_x") == "AbC-12_x"
    assert invite_hash_from_link("https://t.me/joinchat/XYZ") == "XYZ"
    with pytest.raises(ValueError):
        invite_hash_from_link("https://t.me/kanal")


def test_text_copied_and_reply_linked_to_copied_parent(store):
    c = FakeClient()
    assert run(copy_message(c, "dest", msg(1), -100, "A", store)) == 101
    assert run(copy_message(c, "dest", msg(2, reply_to=1), -100, "A", store)) == 102
    assert c.sent[1] == ("text", "salom", 101)


def test_reply_to_uncopied_parent_and_protected_are_skipped(store):
    c = FakeClient()
    assert run(copy_message(c, "dest", msg(5, reply_to=4), -100, "A", store)) is None
    assert run(copy_message(c, "dest", msg(6, noforwards=True), -100, "A", store)) is None
    assert run(copy_message(c, "dest", msg(7), -100, "A", store, chat_protected=True)) is None
    assert c.sent == []


def test_media_sent_as_file_and_webpage_as_text(store):
    c = FakeClient()
    photo = types.MessageMediaPhoto()
    run(copy_message(c, "dest", msg(1, media=photo), -100, "A", store))
    run(copy_message(c, "dest", msg(2, media=types.MessageMediaWebPage(webpage=None)), -100, "A", store))
    assert [s[0] for s in c.sent] == ["file", "text"]


def test_flood_wait_retries_once_and_rpc_error_skips(store, monkeypatch):
    async def no_sleep(_): pass
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    flood = errors.FloodWaitError(request=None, capture=3)
    c = FakeClient(fail=[flood])
    assert run(copy_message(c, "dest", msg(1), -100, "A", store)) == 101
    c2 = FakeClient(fail=[errors.ChatWriteForbiddenError(request=None)])
    assert run(copy_message(c2, "dest", msg(2), -100, "A", store)) is None
    assert store.get(-100, 2) is None


def test_empty_message_skipped(store):
    assert run(copy_message(FakeClient(), "dest", msg(1, text=""), -100, "A", store)) is None
