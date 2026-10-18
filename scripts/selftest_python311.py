"""防止高版本 Python 语法进入魔搭 Python 3.11 运行环境。"""
import ast
import io
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = [ROOT / 'app.py', ROOT / 'app_main.py']
    for folder in ('core', 'modules', 'scripts'):
        paths.extend((ROOT / folder).rglob('*.py'))
    failures = []
    for path in sorted(set(paths)):
        try:
            source = path.read_text(encoding='utf-8-sig')
            ast.parse(source, filename=str(path), feature_version=(3, 11))
            # 新版解析器的 feature_version 不能完整还原旧版 f-string 分词规则。
            stack = []
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type == getattr(tokenize, 'FSTRING_START', -1):
                    stack.append(token)
                elif token.type == getattr(tokenize, 'FSTRING_END', -1):
                    start = stack.pop()
                    triple = start.string.endswith(('\"\"\"', "'''"))
                    if not triple and token.end[0] != start.start[0]:
                        failures.append(f'{path.relative_to(ROOT)}:{start.start[0]}: 单引号 f-string 跨行，不兼容 Python 3.11')
        except SyntaxError as exc:
            failures.append(f'{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}')
    for failure in failures:
        print(failure)
    assert not failures, f'Python 3.11 语法不兼容：{len(failures)}项'
    print(f'Python 3.11 syntax: PASS ({len(set(paths))} files)')


if __name__ == '__main__':
    main()
