"""Video lab (ADR 012) with real FFmpeg on small generated videos; fal.ai, YouTube and the LLM are fakes.
Every cut, time and credit is checked against what code must compute."""
import json
import os
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.agents import youtube as agents
from del_social.billing import credits
from del_social.connections.youtube import GoogleOAuth, QuotaMeter, YouTubeClient
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLMResult
from del_social.llm.pricing import Usage
from del_social.media.fal import FalClient
from del_social.team import lead
from del_social.youtube.lab import ffmpeg, files, jobs, subs

from .conftest import O
from .test_posts import connect

pytestmark = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0, reason="needs ffmpeg")


def make_video(path: Path, seconds: int = 12, silent: tuple[int, int] | None = (4, 8), size: str = "320x240") -> bytes:
    af = f"volume=enable='between(t,{silent[0]},{silent[1]})':volume=0" if silent else "anull"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-af", af, "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path)], check=True)
    return path.read_bytes()


CHUNKS = [{"timestamp": [0.0, 3.5], "text": "Salam, bu gün maşına baxırıq"},
          {"timestamp": [8.2, 11.8], "text": "Nəticə: almağa dəyər, çünki qiyməti yaxşıdır və sərfəlidir"}]


class Fakes:
    def __init__(self, tmp: Path):
        self.calls: list[str] = []
        self.clip = make_video(tmp / "clip.mp4", 5, None, "640x360")
        self.uploaded = 0
        self.upload_meta: dict | None = None
        self.captions: list[bytes] = []

    def handle(self, r: httpx.Request) -> httpx.Response:
        host, path = r.url.host, r.url.path
        self.calls.append(f"{r.method} {host}{path}")
        if host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3599})
        if host == "queue.fal.run":
            if r.method == "POST":
                return httpx.Response(200, json={"request_id": "x", "status_url": "https://queue.fal.run/s", "response_url": f"https://queue.fal.run/r{path}"})
            if path == "/s":
                return httpx.Response(200, json={"status": "COMPLETED"})
            if "whisper" in path:
                return httpx.Response(200, json={"text": "…", "chunks": CHUNKS, "inferred_languages": ["az"]})
            return httpx.Response(200, json={"video": {"url": "https://fal.media/clip.mp4"}})
        if host == "fal.media":
            return httpx.Response(200, content=self.clip)
        if path == "/upload/youtube/v3/videos" and r.method == "POST":
            self.upload_meta = json.loads(r.content)
            return httpx.Response(200, headers={"location": "https://www.googleapis.com/upload/session/1"})
        if path == "/upload/session/1":
            self.uploaded += len(r.content)
            total = int(r.headers["content-range"].split("/")[1])
            if self.uploaded < total:
                return httpx.Response(308, headers={"range": f"bytes=0-{self.uploaded - 1}"})
            return httpx.Response(200, json={"id": "newvid"})
        if path == "/upload/youtube/v3/captions":
            self.captions.append(r.content)
            return httpx.Response(200, json={"id": "cap"})
        if path == "/youtube/v3/channels":
            return httpx.Response(200, json={"items": [{"id": "UCx", "snippet": {"title": "Auto"}}]})
        return httpx.Response(404, json={"error": {"message": "unknown"}})


class LabLLM:
    def __init__(self):
        self.users: list[tuple[str, str]] = []

    async def structured(self, *, tenant_id, prompt, user, output, tier, max_tokens, effort=None, images=None):
        self.users.append((prompt.agent, user))
        if output is agents.ShortPicks:
            out = agents.ShortPicks(shorts=[agents.ShortPick(first=0, last=1, hook="Almağa dəyər?", title="Kia: nəticə", why="verdict"),
                                            agents.ShortPick(first=1, last=5, hook="x", title="bad", why="out of range")])
        elif output is agents.VideoPlan:
            out = agents.VideoPlan(scenes=[agents.Scene(prompt="A red SUV drives up a mountain road at sunset", caption="Dağlarda"),
                                           agents.Scene(prompt="The SUV parks by a lake", caption="Göl kənarında")])
        elif output is agents.TranslatedSegments:
            out = agents.TranslatedSegments(segments=[agents.SegmentText(index=0, text="Привет, сегодня смотрим машину")])
        else:
            raise AssertionError(output)
        return LLMResult(out, "fake", Usage(1, 1), Decimal("0.01"), 1, uuid.uuid4().hex)


