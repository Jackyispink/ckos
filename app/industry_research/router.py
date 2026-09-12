import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from . import (charts, collection_jobs, database, decision_auto_calculation,
               decision_extraction, planner, writer)
from .schemas import (ChapterCollectRequest, ChapterSearchRequest, ChapterUpdate,
                      ChartChoice, ChartChoices, DecisionAutoExtractRequest,
                      DecisionRecordCreate, DecisionRecordUpdate, EvidenceCreate,
                      ProjectUpdate, ResearchBrief)
from .search import SearchProviderError, configured, provider_name
from .search.service import search_chapter
from .sources import collect_chapter
from .exporter import build_docx
from .manufacturing_calculations import ManufacturingScenario, calculate

router = APIRouter(prefix='/api/industry', tags=['industry research'])
logger = logging.getLogger(__name__)


from .decision_finance import FinanceInputs, calculate_finance
from .decision_gate import DecisionGateInputs, calculate_gate
from .decision_market import MarketInputs, calculate_market
from .decision_city import CityInputs, calculate_city
from .evidence_grading import audit as audit_evidence, classify as classify_evidence


@router.post('/decision/finance/calculate')
def decision_finance(body: FinanceInputs):
    return calculate_finance(body)


@router.post('/decision/market/calculate')
def decision_market(body: MarketInputs):
    return calculate_market(body)


@router.post('/decision/gate/calculate')
def decision_gate(body: DecisionGateInputs):
    return calculate_gate(body)


@router.post('/decision/city/calculate')
def decision_city(body: CityInputs):
    return calculate_city(body)


@router.get('/projects/{project_id}/decision-records')
def list_decision_records(project_id: str, record_type: str | None = None):
    if not database.project(project_id):
        raise HTTPException(404, '行业研究项目不存在')
    if record_type and record_type not in {
            'market','customer','supplier','equipment','city','finance','threshold',
            'competitor','product','certification','risk','swot','interview'}:
        raise HTTPException(422, '不支持的决策数据类型')
    return database.decision_records(project_id, record_type)


@router.post('/projects/{project_id}/decision-records', status_code=201)
def create_decision_record(project_id: str, body: DecisionRecordCreate):
    if writer.is_running(project_id):
        raise HTTPException(409, '报告生成中，请完成或取消后再修改决策数据')
    record_id = database.add_decision_record(project_id, body)
    if not record_id:
        raise HTTPException(404, '行业研究项目不存在')
    return database.decision_record(project_id, record_id)


@router.post('/projects/{project_id}/decision-records/auto-extract')
async def auto_extract_decision_records(
        project_id: str, body: DecisionAutoExtractRequest | None = None):
    if not database.project(project_id):
        raise HTTPException(404, '行业研究项目不存在')
    if writer.is_running(project_id):
        raise HTTPException(409, '报告生成中，自动整理会随生成流程完成；请稍后查看')
    options = body or DecisionAutoExtractRequest()
    try:
        result = await decision_extraction.extract_project(
            project_id, use_ai=options.use_ai, force=options.force)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        result['calculation'] = decision_auto_calculation.calculate_project(project_id)
    except Exception as exc:
        logger.exception(
            'industry project=%s automatic calculation failed after extraction',
            project_id,
        )
        result['calculation'] = {
            'error': str(exc) or '自动计算暂时不可用',
        }
    return result


@router.patch('/projects/{project_id}/decision-records/{record_id}')
def edit_decision_record(project_id: str, record_id: str, body: DecisionRecordUpdate):
    if writer.is_running(project_id):
        raise HTTPException(409, '报告生成中，请完成或取消后再修改决策数据')
    old = database.decision_record(project_id, record_id)
    if not old:
        raise HTTPException(404, '决策数据不存在')
    merged = dict(old)
    merged.update(body.model_dump(exclude_unset=True))
    DecisionRecordCreate(**{k: merged[k] for k in ('record_type','name','fields','basis','source','as_of_date','verified')})
    database.update_decision_record(project_id, record_id, body)
    return database.decision_record(project_id, record_id)


@router.delete('/projects/{project_id}/decision-records/{record_id}')
def remove_decision_record(project_id: str, record_id: str):
    if writer.is_running(project_id):
        raise HTTPException(409, '报告生成中，请完成或取消后再修改决策数据')
    if not database.delete_decision_record(project_id, record_id):
        raise HTTPException(404, '决策数据不存在')
    return {'deleted': record_id}


