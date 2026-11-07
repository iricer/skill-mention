#!/usr/bin/env python3
"""Read the small feature registry; render clickable catalogs without loading prompts."""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def resolve_resource(relative):
    p = (ROOT / relative).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError(f"Resource escapes skill directory: {relative}")
    if not p.is_file():
        raise ValueError(f"Missing resource: {relative}")
    return p


def load_registry():
    data = json.loads((ROOT / 'catalog.json').read_text(encoding='utf-8-sig'))
    if data.get('schema_version') != 1:
        raise ValueError('Unsupported catalog schema')
    seen = set()
    for f in data['features']:
        fid = f['id']
        if not isinstance(fid, str) or not re.fullmatch(r'\d{4,}', fid) or fid != f"{int(fid):04d}" or int(fid) < 1:
            raise ValueError(f'Invalid stable ID: {fid}')
        if int(fid) in seen:
            raise ValueError(f'Duplicate ID: {fid}')
        seen.add(int(fid))
        for field in ['title', 'summary', 'category']:
            if not isinstance(f.get(field), str) or not f[field].strip():
                raise ValueError(f'{fid}: missing {field}')
        if f.get('status') not in ['active', 'retired']:
            raise ValueError(f'{fid}: invalid status')
        if not isinstance(f.get('tags', []), list):
            raise ValueError(f'{fid}: tags must be a list')
        resolve_resource(f['prompt'])
        for field, index in [('examples', 'example_index'), ('templates', 'template_index')]:
            resources = f.get(field, [])
            if not isinstance(resources, list):
                raise ValueError(f'{fid}: {field} must be a list')
            for resource in resources:
                if not resource.get('label'):
                    raise ValueError(f'{fid}: resource label missing')
                resolve_resource(resource['path'])
            if len(resources) > 1 and not f.get(index):
                raise ValueError(f'{fid}: {index} required for multiple resources')
            if f.get(index):
                resolve_resource(f[index])
    if not isinstance(data.get('next_id'), int) or data['next_id'] <= max(seen, default=0):
        raise ValueError('next_id must be greater than every historical ID')
    if not isinstance(data.get('page_size'), int) or data['page_size'] <= 0:
        raise ValueError('page_size must be positive')
    return data


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def link(label, relative, absolute=True):
    p = resolve_resource(relative)
    target = p.as_posix() if absolute else relative
    return f'[{cell(label)}](<{target}>)'


def resource_cell(f, field, index, label, absolute):
    resources = f.get(field, [])
    if not resources:
        return '—'
    if len(resources) == 1:
        return link(label, resources[0]['path'], absolute)
    return link(f'{label}（{len(resources)}）', f[index], absolute)


def table(features, absolute=True):
    lines = ['| 编号 | 功能 | 提示词 | 示例 | 模板 |', '|---|---|---|---|---|']
    for f in features:
        lines.append('| ' + ' | '.join([
            f['id'], cell(f['title']), link('查看提示词', f['prompt'], absolute),
            resource_cell(f, 'examples', 'example_index', '查看示例', absolute),
            resource_cell(f, 'templates', 'template_index', '查看模板', absolute),
        ]) + ' |')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page', type=int, default=1)
    parser.add_argument('--page-size', type=int)
    parser.add_argument('--query', default='')
    parser.add_argument('--category', default='')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--write-index', action='store_true')
    args = parser.parse_args()
    try:
        data = load_registry()
        active = sorted((f for f in data['features'] if f['status'] == 'active'), key=lambda f: int(f['id']))
        if args.check:
            print(f"检查通过：{len(data['features'])}条历史记录，{len(active)}项启用功能，下一个编号{data['next_id']:04d}。")
            return
        if args.write_index:
            text = '# skill-mention 完整功能目录\n\n'
            text += f'当前启用功能：{len(active)}项。编号保持稳定，停用项不在默认目录显示。\n\n'
            text += '分类：' + '；'.join(f'{k}（{v}）' for k, v in sorted(Counter(f['category'] for f in active).items())) + '\n\n'
            text += table(active, absolute=False) + '\n\n'
            text += '\n'.join(f"- {f['id']} {cell(f['title'])}（{cell(f['category'])}）：{cell(f['summary'])}" for f in active) + '\n'
            (ROOT / 'INDEX.md').write_text(text, encoding='utf-8')
            print('已刷新完整目录：' + str(ROOT / 'INDEX.md'))
            return
        size = args.page_size or data['page_size']
        if size < 1 or args.page < 1:
            raise ValueError('Page and page size must be positive')
        query = args.query.casefold().strip()
        selected = [f for f in active if (not args.category or f['category'] == args.category) and (
            not query or query in ' '.join([f['id'], f['title'], f['summary'], f['category'], *f.get('tags', [])]).casefold())]
        start = 0 if args.all else (args.page - 1) * size
        shown = selected if args.all else selected[start:start + size]
        print('功能提示词与示例库（skill-mention）\n')
        print(f'共{len(active)}项启用功能，当前匹配{len(selected)}项。')
        if len(active) > size:
            print('分类：' + '；'.join(f'{k}（{v}）' for k, v in sorted(Counter(f['category'] for f in active).items())))
        if shown:
            print(f'当前显示第{start + 1}–{start + len(shown)}项。\n')
            print(table(shown))
        elif selected:
            print('\n本页无条目，请返回前一页或显示全部。')
        else:
            print('\n没有匹配功能，可更换关键词或查看完整目录。')
        print('\n' + link('完整目录', 'INDEX.md'))
        if not args.all and start + len(shown) < len(selected):
            print(f'可说“下一页”（第{args.page + 1}页）、“显示全部”，或指定分类/关键词。')
        if shown:
            example_id = shown[0]['id']
            print(f'可说“展开{example_id}的提示词”“使用{example_id}＋任务”或“新增功能：……”。')
        else:
            print('可指定新的分类/关键词，或说“新增功能：……”。')
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('目录错误：' + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
