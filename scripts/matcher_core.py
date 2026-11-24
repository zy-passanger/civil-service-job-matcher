"""Three-valued, path-bound eligibility. Unknown input never means unrestricted."""
import re
from datetime import date
from common import LEVELS, compact, source_evidence, digest

PASS, FAIL, REVIEW = 'PASS', 'FAIL', 'REVIEW'
UNRESTRICTED = {'不限', '无', '无要求', '不要求', '不限制', '不作要求'}
FIELD_LABELS = {'path.level': '学历层次', 'path.full_time': '全日制属性', 'path.national_unified_admission': '统招属性', 'path.degree.status': '学位取得状态', 'path.degree.level': '学位层次', 'path.degree.award_date': '学位取得日期', 'path.graduation_status': '毕业证状态', 'path.graduation_date': '毕业日期', 'path.recognition_status': '学历认可情况', 'path.credential_status': '专业证书依据', 'user.sex': '性别', 'user.nationality': '国籍', 'user.political_status': '政治面貌', 'user.birth_date': '出生日期', 'policy_facts.grassroots_months': '已核实基层经历月数'}
VALUE_LABELS = {'junior_college': '专科', 'bachelor': '本科／学士', 'master': '硕士', 'doctorate': '博士', 'obtained': '已取得', 'verified': '已核验', 'self_declared': '本人确认'}

def display(value):
    if isinstance(value, list):
        return '、'.join(display(x) for x in value)
    return VALUE_LABELS.get(str(value), str(value))

def conjunction(values):
    return FAIL if FAIL in values else PASS if values and all(x == PASS for x in values) else REVIEW

def disjunction(values):
    return PASS if PASS in values else FAIL if values and all(x == FAIL for x in values) else REVIEW

def result(status, reason, **extra):
    return {'status': status, 'reason': reason, **extra}

def get_value(context, dotted):
    value = context
    for part in dotted.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value

def evaluate(expression, context):
    if not isinstance(expression, dict):
        return result(REVIEW, '缺少有效条件表达式')
    for op, combine in [('all_of', conjunction), ('any_of', disjunction)]:
        if op in expression:
            children = [evaluate(x, context) for x in expression[op]]
            return result(combine([x['status'] for x in children]), op, children=children)
    if 'not' in expression:
        child = evaluate(expression['not'], context)
        return result({PASS: FAIL, FAIL: PASS, REVIEW: REVIEW}[child['status']], 'not', children=[child])
    field, op, expected = expression.get('field'), expression.get('op'), expression.get('value')
    if op == 'review':
        return result(REVIEW, expression.get('reason', '需核验条件'))
    actual = get_value(context, field or '')
    if actual is None or actual == 'unknown':
        return result(REVIEW, f'待补充：{FIELD_LABELS.get(field, field)}', field=field)
    try:
        if op == 'eq':
            ok = actual == expected
        elif op == 'in':
            ok = actual in expected
        elif op == 'gte':
            ok = LEVELS.get(actual, actual) >= LEVELS.get(expected, expected)
        elif op == 'lte':
            ok = LEVELS.get(actual, actual) <= LEVELS.get(expected, expected)
        elif op == 'date_between':
            current = date.fromisoformat(actual)
            ok = date.fromisoformat(expected[0]) <= current <= date.fromisoformat(expected[1])
        elif op == 'on_or_before':
            ok = date.fromisoformat(actual) <= date.fromisoformat(expected)
        elif op == 'contains_any':
            ok = any(x in actual for x in expected)
        else:
            return result(REVIEW, f'不支持的条件运算：{op}')
    except (ValueError, TypeError, KeyError):
        return result(REVIEW, f'字段类型或日期精度不足：{field}')
    operator = {'eq': '等于', 'in': '属于', 'gte': '不低于', 'lte': '不高于', 'date_between': '在日期区间', 'on_or_before': '不晚于', 'contains_any': '包含任一项'}.get(op, op)
    reason = expression.get('description') or f'{FIELD_LABELS.get(field, field)}要求{operator}“{display(expected)}”，档案为“{display(actual)}”'
    return result(PASS if ok else FAIL, reason, actual=actual, field=field)