from .evidence_review import (BulkReviewRequest, PreReviewRequest, ReviewDecision,
                              current_pre_review,
                              usable as usable_evidence,
                              warnings as review_warnings)
from . import evidence_pre_review


def _usable_project_evidence(project_id):
    """One evidence view for UI audits and current-report exports."""
    return usable_evidence(database.all_evidence(project_id))


@router.get('/projects/{project_id}/chapters/{chapter_no}/evidence-review')
def evidence_review(project_id: str, chapter_no: int):
    project = database.project(project_id)
    if not project or not database.chapter(project_id, chapter_no):
        raise HTTPException(404, '章节不存在')
    source_rows = database.review_evidence(project_id, chapter_no)
    if source_rows and any(not current_pre_review(row) for row in source_rows):
        try:
            # Opening an older chapter should immediately show deterministic
            # exact-quote previews. This local pass never calls the model.
            evidence_pre_review.refresh_chapter_from_existing(
                project_id, chapter_no, use_ai=False)
            source_rows = database.review_evidence(project_id, chapter_no)
        except Exception:
            logger.exception(
                'industry project=%s chapter=%s lazy pre-review failed',
                project_id, chapter_no)
    rows = [dict(r, evidence_grade=classify_evidence(r),
                 pre_review=current_pre_review(r),
                 review_warnings=review_warnings(r))
            for r in source_rows]
    return {
        'schema_version': 2,
        'summary': evidence_pre_review.review_summary(project, chapter_no, rows),
        'rows': rows,
    }


@router.post('/projects/{project_id}/chapters/{chapter_no}/evidence-review/auto')
async def auto_review_evidence(project_id: str, chapter_no: int,
                               body: PreReviewRequest | None = None):
    if writer.is_running(project_id):
        raise HTTPException(409, '报告生成中，请完成或取消后再自动整理资料')
    options = body or PreReviewRequest()
    try:
        return await evidence_pre_review.run(
            project_id, chapter_no, use_ai=options.use_ai, force=options.force)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None


@router.post('/projects/{project_id}/chapters/{chapter_no}/evidence-review/apply-suggestions')
def apply_evidence_review_suggestions(project_id: str, chapter_no: int,
                                      body: BulkReviewRequest):
    """Apply only low-risk routing after one explicit human confirmation.

    Suggested rows with traceable quotes are retained; empty and byte-for-byte
    duplicate excerpts are excluded as independent evidence.  Conflicts,
    suspicious relevance, weak sources and all other manual-review rows remain
    untouched.  This is routing confirmation, not factual verification.
    """
    if writer.is_running(project_id):
        raise HTTPException(409, '报告生成中，请完成或取消后再批量处理资料')
    if body.confirm not in {
            'apply_safe_suggestions', 'approve_all_pending',
            'exclude_all_pending'}:
        raise HTTPException(422, '需要明确确认才能批量处理')
    project = database.project(project_id)
    if not project or not database.chapter(project_id, chapter_no):
        raise HTTPException(404, '章节不存在')
    rows = database.review_evidence(project_id, chapter_no)
    if any(not current_pre_review(row) for row in rows):
        evidence_pre_review.refresh_chapter_from_existing(
            project_id, chapter_no, use_ai=False)
        rows = database.review_evidence(project_id, chapter_no)
    decisions = {}
    retained = excluded = 0
    for row in rows:
        if ((row.get('metadata') or {}).get('review') or {}).get('decision'):
            continue
        assessment = current_pre_review(row)
        state = assessment.get('state')
        if body.confirm == 'approve_all_pending' and (row.get('excerpt') or '').strip():
            decisions[str(row.get('id') or '')] = {
                'decision': 'approved',
                'reason': '用户一键确认保留本章全部待处理非空资料；事实、数字与口径仍按报告规则交叉核验。',
            }
            retained += 1
        elif body.confirm == 'exclude_all_pending':
            decisions[str(row.get('id') or '')] = {
                'decision': 'excluded',
                'reason': '用户一键确认排除本章全部待处理资料；原始资料记录仍保留。',
            }
            excluded += 1
        elif body.confirm == 'approve_all_pending':
            # Empty rows can never become usable evidence; approving them would
            # make the UI look complete while the writing gate correctly fails.
            decisions[str(row.get('id') or '')] = {
                'decision': 'excluded',
                'reason': '系统随一键保留操作排除无正文资料；空白内容不能作为报告证据。',
            }
            excluded += 1
        elif state == 'recommended_for_review' and assessment.get('exact_quotes'):
            decisions[str(row.get('id') or '')] = {
                'decision': 'approved',
                'reason': '用户确认系统分流：保留可回查的逐字摘录；关键数字与口径仍待核验。',
            }
            retained += 1
        elif state in {'duplicate', 'empty'}:
            decisions[str(row.get('id') or '')] = {
                'decision': 'excluded',
                'reason': '用户确认系统分流：空白或完全重复资料不作为独立证据。',
            }
            excluded += 1
    saved = database.save_evidence_reviews_bulk(
        project_id, chapter_no, decisions)
    refreshed = database.review_evidence(project_id, chapter_no)
    pending_remaining = sum(
        not (((row.get('metadata') or {}).get('review') or {}).get('decision'))
        for row in refreshed
    )
    return {
        'saved': saved,
        'retained': retained,
        'excluded': excluded,
        'manual_remaining': sum(
            not (((row.get('metadata') or {}).get('review') or {}).get('decision'))
            and current_pre_review(row).get('state') == 'manual_review'
            for row in refreshed
        ),
        'pending_remaining': pending_remaining,
        'review_complete': bool(database.clear_review_requirement_if_complete(
            project_id, chapter_no) or database.evidence_review_state(
                project_id, chapter_no)['complete']),
        'fact_verification': False,
    }


