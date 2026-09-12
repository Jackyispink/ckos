"""Lossless, deterministic reading blocks for existing reports. No paid calls.

These are source adaptations, not independently verified research conclusions.
Chart binding requires every source excerpt to occur in this block, not merely
the same chapter or a coincidentally equal number.
"""
import hashlib
import re
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchBlock(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=80)
    question: str = Field(default='', max_length=160)
    claim: str = Field(default='', max_length=140)
    content: str = Field(default='', max_length=520)
    limitation: str = Field(default='', max_length=120)
    chart_ids: list[str] = Field(default_factory=list, max_length=2)
    columns: list[str] = Field(default_factory=list, max_length=5)
    rows: list[list[str]] = Field(default_factory=list, max_length=5)
    binding_confirmed: bool = False

    @model_validator(mode='after')
    def shape(self):
        if len(set(self.chart_ids)) != len(self.chart_ids):
            raise ValueError('同一内容块不能重复绑定图表')
        if self.rows and (not self.columns or any(len(r)!=len(self.columns) for r in self.rows)):
            raise ValueError('比较表每行列数必须与表头一致')
        if any(len(c)>50 for row in [self.columns,*self.rows] for c in row):
            raise ValueError('比较表单元格最多50字，请拆分维度或行')
        if self.chart_ids and self.rows:
            raise ValueError('图表分析和比较表请分成两个研究内容块')
        if (self.chart_ids or self.rows) and len(self.content)>180:
            raise ValueError('图表或比较表页的分析正文最多180字，请拆页保留完整内容')
        if (self.chart_ids or self.rows) and len(self.claim)+len(self.content)>180:
            raise ValueError('图表或比较表页的核心判断与正文合计最多180字')
        return self


def normalized(text):
    return re.sub(r'[\s#*_`|]|\[\d+(?:-\d+)?\]', '', text)


def chart_matches(content, chart):
    excerpts = [normalized(x) for x in chart.get('source_excerpts',[]) if normalized(x)]
    source = normalized(content)
    return bool(excerpts) and all(len(x)>=6 and x in source for x in excerpts)


def chunks(text, budget=440):
    """Prefer paragraph/sentence boundaries; keep every source character."""
    text=text.strip()
    while len(text)>budget:
        ends=[m.end() for m in re.finditer(r'[。！？\n]',text[:budget])]
        at=ends[-1] if ends else budget
        yield text[:at]
        text=text[at:]
    if text: yield text