def atom(field, op, value):
    return {'field': field, 'op': op, 'value': value}

def unresolved(reason):
    return {'op': 'review', 'reason': reason}

def education_expression(raw, policy, header=''):
    text = compact(raw).replace('学历', '').replace('大学', '')
    conditions = []
    for phrase in ['全日制和非全日制均可', '全日制、非全日制均可', '不限全日制', '不限制全日制']:
        text = text.replace(phrase, '')
    if '非全日制' in text:
        return unresolved(f'培养方式复合条件需解析：{raw}')
    if '全日制' in text:
        conditions.append(atom('path.full_time', 'eq', True))
        text = text.replace('全日制', '')
    if '统招' in text:
        conditions.append(atom('path.national_unified_admission', 'eq', True))
        text = text.replace('统招', '')
    text = text.strip('()，,；; ')
    mapping = {'大专': 'junior_college', '专科': 'junior_college', '本科': 'bachelor', '硕士研究生': 'master', '硕士': 'master', '博士研究生': 'doctorate', '博士': 'doctorate'}
    match = re.fullmatch(r'(仅限|限)?(硕士研究生|博士研究生|大专|专科|本科|硕士|博士)(及以上|以上)?', text)
    if not match:
        return unresolved(f'学历描述需解析：{raw}')
    exact, label, suffix = match.groups()
    if exact:
        op = 'eq'
    elif suffix or '最低' in header:
        op = 'gte'
    else:
        mode = policy.get('plain_level_mode', {}).get(label)
        if mode not in ['minimum', 'exact']:
            return unresolved(f'需确认“{label}”指最低还是限定学历')
        op = 'gte' if mode == 'minimum' else 'eq'
    conditions.append(atom('path.level', op, mapping[label]))
    return {'all_of': conditions}

def major_result(raw, path, policy):
    text = compact(raw)
    if text in UNRESTRICTED:
        return result(PASS, '专业明确不限')
    name = compact(path.get('major_name'))
    if not name or re.search(r'相关|方向|待确认|待填写', name):
        return result(REVIEW, '需要证书正式专业名称')
    # Do not flatten level-specific alternatives or boolean clauses.
    if re.search(r'本科[:：]|研究生[:：]|专科[:：]|且|同时|相近|相关|等|或者|或|除外', text):
        return result(REVIEW, f'复合专业条件需解析：{raw}')
    tokens = [x.strip() for x in re.split('[，,、；;\n]', str(raw)) if x.strip()]
    tokens = [compact(x) for x in tokens]
    tokens = [re.sub(r'专业$', '', x) for x in tokens]
    entries = [x for x in policy.get('catalog', []) if x.get('level') == path.get('level') and (compact(x.get('name')) == name or name in [compact(a) for a in x.get('aliases', [])]) and x.get('evidence')]
    allowed = {name}
    for entry in entries:
        allowed.update(compact(x) for x in entry.get('aliases', []))
        allowed.update(compact(x) for x in entry.get('categories', []))
        if entry.get('code'):
            allowed.add(str(entry['code']))
    if any(token in allowed for token in tokens):
        return result(PASS, '正式专业或适用目录归属匹配', matched_name=name, catalog_evidence=[e['evidence'] for e in entries])
    if not tokens:
        return result(REVIEW, '专业要求空白或缺失')
    if any('类' in token or '门类' in token or re.search(r'\d{4,}', token) for token in tokens):
        if entries and policy.get('catalog_categories_complete', False):
            return result(FAIL, '适用目录中该专业不属于允许类别', catalog_evidence=[e['evidence'] for e in entries])
        return result(REVIEW, '缺少该学历层次的专业类别／代码映射')
    if entries and policy.get('catalog_name_list_complete', False):
        return result(FAIL, '已列入适用目录，且不在职位列明专业中')
    return result(REVIEW, '专业未直接匹配，需排查正式更名或目录外专业认定')

