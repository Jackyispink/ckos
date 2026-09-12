"""Local UI QA against an in-memory copy; never writes the user's report.

Run with the project's Python, then open http://127.0.0.1:8765/industry.
"""
import copy
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.industry_research import charts, database, exporter
from app.industry_research import router as endpoints


def make_app():
    rows = database.list_projects()
    source = next(row for row in rows if row['status'] == 'complete')
    project = database.project(source['id'])
    evidence = database.all_evidence(source['id'])
    project['id'] = 'qa-chart-preview'
    project['title'] = '选图验证副本'
    selection = {}
    database.project = lambda pid: copy.deepcopy(project) if pid == project['id'] else None
    database.chart_selections = lambda pid: copy.deepcopy(selection)
    database.all_evidence = lambda pid: evidence

    def save(pid, choice):
        if pid != project['id']: return False
        selection[choice.id] = dict(chart_id=choice.id, title=choice.title,
                                    chart_type=choice.chart_type, selected=choice.selected)
        return True

    database.save_chart_selection = save
    qa_root = Path(__file__).resolve().parents[1] / 'storage' / 'qa-chart-selection'
    charts.CHART_DIR = qa_root / 'charts'
    exporter.EXPORT_DIR = qa_root / 'exports'
    app = FastAPI()
    app.mount('/static', StaticFiles(directory=qa_root.parents[1] / 'static'), name='static')
    app.add_api_route('/industry', lambda: FileResponse(qa_root.parents[1] / 'static' / 'index.html'), methods=['GET'])
    app.add_api_route('/api/industry/projects', lambda: [project], methods=['GET'])
    app.add_api_route('/api/industry/projects/{project_id}', endpoints.get_project, methods=['GET'])
    app.add_api_route('/api/industry/projects/{project_id}/charts', endpoints.project_charts, methods=['GET'])
    app.add_api_route('/api/industry/projects/{project_id}/charts/{chart_id}', endpoints.choose_one_chart, methods=['PUT'])
    app.add_api_route('/api/industry/projects/{project_id}/download/docx', endpoints.download_docx, methods=['GET'])
    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(make_app(), host='127.0.0.1', port=8765)