@pytest.fixture
async def lab(client, admin, tenants, session_for, account_factory, tmp_path):
    from del_social.core.deps import get_http, get_vault_optional, get_youtube_optional
    from del_social.main import app
    from del_social.routes.lab import get_video_fal
    from del_social.routes.media import get_analyst, get_fal

    fake, llm = Fakes(tmp_path), LabLLM()
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    vault = TokenVault(os.urandom(32))
    yt = YouTubeClient(http, GoogleOAuth(http, "c", "s"), QuotaMeter(10_000))
    fal = FalClient(http, "k", poll_seconds=0, timeout_seconds=5)
    for dep, value in ((get_vault_optional, vault), (get_http, http), (get_youtube_optional, yt), (get_analyst, llm),
                       (get_fal, fal), (get_video_fal, fal)):
        app.dependency_overrides[dep] = (lambda v: lambda: v)(value)
    platform = await session_for(await account_factory(is_platform_admin=True))
    await client.put(f"/platform/tenants/{tenants['a']}/addons/youtube", json={"active": True}, headers={**platform, **O})
    await client.post(f"/platform/tenants/{tenants['a']}/credits", json={"credits": 500}, headers={**platform, **O})
    await connect(admin, vault, tenants["a"], "youtube", "UCx")
    owner = await session_for(tenants["a_owner"])
    return type("L", (), {"fake": fake, "llm": llm, "owner": owner, "base": f"/tenants/{tenants['a']}/youtube/lab", "tmp": tmp_path})


