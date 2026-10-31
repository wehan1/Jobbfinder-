"""Acceptance checks from the build brief, run against a FakeLLM so they are
deterministic and need no API key. Each test names the brief's criterion."""
from __future__ import annotations

import json
import re
import os
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from jarvis.config import Config
from jarvis.core import ESCALATE, Jarvis
from jarvis.llm import FakeLLM, LLMResponse
from jarvis.server import make_server

FAST, FRONTIER = "fast-model", "frontier-model"


def system_of(messages):
    return messages[0]["content"]


def default_responder(messages, model, tools):
    """Echo which notes were in context so tests can assert retrieval happened."""
    sys_ = system_of(messages)
    if "executing the skill" in sys_:
        skill = re.search(r"executing the skill `(\w+)`", sys_).group(1)
        return f"# {skill} output\nGrounded on context:\n{messages[-1]['content'][:2000]}"
    return f"[{model}] answer. context:\n{sys_}"


@pytest.fixture
def make_jarvis(tmp_path):
    def _make(responder=default_responder, **cfg):
        llm = FakeLLM(responder)
        config = Config(vault_path=tmp_path / "vault", fast_model=FAST, frontier_model=FRONTIER, **cfg)
        return Jarvis(config, llm=llm), llm
    return _make


# --- 1. three tiers, for typed and voice requests ---------------------------

TIER_CASES = [
    ("what time is it", 1),
    ("remember that the sponsor deadline is Friday", 1),
    ("what's a punchier word for 'good'?", 2),
    ("Build a step-by-step plan to launch my newsletter and draft the first issue", 3),
    ("/research creator economy pricing", 3),
]


@pytest.mark.parametrize("text,tier", TIER_CASES)
def test_typed_requests_route_through_all_three_tiers(make_jarvis, text, tier):
    j, llm = make_jarvis()
    r = j.handle(text, source="web")
    assert r.tier == tier, r.route
    if tier == 1:
        assert llm.calls == [], "tier 1 must not call a model"
    elif tier == 2:
        assert [c["model"] for c in llm.calls] == [FAST]
        assert llm.calls[0]["tools"] is None
    else:
        assert all(c["model"] == FRONTIER for c in llm.calls)
    log = (j.vault.state_dir / "router.jsonl").read_text().splitlines()
    assert json.loads(log[-1])["final_tier"] == tier


@pytest.mark.parametrize("text,tier", TIER_CASES)
def test_voice_requests_route_identically(make_jarvis, text, tier):
    j, llm = make_jarvis()
    j.stt.transcribe = lambda audio, suffix=".webm": text  # stand-in for local Whisper
    r = j.handle_voice(b"fake-audio", ".webm", source="web")
    assert r.transcript == text
    assert r.tier == tier
    assert "(voice)" in j.vault.read(r.log_path)


def test_fast_model_can_escalate(make_jarvis):
    def responder(messages, model, tools):
        return ESCALATE if model == FAST else "frontier handled it"
    j, llm = make_jarvis(responder)
    r = j.handle("hmm, what should I do about that thing")
    assert r.tier == 3 and r.escalated and r.reply == "frontier handled it"
    assert [c["model"] for c in llm.calls] == [FAST, FRONTIER]


def test_code_mode_selected_for_code_requests(make_jarvis):
    j, llm = make_jarvis()
    r = j.handle("/code write a python script that counts words in a csv")
    assert r.mode == "code"
    tool_names = {t["function"]["name"] for t in llm.calls[0]["tools"]}
    assert "run_python" in tool_names
    r2 = j.handle("/build reorganise my content calendar note")
    assert r2.mode == "build"
    assert "run_python" not in {t["function"]["name"] for t in llm.calls[-1]["tools"]}


# --- 2. answer using a note written days earlier ---------------------------

def test_answers_from_note_written_days_ago(make_jarvis):
    j, llm = make_jarvis()
    old = j.vault.root / "Ideas" / "Sponsor decisions.md"
    old.parent.mkdir(parents=True)
    old.write_text("---\ndate: 2026-10-20\n---\n# Sponsor decisions\n\n"
                   "We decided to reject the Glowbrew energy drink sponsorship because of audience trust.\n")
    week_ago = time.time() - 11 * 86400
    os.utime(old, (week_ago, week_ago))
    for i in range(20):  # noise
        j.vault.write(f"Misc/noise {i}.md", f"# Noise {i}\nCamera settings, lighting, b-roll tips number {i}.")

    r = j.handle("why did we turn down Glowbrew?")
    assert r.sources and r.sources[0]["path"] == "Ideas/Sponsor decisions.md"
    assert r.sources[0]["date"] == "2026-10-20"
    assert "audience trust" in system_of(llm.calls[-1]["messages"])


# --- 3. research, repurposing, Q&A run as repeatable skills ----------------

