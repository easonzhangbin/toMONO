"""Maintain cumulative donor credits and require a human review before a release."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- toMONO:donors:start -->'
END = '<!-- toMONO:donors:end -->'
INTRO = [
    '感谢支持 toMONO 开发与影像研究的朋友。',
    '名单按首次加入顺序累计，随新版本补充，并保留此前的署名。仅展示确认公开的姓名或昵称，不展示金额或支付记录。',
]
EMPTY = '感谢每一份支持，捐赠者署名将在后续版本确认后补充。'
FOOTER = '支持完全自愿，不影响软件功能。也感谢匿名支持、反馈问题和贡献代码的朋友。'


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def normalized_name(value):
    name = unicodedata.normalize('NFC', value.strip())
    if not name or len(name) > 80 or not all(c.isprintable() for c in name):
        raise ValueError('请提供 1–80 字的公开姓名或昵称，不能包含换行或控制字符。')
    return name


def load_names(root):
    data = json.loads((root / 'docs/donors.json').read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('donors'), list):
        raise ValueError('捐赠者名单格式不正确。')
    names = data['donors']
    if any(not isinstance(n, str) or normalized_name(n) != n for n in names):
        raise ValueError('名单包含无效署名。')
    if len(set(n.casefold() for n in names)) != len(names):
        raise ValueError('名单包含重复署名。')
    return names


def check_history(root, names):
    # A tracked list may only grow; reject accidental manual deletion/reordering.
    result = subprocess.run(['git', 'show', 'HEAD:docs/donors.json'], cwd=root,
                            capture_output=True, text=True, encoding='utf-8')
    if result.returncode == 0:
        previous = json.loads(result.stdout)['donors']
        if names[:len(previous)] != previous:
            raise ValueError('历史捐赠者署名被删除或改动；名单只能在末尾累加。')


def fingerprint(names):
    return hashlib.sha256(json_text(names).encode('utf-8')).hexdigest()


def append_names(root, names, additions):
    known = {name.casefold() for name in names}
    for name in map(normalized_name, additions):
        if name.casefold() not in known:
            names.append(name)
            known.add(name.casefold())
    (root / 'docs/donors.json').write_text(json_text({'schema_version': 1, 'donors': names}), encoding='utf-8')
    sync(root, names)


def markdown_name(name):
    # Credits are literal names, never Markdown links, formatting, or HTML.
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~-])', r'\\\1', html.escape(name))


def topic(names):
    return {'id': 'donors', 'title': '捐赠者名单', 'symbol': 'heart.text.clipboard',
            'paragraphs': INTRO + (names or [EMPTY]) + [FOOTER]}


def rendered(root, names):
    listing = '\n'.join('- ' + markdown_name(n) for n in names) if names else EMPTY
    block = (START + '\n## 捐赠者名单\n\n' + '\n\n'.join(INTRO) + '\n\n' + listing
             + '\n\n' + FOOTER + '\n\n[完整名单与更新方式](docs/DONORS.md)\n' + END)
    readme_path = root / 'README.md'
    readme = readme_path.read_text(encoding='utf-8')
    if START in readme and END in readme:
        readme = readme[:readme.index(START)] + block + readme[readme.index(END) + len(END):]
    elif START in readme or END in readme:
        raise ValueError('README 捐赠者名单标记不完整。')
    else:
        readme = readme.replace('\n## 许可\n', '\n' + block + '\n\n## 许可\n', 1)
        if START not in readme:
            raise ValueError('README 缺少名单插入位置。')
    help_path = root / 'macos/assets/HelpContent.json'
    help_topics = json.loads(help_path.read_text(encoding='utf-8'))
    help_topics = [t for t in help_topics if t['id'] != 'donors']
    position = next(i for i, t in enumerate(help_topics) if t['id'] == 'donate') + 1
    help_topics.insert(position, topic(names))
    document = ('# 捐赠者名单\n\n' + '\n\n'.join(INTRO) + '\n\n' + listing + '\n\n'
                + FOOTER + '\n\n名单由维护者在每次正式打包发布前询问项目负责人后增量更新。'
                '可使用公开昵称，也可选择匿名支持。软件中可在“使用帮助 → 捐赠者名单”离线查看本版名单。'
                'GitHub 名单可能比已安装版本更新，应用内名单随下次打包同步。\n\n'
                '维护者可运行 `python3 scripts/donors.py append "公开昵称"` 同步已确认的署名。'
                '请勿直接改写本页或 README 中的自动生成区块。\n')
    return {readme_path: readme, help_path: json_text(help_topics), root / 'docs/DONORS.md': document}


def sync(root, names, check=False):
    stale = []
    for path, expected in rendered(root, names).items():
        if not path.exists() or path.read_text(encoding='utf-8') != expected:
            if check:
                stale.append(str(path.relative_to(root)))
            else:
                path.write_text(expected, encoding='utf-8')
    if stale:
        raise ValueError('名单未同步：' + '、'.join(stale) + '；请运行 python3 scripts/donors.py sync。')


def verify_release(root, version, build):
    names = load_names(root)
    check_history(root, names)
    sync(root, names, check=True)
    receipt = root / '.build/donor-review.json'
    review = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
    if (review.get('version'), review.get('build'), review.get('donors_sha256')) != (version, build, fingerprint(names)):
        raise ValueError('正式打包前请先询问用户：“本版有哪些需要新增的捐赠者公开姓名或昵称？若无新增请回复无新增。”'
                         '收到答复后按 docs/BUILD.md 记录本版确认；不得自行假定无新增。')
    return review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('sync', help='从累计名单同步 GitHub 与软件帮助')
    sub.add_parser('check', help='检查只增不删与文档同步')
    append = sub.add_parser('append', help='新增已确认的公开署名，不记录发版确认')
    append.add_argument('names', nargs='+', metavar='公开姓名')
    review = sub.add_parser('review', help='仅在收到用户本版答复后使用')
    review.add_argument('--version', required=True)
    review.add_argument('--build', required=True)
    answer = review.add_mutually_exclusive_group(required=True)
    answer.add_argument('--add', nargs='+', metavar='公开姓名', help='用户本次明确要求新增的署名')
    answer.add_argument('--no-additions', action='store_true', help='用户明确回复本版没有新增')
    check = sub.add_parser('check-release', help='正式构建和 DMG 打包的发版确认检查')
    check.add_argument('--version', required=True)
    check.add_argument('--build', required=True)
    args = parser.parse_args()
    try:
        names = load_names(ROOT)
        check_history(ROOT, names)
        if args.command == 'review':
            if not re.fullmatch(r'\d+\.\d+\.\d+', args.version) or not args.build.isdigit():
                raise ValueError('请提供正式版本号（例如 1.3.0）和数字构建号。')
            append_names(ROOT, names, args.add or [])
            receipt = ROOT / '.build/donor-review.json'
            receipt.parent.mkdir(exist_ok=True)
            receipt.write_text(json_text({'version': args.version, 'build': args.build,
                'donors_sha256': fingerprint(names), 'answer': 'additions' if args.add else 'no-additions'}), encoding='utf-8')
            print('本版捐赠者确认已记录；历史名单保留，GitHub 与软件帮助已同步。')
        elif args.command == 'append':
            append_names(ROOT, names, args.names)
            print('公开署名已追加，GitHub 与软件帮助已同步。')
        elif args.command == 'check-release':
            verify_release(ROOT, args.version, args.build)
            print('本版捐赠者名单已确认并同步。')
        else:
            sync(ROOT, names, check=args.command == 'check')
            print('累计捐赠者名单已' + ('检查。' if args.command == 'check' else '同步。'))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