def field_result(job, field, path, context, policy):
    raw = job.get('requirements', {}).get(field, '')
    override = job.get('field_rules', {}).get(field)
    if override:
        if override.get('raw') != raw or not override.get('evidence'):
            return result(REVIEW, f'{field}解析覆盖缺少原文绑定／依据')
        evaluated = evaluate(override.get('expression'), context)
        evaluated['interpretation_evidence'] = override['evidence']
        return evaluated
    if field == 'major':
        branch_keys = [k for k in job.get('requirements', {}) if k.startswith('major_')]
        if branch_keys:
            branch = 'major_' + str(path.get('level'))
            if branch not in job['requirements'] or not compact(job['requirements'][branch]):
                return result(REVIEW, '该学历层次专业分支缺失或空白')
            raw = job['requirements'][branch]
    if not compact(raw):
        default = policy.get('blank_defaults', {}).get(field)
        if not isinstance(default, dict) or not default.get('evidence'):
            return result(REVIEW, f'{field}空白／缺列，需表注或政策解释')
        raw = default.get('value', '')
    text = compact(raw)
    if text in UNRESTRICTED:
        return result(PASS, f'{field}明确无此项限制')
    if field == 'education':
        header = job.get('locations', {}).get(field, {}).get('header', '')
        return evaluate(education_expression(raw, policy, header), context)
    if field == 'major':
        return major_result(raw, path, policy)
    if field == 'degree':
        match = re.fullmatch(r'(学士|硕士|博士)(及以上|以上)?(?:学位)?', text)
        if not match:
            return result(REVIEW, f'学位描述需解析：{raw}')
        levels = {'学士': 'bachelor', '硕士': 'master', '博士': 'doctorate'}
        status = path.get('degree', {}).get('status')
        if status in ['pending', 'not_obtained']:
            return result(REVIEW, '学位尚未取得，需结合期限及延期规则确认')
        if status == 'not_applicable':
            return result(FAIL, '该路径无职位要求的学位')
        expr = {'all_of': [atom('path.degree.status', 'eq', 'obtained'), atom('path.degree.level', 'gte' if match.group(2) else 'eq', levels[match.group(1)])]}
        base = evaluate(expr, context)
        cutoff = policy.get('credential_deadline')
        deadline = evaluate(atom('path.degree.award_date', 'on_or_before', cutoff), context) if cutoff else result(REVIEW, '缺少学位取得截止规则')
        return result(conjunction([base['status'], deadline['status']]), '学位及取得时点', children=[base, deadline])
    if field == 'gender' and text in ['男', '女', '男性', '女性']:
        return evaluate(atom('user.sex', 'eq', text[0]), context)
    if field == 'party':
        if text in ['中共党员', '中共党员(含预备党员)']:
            allowed = ['中共党员']
            if '含预备党员' in text or policy.get('party_includes_probationary') is True:
                allowed.append('中共预备党员')
            elif context['user'].get('political_status') == '中共预备党员':
                return result(REVIEW, '需确认本次党员限定是否包含预备党员')
            return evaluate(atom('user.political_status', 'in', allowed), context)
    if field == 'experience':
        match = re.fullmatch(r'(?:具有)?([0-9]+)年(?:及?以上)?(?:基层工作经历)?', text)
        if match:
            fact = policy.get('profile_facts', {}).get('grassroots_months')
            if not fact or not fact.get('evidence'):
                return result(REVIEW, '需按当次定义和截止时间核实基层经历月数')
            return evaluate(atom('policy_facts.grassroots_months', 'gte', int(match.group(1))*12), context)
    return result(REVIEW, f'{field}需要按当次政策解析：{raw}')

