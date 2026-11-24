"""Fetch agent-verified provincial entry points and their relevant attachments."""
import argparse
import io
import re
import time
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
from urllib.request import Request, urlopen
from common import read_json, write_json, digest, now, province

DOCUMENT_EXTS = {'.xlsx', '.xls', '.csv', '.pdf', '.docx', '.doc', '.zip'}
KINDS = [('catalog', r'专业.*(目录|对照|清单)'), ('guide', r'报考指南|政策解答|报考政策'), ('jobs', r'职位表|招考简章|职位计划表'), ('revision', r'更正|核减|取消.*职位|调整.*(招录|职位).*计划'), ('announcement', r'(考试录用|招录).*公告')]

def classify(label):
    for kind, pattern in KINDS:
        if re.search(pattern, label):
            return kind
    return None

def fetch(url, timeout=25, retries=2):
    if urlparse(url).scheme not in ('http', 'https'):
        raise ValueError('仅获取HTTP(S)公开链接')
    last = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; CivilServiceJobMatcher/1.0)'})
            with urlopen(request, timeout=timeout) as response:
                data = response.read(50 * 1024 * 1024 + 1)
                if len(data) > 50 * 1024 * 1024:
                    raise ValueError('附件超过50MB，需要单独处理')
                return data, response.headers.get('Content-Type', ''), response.geturl()
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(min(attempt + 1, 2))
    raise RuntimeError(str(last))

def html_content(data):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(data, 'html.parser')
    for element in soup(['script', 'style', 'noscript']):
        element.decompose()
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    text = soup.get_text('\n', strip=True)
    links = []
    for a in soup.find_all('a', href=True):
        label = a.get_text(' ', strip=True)
        if len(label) < 6 and a.parent:
            label = a.parent.get_text(' ', strip=True)[:400]
        links.append((a['href'], label))
    return title, text, links

def extract_document(path):
    ext = path.suffix.lower()
    if ext == '.docx':
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        return '\n'.join(''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in root.findall('.//w:p', ns))
    if ext == '.pdf':
        from pypdf import PdfReader
        texts = [(page.extract_text() or '') for page in PdfReader(path).pages]
        if not any(t.strip() for t in texts):
            return ''
        return '\n'.join(f'--- Page {i+1} ---\n{text}' for i, text in enumerate(texts))
    if ext == '.csv':
        for encoding in ['utf-8-sig', 'gb18030']:
            try:
                return path.read_text(encoding=encoding)
            except UnicodeError:
                pass
    return None