@pytest.mark.parametrize("request_text,skill,folder", [
    ("/research short-form video retention", "research", "Jarvis/Research/"),
    ("repurpose this into posts: Batching content on Sundays saves me 6 hours a week.", "repurpose", "Jarvis/Content/"),
    ("someone asked what mic I use", "qa", "Jarvis/QA/"),
])
def test_skills_are_repeatable_and_save_to_vault(make_jarvis, request_text, skill, folder):
    j, llm = make_jarvis()
    j.vault.write("Gear/Mic.md", "# Mic\nI record with a Shure SM7B through a Cloudlifter.")
    outs = [j.handle(request_text) for _ in range(2)]
    for r in outs:
        assert r.tier == 3 and r.skill == skill
        saved = [s for s in r.saved if s.startswith(folder)]
        assert saved, r.saved
        body = j.vault.read(saved[0])
        assert f"skill: {skill}" in body and f"# {skill} output" in body
    assert outs[0].saved[-1] != outs[1].saved[-1], "second run must not clobber the first"
    procedure_prompt = system_of(llm.calls[0]["messages"])
    assert "## Steps" in procedure_prompt and "## Output format" in procedure_prompt
    if skill == "qa":
        assert "Shure SM7B" in llm.calls[0]["messages"][-1]["content"]


def test_skills_are_editable_vault_notes(make_jarvis):
    j, _ = make_jarvis()
    (j.vault.root / "Jarvis/Skills/hooks.md").write_text(
        "---\nname: hooks\ndescription: write hooks\ntriggers: [hook ideas]\nmode: build\n"
        "save_to: Jarvis/Content/hooks {slug}.md\n---\n## Steps\n1. write 10 hooks\n## Output format\nlist\n")
    r = j.handle("give me hook ideas for a coffee video")
    assert r.skill == "hooks" and any(s.startswith("Jarvis/Content/hooks") for s in r.saved)


# --- 4. one vault, two front doors -----------------------------------------

@pytest.fixture
def server(make_jarvis):
    j, llm = make_jarvis()
    srv = make_server(j, "127.0.0.1", 0, token="")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield j, llm, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def post(url, payload, ctype="application/json"):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": ctype})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_web_note_visible_in_obsidian_and_vice_versa(server):
    j, llm, base = server
    # web app → vault file (what Obsidian reads)
    saved = post(f"{base}/api/note", {"title": "Q4 launch", "content": "Launch the course on Nov 12.", "source": "web"})
    path = j.vault.root / saved["saved"]
    assert path.is_file() and "Nov 12" in path.read_text()

    # Obsidian (a human editing the folder) → retrievable by both doors
    (j.vault.root / "Typed in Obsidian.md").write_text("# Pricing\nThe membership tier costs $19 per month.\n")
    for source in ("web", "obsidian"):
        r = post(f"{base}/api/chat", {"text": "how much is the membership tier?", "source": source})
        assert r["tier"] == 2
        assert any(s["path"] == "Typed in Obsidian.md" for s in r["sources"])

    # both doors land in the same conversation log
    convo = j.vault.read(r["log_path"])
    assert "· web ·" in convo and "· obsidian ·" in convo


def test_obsidian_context_note_is_injected(server):
    j, llm, base = server
    j.vault.write("Drafts/Script.md", "# Script\nOpening line about Zanzibar spice farms.")
    post(f"{base}/api/chat", {"text": "what is a quick title for this", "source": "obsidian",
                              "context_path": "Drafts/Script.md"})
    assert "Zanzibar" in system_of(llm.calls[-1]["messages"])


# --- safety ------------------------------------------------------------------

def test_vault_paths_cannot_escape(make_jarvis):
    j, _ = make_jarvis()
    from jarvis.vault import VaultError
    for bad in ["../outside.md", "Jarvis/../../outside.md", ".obsidian/plugins/x.md", ".jarvis/rules.json"]:
        with pytest.raises(VaultError):
            j.vault.write(bad, "x")
    # absolute paths are treated as vault-relative, never as real filesystem paths
    assert j.vault.write("/etc/passwd", "x") == "etc/passwd.md"


def test_cross_site_simple_post_rejected(server):
    j, llm, base = server
    with pytest.raises(urllib.error.HTTPError) as e:
        post(f"{base}/api/note", {"title": "pwned", "content": "x"}, ctype="text/plain")
    assert e.value.code == 400
    assert not (j.vault.root / "Jarvis/Inbox/pwned.md").exists()


def test_tool_loop_writes_back_to_vault(make_jarvis):
    calls = {"n": 0}

    def responder(messages, model, tools):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResponse(tool_calls=[{"id": "1", "name": "remember",
                                            "arguments": {"fact": "Posting cadence is 3x/week"}}])
        return "Noted the cadence."
    j, _ = make_jarvis(responder)
    r = j.handle("/deep decide on my posting cadence")
    assert r.reply == "Noted the cadence."
    assert any("Memory" in s for s in r.saved)
    assert "3x/week" in j.vault.read(r.saved[0])


def test_code_exec_disabled_by_default(make_jarvis):
    j, _ = make_jarvis()
    assert "disabled" in j.tools["run_python"].fn(code="print(1)")
    j2, _ = make_jarvis(allow_code_exec=True)
    assert "exit=0" in j2.tools["run_python"].fn(code="print(2)")
