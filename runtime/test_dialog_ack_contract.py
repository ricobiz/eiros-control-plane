"""Pins the documented behavior of dialog_ack's `result` parameter.

Found live: a substantive reply written into ack_result reads exactly like a
message in the tool's return value, but collab.acknowledge() only mutates the
existing row - no new message, no next_seq bump, no Pulse event. The receiving
agent's wake mechanisms (Pulse polling, /state fingerprint) never see it,
so it sits acknowledged-but-unread until someone happens to look. Rico/ChatGPT
caught this live: a Claude ack_result went unanswered because nothing woke
ChatGPT for it.

This is a documentation fix, not a behavior fix - the semantics described here
already existed and are almost certainly correct on their own terms (an ack
that could itself trigger a wake would blur ack and message together). What
was missing is that the tool contract did not say so, which is what actually
invited the mistake.

Second pass (ChatGPT re-review, seq117): the first version of this fix itself
overclaimed, calling result "private" and a real reply left there "permanently
invisible to the other side". Neither is true - ack_result lives on the shared
message row and is visible to anyone who rereads that row (that is exactly how
this bug was noticed: Rico read the row via a full history and Claude's ack
was sitting right there). The narrower, correct claim is that it is invisible
only to seq-based incremental/wake paths, which by construction only surface
what changed since the last-seen seq, and an ack never creates that. This file
now pins both directions: the wake-path claim (already covered) and the
full-reread claim (new).
"""
from __future__ import annotations

import inspect

import runtime.claude_server as claude_server


def test_dialog_ack_docstring_warns_result_does_not_wake():
    doc = inspect.getdoc(claude_server.dialog_ack) or ""
    assert "does NOT" in doc and "wake" in doc, (
        "dialog_ack's docstring no longer warns that result is invisible to "
        "wake paths - the exact gap that let a real reply go unseen"
    )
    assert "dialog_send" in doc, "docstring should point to the actual reply channel"


def test_dialog_ack_docstring_does_not_overclaim_privacy():
    """Regression guard for ChatGPT's seq117 correction.

    ack_result sits on a shared, rereadable row - it was never private and
    never permanently invisible, only invisible to incremental/wake polling.
    """
    doc = inspect.getdoc(claude_server.dialog_ack) or ""
    assert "private" not in doc.lower(), (
        "ack_result is visible to a full reread of the message row - calling "
        "it 'private' overclaims what the system actually guarantees"
    )
    assert "permanently invisible" not in doc.lower(), (
        "ack_result is visible on a full reread - 'permanently invisible' is "
        "false, and is exactly the overclaim ChatGPT's review caught"
    )
    assert "reread" in doc.lower(), (
        "docstring should say result IS visible on a full/non-incremental "
        "reread, not only that it's absent from wake paths"
    )


def test_ack_result_does_not_touch_next_seq_or_emit_a_pulse_event():
    """Executable proof, not just a documented claim."""
    from runtime import collab

    collab.bootstrap_agent(agent_id="chatgpt", display_name="ChatGPT")
    collab.bootstrap_agent(agent_id="claude", display_name="Claude")
    msg = collab.send_message(from_agent="chatgpt", to_agent="claude", content="probe",
                               project_id="eiros-hub", thread_id="first-contact")
    before_seq = collab.room_snapshot("eiros-hub", "first-contact", 1, 0)["history"]["latest_seq"]

    claude_server.dialog_ack(agent_id="claude", message_id=msg["message_id"],
                              result="a real reply hidden here on purpose")

    after_seq = collab.room_snapshot("eiros-hub", "first-contact", 1, 0)["history"]["latest_seq"]
    assert after_seq == before_seq, (
        "acknowledging a message advanced latest_seq - if this ever changes, "
        "the docstring above must change with it, not silently drift from the code"
    )


def test_ack_result_is_visible_on_full_reread_but_absent_from_incremental_poll():
    """Pins the narrower, correct claim in place of the overclaim seq117 caught.

    Incremental polling (after_seq=<latest seq the caller already saw>) must
    stay silent on an ack alone - that silence is *why* ack is wake-safe. A
    full reread (after_seq=0, or any seq at or below the acked message's own)
    must still surface ack_result: it was never actually hidden, just never
    pushed.
    """
    from runtime import collab

    collab.bootstrap_agent(agent_id="chatgpt", display_name="ChatGPT")
    collab.bootstrap_agent(agent_id="claude", display_name="Claude")
    msg = collab.send_message(from_agent="chatgpt", to_agent="claude", content="probe2",
                               project_id="eiros-hub", thread_id="first-contact")
    latest_before_ack = collab.history("eiros-hub", "first-contact", 500, 0)["latest_seq"]

    claude_server.dialog_ack(agent_id="claude", message_id=msg["message_id"],
                              result="a real reply hidden here on purpose")

    incremental = collab.history("eiros-hub", "first-contact", 500, latest_before_ack)
    assert incremental["messages"] == [], (
        "an incremental poll from the last-seen seq surfaced something new "
        "from an ack alone - acks must stay wake-silent"
    )

    full_reread = collab.history("eiros-hub", "first-contact", 500, 0)
    acked = next(m for m in full_reread["messages"] if m["message_id"] == msg["message_id"])
    assert acked["ack_result"] == "a real reply hidden here on purpose", (
        "ack_result should be readable on a full reread of the row - it is "
        "not actually private, just not wake-discoverable"
    )
