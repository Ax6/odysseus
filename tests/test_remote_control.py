import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from src.remote_control import RemoteControlManager


class FakeAPIKeyManager:
    def encrypt_api_key(self, value):
        return f"enc:{value}"

    def decrypt_api_key(self, value):
        if not value.startswith("enc:"):
            raise ValueError("not encrypted")
        return value[4:]


class FakeAuthManager:
    users = {
        "ken": {"is_admin": True},
    }


class FakeSession:
    def __init__(self, session_id, endpoint_url="", model=""):
        self.id = session_id
        self.endpoint_url = endpoint_url
        self.model = model
        self.headers = {}


class FakeSessionManager:
    def __init__(self):
        self.sessions = {}

    def get_session(self, session_id):
        return self.sessions[session_id]

    def create_session(self, session_id, name, endpoint_url, model, rag=False, owner=None):
        session = FakeSession(session_id, endpoint_url, model)
        session.name = name
        session.owner = owner
        self.sessions[session_id] = session
        return session


class FakeTaskScheduler:
    async def run_task_now(self, task_id):
        return True


@pytest.mark.asyncio
async def test_provider_update_encrypts_and_masks_token(tmp_path):
    manager = RemoteControlManager(
        session_manager=FakeSessionManager(),
        task_scheduler=FakeTaskScheduler(),
        auth_manager=FakeAuthManager(),
        api_key_manager=FakeAPIKeyManager(),
        data_file=str(tmp_path / "remote_control.json"),
    )

    data = await manager.update_provider(
        "telegram",
        {"token": "12345:secret", "allowed_chat_ids": "-1001\n-1002", "enabled": False},
        actor="ken",
    )

    cfg = data["providers"]["telegram"]
    assert cfg["configured"] is True
    assert cfg["token_mask"] == "1234...cret"
    assert cfg["allowed_chat_ids"] == ["-1001", "-1002"]
    assert "mode" not in cfg
    assert "owner" not in cfg
    assert "sessions" not in cfg
    assert manager._provider_cfg("telegram")["token"] == "enc:12345:secret"


def test_allowlists_default_to_denied(tmp_path):
    manager = RemoteControlManager(
        session_manager=FakeSessionManager(),
        task_scheduler=FakeTaskScheduler(),
        auth_manager=FakeAuthManager(),
        data_file=str(tmp_path / "remote_control.json"),
    )

    assert manager._telegram_authorized("-1001") is False


@pytest.mark.asyncio
async def test_reset_clears_provider_config(tmp_path):
    manager = RemoteControlManager(
        session_manager=FakeSessionManager(),
        task_scheduler=FakeTaskScheduler(),
        auth_manager=FakeAuthManager(),
        api_key_manager=FakeAPIKeyManager(),
        data_file=str(tmp_path / "remote_control.json"),
    )
    await manager.update_provider("telegram", {
        "token": "telegram-token",
        "enabled": False,
        "allow_all": True,
        "allowed_chat_ids": "123",
    })

    data = await manager.update_provider("telegram", {"reset": True})

    cfg = data["providers"]["telegram"]
    assert cfg["configured"] is False
    assert cfg["enabled"] is False
    assert cfg["allow_all"] is False
    assert cfg["allowed_chat_ids"] == []


@pytest.mark.asyncio
async def test_dispatch_uses_chat_stream_front_door(tmp_path):
    app = FastAPI()
    seen = {}

    @app.post("/api/chat_stream")
    async def chat_stream(request: Request):
        form = await request.form()
        seen["form"] = dict(form)
        seen["owner"] = request.headers.get("X-Odysseus-Owner")

        async def events():
            yield 'data: {"delta":"Calendar "}\n\n'
            yield 'data: {"delta":"works"}\n\n'
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    manager = RemoteControlManager(
        session_manager=FakeSessionManager(),
        task_scheduler=FakeTaskScheduler(),
        auth_manager=FakeAuthManager(),
        app=app,
        data_file=str(tmp_path / "remote_control.json"),
    )
    manager._resolve_chat_endpoint = lambda owner: ("http://model/chat/completions", "model", {})

    reply = await manager._dispatch_to_chat_front_door(
        "telegram:8666203886",
        "8666203886",
        "What calander entries do I have?",
        "chat",
    )

    assert reply == "Calendar works"
    assert seen["owner"] == "ken"
    assert seen["form"]["message"] == "What calander entries do I have?"
    assert seen["form"]["mode"] == "chat"
    assert seen["form"]["remote_provider"] == "telegram"


@pytest.mark.asyncio
async def test_plain_message_defaults_to_agent_mode(tmp_path):
    """Plain remote messages must run in agent mode so tools are available;
    /chat forces a plain tool-less turn. (Regression: messages used to default
    to chat mode and the model answered from training without calling tools.)"""
    manager = RemoteControlManager(
        session_manager=FakeSessionManager(),
        task_scheduler=FakeTaskScheduler(),
        auth_manager=FakeAuthManager(),
        data_file=str(tmp_path / "remote_control.json"),
    )
    dispatched = []

    async def fake_dispatch(surface_id, actor_id, prompt, mode):
        dispatched.append({"prompt": prompt, "mode": mode})
        return "ok"

    manager._dispatch_to_chat_front_door = fake_dispatch

    async def reply(_):
        pass

    async def typing():
        pass

    # Plain message → agent mode (tools available)
    await manager._handle_message(
        surface_id="telegram:1", actor_id="1",
        text="what's in my calendar for today",
        reply=reply, typing=typing, identity_text="",
    )
    # /chat → plain chat mode (no tools)
    await manager._handle_message(
        surface_id="telegram:1", actor_id="1",
        text="/chat just say hi",
        reply=reply, typing=typing, identity_text="",
    )
    # /agent → agent mode
    await manager._handle_message(
        surface_id="telegram:1", actor_id="1",
        text="/agent do the thing",
        reply=reply, typing=typing, identity_text="",
    )

    assert dispatched[0] == {"prompt": "what's in my calendar for today", "mode": "agent"}
    assert dispatched[1] == {"prompt": "just say hi", "mode": "chat"}
    assert dispatched[2] == {"prompt": "do the thing", "mode": "agent"}
