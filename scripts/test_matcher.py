"""Run with python3 -B test_matcher.py; all fixtures are synthetic, no network."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from common import parse_text, province, digest, validate_profile
from matcher_core import PASS, FAIL, REVIEW, conjunction, disjunction, evaluate, atom, match_job
from normalize_jobs import normalize
from match_jobs import run, active, safe_cell
from extract_catalog import extract

TARGET = {'province': '湖南', 'year': 2026, 'batch': 'regular', 'exam_type': '省考公开招录'}
EVIDENCE = {'source_url': 'https://example.invalid/synthetic', 'quote': '虚构测试依据'}

def fixtures():
    profile = parse_text('省份：湖南\n本科—计算机科学与技术（自考）\n年度：2026')
    profile.update(nationality='中国', birth_date='1995-05-05', sex='男', political_status='群众', educations_complete=True, as_of_date='2026-01-15')
    ed = profile['educations'][0]
    ed.update(recognition_status='self_declared', graduation_status='obtained', graduation_date='2024-06-30', majors_complete=True)
    ed['majors'][0].update(role='primary', credential_status='self_declared', degree={'status': 'obtained', 'level': 'bachelor', 'award_date': '2024-07-01'})
    fields = ['education', 'major', 'degree', 'party', 'experience', 'fresh', 'gender', 'age', 'household', 'other']
    job = {'job_uid': 'TEST-001', 'job_code': '000001', 'target': TARGET, 'agency': '合成测试单位', 'job_name': '合成测试职位', 'duties': '信息化', 'requirements': {k: '不限' for k in fields}, 'source': {'verified': True, 'source_type': 'synthetic_fixture', 'url': 'https://example.invalid/synthetic'}, 'location': {'sheet': '合成测试', 'row': 2}, 'availability': 'open'}
    job['requirements'].update(education='本科及以上', major='计算机科学与技术')
    policy = {'target': TARGET, 'reviewed': True, 'global_rules_complete': True, 'global_rules': [{'id': 'synthetic_general', 'expression': atom('user.nationality', 'eq', '中国'), 'evidence': EVIDENCE}], 'credential_deadline': '2026-01-31', 'plain_level_mode': {'本科': 'minimum', '专科': 'minimum'}, 'catalog_categories_complete': True, 'catalog_name_list_complete': True, 'catalog': [{'level': 'bachelor', 'name': '计算机科学与技术', 'categories': ['电子信息和计算机类'], 'aliases': [], 'evidence': EVIDENCE}, {'level': 'junior_college', 'name': '物流管理', 'categories': ['管理类'], 'aliases': [], 'evidence': EVIDENCE}], 'registration': {'start': '2026-01-01', 'end': '2026-01-31'}}
    return profile, job, policy

class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.p, self.j, self.rules = fixtures()

    def match(self):
        return match_job(self.p, self.j, self.rules)

    def test_truth_tables(self):
        cases = [(PASS,PASS,PASS,PASS),(PASS,FAIL,FAIL,PASS),(PASS,REVIEW,REVIEW,PASS),(FAIL,FAIL,FAIL,FAIL),(FAIL,REVIEW,FAIL,REVIEW),(REVIEW,REVIEW,REVIEW,REVIEW)]
        for a,b,c,d in cases:
            for pair in ([a,b],[b,a]):
                with self.subTest(pair=pair):
                    self.assertEqual(conjunction(pair),c)
                    self.assertEqual(disjunction(pair),d)
        self.assertEqual(conjunction([]),REVIEW)
        self.assertEqual(disjunction([]),REVIEW)

    def test_normal_input(self):
        p=parse_text('省份：湘、安徽省、湖北\n大专—物流管理（全日制）\n本科—自考—计算机科学与技术、软件工程\n本科—会计学（全日制）\n博士研究生—电子信息（非全日制）')
        self.assertEqual(p['target']['provinces'],['湖南','安徽','湖北'])
        self.assertEqual(len(p['educations']),4)
        self.assertEqual(len(p['educations'][1]['majors']),2)
        self.assertFalse(p['educations'][1]['full_time'])
        self.assertIsNone(p['educations'][0]['national_unified_admission'])

    def test_ambiguous_graduate(self):
        p=parse_text('省份：湖南\n研究生—软件工程（全日制）')
        self.assertEqual(p['educations'][0]['level'],'other')
        self.assertTrue(p['input_warnings'])

    def test_conflicting_form(self):
        self.p['educations'][0]['input_conflict']=True
        self.assertEqual(self.match()['category'],'B')

    def test_simple_pass_and_preference(self):
        self.assertEqual(self.match()['category'],'C')
        self.p['preferences']={'preferred_duties':['信息化']}
        self.assertEqual(self.match()['category'],'A')

    def test_fulltime_fail(self):
        self.j['requirements']['education']='全日制本科及以上'
        self.assertEqual(self.match()['category'],'D')

    def test_negated_fulltime(self):
        for text in ['本科及以上，不限全日制','本科及以上（全日制和非全日制均可）']:
            self.j['requirements']['education']=text
            with self.subTest(text=text): self.assertEqual(self.match()['eligibility_status'],PASS)

    def test_degree_missing_and_unknown(self):
        self.j['requirements']['degree']='学士'
        self.p['educations'][0]['majors'][0]['degree']['status']='unknown'
        self.assertEqual(self.match()['category'],'B')
        self.p['educations'][0]['majors'][0]['degree']['status']='not_applicable'
        self.assertEqual(self.match()['category'],'D')

    def test_degree_deadline(self):
        self.j['requirements']['degree']='学士及以上'
        self.p['educations'][0]['majors'][0]['degree']['award_date']='2026-02-01'
        self.assertEqual(self.match()['category'],'D')

    def test_blank_not_unrestricted(self):
        self.j['requirements']['degree']=''
        self.assertEqual(self.match()['category'],'B')
        self.rules['blank_defaults']={'degree':{'value':'不限','evidence':EVIDENCE}}
        self.assertEqual(self.match()['eligibility_status'],PASS)

    def test_category_matches(self):
        self.j['requirements']['major']='电子信息和计算机类'
        self.assertEqual(self.match()['eligibility_status'],PASS)

    def test_wrong_catalog_category_fails(self):
        self.j['requirements']['major']='管理类'
        self.assertEqual(self.match()['category'],'D')

    def test_no_catalog_is_review(self):
        self.j['requirements']['major']='计算机类'
        self.rules['catalog']=[]
        self.assertEqual(self.match()['category'],'B')

    def test_major_unrestricted(self):
        self.j['requirements']['major']='不限'
        self.p['preferences']={'preferred_duties':['信息化']}
        self.assertEqual(self.match()['category'],'A')

    def test_vague_major(self):
        self.p['educations'][0]['majors'][0]['name_on_certificate']='计算机相关'
        self.assertEqual(self.match()['category'],'B')

    def add_college(self):
        ed=copy.deepcopy(self.p['educations'][0]);ed['id']='college';ed['level']='junior_college';ed['full_time']=True
        ed['majors'][0].update(id='logistics',name_on_certificate='物流管理')
        self.p['educations'].append(ed)

    def test_no_cross_education_borrowing(self):
        self.add_college();self.j['requirements']['major']='物流管理'
        self.assertEqual(self.match()['category'],'D')

    def test_nonhighest_path(self):
        self.add_college();self.j['requirements'].update(education='专科及以上',major='物流管理')
        r=self.match();self.assertEqual(r['eligibility_status'],PASS)
        self.assertEqual(r['selected_path']['education_id'],'college')

    def test_one_pass_other_fail(self):
        self.add_college()
        self.assertEqual(self.match()['eligibility_status'],PASS)

    def test_incomplete_paths(self):
        self.p['educations_complete']=False
        self.j['requirements']['education']='博士研究生及以上'
        self.assertEqual(self.match()['category'],'B')

    def test_multiple_majors(self):
        other=copy.deepcopy(self.p['educations'][0]['majors'][0]);other.update(id='second',name_on_certificate='法学')
        self.p['educations'][0]['majors'].append(other)
        r=self.match();self.assertEqual(r['eligibility_status'],PASS);self.assertEqual(len(r['path_results']),2)

    def test_minor_not_inherit(self):
        self.p['educations'][0]['majors'][0]['role']='minor'
        self.assertEqual(self.match()['category'],'B')

    def test_major_level_branches(self):
        self.j['requirements'].update(major_bachelor='法学',major_master='计算机科学与技术')
        self.assertEqual(self.match()['category'],'D')

    def test_unknown_boolean_not_true(self):
        self.assertEqual(evaluate(atom('user.x','eq',False),{'user':{}})['status'],REVIEW)
        self.assertEqual(evaluate(atom('user.x','eq',False),{'user':{'x':False}})['status'],PASS)

    def test_manual_and_or(self):
        raw='中共党员或男性';self.j['requirements']['other']=raw
        self.j['field_rules']={'other':{'raw':raw,'expression':{'any_of':[atom('user.political_status','eq','中共党员'),atom('user.sex','eq','男')]},'evidence':EVIDENCE}}
        self.assertEqual(self.match()['eligibility_status'],PASS)
        self.j['field_rules']['other']['expression']={'all_of':[atom('user.political_status','eq','中共党员'),atom('user.sex','eq','男')]}
        self.assertEqual(self.match()['category'],'D')

    def test_stale_field_override(self):
        self.j['requirements']['other']='新条件'
        self.j['field_rules']={'other':{'raw':'旧条件','expression':atom('user.sex','eq','男'),'evidence':EVIDENCE}}
        self.assertEqual(self.match()['category'],'B')

    def test_date_bounds(self):
        expr=atom('user.birth_date','date_between',['1990-01-01','2000-12-31'])
        for value,expected in [('1990-01-01',PASS),('2000-12-31',PASS),('1989-12-31',FAIL),('1990-01',REVIEW)]:
            with self.subTest(value=value): self.assertEqual(evaluate(expr,{'user':{'birth_date':value}})['status'],expected)

    def test_policy_target_mismatch(self):
        self.rules['target']={**TARGET,'year':2025}
        self.assertEqual(self.match()['category'],'B')

    def test_profile_facts_bound(self):
        self.j['requirements']['experience']='2年以上'
        self.rules['profile_facts']={'grassroots_months':{'value':24,'evidence':EVIDENCE}}
        self.rules['profile_hash']=digest(self.p)
        self.assertEqual(self.match()['eligibility_status'],PASS)
        self.p['birth_date']='1994-01-01'
        self.assertEqual(self.match()['category'],'B')

    def test_closed_not_current(self):
        self.p['as_of_date']='2026-11-24'
        r=self.match();self.assertEqual(r['availability'],'closed');self.assertFalse(active(r))

    def test_simulation_not_current(self):
        r=self.match();self.assertEqual(r['data_mode'],'simulation');self.assertFalse(active(r))

    def test_future_scenario_not_current(self):
        self.p['target']['mode']='future_scenario'
        self.j['source']['source_type']='official_original'
        r=self.match();self.assertEqual(r['evaluation_mode'],'future_scenario');self.assertFalse(active(r))

    def test_registration_boundary_needs_time(self):
        self.p['as_of_date']='2026-01-31'
        self.assertEqual(self.match()['availability'],'unknown')

    def test_global_failure_dominates_unknown(self):
        self.p['nationality']='其他'
        self.j['requirements']['degree']=''
        self.assertEqual(self.match()['category'],'D')

    def test_fail_with_alternative_unknown(self):
        self.add_college()
        self.p['educations'][0]['majors'][0]['degree']['status']='unknown'
        self.j['requirements']['degree']='学士'
        self.assertEqual(self.match()['category'],'B')

    def test_collector_partial_failure(self):
        from unittest.mock import patch
        from collect_official_sources import collect_target
        target={**TARGET,'sources':[{'url':'https://example.invalid/a','kind':'announcement','verified':True},{'url':'https://example.invalid/b','kind':'jobs','verified':True}]}
        def mocked(url,**kw):
            if url.endswith('/b'): raise RuntimeError('synthetic timeout')
            return '<html><title>测试</title><body>合成公告</body></html>'.encode(),'text/html',url
        with tempfile.TemporaryDirectory() as directory, patch('collect_official_sources.fetch',side_effect=mocked):
            r=collect_target(target,Path(directory))
            self.assertEqual(r['status'],'partial');self.assertEqual(len(r['failures']),1)
            self.assertIn('jobs',r['missing_kinds'])

    def test_preference_not_qualification(self):
        self.p['preferences']={'excluded_regions':['合成测试单位']}
        r=self.match();self.assertEqual(r['eligibility_status'],PASS);self.assertEqual(r['preference_status'],'rejected')

    def test_scope(self):
        self.p['target']['provinces']=['安徽']
        self.assertEqual(self.match()['scope_status'],'out_of_scope')

    def test_other_exam_not_provincial_exam(self):
        self.j['target']={**TARGET,'exam_type':'事业单位招聘'}
        self.assertEqual(self.match()['scope_status'],'out_of_scope')

    def test_normalize_merged_and_zeros(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'fixture.xlsx';w=Workbook();sh=w.active
            sh.append(['合成测试职位表']);sh.merge_cells('A1:F1')
            sh.append(['单位名称','职位名称','职位代码','学历','专业','招录人数'])
            sh.append(['合成单位','合成职位',1,'本科及以上','计算机科学与技术',2]);sh['C3'].number_format='000000'
            sh.append(['说明：合成尾注']);sh.merge_cells('A4:F4');w.save(file)
            data=normalize(file,TARGET)
            self.assertEqual(len(data['jobs']),1);self.assertEqual(data['jobs'][0]['job_code'],'000001')
            self.assertTrue(any('合成尾注' in n.get('text','') for n in data['notes']))

    def test_export_duplicate_paths_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            r=run(self.p,[{'jobs':[self.j,self.j]}],[self.rules],directory)
            self.assertEqual(len(r['results']),1)
            self.assertTrue((Path(directory)/'岗位匹配.xlsx').exists())
            self.assertEqual(safe_cell('=1+1'),"'=1+1")

    def test_conflicting_revisions(self):
        other=copy.deepcopy(self.j);other['requirements']['degree']='学士'
        with tempfile.TemporaryDirectory() as directory:
            r=run(self.p,[{'jobs':[self.j,other]}],[self.rules],directory)
            self.assertEqual(r['conflicting_jobs'],['TEST-001'])
            self.assertEqual(r['results'][0]['category'],'B')

if __name__ == '__main__':
    unittest.main(verbosity=2)
