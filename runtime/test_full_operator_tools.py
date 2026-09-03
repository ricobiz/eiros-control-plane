import asyncio

from runtime import vps_ops_server


REQUIRED = {
    "fs_stat", "fs_list", "fs_read", "fs_write", "fs_replace", "fs_copy", "fs_move", "fs_mkdir", "fs_delete", "fs_chmod", "fs_chown",
    "desktop_status", "desktop_frame", "desktop_windows", "desktop_focus", "desktop_pointer", "desktop_drag", "desktop_scroll", "desktop_key", "desktop_text", "desktop_clipboard_set", "desktop_wait",
    "secret_list", "secret_exists", "secret_set", "secret_delete", "secret_type", "secret_exec_env", "secret_exec_stdin",
    "pty_start", "pty_write", "pty_read", "pty_resize", "pty_signal", "pty_close", "pty_list",
    "critical_stage", "critical_write", "critical_verify", "critical_commit", "critical_rollback", "critical_status",
}


def test_vps_ops_registers_full_operator_tools() -> None:
    names = {tool.name for tool in asyncio.run(vps_ops_server.mcp.list_tools())}
    assert REQUIRED <= names, sorted(REQUIRED - names)


def test_desktop_frame_converts_to_native_mcp_image_content() -> None:
    result = asyncio.run(
        vps_ops_server.mcp._tool_manager.call_tool(
            "desktop_frame",
            {"after_seq": 0},
            convert_result=True,
        )
    )
    assert any(getattr(item, "type", "") == "image" for item in result)
    image = next(item for item in result if getattr(item, "type", "") == "image")
    assert image.mimeType == "image/jpeg"
    assert len(image.data) > 1000


def test_vps_ops_instructions_advertise_full_operator_capabilities() -> None:
    text = vps_ops_server.mcp.instructions.lower()
    assert "unrestricted filesystem" in text
    assert "desktop" in text
    assert "persistent pty" in text
    assert "secret" in text
