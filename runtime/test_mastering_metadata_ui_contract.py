from pathlib import Path


def test_metadata_view_separates_structural_from_removable_and_disclaims_watermark_claims():
    html=Path('runtime/mastering_panel_v17.html').read_text(encoding='utf-8')
    for token in ('id="structuralMeta"','id="removableMeta"','id="cleanExportReport"','No claim is made that proprietary acoustic watermarks were detected or removed.'):
        assert token in html, token


def test_memory_view_is_advisory_and_never_applies_dsp_directly():
    html=Path('runtime/mastering_panel_v17.html').read_text(encoding='utf-8')
    for token in ('id="experience-memory"','id="memoryList"','Use as context','/api/experience-similar','memoryContext'):
        assert token in html, token
    assert 'Memory is advisory' in html
    # Context selection must not call render directly.
    context_fn=html.split('function useMemoryContext',1)[1].split('function ',1)[0]
    assert '/api/render-directed' not in context_fn
