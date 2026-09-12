"""Read-only corpus comparison, except for reusable original-profile cache and a local summary."""
import json
from pathlib import Path
from statistics import median

from app import database, duplicates, structured


def main():
    database.init(); structured.init()
    with database.connect() as db:
        items=duplicates.profiles(db,duplicates.inventory(db))
    parts,weights,unseen=duplicates.weights_for(items)
    totals=[sum(weights[s] for s in p) for p in parts]
    pairs=[]
    for i,left in enumerate(parts):
        for j in range(i):
            intersection=sum(weights[s] for s in left & parts[j])
            score=intersection/max(1e-12,totals[i]+totals[j]-intersection)
            pairs.append((score,items[i][0]['id'],items[j][0]['id']))
    scores=sorted(p[0]*100 for p in pairs)
    revisions=[]
    for (_,profile),original in zip(items,parts):
        changed=dict(profile,paragraphs=profile['paragraphs']+['修订：新增年度内部审计，每季度核对执行情况。'])
        revisions.append(duplicates.similarity(original,duplicates.shingles(changed),weights,unseen)*100)
    result={'documents':len(items),'pairs':len(pairs),'median':median(scores) if scores else 0,
            'p95':scores[int((len(scores)-1)*.95)] if scores else 0,'maximum':max(scores,default=0),
            'pairs_at_90':sum(s>=90 for s in scores),'synthetic_append_min':min(revisions,default=0),
            'top_pairs':sorted(pairs,reverse=True)[:5],
            'note':'Corpus scores and synthetic revisions are not labeled accuracy. Default 90 remains provisional.'}
    out=database.ROOT/'storage'/'duplicate_calibration.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='top_pairs'},ensure_ascii=False))


if __name__=='__main__':
    main()
