"""Extract evidenced catalog rows; Hunan layered format or explicit flat mapping."""
import argparse
from pathlib import Path
from common import compact, read_json, write_json
from normalize_jobs import read_tables, value_text

def extract(path, target, source, layout='hunan', level=None):
    entries, issues = [], []
    for sheet, rows in read_tables(path):
        if layout == 'hunan':
            header = next((i for i, row in enumerate(rows[:30]) if '学科类别名称' in [compact(x) for x in row]), None)
            if header is None:
                issues.append({'sheet': sheet, 'reason': '未识别湖南目录表头'})
                continue
            for i, row in enumerate(rows[header+2:], header+3):
                if len(row) < 8:
                    continue
                broad = value_text(row[1])
                for col, levels in [(2, ['master', 'doctorate']), (4, ['bachelor']), (6, ['junior_college'])]:
                    category, name = value_text(row[col]), value_text(row[col+1])
                    if not name or not category:
                        continue
                    for lev in levels:
                        entries.append({'level': lev, 'name': name, 'code': None, 'aliases': [], 'categories': [x for x in [broad, category] if x], 'evidence': {'source': source, 'sheet': sheet, 'row': i, 'column': col+2, 'raw': name, 'target': target}})
        elif layout == 'flat':
            if not level:
                raise ValueError('flat目录必须显式指定学历层次--level')
            header = next((i for i, row in enumerate(rows[:30]) if '专业名称' in [compact(x) for x in row]), None)
            if header is None:
                issues.append({'sheet': sheet, 'reason': '未识别专业名称列'})
                continue
            headers = [compact(x) for x in rows[header]]
            name_col = headers.index('专业名称')
            code_col = headers.index('专业代码') if '专业代码' in headers else None
            cat_cols = [i for i, x in enumerate(headers) if x in ['专业类', '专业类名称', '学科门类', '门类名称', '类别名称']]
            for row_no, row in enumerate(rows[header+1:], header+2):
                name = value_text(row[name_col]) if name_col < len(row) else ''
                if not name:
                    continue
                entries.append({'level': level, 'name': name, 'code': value_text(row[code_col]) if code_col is not None else None, 'aliases': [], 'categories': [value_text(row[i]) for i in cat_cols if i < len(row) and row[i]], 'evidence': {'source': source, 'sheet': sheet, 'row': row_no, 'column': name_col+1, 'raw': name, 'target': target}})
        else:
            raise ValueError('未知目录格式')
    return {'target': target, 'catalog': entries, 'issues': issues, 'catalog_categories_complete': False, 'catalog_name_list_complete': False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--layout', choices=['hunan', 'flat'], default='hunan')
    parser.add_argument('--level', choices=['junior_college', 'bachelor', 'master', 'doctorate'])
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    data = extract(Path(args.input), read_json(args.target), read_json(args.source), args.layout, args.level)
    write_json(args.out, data)
    print(f'catalog_entries={len(data["catalog"])} issues={len(data["issues"])}')

if __name__ == '__main__':
    main()
