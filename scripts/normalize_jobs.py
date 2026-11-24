"""Normalize XLSX/XLS/CSV without discarding raw cells or table notes."""
import argparse
import csv
import re
from pathlib import Path
from common import compact, digest, read_json, write_json

ALIASES = {
    'job_code': ['职位代码', '职位编码', '岗位代码', '职位代号'],
    'agency': ['招录机关', '招录单位', '招考单位', '招录部门', '部门名称'],
    'employer': ['用人单位', '用人司局', '单位名称'],
    'job_name': ['招录职位', '职位名称', '岗位名称', '招考职位'],
    'duties': ['职位简介', '工作内容', '职位描述', '岗位职责', '职位职责'],
    'count': ['招录人数', '计划数', '录用人数', '招考人数', '招录计划', '计划招录人数'],
    'education': ['学历要求', '学历', '文化程度', '最低学历要求'],
    'degree': ['学位要求', '学位'],
    'major': ['专业要求', '专业', '所学专业'],
    'party': ['政治面貌'],
    'experience': ['基层工作经历最低年限', '基层工作最低年限', '基层工作经历', '工作经历', '基层工作年限', '基层工作年限要求', '经历要求'],
    'fresh': ['招考对象', '招录对象', '考录对象', '应届生要求', '应届毕业生', '报考人员身份要求'],
    'gender': ['性别', '性别要求'],
    'age': ['年龄', '年龄要求', '最高年龄要求'],
    'household': ['户籍', '户籍要求', '生源地'],
    'other': ['其他条件', '其它条件', '备注', '其他要求', '其他资格条件', '报考条件', '其他招录条件及说明', '其他', '职业资格证书等要求'],
    'location': ['工作地点', '工作地区', '职位所在地', '工作所在地', '所在地区'],
    'city': ['市州', '地市', '市', '地市名称'],
    'county': ['区县', '县市区', '县区'],
    'phone': ['咨询电话', '联系电话', '政策咨询电话', '咨询电话1', '咨询电话2'],
    'exam': ['考试类别', '专业科目', '专业考试', '专业测试', '申论类别', '申论试卷类型', '笔试类别', '笔试考试科目'],
}
REQUIREMENT_FIELDS = {'education', 'degree', 'major', 'party', 'experience', 'fresh', 'gender', 'age', 'household', 'other'}
DISPLAY_HEADERS = {'序号', '编号', '备注说明', '机构性质', '单位性质', '机构层级', '职位类别', '单位级别', '开考比例', '面试比例', '考区', '单位层级', '职位性质', '职级层次', '笔试最低开考比例'}

def map_header(header):
    h = compact(header).strip(':：')
    if h == '备注(职位简介)':
        return 'duties'
    for level, terms in [('bachelor', ['本科']), ('master', ['硕士', '研究生']), ('doctorate', ['博士']), ('junior_college', ['专科', '大专'])]:
        if '专业' in h and any(t in h for t in terms):
            return 'major_' + level
    if h == '学历学位' or h == '学历、学位':
        return 'combined_education_degree'
    for key, values in ALIASES.items():
        if h in values:
            return key
    # Common suffixes and parenthetical header annotations only.
    base = re.sub(r'\([^)]*\)', '', h)
    for key, values in ALIASES.items():
        if base in values:
            return key
    return None

def read_tables(path):
    ext = path.suffix.lower()
    if ext == '.xlsx':
        from openpyxl import load_workbook
        book = load_workbook(path, data_only=True, read_only=False)
        tables = []
        for sheet in book:
            # Fill only explicitly merged cells, never arbitrary blanks.
            merged = {}
            for span in sheet.merged_cells.ranges:
                value = sheet.cell(span.min_row, span.min_col).value
                for row in range(span.min_row, span.max_row + 1):
                    for col in range(span.min_col, span.max_col + 1):
                        merged[(row, col)] = value
            rows = []
            for row in sheet:
                values = []
                for cell in row:
                    value = merged.get((cell.row, cell.column), cell.value)
                    if isinstance(value, (int, float)) and re.fullmatch('0+', cell.number_format or ''):
                        value = f'{int(value):0{len(cell.number_format)}d}'
                    values.append(value)
                rows.append(values)
            tables.append((sheet.title, rows))
        book.close()
        return tables
    if ext == '.xls':
        import xlrd
        book = xlrd.open_workbook(str(path), formatting_info=True)
        tables = []
        for sheet in book.sheets():
            rows = [sheet.row_values(r) for r in range(sheet.nrows)]
            for rlo, rhi, clo, chi in sheet.merged_cells:
                value = rows[rlo][clo]
                for r in range(rlo, rhi):
                    for c in range(clo, chi):
                        rows[r][c] = value
            for r in range(sheet.nrows):
                for c in range(sheet.ncols):
                    cell = sheet.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_NUMBER:
                        fmt = book.format_map[book.xf_list[cell.xf_index].format_key].format_str
                        if re.fullmatch('0+', fmt):
                            rows[r][c] = f'{int(cell.value):0{len(fmt)}d}'
            tables.append((sheet.name, rows))
        return tables
    if ext == '.csv':
        data = path.read_bytes()
        try:
            text = data.decode('utf-8-sig')
        except UnicodeError:
            text = data.decode('gb18030')
        try:
            dialect = csv.Sniffer().sniff(text[:10000], delimiters=',\t;')
        except csv.Error:
            dialect = csv.excel
        return [(path.stem, list(csv.reader(text.splitlines(), dialect=dialect)))]
    raise ValueError(f'{ext}职位表需先由技能提取为带原始页码／表格定位的CSV或JSON')

