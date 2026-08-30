#!/usr/bin/env python3
"""Release acceptance：在一個拋棄式的**採用者** repository 上跑完整條生命週期。

為什麼需要它，而且為什麼不能用 Starter 自己的 repo 代替：

`DEVELOPING.md` 說明本 repo 是 Starter **原始碼**，不是採用 Starter 的專案 ——
它刻意不設 `core.hooksPath`，`STATE.md` 是出貨模板。所以拿它 dogfood 會混淆
「產品」與「模板」兩種語意，而且它本來就過不了自己的 runtime audit。

但那留下一個缺口：**這條工作流從未在真實採用者形狀中被整體走完過。**
e2e 測試模擬過各個片段，那是模擬；bootstrap、真實的 git hook、TTY 批准、
以及對整段合法歷史跑伺服器端稽核，這四件事只有在這裡才會同時發生。

涵蓋：
    1. bootstrap / 安裝            5. verification / archive
    2. approve-spec（真 TTY）      6. ARCHIVE 之後的第二個 change
    3. approve-tests（真 TTY）     7. 對整段合法歷史跑 server audit
    4. 產品 commit（經過真 hook）

用法：
    python3 workflow/bin/acceptance.py            # 跑完即清理
    python3 workflow/bin/acceptance.py --keep     # 保留現場供檢查
"""
from __future__ import annotations
import argparse, os, pty, select, shutil, subprocess, sys, tempfile, time
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
CHANGE = 'add-greeting'
SECOND = 'add-farewell'