async def balance(app_engine, tenant_id) -> int:
    async with AsyncSession(app_engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        return (await credits.balance(db)).total


async def upload(client, lab, data: bytes, name="test.mp4") -> dict:
    h = {**lab.owner, **O}
    mid = (await client.post(f"{lab.base}/uploads", json={"filename": name, "size": len(data)}, headers=h)).json()["media_id"]
    half = len(data) // 2
    assert (await client.put(f"{lab.base}/uploads/{mid}?offset=0", content=data[:half], headers=h)).json() == {"bytes": half}
    assert (await client.put(f"{lab.base}/uploads/{mid}?offset=0", content=data[:half], headers=h)).status_code == 409  # no overlaps
    await client.put(f"{lab.base}/uploads/{mid}?offset={half}", content=data[half:], headers=h)
    return (await client.post(f"{lab.base}/uploads/{mid}/complete", headers=h)).json()


async def job(client, lab, path: str, body: dict) -> dict:
    r = await client.post(f"{lab.base}/{path}", json=body, headers={**lab.owner, **O})
    assert r.status_code == 202, r.text
    await lead.settle()
    return (await client.get(f"{lab.base}/jobs/{r.json()['job_id']}", headers=lab.owner)).json()


async def test_upload_transcribe_cut_shorts_export(client, app_engine, tenants, lab):
    m = await upload(client, lab, make_video(lab.tmp / "src.mp4"))
    assert m["status"] == "ready" and 11.5 < m["duration_s"] < 12.5 and m["width"] == 320 and m["has_audio"]
    mid = m["media_id"]
    video = await client.get(f"{lab.base}/media/{mid}/video", headers=lab.owner)
    assert video.status_code == 200 and len(video.content) > 1000
    start = await balance(app_engine, tenants["a"])

    # Subtitles need a transcript first
    assert (await client.post(f"{lab.base}/media/{mid}/shorts", json={}, headers={**lab.owner, **O})).status_code == 409

    j = await job(client, lab, f"media/{mid}/transcribe", {"language": "az"})
    assert j["status"] == "done" and j["result"] == {"segments": 2} and j["credits"] == credits.COST["transcribe_10min"]
    assert any("fal-ai/whisper" in c for c in lab.fake.calls)

    # Silence 4–8 s removed by code (padding 0.25 s on each side)
    j = await job(client, lab, f"media/{mid}/cut", {"level": "normal"})
    assert j["status"] == "done", j
    cut = (await client.get(f"{lab.base}/media/{j['result']['media_id']}", headers=lab.owner)).json()
    assert 7.5 < cut["duration_s"] < 9.2 and j["result"]["removed_seconds"] > 3
    assert cut["transcript"]["segments"][1]["start"] < 6  # the words after the silence moved earlier

    # Shorts: the model chooses segments, code cuts; a pick outside the transcript is ignored
    j = await job(client, lab, f"media/{mid}/shorts", {"count": 2})
    assert j["status"] == "done", j
    assert [s["title"] for s in j["result"]["shorts"]] == ["Kia: nəticə"]
    short = (await client.get(f"{lab.base}/media/{j['result']['shorts'][0]['media_id']}", headers=lab.owner)).json()
    assert (short["width"], short["height"]) == (1080, 1920)

    # Export: trim, remove a part, speed 1.5 → length computed by code
    j = await job(client, lab, f"media/{mid}/export", {"start": 1, "end": 11, "cuts": [[3, 5]], "speed": 1.5, "frame": "square"})
    out = (await client.get(f"{lab.base}/media/{j['result']['media_id']}", headers=lab.owner)).json()
    assert abs(out["duration_s"] - 8 / 1.5) < 0.4 and (out["width"], out["height"]) == (1080, 1080)

    spent = start - await balance(app_engine, tenants["a"])
    assert spent == credits.COST["transcribe_10min"] + credits.COST["render_min"] * 2 + credits.COST["shorts_pick"] + 2 * credits.COST["render_min"]


async def test_subtitles_translate_captions_and_upload(client, app_engine, tenants, lab):
    mid = (await upload(client, lab, make_video(lab.tmp / "src.mp4", silent=None)))["media_id"]
    await job(client, lab, f"media/{mid}/transcribe", {})
    j = await job(client, lab, f"media/{mid}/subtitles", {"translate_to": "ru", "style": {"font": "condensed", "box": True}})
    assert j["status"] == "done", j
    sub = (await client.get(f"{lab.base}/media/{j['result']['media_id']}", headers=lab.owner)).json()
    assert sub["transcript"]["segments"][0]["text"] == "Привет, сегодня смотрим машину"
    assert sub["transcript"]["segments"][1]["text"].startswith("Nəticə")  # untranslated line kept, never dropped

    j = await job(client, lab, f"media/{mid}/captions", {"video_id": "abc", "language": "az"})
    assert j["status"] == "done" and b"00:00:00,000 --> 00:00:03,500" in lab.fake.captions[0]

    j = await job(client, lab, f"media/{mid}/upload", {"title": "Test <video>", "privacy": "unlisted", "tags": ["a", "a"]})
    assert j["status"] == "done" and j["result"]["video_id"] == "newvid", j
    assert lab.fake.upload_meta["snippet"]["title"] == "Test ‹video›" and lab.fake.upload_meta["snippet"]["tags"] == ["a"]
    assert lab.fake.upload_meta["status"]["containsSyntheticMedia"] is False


async def test_generate_ai_video_and_refund(client, app_engine, tenants, lab):
    start = await balance(app_engine, tenants["a"])
    opts = {"idea": "Qırmızı SUV dağ yolunda", "model": "standard", "seconds": 5, "scenes": 2, "captions": True, "style": "cinematic"}
    r = await client.post(f"{lab.base}/generate", data={"options": json.dumps(opts)}, headers={**lab.owner, **O})
    assert r.status_code == 202 and r.json()["credits"] == 4 * 5 * 2
    await lead.settle()
    j = (await client.get(f"{lab.base}/jobs/{r.json()['job_id']}", headers=lab.owner)).json()
    assert j["status"] == "done", j
    m = (await client.get(f"{lab.base}/media/{j['result']['media_id']}", headers=lab.owner)).json()
    assert m["kind"] == "generated" and 9.5 < m["duration_s"] < 10.5
    prompts = [u for a, u in lab.llm.users if a == "yt_video_prompt"][0]
    assert "<scenes>2</scenes>" in prompts and "<seconds>5</seconds>" in prompts
    assert await balance(app_engine, tenants["a"]) == start - 40

    # A job that fails gives its credits back
    lab.fake.clip = b"not a video"
    r = await client.post(f"{lab.base}/generate", data={"options": json.dumps(opts | {"captions": False, "scenes": 1})}, headers={**lab.owner, **O})
    await lead.settle()
    j = (await client.get(f"{lab.base}/jobs/{r.json()['job_id']}", headers=lab.owner)).json()
    assert j["status"] == "failed" and await balance(app_engine, tenants["a"]) == start - 40


async def test_signed_links_and_isolation(client, tenants, lab, session_for):
    from del_social.core.config import get_settings

    mid = (await upload(client, lab, make_video(lab.tmp / "src.mp4", 3, None)))["media_id"]
    s = get_settings()
    d = files.folder(s.media_root, tenants["a"], uuid.UUID(mid))
    (d / "audio.mp3").write_bytes(b"ID3fake")
    link = files.public_link("", s.secret_key, tenants["a"], uuid.UUID(mid), "audio.mp3")
    assert (await client.get(link)).content == b"ID3fake"
    assert (await client.get(link.replace("audio.mp3", "video.mp4"))).status_code == 404  # the signature covers the file name
    assert (await client.get(link[:-4] + "0000")).status_code == 404
    other = await session_for(tenants["b_owner"])
    assert (await client.get(f"/tenants/{tenants['b']}/youtube/lab/media/{mid}", headers=other)).status_code == 404


def test_code_computes_cuts_and_times():
    assert ffmpeg.parse_silences("[x] silence_start: 4.02\n[x] silence_end: 8.01 | silence_duration: 3.99\n") == [(4.02, 8.01)]
    assert ffmpeg.keep_ranges(12, [(4.0, 8.0)], 0.25) == [(0.0, 4.25), (7.75, 12.0)]
    assert ffmpeg.keep_ranges(12, [(0.0, 0.2)], 0.25) == [(0.0, 12.0)]  # too short to cut
    assert ffmpeg.merge_close([(0, 1), (1.05, 2), (3, 4)]) == [(0, 2), (3, 4)]
    segs = [{"start": 1, "end": 3, "text": "a"}, {"start": 9, "end": 10, "text": "b"}]
    assert subs.retime(segs, [(0, 4), (8, 12)]) == [{"start": 1, "end": 3, "text": "a"}, {"start": 5, "end": 6, "text": "b"}]
    assert subs.retime(segs, [(0, 4)], speed=2) == [{"start": 0.5, "end": 1.5, "text": "a"}]
    assert len(subs.cues([{"start": 0, "end": 10, "text": "söz " * 40}])) >= 2  # long lines split
    o = jobs.ExportOptions(start=1, end=11, cuts=[(3, 5)])
    assert jobs.export_ranges(12, o) == [(1, 3), (5, 11)]
    picks = [agents.ShortPick(first=0, last=0, hook="h", title="t", why="w"), agents.ShortPick(first=0, last=2, hook="h", title="t", why="w")]
    segs = [{"start": 0, "end": 5}, {"start": 5, "end": 30}, {"start": 30, "end": 50}]
    assert [(a, b) for _, a, b in jobs.pick_ranges(picks, segs)] == [(0.0, 50.35)]  # 5 s is too short
