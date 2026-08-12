from pathlib import Path


def test_v17_panel_has_workstation_semantic_anchors():
    html=Path('runtime/mastering_panel_v17.html').read_text(encoding='utf-8')
    for anchor in ('workstation','transport','master-timeline','director-plan','verification','metadata-audit','revision-list'):
        assert f'id="{anchor}"' in html or f"id='{anchor}'" in html, anchor


def test_v17_panel_is_responsive_and_not_card_grid_first():
    html=Path('runtime/mastering_panel_v17.html').read_text(encoding='utf-8')
    assert '@media (max-width: 520px)' in html or '@media(max-width:520px)' in html
    assert '@media (min-width: 900px)' in html or '@media(min-width:900px)' in html
    assert 'overflow-x:hidden' in html.replace(' ','')
    # Primary audio surface must be an open timeline, not buried in repeated generic cards.
    assert 'class="card" id="master-timeline"' not in html


def test_mcp_resource_points_to_v17_and_keeps_v16_legacy():
    import runtime.mastering_mcp_server as s
    assert s.PANEL_URI.endswith('mastering-panel-v17-1.html')
    assert s.LEGACY_PANEL_URI.endswith('mastering-panel-v16.html')
    rendered=s.mastering_panel_resource()
    assert '__PUBLIC_BASE__' not in rendered
    assert 'id="workstation"' in rendered


def test_v17_director_workflow_shows_reasons_bounds_and_revision_controls():
    html=Path('runtime/mastering_panel_v17.html').read_text(encoding='utf-8')
    for token in ('id="renderDirectedBtn"','maximum_allowed_change','protected_features','expected_effect','rollback_condition','data-revision-output','Rerender'):
        assert token in html, token
    assert 'ERROR: missing Director reason' in html


def test_v17_verification_links_flags_to_timeline_and_server_gates_approval():
    html=Path('runtime/mastering_panel_v17.html').read_text(encoding='utf-8')
    assert 'seekToRange' in html
    assert 'data-qa-start' in html
    assert "v.status!=='PASS'" in html or 'v.status!==\'PASS\'' in html
    assert "post('/api/approve'" in html


def test_v17_has_live_operation_state_and_explicit_error_surface():
    html=Path('runtime/mastering_panel_v17.html').read_text(encoding='utf-8')
    for token in ('id="operationState"','aria-live="polite"','id="errorSurface"','UPLOADING','ANALYZING','RENDERING','VERIFYING','APPROVED','FAILED'):
        assert token in html, token


def test_v17_ios_safe_controls_and_reload_recovery_contract():
    html=Path('runtime/mastering_panel_v17.html').read_text(encoding='utf-8')
    assert 'min-height:44px' in html
    assert 'touch-action:none' in html
    assert 'recoverSelection' in html
    assert "a.play().catch" in html  # playback only follows explicit control action
    assert 'overflow-x:hidden' in html.replace(' ','')


def test_v17_uses_dedicated_widget_origin_without_unneeded_frames():
    import runtime.mastering_mcp_server as s
    assert s.PUBLIC_ORIGIN == 'https://eirosmaster.178-105-43-79.sslip.io'
    meta=s.PANEL_META
    assert meta['ui']['domain'] == s.PUBLIC_ORIGIN
    assert meta['openai/widgetDomain'] == s.PUBLIC_ORIGIN
    assert 'frameDomains' not in meta['ui']['csp']
    assert 'frame_domains' not in meta['openai/widgetCSP']


def test_minimal_diagnostic_widget_contract():
    src=Path('runtime/mastering_mcp_server.py').read_text(encoding='utf-8')
    assert 'ui://eiros/mastering-diagnostic-v1.html' in src
    assert 'open_mastering_diagnostic' in src
    assert 'notifyIntrinsicHeight' in src
    assert 'ui/notifications/tool-result' in src
    assert 'EIROS WIDGET OK' in src