@router.put('/projects/{project_id}/chapters/{chapter_no}/evidence-review/{evidence_id}')
def decide_evidence(project_id: str, chapter_no: int, evidence_id: str, body: ReviewDecision):
    if writer.is_running(project_id):
        raise HTTPException(409, '请先停止生成再审核资料')
    if not database.save_evidence_review(project_id, chapter_no, evidence_id, body.model_dump()):
        raise HTTPException(404, '证据不存在')
    provider_gate_cleared = database.clear_review_requirement_if_complete(project_id, chapter_no)
    state = database.evidence_review_state(project_id, chapter_no)
    chapter_row = database.chapter(project_id, chapter_no)
    return {
        'saved': True,
        'review_complete': bool(provider_gate_cleared or state['complete']),
        'report_update_required': bool(
            chapter_row and chapter_row.get('content', '').strip() and
            chapter_row.get('evidence_revision', 0) > chapter_row.get('content_evidence_revision', 0)),
    }


@router.post('/manufacturing/calculate')
def manufacturing_calculate(body: ManufacturingScenario):
    return calculate(body)


@router.put('/projects/{project_id}/manufacturing-scenario')
def save_manufacturing_scenario(project_id: str, body: ManufacturingScenario):
    if writer.is_running(project_id):
        raise HTTPException(409, '报告生成中，请完成后再保存测算')
    result = calculate(body)
    if not database.save_manufacturing_scenario(project_id, result):
        raise HTTPException(404, '行业研究项目不存在')
    return result


@router.get('/projects/{project_id}/manufacturing-scenario')
def get_manufacturing_scenario(project_id: str):
    project = database.project(project_id)
    if not project:
        raise HTTPException(404, '行业研究项目不存在')
    return project.get('manufacturing_scenario')


@router.get('/search/status')
def search_status():
    return {'provider': provider_name(), 'configured': configured()}


@router.get('/projects')
def projects():
    rows = database.list_projects()
    for row in rows:
        if row['status'] == 'running' and not writer.is_running(row['id']):
            row['status'] = 'interrupted'
    return rows


@router.post('/projects', status_code=201)
def create_project(brief: ResearchBrief):
    plan = planner.build_plan(brief)
    project_id = database.create_project(brief, plan)
    return {'id': project_id, 'brief_summary': planner.brief_summary(brief), 'chapters': plan}


