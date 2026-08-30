#!/usr/bin/env python3
"""平行執行 Starter 自我測試，並回報每個類別的耗時。

為什麼需要它：測試類別彼此**完全獨立** —— 每個都把 Starter 複製到自己的暫存目錄、
自己 `git init`。序列執行等於把一堆互不相干的子行程排隊，總時間是它們的總和。

依 `workflow/CI.md` 的原則：沒有依賴關係的事就同時做。這裡是同一條原則套用在
Starter 自己的測試上 —— 一條要等十分鐘的測試套件，開發者會想辦法不跑它。

用法：
    python3 workflow/bin/run-tests.py            # 全部，平行
    python3 workflow/bin/run-tests.py -j 4       # 指定併發數
    python3 workflow/bin/run-tests.py --slowest 10
    python3 workflow/bin/run-tests.py -k Round16 # 只跑名稱含 Round16 的類別
"""
from __future__ import annotations
import argparse, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / 'workflow/tests'


def discover():
    """(module, class) 清單。用文字掃描而非 import —— 測試模組 import 時會做不少事，
    而這支程式的唯一工作是排程。"""
    out = []
    for f in sorted(TESTS.glob('test_*.py')):
        mod = f'workflow.tests.{f.stem}'
        for name in re.findall(r'^class (\w+)\(unittest\.TestCase\)', f.read_text(encoding='utf-8'), re.M):
            out.append((mod, name))
    return out


def run_one(target):
    mod, cls = target
    t0 = time.time()
    # **不要寫 bytecode。** 有幾條測試會從 SRC 的 workflow/bin import（那是刻意的：
    # 它們驗證的是出貨的那一份判準），於是跑測試本身會在出貨目錄裡產生 __pycache__ ——
    # 而 test_shipped_manifest_entries_exist 正是在檢查出貨目錄不得有生成物。
    # 序列執行時碰巧沒撞到，平行執行 + CI 的乾淨 checkout 就穩定重現。
    # **測試套件不該污染它自己在稽核的那棵樹。**
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    r = subprocess.run([sys.executable, '-m', 'unittest', f'{mod}.{cls}'],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    return cls, r.returncode, time.time() - t0, r.stdout + r.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-j', type=int, default=min(8, (os.cpu_count() or 4)),
                    help='併發數（預設：CPU 數，上限 8）')
    ap.add_argument('-k', default=None, help='只跑類別名稱含此字串的測試')
    ap.add_argument('--slowest', type=int, default=5, help='列出最慢的 N 個類別')
    a = ap.parse_args()

    targets = discover()
    if a.k:
        targets = [t for t in targets if a.k.lower() in t[1].lower()]
    if not targets:
        print('沒有符合的測試類別', file=sys.stderr); raise SystemExit(2)

    t0 = time.time()
    results = []
    # 先送出耗時可能較長的（名稱無從得知，所以維持發現順序）；ThreadPoolExecutor
    # 在這裡只是子行程的排程器，GIL 不構成瓶頸。
    with ThreadPoolExecutor(max_workers=a.j) as ex:
        for res in ex.map(run_one, targets):
            results.append(res)
            cls, code, dt, _ = res
            print(f'{"OK  " if code == 0 else "FAIL"} {dt:6.1f}s  {cls}', flush=True)

    wall = time.time() - t0
    failed = [r for r in results if r[1] != 0]
    total_cpu = sum(r[2] for r in results)

    print()
    print(f'{len(results)} 個類別，牆鐘 {wall:.1f}s（序列約需 {total_cpu:.1f}s，'
          f'加速 {total_cpu / wall:.1f}×，併發 {a.j}）')
    if a.slowest:
        print(f'最慢的 {a.slowest} 個：')
        for cls, _, dt, _ in sorted(results, key=lambda r: -r[2])[:a.slowest]:
            print(f'  {dt:6.1f}s  {cls}')
    if failed:
        print()
        for cls, _, _, out in failed:
            print(f'===== {cls} =====')
            print(out)
        print(f'失敗：{len(failed)} 個類別', file=sys.stderr)
        raise SystemExit(1)
    print('全部通過')


if __name__ == '__main__':
    main()
