"""Export a read-only report copy for QA; never updates database selections."""
import argparse
import json
from uuid import uuid4

from docx import Document
from app.kb import ROOT
from app.industry_research import charts, database, exporter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project_id')
    args = parser.parse_args()
    project = database.project(args.project_id)
    if not project:
        raise SystemExit('Report not found')
    output = ROOT / 'storage' / ('qa-report-layout-' + uuid4().hex[:8])
    charts.CHART_DIR = output / 'charts'
    exporter.EXPORT_DIR = output
    specs = [dict(s, selected_type='line') for s in charts.discover(project) if s['kind'] == 'time_series']
    for spec in specs:
        spec['image_path'] = str(charts.render('preview', spec))
    path = exporter.build_docx(project, database.all_evidence(args.project_id), specs)
    doc = Document(path)
    print(json.dumps(dict(path=str(path), headings=[(p.style.name, p.text) for p in doc.paragraphs
        if p.style.name.startswith('Heading')], charts=[{k:s[k] for k in
        ('chapter_no', 'title', 'labels', 'values', 'image_path')} for s in specs]), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
