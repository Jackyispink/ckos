"""Incremental persistent index maintenance; explicit --refresh-weights starts a new generation."""
import argparse
import json
from time import perf_counter

from app import database, duplicates, duplicate_index, structured


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--refresh-weights',action='store_true',help='Recalibrate weights and rebuild every index atomically')
    args=parser.parse_args()
    database.init();structured.init()
    start=perf_counter()
    with database.connect() as db:
        db.execute('SELECT pg_advisory_xact_lock(%s)',(duplicates.LOCK,))
        rows=duplicates.inventory(db)
        print(f'正在检查 {len(rows)} 份原报告的持久化索引…',flush=True)
        mid,_,_,count=duplicate_index.ensure(db,rows,args.refresh_weights)
    print(json.dumps({'documents':len(rows),'updated':count,'weight_version':mid,'seconds':round(perf_counter()-start,2)},ensure_ascii=False))


if __name__=='__main__': main()
