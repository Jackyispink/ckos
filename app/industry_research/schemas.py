import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ResearchBrief(BaseModel):
    research_template: Literal['general', 'manufacturing'] = 'general'
    manufacturing_type: Literal['process', 'components', 'equipment', 'consumer', 'other'] = 'other'
    product_scope: str = Field(default='', max_length=2000)
    downstream_applications: str = Field(default='', max_length=2000)
    target_company: str = Field(default='', max_length=300)
    topic: str = Field(min_length=2, max_length=120)
    geography: str = Field(default='中国', min_length=1, max_length=500)
    history_start: int = Field(default=2021, ge=1990, le=2100)
    history_end: int = Field(default=2025, ge=1990, le=2100)
    forecast_end: int = Field(default=2030, ge=1990, le=2100)
    purpose: str = Field(default='行业战略与投资机会判断', max_length=1000)
    focus: str = Field(default='', max_length=6000)
    included_segments: str = Field(default='', max_length=3000)
    excluded_segments: str = Field(default='', max_length=3000)
    key_companies: str = Field(default='', max_length=2000)
    depth: Literal['quick', 'standard', 'deep'] = 'standard'

    @model_validator(mode='after')
    def validate_period(self):
        if self.history_start > self.history_end:
            raise ValueError('历史起始年份不能晚于结束年份')
        if self.forecast_end <= self.history_end:
            raise ValueError('预测结束年份必须晚于历史结束年份')
        return self


class EvidenceCreate(BaseModel):
    chapter_no: int = Field(ge=1, le=10)
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(default='', max_length=2000)
    publisher: str = Field(default='', max_length=200)
    published_at: str = Field(default='', max_length=40)
    excerpt: str = Field(min_length=1, max_length=12000)
    source_type: str = Field(default='用户补充', max_length=80)


class ChapterSearchRequest(BaseModel):
    max_queries: int = Field(default=3, ge=1, le=5)
    results_per_query: int = Field(default=8, ge=1, le=10)


class ChapterCollectRequest(BaseModel):
    max_web_queries: int = Field(default=3, ge=1, le=5)
    results_per_query: int = Field(default=8, ge=1, le=10)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)


class ChapterUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=50000)


class ChartChoice(BaseModel):
    id: str = Field(min_length=8, max_length=40)
    selected: bool = True
    chart_type: Literal['line', 'bar', 'pie', 'card', 'area', 'column', 'scatter', 'lollipop'] = 'bar'
    title: str = Field(min_length=1, max_length=200)


class ChartChoices(BaseModel):
    charts: list[ChartChoice] = Field(default_factory=list, max_length=300)

    @model_validator(mode='after')
    def unique_choices(self):
        if len({item.id for item in self.charts}) != len(self.charts):
            raise ValueError('同一张图表不能重复提交')
        return self


class DecisionRecordCreate(BaseModel):
    record_type: Literal['market', 'customer', 'supplier', 'equipment', 'city', 'finance', 'threshold',
                         'competitor', 'product', 'certification', 'risk', 'swot', 'interview']
    name: str = Field(min_length=1, max_length=200)
    fields: dict[str, Any] = Field(default_factory=dict)
    basis: Literal['actual', 'quote', 'assumption', 'calculated', 'unverified'] = 'unverified'
    source: str = Field(default='', max_length=1000)
    as_of_date: str = Field(default='', max_length=40)
    verified: bool = False

    @model_validator(mode='after')
    def verified_requires_provenance(self):
        if len(json.dumps(self.fields, ensure_ascii=False, default=str)) > 20000:
            raise ValueError('单条结构化记录不能超过20000字符，请拆分记录')
        if self.verified and (not self.source.strip() or not self.as_of_date.strip()):
            raise ValueError('确认记录必须填写来源和日期')
        if self.verified and self.basis in ('assumption', 'unverified'):
            raise ValueError('假设或待验证记录不能标为已核对事实')
        if self.verified and self.basis == 'calculated':
            if (self.fields.get('gaps') or self.fields.get('pending')):
                raise ValueError('仍有缺失或待核对输入的程序测算不能标为已核对')
        return self


class DecisionRecordUpdate(BaseModel):
    record_type: Literal['market', 'customer', 'supplier', 'equipment', 'city', 'finance', 'threshold',
                         'competitor', 'product', 'certification', 'risk', 'swot', 'interview'] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    fields: dict[str, Any] | None = None
    basis: Literal['actual', 'quote', 'assumption', 'calculated', 'unverified'] | None = None
    source: str | None = Field(default=None, max_length=1000)
    as_of_date: str | None = Field(default=None, max_length=40)
    verified: bool | None = None


class DecisionAutoExtractRequest(BaseModel):
    """Optional controls for extracting decision candidates from saved evidence."""

    use_ai: bool = True
    force: bool = False
