import pytest
from runtime.mastering_director import validate_director_plan, plan_fingerprint


def base_plan():
    return {
        'intent': 'preserve ritual sub mass',
        'protected_traits': ['sub_mass'],
        'target': {'lufs': -10.8, 'true_peak_dbtp': -1.1},
        'sections': [{'start': 0.0, 'end': 20.0, 'actions': []}],
    }


def test_rejects_action_without_reason():
    plan = base_plan()
    plan['sections'][0]['actions'] = [{'type': 'eq', 'frequency_hz': 62, 'gain_db': -0.5}]
    with pytest.raises(ValueError, match='reason'):
        validate_director_plan(plan, 20.0)


def test_rejects_overlapping_sections():
    plan = base_plan()
    plan['sections'] = [{'start': 0, 'end': 12, 'actions': []}, {'start': 10, 'end': 20, 'actions': []}]
    with pytest.raises(ValueError, match='overlap'):
        validate_director_plan(plan, 20.0)


def test_rejects_action_outside_duration():
    plan = base_plan()
    plan['sections'][0]['actions'] = [{'type': 'gain', 'gain_db': 0.5, 'start': 19, 'end': 21, 'reason': 'lift outro'}]
    with pytest.raises(ValueError, match='duration'):
        validate_director_plan(plan, 20.0)


def test_rejects_unbounded_limiter():
    plan = base_plan()
    plan['sections'][0]['actions'] = [{'type': 'limiter', 'reason': 'safety peaks'}]
    with pytest.raises(ValueError, match='bounds'):
        validate_director_plan(plan, 20.0)


def test_valid_plan_is_normalized_and_fingerprint_stable():
    plan = base_plan()
    plan['sections'][0]['actions'] = [{
        'type': 'dynamic_eq', 'frequency_hz': 62, 'gain_db': -0.4,
        'reason': 'local resonance only', 'bounds': {'max_abs_gain_db': 0.5},
    }]
    a = validate_director_plan(plan, 20.0)
    b = validate_director_plan(plan, 20.0)
    assert a['schema_version'] == '0.4'
    assert a['protected_traits'] == ['sub_mass']
    assert a['sections'][0]['actions'][0]['start'] == 0.0
    assert a['sections'][0]['actions'][0]['end'] == 20.0
    assert plan_fingerprint(a) == plan_fingerprint(b)