def value_text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()

def normalize(path, target, source=None, field_map=None):
    source = source or {'verified': False, 'source_type': 'user_supplied_unverified'}
    checksum = digest(path.read_bytes())
    source = {**source, 'file': path.name, 'sha256': checksum}
    jobs, notes, sheets, issues = [], [], [], []
    for name, rows in read_tables(path):
        if not rows:
            continue
        mapped = [(i, [map_header(x) for x in row]) for i, row in enumerate(rows[:30])]
        idx, headers = max(mapped, key=lambda pair: len(set(x for x in pair[1] if x)))
        score = len(set(x for x in headers if x))
        if score < 3:
            notes.append({'sheet': name, 'rows': [[value_text(x) for x in row] for row in rows], 'reason': 'non_job_sheet_or_header_unrecognized'})
            continue
        raw_headers = [value_text(x) for x in rows[idx]]
        for i, header in enumerate(raw_headers):
            if field_map and header in field_map:
                headers[i] = field_map[header]
        count = 0
        for row_index, row in enumerate(rows):
            if row_index <= idx:
                if row_index < idx:
                    notes.append({'sheet': name, 'row': row_index + 1, 'text': ' '.join(value_text(x) for x in row if x is not None)})
                continue
            values = [value_text(x) for x in row]
            if not any(values):
                continue
            if len(set(v for v in values if v)) == 1:
                notes.append({'sheet': name, 'row': row_index + 1, 'text': next(v for v in values if v), 'reason': 'single_merged_note'})
                continue
            if sum(bool(map_header(x)) for x in values) >= 3:
                continue
            fields, locations, raw_fields = {}, {}, {}
            for c, header in enumerate(raw_headers):
                value = values[c] if c < len(values) else ''
                raw_fields[f'{c+1}:{header}'] = value
                key = headers[c]
                if key:
                    if key in fields and fields[key] != value and value:
                        fields[key] += '；' + value
                    else:
                        fields[key] = value
                    locations[key] = {'sheet': name, 'row': row_index + 1, 'column': c + 1, 'header': header}
                elif value and compact(header) not in DISPLAY_HEADERS:
                    fields['unmapped_conditions'] = fields.get('unmapped_conditions', '') + f'{header}：{value}；'
            if not (fields.get('job_code') or fields.get('job_name')):
                notes.append({'sheet': name, 'row': row_index + 1, 'text': ' '.join(values)})
                continue
            if not fields.get('education') and not fields.get('major') and not any(k.startswith('major_') for k in fields) and not fields.get('combined_education_degree'):
                notes.append({'sheet': name, 'row': row_index + 1, 'text': ' '.join(values), 'reason': 'possible_non_job_row'})
                continue
            if fields.get('unmapped_conditions'):
                fields['other'] = (fields.get('other', '') + '；未映射列：' + fields['unmapped_conditions']).strip('；')
            if fields.get('combined_education_degree'):
                fields['education'] = fields['combined_education_degree']
                fields['degree'] = fields['combined_education_degree']
            requirements = {k: fields.get(k, '') for k in REQUIREMENT_FIELDS}
            for k, v in fields.items():
                if k.startswith('major_'):
                    requirements[k] = v
            code = fields.get('job_code', '')
            namespace = fields.get('agency') or fields.get('employer') or target.get('publisher_namespace', '')
            uid_parts = [str(target.get(k, '')) for k in ['province', 'year', 'exam_type', 'batch']] + [namespace, code or f'{checksum[:12]}:{name}:{row_index+1}']
            job = {'job_uid': '|'.join(uid_parts), 'job_code': code, 'target': target, 'agency': fields.get('agency', ''), 'employer': fields.get('employer', ''), 'job_name': fields.get('job_name', ''), 'duties': fields.get('duties', ''), 'location_name': fields.get('location', ''), 'city': fields.get('city', ''), 'county': fields.get('county', ''), 'count_raw': fields.get('count', ''), 'phone': fields.get('phone', ''), 'exam': fields.get('exam', ''), 'requirements': requirements, 'source': source, 'locations': locations, 'location': {'sheet': name, 'row': row_index + 1}, 'raw_fields': raw_fields, 'availability': 'unknown', 'field_rules': {}}
            try:
                job['count'] = int(fields.get('count', ''))
            except ValueError:
                job['count'] = None
            jobs.append(job)
            count += 1
        sheets.append({'name': name, 'header_row': idx + 1, 'headers': dict(zip(raw_headers, headers)), 'jobs': count})
        if 'education' not in headers or not any(h and h.startswith('major') for h in headers):
            issues.append({'sheet': name, 'reason': '关键列缺失或需人工映射'})
    return {'target': target, 'jobs': jobs, 'sheets': sheets, 'notes': notes, 'issues': issues, 'source': source}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--target', required=True, help='target.json, including province/year/batch/exam_type')
    parser.add_argument('--source', help='source metadata JSON')
    parser.add_argument('--field-map', help='JSON mapping exact headers to standard fields')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = normalize(Path(args.input), read_json(args.target), read_json(args.source) if args.source else None, read_json(args.field_map) if args.field_map else None)
    write_json(args.out, result)
    print(f'jobs={len(result["jobs"])} sheets={len(result["sheets"])} issues={len(result["issues"])}')

if __name__ == '__main__':
    main()
