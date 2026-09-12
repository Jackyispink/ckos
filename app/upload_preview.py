"""Local staging and name suggestions. No database, chunking or duplicate checks."""
import json
import re
import time
import unicodedata
import uuid
from pathlib import Path
from threading import BoundedSemaphore
from zipfile import ZipFile

from fastapi import HTTPException, UploadFile
from lxml import etree

from . import kb

_slots=BoundedSemaphore(3)
MAX_BYTES=50*1024*1024
TTL=24*60*60
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def suggest(filename, paragraphs):
    stem=Path(filename).stem
    def clean(text):
        text=unicodedata.normalize('NFKC',text).strip()
        text=re.sub(r'^(?:企业名称|公司名称|被诊断企业|诊断企业|报告名称)\s*[:：]?\s*','',text)
        return re.sub(r'^\d+[\s、.．_-]*','',text).strip()
    def company(text):
        text=clean(text)
        if len(text)>140: return ''
        match=re.match(r'([\u4e00-\u9fffA-Za-z0-9()（）·&\-\s]{2,100}?(?:股份有限公司|有限责任公司|有限公司|集团公司))',text)
        return match[1].strip() if match else ''
    from_file=company(stem)
    cover=[]
    for p in paragraphs[:35]:
        c=company(p)
        if c and c not in cover: cover.append(c)
    chosen=cover[0] if cover else from_file
    alternatives=list(dict.fromkeys(filter(None,[chosen,from_file,*cover])))
    conflict=len(alternatives)>1
    report_title=stem[:120]
    # Preserve original filename identity and years instead of inventing unique suffixes.
    if re.fullmatch(r'(?:upload[_-]?[a-z0-9]+|扫描件\d*|文档\d*|document\d*|\d+)',stem,re.I):
        title=next((clean(p) for p in paragraphs[:25] if '报告' in p and 2<=len(p.strip())<=100),'')
        if title: report_title=(chosen+title if chosen and chosen not in title else title)[:120]
    return {'company_name':chosen,'report_title':report_title,'candidates':alternatives,
            'needs_review':not chosen or conflict,
            'reason':'封面与文件名出现多个企业名称，请核对' if conflict else ('未可靠识别企业名称，请补充' if not chosen else ('依据封面文字识别' if cover else '依据文件名识别'))}


def folder():
    p=kb.ROOT/'storage'/'upload_staging';p.mkdir(parents=True,exist_ok=True);return p


def resolve(token):
    if not re.fullmatch(r'[a-f0-9]{32}',token): raise HTTPException(404,'暂存文件不存在')
    base=folder(); meta=base/(token+'.json');path=base/(token+'.docx')
    if not meta.is_file() or not path.is_file(): raise HTTPException(404,'暂存文件已失效，请重新选择')
    info=json.loads(meta.read_text(encoding='utf-8'))
    if time.time()-info['created']>TTL:
        discard(token);raise HTTPException(410,'暂存已超过24小时，请重新选择文件')
    return path,info


def discard(token):
    if not re.fullmatch(r'[a-f0-9]{32}',token): return
    for suffix in ('.docx','.json'): (folder()/(token+suffix)).unlink(missing_ok=True)


def preview(file:UploadFile):
    if not (file.filename or '').lower().endswith('.docx'): raise HTTPException(422,'目前仅支持 .docx 文件')
    with _slots:
        base=folder()
        # Only expired UUID-named staging files owned by this feature are removed.
        for old in base.glob('*.json'):
            if re.fullmatch(r'[a-f0-9]{32}',old.stem) and time.time()-old.stat().st_mtime>TTL: discard(old.stem)
        token=uuid.uuid4().hex;path=base/(token+'.docx')
        try:
            size=0
            with path.open('xb') as output:
                while chunk:=file.file.read(1024*1024):
                    size+=len(chunk)
                    if size>MAX_BYTES: raise HTTPException(413,'文件超过50 MB')
                    output.write(chunk)
            with ZipFile(path) as z:
                if len(z.infolist())>10000 or sum(i.file_size for i in z.infolist())>250*1024*1024: raise HTTPException(422,'文档解压后过大')
                root=etree.fromstring(z.read('word/document.xml'),etree.XMLParser(resolve_entities=False,no_network=True))
                paragraphs=[''.join(p.xpath('.//w:t/text()',namespaces=NS)).strip() for p in root.xpath('.//w:p',namespaces=NS)]
                paragraphs=[p for p in paragraphs if p]
                if not paragraphs: raise HTTPException(422,'未读取到文字，暂不支持纯图片报告')
            original=(file.filename or '').replace('\\','/').rsplit('/',1)[-1]
            info={'created':time.time(),'original_filename':original}
            (base/(token+'.json')).write_text(json.dumps(info,ensure_ascii=False),encoding='utf-8')
            return dict(suggest(original,paragraphs),token=token,original_filename=original)
        except Exception as exc:
            discard(token)
            if isinstance(exc,HTTPException):raise
            raise HTTPException(422,'无法读取文档，请确认它是未加密且未损坏的 .docx 文件') from None
