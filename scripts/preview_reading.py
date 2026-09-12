"""Replay real report chapters as reading pages; no database or model writes."""
import json
import subprocess
import sys
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.industry_research.research_blocks import build_reading_outline
source=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
source['snapshot']['project']['chapters']=[c for c in source['snapshot']['project']['chapters'] if c['chapter_no'] in (4,6,8)]
source['slides']=build_reading_outline(source['snapshot'])
source['runtime']=json.loads((ROOT/'config/ppt_runtime.json').read_text(encoding='utf-8'))
folder=ROOT/'storage'/('reading-review-'+uuid.uuid4().hex[:8]);folder.mkdir()
source['output']=str(folder)
file=folder/'input.json';file.write_text(json.dumps(source,ensure_ascii=False),encoding='utf-8')
print(folder,flush=True)
subprocess.run([source['runtime']['node'],str(ROOT/'scripts/render_presentation.mjs'),str(file)],check=True,cwd=ROOT)