def collect_target(target, out, timeout=25, max_pages=20):
    target = dict(target)
    target['province'] = province(target['province'])
    if not isinstance(target.get('year'), int) or target.get('batch') not in ['regular', 'supplementary']:
        raise ValueError('采集前必须逐省解析year和batch')
    folder = out / f'{target["province"]}-{target["year"]}-{target["batch"]}'
    folder.mkdir(parents=True, exist_ok=True)
    queue = deque()
    for seed in target.get('sources', []):
        item = dict(seed)
        item.update(depth=0, parent_url=None)
        queue.append(item)
    records, failures, skipped = [], [], []
    seen = set()
    html_count = 0
    while queue:
        item = queue.popleft()
        url = item['url'].split('#')[0]
        if url in seen:
            continue
        seen.add(url)
        if not item.get('verified'):
            skipped.append({'url': url, 'reason': 'source_unverified'})
            continue
        if html_count >= max_pages and Path(urlparse(url).path).suffix.lower() not in DOCUMENT_EXTS:
            skipped.append({'url': url, 'reason': 'page_limit'})
            continue
        try:
            data, content_type, resolved_url = fetch(url, timeout=timeout)
            checksum = digest(data)
            ext = Path(unquote(urlparse(resolved_url).path)).suffix.lower()
            is_html = 'html' in content_type or data.lstrip().lower().startswith((b'<!doctype html', b'<html'))
            if is_html:
                ext = '.html'
            elif ext not in DOCUMENT_EXTS:
                if data.startswith(b'%PDF'):
                    ext = '.pdf'
                elif data.startswith(b'PK'):
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        ext = '.xlsx' if 'xl/workbook.xml' in z.namelist() else '.docx' if 'word/document.xml' in z.namelist() else '.zip'
                else:
                    ext = '.bin'
            saved = folder / (checksum[:20] + ext)
            saved.write_bytes(data)
            record = {**item, 'url': url, 'resolved_url': resolved_url, 'source_id': checksum[:20], 'sha256': checksum, 'path': str(saved.resolve()), 'content_type': content_type, 'fetched_at': now(), 'target': {k: target[k] for k in ['province', 'year', 'batch']}, 'source_type': item.get('source_type', 'official_linked')}
            if is_html:
                html_count += 1
                title, text, links = html_content(data)
                record['title'] = title or item.get('title', '')
                text_path = saved.with_suffix('.txt')
                text_path.write_text(text)
                record['text_path'] = str(text_path.resolve())
                requested_ext = Path(urlparse(url).path).suffix.lower()
                if requested_ext in DOCUMENT_EXTS:
                    record['usable'] = False
                    record['extraction_error'] = '附件链接返回HTML，需检查登录、验证码或下载跳转'
                    failures.append({'url': url, 'kind': item.get('kind'), 'error': record['extraction_error']})
                # Relevant links only; no crawling of generic navigation/search.
                if item['depth'] < 2:
                    for href, label in links:
                        link = urljoin(resolved_url, href).split('#')[0]
                        if urlparse(link).scheme not in ['http', 'https']:
                            continue
                        kind = classify(label)
                        if not kind:
                            continue
                        years = re.findall(r'20\d{2}', label)
                        if years and str(target['year']) not in years and kind not in ['catalog']:
                            continue
                        if target['batch'] == 'regular' and re.search(r'补录|补充录用|特殊职位', label):
                            continue
                        link_ext = Path(urlparse(link).path).suffix.lower()
                        same_host = urlparse(link).hostname == urlparse(resolved_url).hostname
                        if not same_host and link_ext not in DOCUMENT_EXTS:
                            skipped.append({'url': link, 'label': label, 'reason': 'cross_site_page_needs_verification'})
                            continue
                        queue.append({'url': link, 'title': label, 'kind': kind, 'verified': True, 'publisher': item.get('publisher'), 'verification_evidence': f'官方父页直接链接：{resolved_url}', 'parent_url': resolved_url, 'depth': item['depth'] + 1})
            elif ext == '.zip':
                members = []
                with zipfile.ZipFile(saved) as archive:
                    total = 0
                    for member in archive.infolist():
                        if member.is_dir() or Path(member.filename).suffix.lower() not in DOCUMENT_EXTS - {'.zip'}:
                            continue
                        total += member.file_size
                        if total > 150 * 1024 * 1024:
                            raise ValueError('解压内容超过150MB')
                        content = archive.read(member)
                        output = folder / (digest(content)[:20] + Path(member.filename).suffix.lower())
                        output.write_bytes(content)
                        child = {**record, 'path': str(output.resolve()), 'source_id': digest(content)[:20], 'sha256': digest(content), 'archive_member': member.filename, 'kind': classify(member.filename) or item.get('kind')}
                        try:
                            extracted = extract_document(output)
                            if extracted:
                                child['text_path'] = str(output.with_suffix('.txt').resolve())
                                output.with_suffix('.txt').write_text(extracted)
                        except Exception as exc:
                            child['extraction_error'] = str(exc)
                        members.append(child)
                records.extend(members)
            else:
                try:
                    extracted = extract_document(saved)
                    if extracted:
                        saved.with_suffix('.txt').write_text(extracted)
                        record['text_path'] = str(saved.with_suffix('.txt').resolve())
                    elif ext == '.pdf':
                        record['needs_ocr'] = True
                        record['usable'] = False
                except Exception as exc:
                    record['extraction_error'] = str(exc)
            records.append(record)
        except Exception as exc:
            failures.append({'url': url, 'kind': item.get('kind'), 'error': str(exc)})
    obtained = {r.get('kind') for r in records if r.get('usable') is not False}
    missing = sorted(set(target.get('required_kinds', ['announcement', 'jobs', 'guide', 'catalog'])) - obtained)
    complete = not missing and not failures and not skipped and bool(target.get('coverage_confirmed'))
    status = 'complete' if complete else 'partial' if records else 'fetch_failed' if failures else 'source_unverified'
    result = {'target': target, 'status': status, 'scope_coverage_confirmed': bool(target.get('coverage_confirmed')), 'records': records, 'missing_kinds': missing, 'failures': failures, 'skipped': skipped, 'finished_at': now()}
    write_json(folder / 'manifest.json', result)
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, help='Agent-verified sources.json')
    parser.add_argument('--out', required=True)
    parser.add_argument('--timeout', type=int, default=25)
    parser.add_argument('--max-pages', type=int, default=20)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    targets = read_json(args.sources)['targets']
    def run(target):
        try:
            return collect_target(target, out, args.timeout, args.max_pages)
        except Exception as exc:
            return {'target': target, 'status': 'fetch_failed', 'error': str(exc), 'records': []}
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(targets)))) as pool:
        results = list(pool.map(run, targets))
    write_json(out / 'collection.json', {'targets': results, 'finished_at': now()})
    for item in results:
        print(json_summary(item))

def json_summary(item):
    import json
    return json.dumps({'province': item['target'].get('province'), 'status': item['status'], 'files': len(item.get('records', [])), 'missing': item.get('missing_kinds', []), 'errors': len(item.get('failures', []))}, ensure_ascii=False)

if __name__ == '__main__':
    main()