def build_reading_outline(snapshot):
    title=snapshot['project']['title']
    slides=[dict(title=title[:44],chapter=0,layout='cover',bullets=[],chart_id=None,enabled=True)]
    for chapter in sorted(snapshot['project']['chapters'],key=lambda c:c['chapter_no']):
        no=chapter['chapter_no']; heading=chapter['title']; lines=[]
        def emit(content, columns=None, rows=None):
            if not content.strip() and not rows:return
            parts=list(chunks(content)) if not rows else [content]
            for part in parts:
                identifier=hashlib.sha256(f'{no}:{len(slides)}:{part}:{rows}'.encode()).hexdigest()[:24]
                block=ResearchBlock(id=identifier,content=part,columns=columns or [],rows=rows or [])
                # Only automatically bind if the entire quoted evidence fits the
                # available analysis area; otherwise leave the chart unassigned.
                if not rows and len(part)<=180:
                    block.chart_ids=[c['id'] for c in snapshot.get('charts',[]) if c['chapter_no']==no and chart_matches(part,c)][:2]
                slides.append(dict(title=heading[:44],chapter=no,layout='research',bullets=[],chart_id=None,
                                   enabled=True,research=block.model_dump()))
        def flush():
            if lines: emit('\n'.join(lines));lines.clear()
        raw=(chapter.get('content') or '').splitlines();i=0
        while i<len(raw):
            line=raw[i]
            if re.match(r'^\s*#{1,6}\s+',line):
                flush();heading=re.sub(r'^\s*#{1,6}\s+','',line).replace('**','').strip();i+=1;continue
            if line.strip().startswith('|'):
                flush(); table=[]
                while i<len(raw) and raw[i].strip().startswith('|'):
                    cells=[c.strip().replace('**','') for c in raw[i].strip().strip('|').split('|')]
                    if not all(re.fullmatch(r':?-{2,}:?',c) for c in cells): table.append(cells)
                    i+=1
                if len(table)>1 and 1<=len(table[0])<=5 and all(len(r)==len(table[0]) and all(len(c)<=50 for c in r) for r in table):
                    for offset in range(1,len(table),5):emit('',table[0],table[offset:offset+5])
                else:
                    # Preserve oversized tables as text, never drop columns.
                    emit('\n'.join(' | '.join(row) for row in table))
                continue
            lines.append(line.replace('**',''));i+=1
        flush()
    # Short subsections share a reading page, retaining their own headings.
    # A subsection is not automatically a whole slide (a major source of whitespace).
    merged=[]
    chapter_titles={c['chapter_no']:c['title'] for c in snapshot['project']['chapters']}
    for page in slides:
        previous=merged[-1] if merged else None
        b=page.get('research');a=previous.get('research') if previous else None
        if a and b and page['chapter']==previous['chapter'] and not any((a['rows'],b['rows'],a['chart_ids'],b['chart_ids'])):
            prior=a['content'] if previous.get('_grouped') else previous['title']+'\n'+a['content']
            combined=prior+'\n\n'+page['title']+'\n'+b['content']
            if len(combined)<=400:
                a['content']=combined;previous['title']=chapter_titles[page['chapter']][:44];previous['_grouped']=True
                continue
        merged.append(page)
    for page in merged:page.pop('_grouped',None)
    if len(merged)>120:raise ValueError('阅读版超过120页，请先缩小报告范围；没有自动删除正文')
    return merged


def reading_warnings(slides, charts, chapters=()):
    result=[];bound=set()
    originals={c['chapter_no']:c.get('content','') for c in chapters}
    for i,s in enumerate(slides,1):
        if not s.get('enabled') or not s.get('research'):continue
        b=s['research'];bound.update(b['chart_ids'])
        if b['chart_ids'] and not b.get('binding_confirmed'):
            result.append(f'第{i}页：图表按原文摘录绑定，请核对指标口径和论点后确认关系')
        if b.get('claim') and not re.search(r'\[\d+(?:-\d+)?\]',b['claim']+b['content']):
            result.append(f'第{i}页：核心判断没有引用编号，请核对支撑证据')
        combined=b.get('claim','')+b.get('content','')+b.get('limitation','')+' '.join(' '.join(r) for r in b.get('rows',[]))
        if chapters:
            missing=set(re.findall(r'\d+(?:\.\d+)?',combined))-set(re.findall(r'\d+(?:\.\d+)?',originals.get(s['chapter'],'')))
            if missing:result.append(f'第{i}页：新增数字 {"、".join(sorted(missing))} 未在原章节找到，需核对来源')
        if re.search('预测|预计',combined) and not re.search(r'假设|情景|测算|依据|来源|\[\d',combined):
            result.append(f'第{i}页：预测未标明依据或引用，请补充假设；此检查不代表事实已核实')
    unbound=[c for c in charts if c['id'] not in bound]
    if unbound: result.append(f'{len(unbound)}张图尚未绑定到具体内容块，未自动插入；可在编辑器中核对出处后选择')
    return result


def dataset_ledger(snapshot):
    """Expose the existing literal data, never guess missing statistical scope."""
    return [dict(id=c['id'],chapter=c['chapter_no'],metric=c['title'],unit=c['unit'],
                 scope=c.get('scope') or '未确认：请核对原文统计范围',
                 geography=c.get('geography') or '未确认',
                 observations=[dict(period=label,value=value,basis='待核对实际/预测',
                                    source_excerpt=(c.get('source_excerpts') or [''])[min(i,len(c.get('source_excerpts') or [''])-1)])
                               for i,(label,value) in enumerate(zip(c['labels'],c['values']))],
                 provenance='旧报告正文提取，非独立核验数据') for c in snapshot.get('charts',[])]
