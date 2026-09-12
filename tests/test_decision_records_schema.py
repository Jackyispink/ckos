import pytest
from pydantic import ValidationError

from app.industry_research.schemas import DecisionRecordCreate


def test_verified_record_requires_source_and_date():
    with pytest.raises(ValidationError):
        DecisionRecordCreate(record_type='customer',name='客户A',verified=True)


def test_unverified_record_preserves_unknown_fields():
    item=DecisionRecordCreate(record_type='equipment',name='瓦楞线',fields={'报价':'待询价'})
    assert item.basis == 'unverified' and item.fields['报价'] == '待询价'


@pytest.mark.parametrize('basis', ['assumption', 'unverified'])
def test_assumption_or_unverified_record_cannot_be_marked_verified(basis):
    with pytest.raises(ValidationError):
        DecisionRecordCreate(record_type='finance', name='投资假设', fields={'capex': 1000},
                             basis=basis, source='管理层假设', as_of_date='2026-09-09', verified=True)


def test_calculated_record_with_pending_inputs_cannot_be_marked_verified():
    with pytest.raises(ValidationError):
        DecisionRecordCreate(record_type='market', name='TAM测算',
                             fields={'gaps': [], 'pending': ['unit_price']}, basis='calculated',
                             source='程序计算', as_of_date='2026-09-09', verified=True)


@pytest.mark.parametrize('record_type', [
    'competitor', 'product', 'certification', 'risk', 'swot', 'interview',
])
def test_manufacturing_decision_record_types_are_supported(record_type):
    item = DecisionRecordCreate(record_type=record_type, name='待核验记录',
                                fields={'status': '待验证'})
    assert item.record_type == record_type
