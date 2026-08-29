import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path

SRC=Path(__file__).resolve().parents[2]

def shipped_roots(src):
    manifest=src/"workflow/SHIPPED-MANIFEST.txt"
    return [line.strip().rstrip('/') for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith('#')]

OWNED=shipped_roots(SRC)
def fixture():
    td=Path(tempfile.mkdtemp(prefix="starter-reg-")); r=td/"repo"; r.mkdir()
    for rel in OWNED:
        s=SRC/rel
        if not s.exists(): continue
        d=r/rel
        if s.is_dir(): shutil.copytree(s,d,ignore=shutil.ignore_patterns("tests","__pycache__","*.pyc","node_modules","dist","build",".next","venv",".venv","coverage","playwright-report","test-results"))
        else: d.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(s,d)
    return td,r

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
        self.git('checkout','-q','main');(self.r/'main-only').write_text('m');self.git('add','main-only');self.git('commit','-m','main diverge');self.git('merge','--no-ff','feat','-m','merge feat')
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
                      +body+'Overall exit code: 0\n')
                ok,why=self._status(r,text)
                self.assertFalse(ok,f'{label} 應被拒絕')
                self.assertIn(expect,why,label)
            good=('# x\nCore evidence schema: 2\nChange: demo\nVerification policy: auto\n'
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
                              'Verification policy: not-applicable\nChecks selected: 0\nChecks executed: 0\n'
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
            def check(text): ev.write_text(text,encoding='utf-8'); return m.core_evidence_status(ev)

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


# 必須放在檔案最末端。放在 class 定義之前會讓「直接執行本檔」只跑到當下已定義的少數測試，
# 卻仍印出 OK —— 那是比沒有測試更危險的假信心。
if __name__ == "__main__":
    unittest.main()
