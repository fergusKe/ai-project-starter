import os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
SRC=Path(__file__).resolve().parents[2]

def shipped_roots(src):
    manifest=src/"workflow/SHIPPED-MANIFEST.txt"
    return [line.strip().rstrip('/') for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith('#')]

STARTER_OWNED = shipped_roots(SRC)
def copy_starter_fixture(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    for rel in STARTER_OWNED:
        s=src/rel
        if not s.exists(): continue
        d=dst/rel
        if s.is_dir():
            shutil.copytree(s,d,ignore=shutil.ignore_patterns("tests","__pycache__","*.pyc","node_modules","dist","build",".next","venv",".venv","coverage","playwright-report","test-results"))
        else:
            d.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(s,d)
    # pristine workflow fixture, independent of host repo progress
    state=dst/"workflow/STATE.md"
    state.write_text("""# Workflow State
> 本檔是 Control Plane。不得手動編輯；請使用 `python3 workflow/bin/workflow_transition.py ...`。
> `Implementation allowed` 為推導值，不儲存在 STATE：僅當 Phase=ENGINEERING 且 Spec/Test Design 均 approved 時為 true。

Phase: DISCOVERY
Project mode: UNSET
Active OpenSpec change: none
Spec approved: no
Test design approved: no
Verification passed: no
Approved by: none
Last updated: none
""",encoding="utf-8")
    (dst/"workflow/state-log.md").write_text("# Workflow State Log\n\n",encoding="utf-8")
    for rel in ("workflow/evidence","workflow/test-cases"):
        d=dst/rel
        if d.exists():
            for child in list(d.iterdir()):
                if child.name==".gitkeep": continue
                if child.is_dir(): shutil.rmtree(child)
                else: child.unlink()
    changes=dst/"openspec/changes"
    if changes.exists():
        for child in list(changes.iterdir()):
            if child.name!="archive":
                if child.is_dir(): shutil.rmtree(child)
                else: child.unlink()


def run(cwd,*args,env=None):
 e=os.environ.copy();e.update(env or {}); shim=Path(cwd)/'.test-bin'; e['PATH']=str(shim)+os.pathsep+e.get('PATH','');return subprocess.run(list(args),cwd=cwd,capture_output=True,text=True,env=e,stdin=subprocess.DEVNULL)
class E2E(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());self.r=self.tmp/'repo';copy_starter_fixture(SRC,self.r)
  shim=self.r/'.test-bin';shim.mkdir()
  node=shim/'node';node.write_text('''#!/usr/bin/env python3
import json,sys
try:p=json.load(open('package.json'))
except:sys.exit(1)
name=sys.argv[-1] if len(sys.argv)>1 else ''
sys.exit(0 if name in p.get('scripts',{}) else 1)
''');node.chmod(0o755)
  npm=shim/'npm';npm.write_text('''#!/usr/bin/env python3
import json,os,subprocess,sys
p=json.load(open('package.json')); scripts=p.get('scripts',{})
name='test' if len(sys.argv)>1 and sys.argv[1]=='test' else (sys.argv[2] if len(sys.argv)>2 and sys.argv[1]=='run' else '')
cmd=scripts.get(name,'')
if 'exit 1' in cmd: sys.exit(1)
if name in ('test:e2e','e2e','playwright'):
 os.makedirs('playwright-report',exist_ok=True);open('playwright-report/index.html','w').write('report')
print('shim-'+name)
sys.exit(0)
''');npm.chmod(0o755)
  run(self.r,'git','init');run(self.r,'git','config','user.email','smoke@example.invalid');run(self.r,'git','config','user.name','Smoke');run(self.r,'git','config','core.hooksPath','.githooks');run(self.r,'git','add','.');run(self.r,'git','commit','-m','baseline')
  c=self.r/'openspec/changes/demo';c.mkdir(parents=True);[(c/n).write_text(n) for n in ('proposal.md','spec.md','tasks.md')]
  
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def cli(self,*a):return run(self.r,'python3','workflow/bin/workflow_transition.py',*a)
 def commit_transition(self,msg):
  run(self.r,'git','add','workflow/STATE.md','workflow/state-log.md')
  return run(self.r,'git','commit','-m',msg)
 def approve_internal(self,kind):
  sys.path.insert(0,str(self.r/'workflow/bin'));import workflow_state as ws
  s=ws.parse_state(self.r/'workflow/STATE.md')
  from dataclasses import replace
  # approve-spec 需要 TTY，所以這裡直接寫 STATE 代替。但代替必須**忠實** ——
  # 真正的 approve-spec 會把當下的 profile digest 一併寫進 STATE，
  # start-engineering 會回驗它。少寫這一欄等於假造出一個真實流程不會產生的狀態。
  _,_,_,dg=ws.profile_resolution(self.r)
  assert dg is not None,'e2e fixture 前提：進 approve-spec 之前 profile 必須完全解析'
  ns=replace(s,phase='TEST_DESIGN',spec_approved='yes',approved_by='smoke-human',profile_digest=dg,last_updated=ws.now_iso()) if kind=='spec' else replace(s,test_design_approved='yes',approved_by='smoke-human',last_updated=ws.now_iso())
  ws.write_state(self.r/'workflow/STATE.md',ns);h=ws.state_hash_path(self.r/'workflow/STATE.md')
  with (self.r/'workflow/state-log.md').open('a') as f:f.write(f'## smoke\n- Actor: smoke-human\n- Action: approve-{kind}\n- Change: demo\n- From: X\n- To: {ns.phase}\n- Git SHA: SMOKE\n- State hash: {h}\n- Reason: smoke\n\n')
  sys.path.pop(0);sys.modules.pop('workflow_state',None)
 def prep_to_engineering(self,web=False):
  p=self.r/'PROJECT-PROFILE.md';t=p.read_text().replace('Type: UNKNOWN','Type: WEB_APP' if web else 'Type: API').replace('Web verification required: auto','Web verification required: yes' if web else 'Web verification required: no')
  # 其餘必填欄位也要解析。approve-spec 是收取 profile 定案的邊界，
  # 讓 fixture 停在 UNKNOWN 等於繞過那個邊界去測後面的階段。
  for a,b in (('Primary stack: UNKNOWN','Primary stack: Node.js'),
              ('Package manager: UNKNOWN','Package manager: npm'),
              ('Monorepo: UNKNOWN','Monorepo: no'),
              ('CI provider: UNKNOWN','CI provider: GitHub Actions'),
              ('Test database strategy: UNKNOWN','Test database strategy: not-applicable')):
   t=t.replace(a,b)
  p.write_text(t);
  for a in [('set-mode','GREENFIELD'),('start-change','demo'),('submit-for-review','demo')]:self.assertEqual(self.cli(*a).returncode,0);self.assertEqual(self.commit_transition(a[0]).returncode,0)
  self.approve_internal('spec');self.assertEqual(self.commit_transition('approve spec').returncode,0)
  (self.r/'workflow/test-cases/demo.md').write_text('cases')
  self.approve_internal('tests');self.assertEqual(self.commit_transition('approve tests').returncode,0)
  self.assertEqual(self.cli('start-engineering','demo').returncode,0);self.assertEqual(self.commit_transition('start engineering').returncode,0)
 def test_non_web_disc_to_archive(self):
  self.prep_to_engineering(False);(self.r/'package.json').write_text('{"scripts":{"test":"echo ok","build":"echo build"}}');
  self.assertEqual(self.cli('verification-pass','demo').returncode,0);self.assertEqual(self.commit_transition('verification').returncode,0);self.assertEqual(self.cli('archive','demo').returncode,0)
  self.assertIn('Phase: ARCHIVE',(self.r/'workflow/STATE.md').read_text());self.assertTrue(list((self.r/'workflow/evidence/demo/core').glob('*.md')));self.assertIn('NOT APPLICABLE',(self.r/'workflow/evidence/demo/browser.md').read_text())
 def test_web_disc_to_archive(self):
  self.prep_to_engineering(True);(self.r/'package.json').write_text('{"scripts":{"test":"echo ok","build":"echo build","test:e2e":"mkdir -p playwright-report; echo report > playwright-report/index.html; echo e2e"}}');
  self.assertEqual(run(self.r,'bash','workflow/bin/verify.sh','--full').returncode,0);core=sorted((self.r/'workflow/evidence/demo/core').glob('*.md'))[-1]
  (self.r/'workflow/evidence/demo/browser.md').write_text(f'# Browser Verification Evidence\nCore evidence: {core.name}\nPlaywright report: playwright-report/index.html\nChrome DevTools MCP: console/network checked; no blocking errors\n')
  self.assertEqual(self.cli('verification-pass','demo').returncode,0);self.assertEqual(self.commit_transition('verification').returncode,0);self.assertEqual(self.cli('archive','demo').returncode,0);self.assertIn('Phase: ARCHIVE',(self.r/'workflow/STATE.md').read_text())
 def test_failed_check_records_failure(self):
  self.prep_to_engineering(False);(self.r/'package.json').write_text('{"scripts":{"test":"exit 1","build":"echo build"}}');
  r=self.cli('verification-pass','demo');self.assertNotEqual(r.returncode,0);core=sorted((self.r/'workflow/evidence/demo/core').glob('*.md'))[-1];self.assertIn('Overall exit code: 1',core.read_text());self.assertIn('Exit code: 1',core.read_text())
 def test_no_tty_approval(self):
  # front half to review
  p=self.r/'PROJECT-PROFILE.md';p.write_text(p.read_text().replace('Type: UNKNOWN','Type: API').replace('Web verification required: auto','Web verification required: no').replace('Primary stack: UNKNOWN','Primary stack: Python 3.12').replace('Package manager: UNKNOWN','Package manager: uv').replace('Monorepo: UNKNOWN','Monorepo: no').replace('CI provider: UNKNOWN','CI provider: GitHub Actions').replace('Test database strategy: UNKNOWN','Test database strategy: not-applicable'));
  for a in [('set-mode','GREENFIELD'),('start-change','demo'),('submit-for-review','demo')]:self.cli(*a);self.commit_transition(a[0])
  self.assertEqual(self.cli('approve-spec','demo').returncode,20)
 def test_unknown_auto_fails_closed(self):
  self.prep_to_engineering(False);p=self.r/'PROJECT-PROFILE.md';p.write_text(p.read_text().replace('Type: API','Type: UNKNOWN').replace('Web verification required: no','Web verification required: auto'))
  self.assertNotEqual(run(self.r,'bash','workflow/bin/verify.sh','--full').returncode,0)
if __name__=='__main__':unittest.main()
