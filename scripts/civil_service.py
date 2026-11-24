#!/usr/bin/env python3
"""Skill entry point for profile parsing, official discovery tasks and matching."""
import argparse
from pathlib import Path
from common import PROVINCES, parse_text, read_json, write_json, validate_profile

def discovery_plan(profile):
    target = profile['target']
    year = target.get('recruitment_year')
    batch = target.get('batch', 'regular')
    tasks = []
    registry_path = Path(__file__).resolve().parents[1] / 'references/official-source-registry.json'
    registry = read_json(registry_path)
    for province in target['provinces']:
        label = str(year) if year else '最新'
        tasks.append({'province': province, 'requested_year': year, 'batch': batch, 'search_queries': [f'{province} {label} 公务员 考试录用 公告 职位表 官方' + (' 补充录用' if batch == 'supplementary' else ''), f'{province} {label} 公务员 报考指南 专业目录 更正 职位调整'], 'verified_historical_hints': registry.get('verified_examples', {}).get(province, []), 'state': 'needs_official_discovery', 'required_materials': ['公告', '职位表', '报考指南', '适用专业目录', '补充更正及职位调整'], 'instruction': '由调用技能的助手使用联网搜索与网页读取核验来源、实际年度和批次，生成sources.json后自动继续collect；不要求用户自己找网站。历史入口不能替代最新检索。'})
    return {'tasks': tasks, 'supported_province_names': PROVINCES, 'source_manifest_contract': {'targets': [{'province': '所选省份', 'year': '解析后的整数年份', 'exam_type': '省考公开招录', 'batch': batch, 'coverage_confirmed': False, 'sources': [{'url': '核验后的官方公告或专题URL', 'kind': 'announcement', 'verified': True, 'publisher': '实际主办机构', 'verification_evidence': '核验依据及时间'}]}]}}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('profile', help='Parse the documented Chinese line input')
    p.add_argument('--input', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('discover', help='Prepare per-province tasks for the skill agent web tools')
    p.add_argument('--profile', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('validate-profile')
    p.add_argument('--profile', required=True)
    args = parser.parse_args()
    if args.command == 'profile':
        profile = parse_text(Path(args.input).read_text())
        write_json(args.out, profile)
        print(f'学历记录={len(profile["educations"])} 省份={profile["target"]["provinces"]} 待解析项={len(profile["input_warnings"])}')
    elif args.command == 'discover':
        plan = discovery_plan(validate_profile(read_json(args.profile)))
        write_json(args.out, plan)
        print(f'已生成{len(plan["tasks"])}省官方资料发现任务；技能助手应立即执行联网搜索并继续采集。')
    else:
        validate_profile(read_json(args.profile))
        print('profile valid')

if __name__ == '__main__':
    main()
