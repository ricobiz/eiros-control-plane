from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_systemd_contract() -> None:
    text = (ROOT/'deploy/eiros-file-vault.service').read_text()
    assert 'WorkingDirectory=/opt/eiros-control-plane' in text
    assert 'ExecStart=/opt/eiros-control-plane/venv/bin/python -m runtime.file_vault_mcp_server' in text
    assert 'EnvironmentFile=-/etc/eiros/file-vault.env' in text
    assert 'Restart=always' in text
    assert 'UMask=0077' in text


def test_nginx_contract_is_proxy_only_and_range_safe() -> None:
    text = (ROOT/'deploy/nginx/eiros-file-vault.conf').read_text()
    assert '/vault/s/' in text
    assert '__PANEL_PREFIX__' in text
    assert '__PORT__' in text
    assert 'proxy_set_header Range $http_range' in text
    assert 'proxy_set_header If-Range $http_if_range' in text
    assert 'proxy_request_buffering off' in text
    assert '/var/lib/eiros/file-vault' not in text
    assert 'alias ' not in text
    assert '/mcp' not in text


def test_docs_explain_private_permanence_and_temporary_shares() -> None:
    text = (ROOT/'docs/FILE_VAULT.md').read_text().lower()
    assert 'permanent' in text
    assert '24' in text and 'hour' in text
    assert 'password' in text
    assert 'range' in text
    assert 'browser' in text and 'fallback' in text
    assert 'secret' in text and 'panel' in text
