from app.industry_research import writer


def test_no_project_flag_means_no_universal_chapter_three_gate(monkeypatch):
    updates=[]
    monkeypatch.setattr(writer.llm, 'configured', lambda: True)
    monkeypatch.setattr(writer, '_prepare_evidence', lambda *args: None)
    monkeypatch.setattr(writer, '_update', lambda *args, **kwargs: updates.append((args,kwargs)))
    class DB:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def execute(self, sql, params=()):
            if 'SELECT * FROM industry_projects' in sql:
                return Rows([{'id':'p','brief':{},'review_required_chapter':None}])
            if 'chapter_no BETWEEN 1 AND 10' in sql:
                return Rows([{'chapter_no':n,'title':str(n),'status':'complete','content':'正文'} for n in range(1,11)])
            if 'chapter_no=0' in sql:
                return Rows([{'status':'complete','content':'摘要'}])
            return Rows([])
    class Rows(list):
        def fetchone(self): return self[0] if self else None
    monkeypatch.setattr(writer, 'connect', DB)
    writer._run('p','resume')
    assert any(args[1:3] == ('complete','十章与摘要生成完成') for args,kwargs in updates)
    assert not any('待人工复核' in str(args) for args,kwargs in updates)