@router.get('/projects/{project_id}')
def get_project(project_id: str):
    result = database.project(project_id)
    if not result:
        raise HTTPException(404, '行业研究项目不存在')
    result['generation_active'] = writer.is_running(project_id)
    if result.get('brief', {}).get('research_template') == 'manufacturing':
        expected = {x['chapter_no']: x['title'] for x in planner.build_plan(ResearchBrief(**result['brief']))}
        actual = {x['chapter_no']: x['title'] for x in result['chapters'] if x['chapter_no'] > 0}
        result['manufacturing_plan_current'] = actual == expected
    evidence_by_chapter = {}
    for item in _usable_project_evidence(project_id):
        evidence_by_chapter.setdefault(item['chapter_no'], []).append(item)
    for chapter in result['chapters']:
        chapter['evidence_audit'] = audit_evidence(evidence_by_chapter.get(chapter['chapter_no'], []))
    result.update(writer.generation_state(project_id))
    if result['cancel_requested']:
        result['current_stage'] = '正在取消：等待当前模型请求结束，不再生成后续章节'
    if result['status'] == 'running' and not result['generation_active']:
        result['status'] = 'interrupted'
        result['current_stage'] = '生成已中断，点击继续生成；已完成章节将保留'
    return result


@router.post('/projects/{project_id}/upgrade-manufacturing-plan')
def upgrade_manufacturing_plan(project_id: str):
    if writer.is_running(project_id):
        raise HTTPException(409, '请先取消生成并等待任务停止')
    project = database.project(project_id)
    if not project:
        raise HTTPException(404, '行业研究项目不存在')
    if project.get('brief', {}).get('research_template') != 'manufacturing':
        raise HTTPException(409, '仅制造业研究可以升级为进入决策版')
    plan = planner.build_plan(ResearchBrief(**project['brief']))
    state = database.upgrade_manufacturing_plan(project_id, plan)
    return {'state': state, 'version_saved': state == 'upgraded'}


@router.patch('/projects/{project_id}')
def edit_project(project_id: str, body: ProjectUpdate):
    if body.title is None or not database.update_project(project_id, body.title.strip()):
        raise HTTPException(404, '行业研究项目不存在')
    return database.project(project_id)


@router.delete('/projects/{project_id}')
def remove_project(project_id: str):
    if writer.is_running(project_id):
        raise HTTPException(409, '请先取消生成，等待任务停止后再删除报告')
    if not database.delete_project(project_id):
        raise HTTPException(404, '行业研究项目不存在')
    return {'deleted': project_id}


@router.patch('/projects/{project_id}/chapters/{chapter_no}')
def edit_chapter(project_id: str, chapter_no: int, body: ChapterUpdate):
    if writer.is_running(project_id):
        raise HTTPException(409, '生成期间不能修改正文，请先取消并等待任务停止')
    if not database.update_chapter(project_id, chapter_no, body.title,
                                   body.content.strip() if body.content is not None else None):
        raise HTTPException(404, '行业研究章节不存在')
    return database.chapter(project_id, chapter_no)


@router.post('/projects/{project_id}/chapters/{chapter_no}/refresh-from-evidence', status_code=202)
def refresh_chapter_from_reviewed_evidence(project_id: str, chapter_no: int):
    """Regenerate one chapter only after its complete evidence review."""
    if chapter_no < 1 or chapter_no > 10:
        raise HTTPException(422, '只能更新第1至第10章')
    if writer.is_running(project_id):
        raise HTTPException(409, '报告正在生成，请完成或取消后再更新')
    state = database.evidence_review_state(project_id, chapter_no)
    if not state['complete']:
        raise HTTPException(
            409, f'本章资料尚未复核完成：待处理{state["pending"]}条；每条须保留或排除，并至少保留一条有效资料。')
    queued = database.queue_reviewed_chapter_refresh(project_id, chapter_no)
    if not queued or not queued[0]:
        raise HTTPException(404, '行业研究章节不存在')
    if not writer.start(project_id, mode='resume'):
        raise HTTPException(409, '生成任务已经在运行')
    return {'started': True, 'chapter_no': chapter_no, 'review_complete': True}


