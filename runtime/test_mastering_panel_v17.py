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
    assert s.PANEL_URI.endswith('mastering-panel-v17.html')
    assert s.LEGACY_PANEL_URI.endswith('mastering-panel-v16.html')
    rendered=s.mastering_panel_resource()
    assert '__PUBLIC_BASE__' not in rendered
    assert 'id="workstation"' in rendered