def paths(profile):
    for ed in profile.get('educations', []):
        for major in ed.get('majors', []):
            yield {**ed, 'education_id': ed['id'], 'major_id': major['id'], 'major_name': major.get('name_on_certificate'), 'major_code': major.get('code'), 'major_role': major.get('role', 'unknown'), 'credential_status': major.get('credential_status', 'unknown'), 'degree': major.get('degree', {})}

def target_matches(a, b):
    return all(a.get(k) == b.get(k) for k in ['province', 'year', 'batch', 'exam_type'])

def match_job(profile, job, policy):
    policy = policy if target_matches(job.get('target', {}), policy.get('target', {})) else {}
    policy_facts = {k: v.get('value') for k, v in policy.get('profile_facts', {}).items() if v.get('evidence')} if policy.get('profile_hash') == digest(profile) else {}
    base_context = {'user': profile, 'policy_facts': policy_facts}
    shared = []
    global_rules = policy.get('global_rules', [])
    for item in global_rules:
        value = evaluate(item.get('expression'), base_context) if item.get('evidence') else result(REVIEW, '通用规则缺少依据')
        shared.append({**value, 'rule_id': item.get('id', 'global'), 'evidence': item.get('evidence')})
    shared.append(result(PASS if policy.get('reviewed') and policy.get('global_rules_complete') and global_rules else REVIEW, '当次通用报考规则覆盖', rule_id='policy_coverage'))
    shared.append(result(PASS if job.get('source', {}).get('verified') else REVIEW, '职位来源核验', rule_id='source_verified'))
    path_results = []
    for path in paths(profile):
        context = {**base_context, 'path': path}
        checks = []
        for field in ['education', 'major', 'degree', 'party', 'experience', 'fresh', 'gender', 'age', 'household', 'other']:
            check = field_result(job, field, path, context, policy)
            checks.append({**check, 'rule_id': field, 'evidence': source_evidence(job, field)})
        if path.get('input_conflict'):
            checks.append(result(REVIEW, '学历输入存在冲突', rule_id='input_conflict'))
        role_rule = policy.get('special_major_rules', {}).get(path.get('major_role'))
        if path.get('major_role') != 'primary':
            check = evaluate(role_rule.get('expression'), context) if role_rule and role_rule.get('evidence') else result(REVIEW, '需核实该专业性质及其报考资格（主修／辅修／第二学位等）')
            checks.append({**check, 'rule_id': 'major_credential'})
        else:
            checks.append({**evaluate(atom('path.credential_status', 'in', ['verified', 'self_declared']), context), 'rule_id': 'major_credential'})
        checks.append({**evaluate(atom('path.recognition_status', 'in', ['verified', 'self_declared']), context), 'rule_id': 'education_recognition'})
        graduation = policy.get('graduation_rule')
        if graduation and graduation.get('evidence'):
            check = evaluate(graduation['expression'], context)
        elif path.get('graduation_status') in ['pending', 'not_obtained']:
            check = result(REVIEW, '毕业证尚未取得，需要适用期限及延期政策')
        else:
            check = evaluate({'all_of': [atom('path.graduation_status', 'eq', 'obtained'), atom('path.graduation_date', 'on_or_before', policy.get('credential_deadline'))]}, context)
        checks.append({**check, 'rule_id': 'graduation'})
        for item in policy.get('path_rules', []):
            check = evaluate(item.get('expression'), context) if item.get('evidence') else result(REVIEW, '学历路径规则缺少依据')
            checks.append({**check, 'rule_id': item.get('id', 'path_policy'), 'evidence': item.get('evidence')})
        education_major = conjunction([x['status'] for x in checks if x['rule_id'] in ['education', 'major', 'input_conflict']])
        path_results.append({'education_id': path['education_id'], 'major_id': path['major_id'], 'level': path['level'], 'major_name': path.get('major_name'), 'education_form': path.get('education_form'), 'status': conjunction([x['status'] for x in checks]), 'education_major_status': education_major, 'checks': checks})
    path_status = disjunction([p['status'] for p in path_results])
    complete = profile.get('educations_complete') is True and all(e.get('majors_complete') is True for e in profile.get('educations', []))
    if path_status == FAIL and not complete:
        path_status = REVIEW
    status = conjunction([path_status] + [x['status'] for x in shared])
    prefilter = disjunction([p['education_major_status'] for p in path_results])
    eligible = [{'education_id': p['education_id'], 'major_id': p['major_id']} for p in path_results if p['status'] == PASS]
    prefs = profile.get('preferences', {})
    location = ' '.join([job.get('location_name', ''), job.get('city', ''), job.get('county', ''), job.get('agency', ''), job.get('employer', '')])
    pref_status = 'accepted'
    if any(x in location for x in prefs.get('excluded_regions', [])):
        pref_status = 'rejected'
    if prefs.get('accept_township') is False and '乡镇' in ' '.join([location, job.get('job_name', '')]):
        pref_status = 'rejected'
    scope = 'in_scope'
    target = profile.get('target', {})
    if job.get('target', {}).get('province') not in target.get('provinces', []):
        scope = 'out_of_scope'
    if target.get('recruitment_year') and target['recruitment_year'] != job.get('target', {}).get('year'):
        scope = 'out_of_scope'
    if target.get('batch', 'regular') != job.get('target', {}).get('batch'):
        scope = 'out_of_scope'
    if target.get('exam_type', '省考公开招录') != job.get('target', {}).get('exam_type'):
        scope = 'out_of_scope'
    preferred = any(x in location for x in prefs.get('cities_ranked', [])) or any(x in job.get('duties', '') for x in prefs.get('preferred_duties', []))
    category = 'D' if status == FAIL else 'B' if status == REVIEW else 'A' if preferred else 'C'
    availability = job.get('availability', 'unknown')
    interval = policy.get('registration', {})
    as_of = profile.get('as_of_date')
    if availability not in ['cancelled', 'closed'] and as_of and interval.get('start') and interval.get('end'):
        if as_of < interval['start']:
            availability = 'not_started'
        elif as_of > interval['end']:
            availability = 'closed'
        elif as_of in [interval['start'], interval['end']]:
            availability = 'unknown'  # Date-only input cannot resolve opening/closing time.
        else:
            availability = 'open'
    # Only pending facts on viable alternative paths are actionable blockers.
    viable = [p for p in path_results if p['status'] != FAIL]
    pending = [c for p in viable for c in p['checks'] if c['status'] == REVIEW] + [c for c in shared if c['status'] == REVIEW]
    if not complete and path_status == REVIEW and not viable:
        pending.append(result(REVIEW, '学历或专业列表未确认完整', rule_id='profile_completeness'))
    official = job.get('source', {}).get('verified') and job.get('source', {}).get('source_type') not in ['synthetic_fixture', 'third_party', 'user_supplied_unverified']
    return {'job_uid': job['job_uid'], 'job_code': job.get('job_code'), 'target': job['target'], 'evaluation_mode': profile.get('target', {}).get('mode', 'current_eligibility'), 'agency': job.get('agency') or job.get('employer'), 'job_name': job.get('job_name'), 'eligibility_status': status, 'education_major_status': prefilter, 'assessment_level': 'full_eligibility_check' if status != REVIEW else 'education_major_prefilter', 'category': category, 'scope_status': scope, 'preference_status': pref_status, 'availability': availability, 'data_mode': 'official' if official else 'simulation', 'selected_path': eligible[0] if eligible else None, 'eligible_paths': eligible, 'path_results': path_results, 'shared_checks': shared, 'pending_checks': pending, 'failed_rules': [c for p in path_results for c in p['checks'] if c['status'] == FAIL] + [c for c in shared if c['status'] == FAIL], 'requirements': job.get('requirements'), 'source': job.get('source'), 'location': job.get('location'), 'ranking_basis': {'cities_ranked': prefs.get('cities_ranked', []), 'preferred_duties': prefs.get('preferred_duties', []), 'preference_matched': preferred}}