def shipped_roots():
    manifest = SRC / 'workflow/SHIPPED-MANIFEST.txt'
    return [l.strip().rstrip('/') for l in manifest.read_text(encoding='utf-8').splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


class Fail(Exception):
    pass


class Acceptance:
    def __init__(self, root: Path):
        self.r = root
        self.step = 0

    # ---- 基礎設施 --------------------------------------------------------
    def run(self, *args, check=True, **kw):
        p = subprocess.run(list(args), cwd=self.r, capture_output=True, text=True, **kw)
        if check and p.returncode != 0:
            raise Fail(f'指令失敗（exit {p.returncode}）：{" ".join(args)}\n'
                       f'{p.stdout}\n{p.stderr}')
        return p

    def cli(self, *args, check=True):
        return self.run(sys.executable, 'workflow/bin/workflow_transition.py', *args, check=check)

    def git(self, *args, check=True):
        return self.run('git', *args, check=check)

    def commit(self, *paths, msg):
        """經過**真的** pre-commit hook。這是重點 —— 不用 --no-verify。"""
        self.git('add', '--', *paths)
        return self.git('commit', '-m', msg, '--', *paths)

    def say(self, text):
        self.step += 1
        print(f'\n[{self.step:02d}] {text}', flush=True)

    def approve_on_pty(self, command, change, actor='release-acceptance'):
        """在真的 controlling terminal 上執行 approve-*。

        approve-spec / approve-tests 要求 TTY，所以這一段不能用 subprocess ——
        而「不能用 subprocess」正是那道邊界存在的意義，因此驗收必須真的跨過它。
        """
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(str(self.r))
            os.execvp(sys.executable,
                      [sys.executable, 'workflow/bin/workflow_transition.py', command, change])
            os._exit(127)
        out, sent, deadline = b'', 0, time.time() + 60
        try:
            while time.time() < deadline:
                rl, _, _ = select.select([fd], [], [], 0.5)
                if rl:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    out += chunk
                text = out.decode('utf-8', 'replace')
                if sent == 0 and change in text:
                    os.write(fd, (change + '\n').encode()); sent = 1
                elif sent == 1 and 'Approval actor' in text:
                    os.write(fd, (actor + '\n').encode()); sent = 2
            _, status = os.waitpid(pid, 0)
            code = os.waitstatus_to_exitcode(status)
        finally:
            os.close(fd)
        text = out.decode('utf-8', 'replace')
        if code != 0:
            raise Fail(f'{command} 失敗（exit {code}）：\n{text}')
        return text

    # ---- 生命週期 --------------------------------------------------------
    def install(self):
        self.say('安裝 Starter 到一個空的採用者 repository')
        for rel in shipped_roots():
            s = SRC / rel
            if not s.exists():
                continue
            d = self.r / rel
            if s.is_dir():
                shutil.copytree(s, d, ignore=shutil.ignore_patterns(
                    'tests', '__pycache__', '*.pyc', 'node_modules', '.venv'))
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'acceptance@example.invalid')
        self.git('config', 'user.name', 'Release Acceptance')
        self.run('bash', 'workflow/bin/bootstrap.sh')
        d = self.cli('doctor')
        if 'Repository enforcement: ACTIVE' not in d.stdout:
            raise Fail('bootstrap 之後 Repository enforcement 必須是 ACTIVE：\n' + d.stdout)
        print('    ✓ bootstrap 完成，Repository enforcement: ACTIVE')

    def discovery(self):
        self.say('DISCOVERY：定案 PROJECT-PROFILE，寫 OpenSpec change')
        p = self.r / 'PROJECT-PROFILE.md'
        t = p.read_text(encoding='utf-8')
        for a, b in (('Type: UNKNOWN', 'Type: API'),
                     ('Web verification required: auto', 'Web verification required: no'),
                     ('Primary stack: UNKNOWN', 'Primary stack: Node.js'),
                     ('Package manager: UNKNOWN', 'Package manager: npm'),
                     ('Monorepo: UNKNOWN', 'Monorepo: no'),
                     ('CI provider: UNKNOWN', 'CI provider: GitHub Actions'),
                     ('Test database strategy: UNKNOWN', 'Test database strategy: not-applicable')):
            if a not in t:
                raise Fail(f'PROJECT-PROFILE 模板缺少預期欄位：{a}')
            t = t.replace(a, b)
        # API 專案必須列出 critical journeys —— 它們決定端點驗證的**範圍**，
        # 並納入被批准的 profile digest。
        t = t.replace('## Critical user journeys\n- 尚未定義',
                      '## Critical user journeys\n'
                      '- [J1] 呼叫端可以取得問候語\n'
                      '- [J2] 空白名稱會被後端拒絕')
        p.write_text(t, encoding='utf-8')

        # 這裡刻意用 `Core verification policy: auto`（採用者的常見路徑）。
        # `custom` 有一個 greenfield 死結：驗證腳本本身是產品程式碼，ENGINEERING
        # 之前不能 commit，但 profile 一宣告它，每個 commit 都要先跑它 ——
        # 而 verify.sh 的 custom 分支完全忽略 plan_mode。見 GATES.md。

        c = self.r / 'openspec/changes' / CHANGE
        (c / 'specs').mkdir(parents=True)
        (c / 'proposal.md').write_text(
            f'# {CHANGE}\n\n加入一個 greeting 函式。**不做**任何網路或檔案存取。\n',
            encoding='utf-8')
        (c / 'specs/main.md').write_text(
            '# Spec\n\n`greet(name)` 回傳 `"Hello, <name>!"`。\n'
            'name 為空字串時 raise ValueError。\n', encoding='utf-8')
        (c / 'tasks.md').write_text('# Tasks\n\n- [ ] 實作 greet\n- [ ] 加測試\n',
                                    encoding='utf-8')

        self.cli('set-mode', 'GREENFIELD')
        self.commit('workflow/STATE.md', 'workflow/state-log.md', msg='chore: set mode')
        self.cli('start-change', CHANGE)
        self.commit('workflow/STATE.md', 'workflow/state-log.md', msg='chore: start change')
        # **必須在 submit-for-review 之前 commit。** PROJECT-PROFILE.md 一進
        # SPEC_REVIEW 就變成唯讀的 Control Plane，那時再想 commit 就來不及了。
        self.commit('PROJECT-PROFILE.md', f'openspec/changes/{CHANGE}',
                    msg=f'spec: {CHANGE} 送審版本')
        self.cli('submit-for-review', CHANGE)
        self.commit('workflow/STATE.md', 'workflow/state-log.md', msg='chore: submit for review')
        print('    ✓ 進入 SPEC_REVIEW（送審內容已在 HEAD）')

    def approve_spec(self):
        self.say('SPEC_REVIEW：人類在真的 TTY 上批准')
        out = self.approve_on_pty('approve-spec', CHANGE)
        if 'Core verification policy: auto' not in out:
            raise Fail('TTY 畫面必須列出即將定案的 verification policy：\n' + out)
        self.commit('workflow/STATE.md', 'workflow/state-log.md', msg='chore: approve spec')
        print('    ✓ approve-spec 完成（TTY 畫面有列出 verification policy）')

    def approve_tests(self):
        self.say('TEST_DESIGN：寫測試案例文件，送進 HEAD，人類批准')
        (self.r / 'workflow/test-cases' / f'{CHANGE}.md').write_text(
            f'# Test Design — {CHANGE}\n\n'
            '| ID | 情境 | 輸入 | 期待 |\n|---|---|---|---|\n'
            '| T1 | 正常 | `greet("World")` | `"Hello, World!"` |\n'
            '| T2 | 邊界 | `greet("")` | raise ValueError |\n\n'
            '- [ ] T1\n- [ ] T2\n', encoding='utf-8')
        self.commit(f'workflow/test-cases/{CHANGE}.md', msg=f'test: {CHANGE} 測試設計')
        self.approve_on_pty('approve-tests', CHANGE)
        self.commit('workflow/STATE.md', 'workflow/state-log.md', msg='chore: approve tests')
        self.cli('start-engineering', CHANGE)
        self.commit('workflow/STATE.md', 'workflow/state-log.md', msg='chore: start engineering')
        print('    ✓ 進入 ENGINEERING')

    def engineering(self):
        self.say('ENGINEERING：產品 commit 走真實的 pre-commit hook')
        (self.r / 'package.json').write_text(
            '{\n  "name": "consumer-project",\n  "private": true,\n'
            '  "scripts": {\n'
            '    "test": "node --test",\n'
            '    "build": "node -e \\"console.log(\'build ok\')\\""\n'
            '  }\n}\n', encoding='utf-8')
        (self.r / 'src').mkdir()
        (self.r / 'src/greeting.js').write_text(
            'export function greet(name) {\n'
            '  if (!name) throw new Error("name 不得為空");\n'
            '  return `Hello, ${name}!`;\n'
            '}\n', encoding='utf-8')
        (self.r / 'tests').mkdir()
        (self.r / 'tests/greeting.test.js').write_text(
            'import test from "node:test";\nimport assert from "node:assert";\n'
            'import { greet } from "../src/greeting.js";\n\n'
            'test("T1 正常", () => assert.equal(greet("World"), "Hello, World!"));\n'
            'test("T2 邊界", () => assert.throws(() => greet("")));\n', encoding='utf-8')
        (self.r / 'package.json').write_text(
            (self.r / 'package.json').read_text(encoding='utf-8').replace(
                '"private": true,', '"private": true,\n  "type": "module",'),
            encoding='utf-8')
        self.commit('package.json', 'src', 'tests', msg=f'feat({CHANGE}): 實作 greet')

        # 打勾是進度，不得撤銷批准
        tasks = self.r / 'openspec/changes' / CHANGE / 'tasks.md'
        tasks.write_text(tasks.read_text(encoding='utf-8').replace('- [ ]', '- [x]'),
                         encoding='utf-8')
        self.commit(f'openspec/changes/{CHANGE}/tasks.md', msg='chore: 標記任務完成')

        # API 專案的端點驗證 evidence。三類情境缺一不可 ——
        # 權限那一類最容易被跳過，也最容易出事。
        ev = self.r / 'workflow/evidence' / CHANGE
        ev.mkdir(parents=True, exist_ok=True)
        (ev / 'api.md').write_text(
            '# API Verification Evidence\n\n'
            'J1: success=PASS validation=PASS authorization=not-applicable\n'
            'J2: success=PASS validation=PASS authorization=not-applicable\n\n'
            '本專案為純函式庫形式的 API，端點無權限層，故 authorization 標記 '
            'not-applicable。\n', encoding='utf-8')
        self.commit(f'workflow/evidence/{CHANGE}/api.md', msg='docs: API 驗證證據')
        print('    ✓ 產品 commit 通過 gate；勾選進度未撤銷批准；API evidence 已寫入')

    def verify_and_archive(self):
        self.say('VERIFICATION → ARCHIVE')
        self.cli('verification-pass', CHANGE)
        self.commit('workflow/STATE.md', 'workflow/state-log.md',
                    'workflow/evidence', msg='chore: verification passed')
        self.cli('archive', CHANGE)
        self.commit('workflow/STATE.md', 'workflow/state-log.md', msg='chore: archive')
        state = (self.r / 'workflow/STATE.md').read_text(encoding='utf-8')
        if 'Phase: ARCHIVE' not in state:
            raise Fail('archive 之後 Phase 必須是 ARCHIVE：\n' + state)
        core = sorted((self.r / 'workflow/evidence' / CHANGE / 'core').glob('*.md'))
        if not core:
            raise Fail('缺少 core evidence')
        print(f'    ✓ ARCHIVE；core evidence: {core[-1].name}')

    def second_round(self):
        self.say('ARCHIVE 之後的第二個 change（生命週期必須有第二輪）')
        c = self.r / 'openspec/changes' / SECOND
        (c / 'specs').mkdir(parents=True)
        (c / 'proposal.md').write_text(f'# {SECOND}\n\n加入 farewell。\n', encoding='utf-8')
        (c / 'specs/main.md').write_text('# Spec\n\n`farewell(name)`。\n', encoding='utf-8')
        (c / 'tasks.md').write_text('# Tasks\n\n- [ ] 實作\n', encoding='utf-8')
        self.commit(f'openspec/changes/{SECOND}', msg=f'spec: {SECOND} 草案')
        self.cli('start-change', SECOND)
        self.commit('workflow/STATE.md', 'workflow/state-log.md', msg='chore: start second change')
        state = (self.r / 'workflow/STATE.md').read_text(encoding='utf-8')
        for field in ('Phase: SPECIFICATION', f'Active OpenSpec change: {SECOND}',
                      'Spec approved: no', 'Approved profile digest: none',
                      'Approved spec digest: none', 'Approved test design digest: none',
                      'Project mode: GREENFIELD'):
            if field not in state:
                raise Fail(f'第二輪的 STATE 缺少 `{field}`：\n{state}')
        print('    ✓ 第二輪開始；批准全部重置，project mode 保留')

    def server_audit(self):
        self.say('對整段合法歷史跑伺服器端稽核（模擬 required check）')
        first = self.git('rev-list', '--max-parents=0', 'HEAD').stdout.split()[0]
        p = self.run(sys.executable, 'workflow/bin/audit-control-plane.py', first, 'HEAD',
                     check=False)
        if p.returncode != 0:
            raise Fail('合法歷史必須通過伺服器端稽核，但被拒絕了：\n'
                       + p.stdout + p.stderr)
        print('    ✓ ' + p.stdout.strip())

        # 反向：稽核必須真的會擋。沒有這一步，上面那個綠燈證明不了任何事。
        self.say('反向驗證：未授權的產品 commit 必須被稽核擋下')
        (self.r / 'src/rogue.js').write_text('// 未經批准\n', encoding='utf-8')
        self.git('add', 'src/rogue.js')
        blocked = self.git('commit', '-m', 'rogue', check=False)
        if blocked.returncode == 0:
            raise Fail('SPECIFICATION 階段的產品 commit 應該被本機 gate 擋下，但它通過了')
        print('    ✓ 本機 gate 擋下（這是繞過前的第一道）')

        self.git('commit', '--no-verify', '-m', 'rogue（--no-verify 繞過本機）')
        p = self.run(sys.executable, 'workflow/bin/audit-control-plane.py', 'HEAD^', 'HEAD',
                     check=False)
        if p.returncode == 0:
            raise Fail('`--no-verify` 繞過本機之後，伺服器端稽核必須擋下，但它放行了：\n'
                       + p.stdout)
        print('    ✓ 伺服器端稽核擋下（--no-verify 繞得過本機、繞不過伺服器）')

    def run_all(self):
        self.install()
        self.discovery()
        self.approve_spec()
        self.approve_tests()
        self.engineering()
        self.verify_and_archive()
        self.second_round()
        self.server_audit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='保留拋棄式 repo 供檢查')
    a = ap.parse_args()

    td = Path(tempfile.mkdtemp(prefix='starter-acceptance-'))
    repo = td / 'consumer-project'
    repo.mkdir()
    print(f'採用者 repository：{repo}')
    try:
        Acceptance(repo).run_all()
    except Fail as e:
        print(f'\n✗ Release acceptance 失敗\n{e}', file=sys.stderr)
        if not a.keep:
            shutil.rmtree(td, ignore_errors=True)
        else:
            print(f'現場保留於 {repo}', file=sys.stderr)
        raise SystemExit(1)
    print('\n✓ Release acceptance 全部通過 —— '
          '安裝、TTY 批准、產品 commit、驗證、封存、第二輪、伺服器稽核（正反兩向）')
    if a.keep:
        print(f'現場保留於 {repo}')
    else:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    main()