def _chart_state(project_id, project=None):
    project = project or database.project(project_id)
    if not project: raise HTTPException(404, '行业研究项目不存在')
    project = dict(
        project,
        decision_records=database.decision_records(project_id),
        evidence=database.all_evidence(project_id),
    )
    saved = database.chart_selections(project_id); result = charts.discover(project)
    stale = {key for key, choice in saved.items() if choice['selected']}
    for item in result:
        choice = saved.get(item['id'])
        valid = bool(choice and choice['chart_type'] in item['chart_types'])
        item['selected'] = bool(valid and choice['selected'])
        item['selected_type'] = choice['chart_type'] if valid else item['chart_types'][0]
        if choice: item['title'] = choice['title']
        if valid: stale.discard(item['id'])
    return result, sorted(stale)


def _chart_candidates(project_id):
    return _chart_state(project_id)[0]


@router.get('/projects/{project_id}/charts')
def project_charts(project_id: str):
    candidates, stale = _chart_state(project_id)
    return {'charts': candidates, 'selected_count': sum(x['selected'] for x in candidates),
            'stale_selected_count': len(stale)}


@router.delete('/projects/{project_id}/charts/stale')
def clear_stale_charts(project_id: str):
    _, stale = _chart_state(project_id)
    database.remove_chart_selections(project_id, stale)
    return project_charts(project_id)


@router.put('/projects/{project_id}/charts')
def choose_charts(project_id: str, body: ChartChoices):
    available = {item['id']: item for item in _chart_candidates(project_id)}
    for choice in body.charts:
        if choice.id not in available or choice.chart_type not in available[choice.id]['chart_types']:
            raise HTTPException(422, f'图表 {choice.id} 不存在或类型不适用')
    if not database.save_chart_selections(project_id, body.charts):
        raise HTTPException(404, '行业研究项目不存在')
    return project_charts(project_id)


@router.put('/projects/{project_id}/charts/{chart_id}')
def choose_one_chart(project_id: str, chart_id: str, body: ChartChoice):
    if body.id != chart_id: raise HTTPException(422, '图表编号不一致')
    available = {item['id']: item for item in _chart_candidates(project_id)}
    if chart_id not in available or body.chart_type not in available[chart_id]['chart_types']:
        raise HTTPException(422, '图表不存在或类型不适用')
    if not database.save_chart_selection(project_id, body):
        raise HTTPException(404, '行业研究项目不存在')
    return next(item for item in _chart_candidates(project_id) if item['id'] == chart_id)


@router.post('/projects/{project_id}/evidence', status_code=201)
def add_evidence(project_id: str, item: EvidenceCreate):
    evidence_id = database.add_evidence(project_id, item)
    if not evidence_id:
        raise HTTPException(404, '行业研究项目不存在')
    try:
        pre_review = evidence_pre_review.refresh_chapter_from_existing(
            project_id, item.chapter_no, use_ai=False)
    except Exception:
        logger.exception(
            'industry project=%s chapter=%s manual evidence pre-review failed',
            project_id, item.chapter_no)
        pre_review = {'error': '原始资料已保存，自动摘录索引暂时未完成'}
    return {'id': evidence_id, 'pre_review': pre_review}


@router.post('/projects/{project_id}/generate', status_code=202)
@router.post('/projects/{project_id}/resume', status_code=202)
def generate(project_id: str):
    if not database.project(project_id):
        raise HTTPException(404, '行业研究项目不存在')
    if not writer.start(project_id):
        raise HTTPException(409, '该报告正在生成中')
    return {'started': True}


@router.post('/projects/{project_id}/regenerate', status_code=202)
def regenerate(project_id: str):
    if not database.project(project_id):
        raise HTTPException(404, '行业研究项目不存在')
    if not writer.start(project_id, mode='regenerate'):
        raise HTTPException(409, '该报告正在生成中，请先取消并等待任务停止')
    return {'started': True, 'mode': 'regenerate'}


@router.post('/projects/{project_id}/cancel', status_code=202)
def cancel_generation(project_id: str):
    if not database.project(project_id):
        raise HTTPException(404, '行业研究项目不存在')
    if not writer.cancel(project_id):
        raise HTTPException(409, '当前没有可以取消的生成任务，请刷新页面')
    return {'cancel_requested': True}


@router.post('/projects/{project_id}/chapters/{chapter_no}/search')
async def run_chapter_search(project_id: str, chapter_no: int, body: ChapterSearchRequest):
    try:
        return await search_chapter(project_id, chapter_no, body.max_queries, body.results_per_query)
    except SearchProviderError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post('/projects/{project_id}/chapters/{chapter_no}/collect')
