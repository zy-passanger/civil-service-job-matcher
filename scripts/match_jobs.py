"""Match normalized jobs and export evidence-rich JSON, XLSX and Markdown."""
import argparse
import csv
from collections import Counter
from pathlib import Path
from common import read_json, write_json, validate_profile, digest, now
from matcher_core import match_job, target_matches

def safe_cell(value):
    value = '' if value is None else str(value)
    return "'" + value if value.startswith(('=', '+', '-', '@')) else value

def flatten(item):
    pending = list(dict.fromkeys(x['reason'] for x in item['pending_checks']))
    failed = list(dict.fromkeys(x['reason'] for x in item['failed_rules']))
    return {'省份': item['target']['province'], '年度': item['target']['year'], '批次': item['target']['batch'], '类别': item['category'], '资格': item['eligibility_status'], '学历专业初筛': item['education_major_status'], '报名状态': item['availability'], '范围': item['scope_status'], '偏好': item['preference_status'], '数据性质': item['data_mode'], '职位代码': item.get('job_code'), '单位': item.get('agency'), '职位': item.get('job_name'), '使用路径': '; '.join(x['education_id'] + '/' + x['major_id'] for x in item['eligible_paths']), '待核验': '; '.join(pending), '不满足项': '; '.join(failed), '来源': item['source'].get('url', ''), '原表位置': str(item['location'])}

def active(item):
    return item['data_mode'] == 'official' and item.get('evaluation_mode', 'current_eligibility') == 'current_eligibility' and item['scope_status'] == 'in_scope' and item['preference_status'] != 'rejected' and item['availability'] == 'open'

def run(profile, datasets, policies, out, collection=None):
    profile = validate_profile(profile)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = {}
    conflicts = []
    for dataset in datasets:
        for job in dataset.get('jobs', []):
            uid = job['job_uid']
            if uid in jobs and jobs[uid].get('requirements') != job.get('requirements'):
                conflicts.append(uid)
            else:
                jobs[uid] = job
    results = []
    for uid, job in jobs.items():
        policy = next((p for p in policies if target_matches(p.get('target', {}), job.get('target', {}))), {})
        if uid in conflicts:
            job = dict(job)
            job['requirements'] = {**job['requirements'], 'other': '同一职位多个版本条件冲突，需确定生效版本'}
            job['field_rules'] = {k: v for k, v in job.get('field_rules', {}).items() if k != 'other'}
        results.append(match_job(profile, job, policy))
    city_order = profile.get('preferences', {}).get('cities_ranked', [])
    def rank(item):
        name = item.get('agency', '') or ''
        city_rank = next((i for i, city in enumerate(city_order) if city in name), len(city_order))
        return ('ABCD'.index(item['category']), city_rank, len(item['pending_checks']), item['job_uid'])
    results.sort(key=rank)
    report = {'run_id': digest({'profile': profile, 'datasets': datasets, 'policies': policies})[:20], 'created_at': now(), 'profile_hash': digest(profile), 'requested_target': profile['target'], 'counts_all': dict(Counter(x['category'] for x in results)), 'counts_current_official': dict(Counter(x['category'] for x in results if active(x))), 'education_major_counts': dict(Counter(x['education_major_status'] for x in results)), 'source_coverage': collection or {'status': 'not_supplied'}, 'conflicting_jobs': sorted(set(conflicts)), 'results': results}
    write_json(out / 'results.json', report)
    rows = [flatten(x) for x in results]
    headers = list(rows[0]) if rows else ['结果']
    with (out / '岗位匹配.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: safe_cell(v) for k, v in row.items()})
    from openpyxl import Workbook
    book = Workbook(write_only=True)
    overview = book.create_sheet('总览')
    for row in [['运行ID', report['run_id']], ['全部数据岗位数', len(results)], ['当前官方岗位数', sum(active(x) for x in results)], ['输入档案哈希', report['profile_hash']], ['覆盖状态', str((collection or {}).get('status', '查看来源台账'))]]:
        overview.append(row)
    for name, subset in [('全部明细', results), ('A主攻', [x for x in results if active(x) and x['category'] == 'A']), ('B待核验', [x for x in results if active(x) and x['category'] == 'B']), ('C备选', [x for x in results if active(x) and x['category'] == 'C']), ('D排除', [x for x in results if active(x) and x['category'] == 'D']), ('历史及其他状态', [x for x in results if not active(x)])]:
        sheet = book.create_sheet(name)
        sheet.freeze_panes = 'A2'
        sheet.append(headers)
        for item in subset:
            flat = flatten(item)
            sheet.append([safe_cell(flat.get(k)) for k in headers])
        from openpyxl.utils import get_column_letter
        sheet.auto_filter.ref = f'A1:{get_column_letter(len(headers))}{len(subset)+1}'
    evidence = book.create_sheet('逐项规则依据')
    evidence_headers = ['职位标识', '学历', '专业', '规则', '状态', '理由', '证据']
    evidence.append(evidence_headers)
    evidence_count, evidence_part = 1, 1
    for item in results:
        for p in item['path_results']:
            for check in p['checks']:
                if evidence_count >= 1000000:
                    evidence_part += 1
                    evidence = book.create_sheet(f'逐项规则依据{evidence_part}')
                    evidence.append(evidence_headers)
                    evidence_count = 1
                evidence.append([safe_cell(x) for x in [item['job_uid'], p['education_id'], p['major_id'], check['rule_id'], check['status'], check['reason'], str(check.get('evidence', ''))]])
                evidence_count += 1
    book.save(out / '岗位匹配.xlsx')
    unresolved = Counter(c['reason'] for x in results for c in x['pending_checks'])
    lines = ['# 公考岗位匹配结果', '', f'运行ID：`{report["run_id"]}`', '', f'读取 {len(results)} 个唯一职位；学历专业初筛：{report["education_major_counts"]}。', '', f'当前报名中且来源已核验的四类数量：{report["counts_current_official"]}。', '', f'全部数据（含历史／模拟／范围外）四类数量：{report["counts_all"]}。', '', '## 资料覆盖', '', '逐省来源、缺失材料和抓取失败见 `results.json` 的 `source_coverage`。未提供或覆盖不完整时，不能作全省零岗位结论。', '', '## 优先补充', '']
    lines += [f'- {reason}（涉及 {n} 条条件记录）' for reason, n in unresolved.most_common(12)] or ['- 无待核验项。']
    lines += ['', '## 学历专业初筛候选（最多展示20条）', '', '| 省份 | 单位 | 职位 | 分类 | 报名状态 |', '|---|---|---|---|---|']
    candidates = [x for x in results if x['education_major_status'] == 'PASS' and x['scope_status'] == 'in_scope']
    for x in candidates[:20]:
        vals = [x['target']['province'], x.get('agency'), x.get('job_name'), x['category'], x['availability']]
        lines.append('| ' + ' | '.join(str(v or '').replace('|', '／').replace('\n', ' ') for v in vals) + ' |')
    lines += ['', '完整清单、实际命中学历与专业、失败原因和原始单元格证据见同目录Excel与JSON。', '']
    (out / '匹配报告.md').write_text('\n'.join(lines), encoding='utf-8')
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--jobs', nargs='+', required=True)
    parser.add_argument('--policies', nargs='*', default=[])
    parser.add_argument('--collection')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    policies = []
    for file in args.policies:
        data = read_json(file)
        policies.extend(data if isinstance(data, list) else [data])
    report = run(read_json(args.profile), [read_json(p) for p in args.jobs], policies, args.out, read_json(args.collection) if args.collection else None)
    print(report['counts_all'])

if __name__ == '__main__':
    main()
