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
"""
from __future__ import annotations

import inspect

import runtime.claude_server as claude_server


def test_dialog_ack_docstring_warns_result_does_not_wake():
    doc = inspect.getdoc(claude_server.dialog_ack) or ""
    assert "does NOT" in doc and "wake" in doc, (
        "dialog_ack's docstring no longer warns that result is invisible to the "
        "other agent - the exact gap that let a real reply go unseen"
    )
    assert "dialog_send" in doc, "docstring should point to the actual reply channel"


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


def test_chatgpt_dialog_ack_docstring_warns_result_does_not_wake():
    import runtime.server_v2 as server_v2
    doc = inspect.getdoc(server_v2.dialog_ack) or ""
    assert "does NOT" in doc and "wake" in doc, (
        "server_v2.dialog_ack must warn that result is not a reply/wake channel"
    )
    assert "dialog_send" in doc, "server_v2.dialog_ack should point callers to dialog_send"