async def run_chapter_collection(project_id: str, chapter_no: int, body: ChapterCollectRequest):
    try:
        result = await collect_chapter(project_id, chapter_no, body.max_web_queries, body.results_per_query)
        if result is None:
            raise HTTPException(404, '行业研究项目不存在')
        return result
    except SearchProviderError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post('/projects/{project_id}/chapters/{chapter_no}/collect/start', status_code=202)
def start_chapter_collection(project_id: str, chapter_no: int, body: ChapterCollectRequest):
    if not database.chapter(project_id, chapter_no):
        raise HTTPException(404, '行业研究项目或章节不存在')
    return collection_jobs.start(project_id, chapter_no, body.max_web_queries, body.results_per_query)


@router.get('/collection-jobs/{job_id}')
def collection_job(job_id: str):
    return collection_jobs.get(job_id)


@router.get('/projects/{project_id}/download/docx')
def download_docx(project_id: str):
    project = database.project(project_id)
    if not project:
        raise HTTPException(404, '行业研究项目不存在')
    if project['status'] != 'complete' or len(project['chapters']) < 11:
        raise HTTPException(409, '报告尚未生成完成，暂时不能下载')
    candidates, stale = _chart_state(project_id, project)
    if stale:
        raise HTTPException(409, '正文或数据已变化，部分选图已失效。请刷新页面，清除失效选图并重新选择后下载。')
    selected = [item for item in candidates if item['selected']]
    try:
        for item in selected:
            item['image_path'] = charts.render(project_id, item)
        # Each download is a separate snapshot. Concurrent downloads and an open
        # Word file must never overwrite or serve one another's chart selections.
        path = build_docx(project, _usable_project_evidence(project_id), selected,
                          export_id=uuid.uuid4().hex)
    except Exception:
        logger.exception('industry project=%s chart/report export failed', project_id)
        raise HTTPException(500, '报告排版或图表绘制失败，本次未生成下载文件。请查看后台日志后重试。') from None
    return FileResponse(path, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        filename=project['title'] + '.docx',
                        headers={'Cache-Control': 'no-store', 'X-Report-Chart-Count': str(len(selected))},
                        background=BackgroundTask(path.unlink, missing_ok=True))


@router.get('/projects/{project_id}/versions')
def versions(project_id: str):
    if not database.project(project_id):
        raise HTTPException(404, '行业研究项目不存在')
    return database.list_versions(project_id)


@router.post('/projects/{project_id}/versions', status_code=201)
def save_version(project_id: str):
    with database.connect() as db:
        vid = database.snapshot_version(db, project_id, '手动保存当前版本')
    if not vid:
        raise HTTPException(409, '项目不存在或尚无正文可保存')
    return {'id': vid}


@router.get('/projects/{project_id}/versions/{version_id}')
def view_version(project_id: str, version_id: str):
    version = database.get_version(project_id, version_id)
    if not version:
        raise HTTPException(404, '历史版本不存在')
    return version


@router.post('/projects/{project_id}/versions/{version_id}/restore')
def restore_version(project_id: str, version_id: str):
    with writer._lock:
        if project_id in writer._running:
            raise HTTPException(409, '请先取消生成并等待任务停止，再恢复版本')
        if not database.restore_version(project_id, version_id):
            raise HTTPException(404, '历史版本不存在')
    return {'restored': version_id}


@router.get('/projects/{project_id}/versions/{version_id}/download/docx')
def download_version(project_id: str, version_id: str):
    data = view_version(project_id, version_id)['snapshot']
    project = data['project']
    selected = data['charts']
    try:
        for spec in selected:
            spec['image_path'] = charts.render(project_id, spec)
        path = build_docx(project, usable_evidence(data['evidence']), selected,
                          export_id=uuid.uuid4().hex)
    except Exception:
        logger.exception('Historical version export failed')
        raise HTTPException(500, '历史版本排版失败，请查看服务日志') from None
    return FileResponse(path, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        filename=project['title'] + '-历史版本.docx',
                        headers={'Cache-Control': 'no-store', 'X-Report-Chart-Count': str(len(selected))},
                        background=BackgroundTask(path.unlink, missing_ok=True))
