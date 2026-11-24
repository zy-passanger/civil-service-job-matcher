"""Shared IO and public input contracts; no network or writes at import time."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

PROVINCES = '北京 天津 河北 山西 内蒙古 辽宁 吉林 黑龙江 上海 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 广西 海南 重庆 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏 新疆'.split()
ALIASES = dict(zip('京 津 冀 晋 蒙 辽 吉 黑 沪 苏 浙 皖 闽 赣 鲁 豫 鄂 湘 粤 桂 琼 渝 川 贵 云 藏 陕 甘 青 宁 新'.split(), PROVINCES))
ALIASES.update({'黔': '贵州', '滇': '云南', '蜀': '四川', '秦': '陕西', '陇': '甘肃'})
LEVELS = {'junior_college': 1, 'bachelor': 2, 'master': 3, 'doctorate': 4}
LEVEL_NAMES = {'大专': 'junior_college', '专科': 'junior_college', '本科': 'bachelor', '硕士研究生': 'master', '硕士': 'master', '博士研究生': 'doctorate', '博士': 'doctorate'}

def now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(value).hexdigest()

def compact(value):
    return re.sub(r'\s+', '', str(value or '')).replace('（', '(').replace('）', ')')

def province(value):
    value = str(value).strip()
    value = ALIASES.get(value, value)
    for suffix in ['维吾尔自治区', '壮族自治区', '回族自治区', '自治区', '省', '市']:
        value = value.removesuffix(suffix)
    if value not in PROVINCES:
        raise ValueError(f'无法识别省份：{value}')
    return value

def blank_degree():
    return {'status': 'unknown', 'level': None, 'award_date': None, 'expected_award_date': None}

def validate_profile(profile):
    errors = []
    target = profile.get('target', {})
    try:
        target['provinces'] = list(dict.fromkeys(province(x) for x in target.get('provinces', [])))
    except ValueError as e:
        errors.append(str(e))
    if not target.get('provinces'):
        errors.append('至少选择一个省份')
    if not profile.get('educations'):
        errors.append('至少填写一条学历—专业')
    seen = set()
    for ed in profile.get('educations', []):
        if not ed.get('id') or ed['id'] in seen:
            errors.append('学历ID缺失或重复')
        seen.add(ed.get('id'))
        if not ed.get('majors'):
            errors.append(f'{ed.get("id")}：至少一个专业')
        mids = set()
        for major in ed.get('majors', []):
            if not major.get('id') or major['id'] in mids:
                errors.append(f'{ed.get("id")}：专业ID缺失或重复')
            mids.add(major.get('id'))
            if not (major.get('name_on_certificate') or major.get('name_hint')):
                errors.append(f'{ed.get("id")}：专业名称为空')
    if errors:
        raise ValueError('；'.join(errors))
    return profile

def parse_text(text):
    """Predictable line syntax. Ambiguous prose is retained for agent resolution."""
    profile = {'schema_version': 1, 'profile_id': 'local-candidate', 'target': {'provinces': [], 'exam_type': '省考公开招录', 'recruitment_year': None, 'year_strategy': 'latest_published_regular', 'batch': 'regular', 'mode': 'current_eligibility'}, 'educations': [], 'educations_complete': False, 'preferences': {}, 'input_warnings': [], 'raw_input': text}
    for raw_line in re.split(r'[\n；;]+', text):
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r'^(目标)?省份\s*[:：]', line):
            value = re.split(r'[:：]', line, 1)[1]
            profile['target']['provinces'] = [province(x) for x in re.split(r'[,，、\s]+', value.strip()) if x]
            continue
        if re.match(r'^(招录)?(年度|年份)\s*[:：]', line):
            year = re.search(r'20\d{2}', line)
            if year:
                profile['target']['recruitment_year'] = int(year.group())
            continue
        if re.match(r'^(招录)?批次\s*[:：]', line):
            profile['target']['batch'] = 'supplementary' if '补录' in line or '补充' in line else 'regular'
            continue
        if line in ['学历专业：', '学历专业:', '学历—专业：']:
            continue
        line = re.sub(r'^\s*(?:[-*]|\d+[.、])\s*', '', line)
        m = re.match(r'^(硕士研究生|博士研究生|大专|专科|本科|硕士|博士|研究生|其他)\s*[—－|｜-]\s*(.+)$', line)
        if not m:
            profile['input_warnings'].append(f'未自动解析：{raw_line.strip()}')
            continue
        level, rest = m.groups()
        full = None
        form = 'unknown'
        contradiction = '自考' in rest and bool(re.search(r'(?<!非)全日制', rest))
        if contradiction:
            profile['input_warnings'].append(f'培养方式冲突：{raw_line.strip()}')
        elif '自考' in rest:
            form, full = 'self_taught', False
        elif '非全日制' in rest:
            form, full = 'graduate_education' if '研究生' in level or level in ['硕士', '博士'] else 'other', False
        elif '全日制' in rest:
            form, full = 'graduate_education' if '研究生' in level or level in ['硕士', '博士'] else 'ordinary_higher', True
        else:
            for word, code in [('成人教育', 'adult'), ('开放教育', 'open'), ('网络教育', 'distance')]:
                if word in rest:
                    form = code
        cleaned = re.sub(r'[（(][^）)]*[）)]', '', rest)
        cleaned = re.sub(r'全日制普通高等教育|非全日制|全日制|成人教育|开放教育|网络教育|自考|待确认', '', cleaned)
        names = [x.strip(' —－|｜-') for x in re.split(r'[、,，|｜]+', cleaned)]
        names = [x for x in names if x]
        eid = f'edu-{len(profile["educations"]) + 1:02d}'
        majors = [{'id': f'{eid}-major-{i+1:02d}', 'name_on_certificate': n, 'name_hint': n, 'code': None, 'role': 'unknown', 'credential_status': 'unknown', 'degree': blank_degree()} for i, n in enumerate(names)]
        profile['educations'].append({'id': eid, 'level': LEVEL_NAMES.get(level, 'other'), 'level_raw': level, 'education_form': form, 'full_time': full, 'national_unified_admission': None, 'graduation_status': 'unknown', 'graduation_date': None, 'recognition_status': 'unknown', 'majors': majors, 'majors_complete': False, 'input_conflict': contradiction})
        if level == '研究生':
            profile['input_warnings'].append(f'{eid}：需确认硕士或博士')
    return validate_profile(profile)

def source_evidence(job, field):
    source = job.get('source', {})
    return {'field': field, 'raw': job.get('requirements', {}).get(field), 'source': {k: source.get(k) for k in ['source_id', 'url', 'sha256', 'file']}, 'location': job.get('locations', {}).get(field, job.get('location', {}))}
