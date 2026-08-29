#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json, os, re, shutil, stat, subprocess

REQUIRED_FIELDS=["Phase","Project mode","Active OpenSpec change","Spec approved","Test design approved","Verification passed","Approved by","Last updated"]
VALID_PHASES=["DISCOVERY","SPECIFICATION","SPEC_REVIEW","TEST_DESIGN","ENGINEERING","VERIFICATION","ARCHIVE"]
VALID_PROJECT_MODES={"UNSET","GREENFIELD","BROWNFIELD"}
YESNO={"yes","no"}
CONTROL_PLANE_PREFIXES=("workflow/bin/","workflow/tests/",".claude/hooks/",".githooks/")
CONTROL_PLANE_FILES={".claude/settings.json","workflow/STATE.md","workflow/state-log.md","workflow/GATES.md","workflow/CI.md","workflow/BROWSER-VERIFICATION.md","workflow/SHIPPED-MANIFEST.txt","templates/CODEOWNERS.example","templates/test-db-safety.md"}
EARLY_MUTABLE_POLICY_FILES={"PROJECT-PROFILE.md"}
AI_WRITABLE_PREFIXES=("docs/","openspec/","prompts/",".claude/skills/","workflow/test-cases/")
AI_WRITABLE_ROOT={"AGENTS.md","CLAUDE.md","CONTEXT.md","README.md","START-HERE.md","SETUP.md",".gitignore"}
CORE_EVIDENCE_RE=re.compile(r"^workflow/evidence/[^/]+/core/\d{8}T\d{6}(?:\d{6})?Z\.md$")
AUDIT_FAIL_CLOSED_PHASE='ENGINEERING'
INSTALLATION_PHASE='DISCOVERY'
INSTALLATION_ALLOWED_ROOTS={'AGENTS.md','CLAUDE.md','CONTEXT.md','PROJECT-PROFILE.md','README.md','SETUP.md','START-HERE.md','.gitignore'}
INSTALLATION_ALLOWED_PREFIXES=('.claude/','.githooks/','docs/','openspec/','prompts/','templates/','workflow/')
BROWSER_EVIDENCE_RE=re.compile(r"^workflow/evidence/[^/]+/browser\.md$")
# Change identifier 的唯一合法形狀。這個名字會被當成 **path component** 使用
# （`openspec/changes/<id>`、`workflow/evidence/<id>/…`），也會被寫進 STATE.md 與
# append-only 的 state-log，所以它同時是路徑輸入與檔案格式輸入，兩邊都要守住。
#
# 不採「純小寫」的建議：大小寫是命名風格不是安全性質，強制它會擋掉合法的既有專案。
# 真正危險的是 `/`、`.`／`..`、控制字元與換行 —— 這條 pattern 把它們全部排除。
CHANGE_ID_RE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def validate_change_id(change:str):
    """回傳錯誤訊息；合法時回傳 None。

    為什麼需要 canonical validator 而不是在 `ensure_change_exists` 裡多檢查幾下：
    change 名字有**兩個**下游消費者，而且它們的失敗模式完全不同。

    1. 路徑：`ROOT/'openspec/changes'/change`。`change='..'` 會解析到 `openspec/`，
       它非空，所以「目錄必須有內容」的檢查會通過。`verify.sh` 也直接把它插進
       `workflow/evidence/<change>/core`，`..` 會把 machine evidence 寫到宣告的
       ownership 範圍之外。
    2. 檔案格式：STATE.md 是 `Key: value` 的逐行格式。change 裡的換行會注入新的一行，
       實測 `evil\\nPhase: ENGINEERING` 會讓 STATE.md 出現第二個 `Phase:`。
       `parse_state_text` 的重複欄位檢查會擋下升級（fail-closed，方向正確），
       但擋下的方式是拋出未被接住的 ValueError —— 此後每一個 transition 都會噴
       traceback，Control Plane 等於被砸爛，而那筆污染已經永久留在 append-only log 裡。

    所以檢查必須發生在**寫入之前**，而且要涵蓋所有接受 change 參數的入口，
    不能只補 `start-change`。
    """
    if not isinstance(change,str) or not change:
        return 'change 名稱不得為空'
    if change in ('.','..'):
        return f'change 名稱不得為 {change!r}：它是路徑巡訪，不是 change'
    if change.casefold() == 'none':
        # `none` 是 `Active OpenSpec change` 的保留哨兵。允許它會產生一個
        # 自相矛盾的狀態：transition 成功、state-log 追加了一筆，但讀取語意
        # 認為「沒有 active change」，而 verify.sh 之後又會因為 change == none
        # 拒絕。那筆矛盾永久留在 append-only 的稽核紀錄裡。
        # 連 `None`／`NONE` 一起擋掉：對人類讀者而言它們無法區分。
        return 'change 名稱不得為 `none`：那是「沒有 active change」的保留字'
    if '/' in change or '\\' in change:
        return f'change 名稱不得包含路徑分隔符：{change!r}（必須是單一 path component）'
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in change):
        return 'change 名稱不得包含控制字元或換行（會注入 STATE.md 與 state-log 的逐行格式）'
    if not CHANGE_ID_RE.match(change):
        return (f'change 名稱不合法：{change!r}\n'
                '  允許的形狀：開頭為英數，其後為英數、`.`、`_`、`-`，長度上限 100。')
    return None


@dataclass(frozen=True)
class GitChange:
    status: str
    old_path: str | None
    new_path: str | None

    @property
    def paths(self):
        return tuple(p for p in (self.old_path,self.new_path) if p)


def parse_name_status_z(data:bytes)->list[GitChange]:
    """Parse `git diff --name-status -z` bytes without quotePath/tab ambiguity."""
    tokens=data.split(b'\0')
    if tokens and tokens[-1]==b'':
        tokens.pop()
    changes=[]
    i=0
    while i < len(tokens):
        status=tokens[i].decode('ascii','strict'); i+=1
        kind=status[0]
        if kind in {'R','C'}:
            if i+1 >= len(tokens): raise ValueError(f'incomplete git rename/copy record: {status}')
            old=tokens[i].decode('utf-8','surrogateescape'); new=tokens[i+1].decode('utf-8','surrogateescape'); i+=2
            changes.append(GitChange(kind,old,new))
        elif kind in {'A','M','D','T','U'}:
            if i >= len(tokens): raise ValueError(f'incomplete git change record: {status}')
            path=tokens[i].decode('utf-8','surrogateescape'); i+=1
            changes.append(GitChange(kind,path if kind=='D' else None,path if kind!='D' else None))
        else:
            raise ValueError(f'unsupported git status: {status}')
    return changes


def _git_name_status_z(root:Path,*args:str)->list[GitChange]:
    r=subprocess.run(['git','-C',str(root),*args,'--name-status','-M','-z'],capture_output=True)
    if r.returncode!=0:
        raise RuntimeError(r.stderr.decode('utf-8','replace').strip() or 'git diff failed')
    return parse_name_status_z(r.stdout)


def staged_changes(root:Path)->list[GitChange]:
    return _git_name_status_z(root,'diff','--cached')


def commit_parents(root:Path,commit:str)->list[str]:
    r=subprocess.run(['git','-C',str(root),'rev-list','--parents','-n','1',commit],capture_output=True,text=True)
    if r.returncode!=0:
        raise RuntimeError(r.stderr.strip() or f'cannot inspect {commit}')
    parts=r.stdout.strip().split()
    return parts[1:]


def commit_changes_against(root:Path,base:str,commit:str)->list[GitChange]:
    return _git_name_status_z(root,'diff',base,commit)


def commit_changes(root:Path,commit:str)->list[GitChange]:
    parents=commit_parents(root,commit)
    if parents:
        return commit_changes_against(root,parents[0],commit)
    r=subprocess.run(['git','-C',str(root),'diff-tree','--root','--no-commit-id','--name-status','-M','-z','-r',commit],capture_output=True)
    if r.returncode!=0:
        raise RuntimeError(r.stderr.decode('utf-8','replace').strip() or f'cannot diff {commit}')
    return parse_name_status_z(r.stdout)

def _path_object_id(root:Path,commit:str,path:str)->str|None:
    r=subprocess.run(['git','-C',str(root),'rev-parse',f'{commit}:{path}'],capture_output=True,text=True)
    return r.stdout.strip() if r.returncode==0 else None


def audit_commit_changes(root:Path,commit:str)->list[GitChange]:
    """For merges, return only mutations introduced by the merge itself, not content inherited unchanged from any parent."""
    parents=commit_parents(root,commit)
    if len(parents)<=1:
        return commit_changes(root,commit)
    candidates=commit_changes_against(root,parents[0],commit)
    introduced=[]
    for ch in candidates:
        paths=ch.paths
        result=tuple(_path_object_id(root,commit,p) for p in paths)
        inherited=False
        for parent in parents:
            parent_sig=tuple(_path_object_id(root,parent,p) for p in paths)
            if parent_sig==result:
                inherited=True
                break
        if not inherited:
            introduced.append(ch)
    return introduced


def _blob_bytes(root:Path,spec:str)->bytes|None:
    r=subprocess.run(['git','-C',str(root),'show',spec],capture_output=True)
    return r.stdout if r.returncode==0 else None


def installation_change_allowed(change:GitChange)->bool:
    return all(p in INSTALLATION_ALLOWED_ROOTS or p.startswith(INSTALLATION_ALLOWED_PREFIXES) for p in change.paths)

def installation_unexpected_changes(changes:list[GitChange])->list[GitChange]:
    return [c for c in changes if not installation_change_allowed(c)]

def staged_state_is_pristine(root:Path)->bool:
    raw=_blob_bytes(root,':workflow/STATE.md')
    if raw is None:return False
    try:text=raw.decode('utf-8')
    except UnicodeDecodeError:return False
    return state_hash_text(text)==initial_state_hash()

# --- Repository enforcement 診斷（R1）------------------------------------
# 本機 hook 是三層防護的第二層。ACTIVE 不代表不可繞過：`git commit --no-verify`、
# `HUSKY=0`、直接改 hook 都是本機 hook 的固有限制，須由政策禁止並由 CI audit /
# PR protection 補強。見 GATES.md。
MANAGED_HOOK_REL = '.githooks/pre-commit'
GATE_BRIDGE_COMMAND = 'bash .githooks/pre-commit'
PROBE_PATH = 'workflow/bin/__starter_enforcement_probe__.py'
# gate 拒絕 Control Plane 變更時的穩定訊號。probe 必須同時看到它與 probe 專用路徑，
# 否則「其他 checker 剛好提到 Control Plane」就會被誤判為串接成功。
GATE_DENY_MARKER = 'DENY: Control Plane 變更不可透過一般 commit'
ENFORCEMENT_ACTIVE_MANAGED = 'ACTIVE_MANAGED'
ENFORCEMENT_ACTIVE_CHAINED = 'ACTIVE_CHAINED'
ENFORCEMENT_CHAINED_STATIC = 'CHAINED_STATIC'
ENFORCEMENT_INACTIVE = 'INACTIVE'
ENFORCEMENT_UNKNOWN = 'UNKNOWN'


def effective_hooks_dir(root:Path):
    """讓 git 自己回答 hook 目錄；不推測 .git/hooks、core.hooksPath 或 worktree 規則。"""
    r = subprocess.run(
        ['git','-C',str(root),'rev-parse','--path-format=absolute','--git-path','hooks'],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = r.stdout.strip()
    return Path(out) if out else None


def effective_pre_commit_hook(root:Path):
    """回傳會被執行的 pre-commit hook 路徑，且**保留最終元件的 symlink 身分**。

    做法：只向 git 要 hook 目錄（`--git-path hooks`），檔名由我們自己追加。
    `--path-format=absolute` 會 canonicalize 目錄與其 ancestor（這正是我們要的：
    它能看穿 `/tmp` vs `/private/tmp`、ancestor symlink、大小寫別名），但因為
    `pre-commit` 是事後才 join 上去的，最終元件不會被 realpath 解析。

    不要改成 `--git-path hooks/pre-commit`：實測 Apple Git 2.50.1 下
    `--path-format=absolute` 必然解析最終 symlink，`--path-format=relative` 在
    相對 core.hooksPath 時也會解析；不加 `--path-format` 的預設格式在本次測試矩陣中
    保留字面名稱，但 git 文件只說預設格式是 option-specific，沒有給出契約保證。
    先取目錄再自行 join 不依賴任何未文件化的行為。
    """
    d = effective_hooks_dir(root)
    return None if d is None else d/'pre-commit'


def _index_mode(root:Path, rel:str):
    r = subprocess.run(['git','-C',str(root),'ls-files','-s','--',rel], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.split()[0]


def _head_mode(root:Path, rel:str):
    """rel 在 HEAD 裡的 file mode。

    **不要用 _index_mode 代替**：`git ls-files -s` 讀的是 index，而 index 是本機狀態。
    fresh clone 拿到的是 HEAD。只 `git add` 未 commit 的 hook、或本機
    `update-index --chmod=+x` 但 HEAD 仍是 100644 的 hook，index 都會回報 100755。
    """
    r = subprocess.run(['git','-C',str(root),'ls-tree','HEAD','--',rel], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.split()[0]


def _head_tree(root:Path):
    r = subprocess.run(['git','-C',str(root),'rev-parse','HEAD^{tree}'], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _bridge_present(text:str)->bool:
    """要求 bridge 指令出現在非註解行。

    這仍無法證明可達性：`if false; then bash .githooks/pre-commit; fi` 與
    `echo bash .githooks/pre-commit` 都會通過。因此靜態命中只得到 CHAINED_STATIC，
    必須經 `enforcement-status --probe` 實際執行並觀察 gate 拒絕，才能升級為 ACTIVE_CHAINED。
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if GATE_BRIDGE_COMMAND in line:
            return True
    return False



def _sha256_file(path:Path):
    h = hashlib.sha256()
    try:
        h.update(path.read_bytes())
    except OSError:
        return None
    return h.hexdigest()


def _path_is_inside_git_dir(root:Path, path:Path)->bool:
    """path 是否位於 .git 目錄（或 linked worktree 的 common dir）之內。"""
    for arg in ('--git-dir','--git-common-dir'):
        r = subprocess.run(['git','-C',str(root),'rev-parse','--path-format=absolute',arg],
                           capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            continue
        base = os.path.realpath(r.stdout.strip())
        try:
            if os.path.commonpath([base, os.path.realpath(str(path.parent))]) == base:
                return True
        except ValueError:
            continue
    return False


def _git_dir(root:Path):
    r = subprocess.run(['git','-C',str(root),'rev-parse','--path-format=absolute','--git-dir'],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def probe_receipt_path(root:Path):
    g = _git_dir(root)
    return (g/'starter-enforcement-probe.json') if g else None


def is_managed_hook(root:Path, hook:Path)->bool:
    """有效 hook 是否就是 Starter 管理的 .githooks/pre-commit。

    用**實體目錄同一性**，不用字串相等：`.GITHOOKS`（case-insensitive 檔案系統）或指向
    本 repository 的絕對 ancestor symlink 都會讓字串比對失手。
    """
    managed_dir = root/MANAGED_HOOK_REL.split('/')[0]
    try:
        return managed_dir.is_dir() and os.path.samefile(str(hook.parent), str(managed_dir))
    except OSError:
        return False


def worktree_tracked_digest(root:Path):
    """所有已追蹤路徑在 worktree 的**原始位元組**摘要（含 mode 與 symlink 目標）。

    不要用 `git add -u` + `write-tree`：`add` 會套用來源本機的 `filter.X.clean`，
    不同的實際內容可以被 clean 成同一個 blob、同一棵 tree。實測繞過：
    `filter.collapse.clean = cat <好的 wrapper>` 讓任何 wrapper 內容都被正規化成好的那份，
    於是把 wrapper 換成 `exit 0` 之後 tree sha 完全不變，receipt 續報有效。
    hook 執行的是磁碟上的位元組，所以這裡也只讀磁碟上的位元組。

    chained hook 可以呼叫 tree 中任何位置的 wrapper，要 fingerprint 的檔案集合無法事先
    枚舉，因此綁整片已追蹤內容。managed 不套用 —— 它的依賴鏈是封閉的（見 _probe_fingerprint）。
    """
    ls = subprocess.run(['git','-C',str(root),'ls-files','-z'], capture_output=True)
    if ls.returncode != 0:
        return None
    h = hashlib.sha256()
    for raw in ls.stdout.split(b'\0'):
        if not raw:
            continue
        h.update(raw+b'\0')
        q = root/os.fsdecode(raw)
        try:
            st = q.lstat()
        except OSError:
            h.update(b'<absent>\0'); continue          # 已追蹤但磁碟上不在了，也是一種改變
        if stat.S_ISLNK(st.st_mode):
            try: h.update(b'L'+os.readlink(str(q)).encode()+b'\0')
            except OSError: h.update(b'L<unreadable>\0')
        else:
            h.update(b'F'+oct(st.st_mode & 0o777).encode()+b'\0')
            try: h.update(hashlib.sha256(q.read_bytes()).hexdigest().encode()+b'\0')
            except OSError: h.update(b'<unreadable>\0')
    return h.hexdigest()


def gate_implementation_digest(root:Path):
    """整個 gate 實作（workflow/bin/** 與 .githooks/**）的合併 digest。

    只綁 hook 檔案不足夠：把 check-implementation-gate.py 改成 exit 0，hook 內容沒變，
    receipt 卻仍然有效 —— enforcement 已失效但系統回報正常。
    """
    h = hashlib.sha256()
    files = []
    for base in ('workflow/bin', '.githooks'):
        d = root/base
        if d.is_dir():
            files.extend(sorted(q for q in d.rglob('*') if q.is_file() and '__pycache__' not in q.parts))
    for q in files:
        try:
            h.update(str(q.relative_to(root)).encode()+b'\0'+q.read_bytes()+b'\0')
        except OSError:
            return None
    return h.hexdigest()


def _probe_fingerprint(root:Path, hook:Path):
    """receipt 綁定有效 hook 的路徑、內容 digest、mode、**整個 gate 實作**的 digest，
    以及 **HEAD 的 tree sha**。任一改變都會讓 receipt 失效，降回未驗證。

    綁整棵 HEAD tree 而不是只綁 workflow/bin 與 .githooks：chained hook 可以透過任意
    wrapper 間接呼叫 gate，那個 wrapper 可能在 tree 的任何位置。範圍縮小就留下藏身處。
    代價是任何 commit 都會讓 receipt 失效，這是刻意的 —— 新的 HEAD 就是沒有被驗證過的 HEAD。
    """
    try:
        mode = oct(hook.stat().st_mode & 0o777)
    except OSError:
        mode = None
    fp = {'hook': str(hook), 'hook_sha256': _sha256_file(hook), 'hook_mode': mode,
          'gate_impl_sha256': gate_implementation_digest(root),
          'head_tree': _head_tree(root)}
    if not is_managed_hook(root, hook):
        # chained：依賴鏈開放，只能綁整片已追蹤 worktree 內容。
        fp['worktree_tree'] = worktree_tracked_digest(root)
    return fp


def probe_enforcement(root:Path)->dict:
    """實際執行有效 hook 並期待 Starter gate 拒絕一個 Control Plane mutation。

    使用暫時的 GIT_INDEX_FILE，不碰真實 index 與 worktree。
    必須觀察到 gate 的特定拒絕訊號，不接受「hook 只是回傳非零」。

    副作用（刻意記載，不宣稱「沒有副作用」）：
    - `git hash-object -w` 會寫入 Git object database（內容固定，不會持續累積）
    - 寫入 `.git/starter-enforcement-probe.json`
    - 在 TMPDIR 建立暫時 index（用完刪除）
    - `.git` 唯讀時會失敗
    - **若有效 hook 已被修改**，probe 會真的執行它；把慢速或互動流程放在 gate 之前，
      最長會等到 120 秒 timeout
    """
    result = {'ok': False, 'reason': '', 'output': ''}
    hook = effective_pre_commit_hook(root)
    if hook is None or not hook.is_file():
        result['reason'] = '找不到有效的 pre-commit hook'; return result

    blob = subprocess.run(['git','-C',str(root),'hash-object','-w','--stdin'],
                          input='# starter enforcement probe\n', capture_output=True, text=True)
    if blob.returncode != 0:
        result['reason'] = f'無法建立 probe blob: {blob.stderr.strip()}'; return result

    tmp = None
    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix='starter-probe-index-')
        os.close(fd); os.unlink(tmp)
        env = dict(os.environ); env['GIT_INDEX_FILE'] = tmp
        rt = subprocess.run(['git','-C',str(root),'read-tree','HEAD'], env=env, capture_output=True, text=True)
        if rt.returncode != 0:
            result['reason'] = f'無法建立 probe index: {rt.stderr.strip()}'; return result
        probe_path = PROBE_PATH
        up = subprocess.run(['git','-C',str(root),'update-index','--add','--cacheinfo',
                             f'100644,{blob.stdout.strip()},{probe_path}'], env=env, capture_output=True, text=True)
        if up.returncode != 0:
            result['reason'] = f'無法在 probe index 建立 mutation: {up.stderr.strip()}'; return result
        # 直接執行，**不要**寫成 `bash <hook>`。git 是直接 exec hook 檔案，因此
        # shebang 與 executable bit 都算數：用 bash 代跑會讓 mode 644 的 hook 通過
        # probe（實測如此），也會讓 `#!/usr/bin/env python3` 這類 hook 被錯誤地當成
        # shell script 而假性失敗。probe 要驗的是 git 實際會做的事。
        try:
            run = subprocess.run([str(hook)], cwd=str(root), env=env,
                                 capture_output=True, text=True, timeout=120)
        except PermissionError:
            result['reason'] = 'hook 沒有執行權限；git 不會執行它'
            return result
        except OSError as exc:
            result['reason'] = f'無法執行 hook（shebang 無效或檔案不可執行）：{exc}'
            return result
        out = (run.stdout or '') + (run.stderr or '')
        result['output'] = out[-2000:]
        if run.returncode == 0:
            result['reason'] = 'hook 執行後回傳 0 —— Starter gate 沒有攔下 Control Plane mutation'
        elif GATE_DENY_MARKER not in out:
            result['reason'] = ('hook 回傳非零，但輸出沒有 Starter gate 的拒絕訊號'
                                f'（需要「{GATE_DENY_MARKER}」）；可能是其他檢查失敗，不能證明 gate 已串接')
        elif PROBE_PATH not in out:
            result['reason'] = ('輸出有 gate 的拒絕訊號，但沒有指名本次 probe 造出的路徑；'
                                '不能排除是其他 Control Plane 變更造成的拒絕')
        else:
            result['ok'] = True
    except subprocess.TimeoutExpired:
        result['reason'] = 'hook 執行逾時'
    except OSError as exc:
        result['reason'] = f'probe 失敗: {exc}'
    finally:
        if tmp and os.path.exists(tmp):
            try: os.unlink(tmp)
            except OSError: pass
    return result


def _materialize_head(root:Path, dest:Path):
    """在 dest 產生一個與**非遞迴 fresh clone 等價**的 repository，內容是來源的 HEAD。

    做法：`git bundle create <tmp> HEAD` → `git clone <tmp> dest`。

    為什麼是 bundle 而不是其他做法（每一種都踩過）：

    | 做法 | 為什麼不行 |
    |---|---|
    | 在來源 repo 跑 `checkout-index` | 套用來源 `.git/config` 的轉換。`.gitattributes` 進得了 clone，`filter.X.smudge` 與 `core.autocrlf` 這些本機設定進不了 —— 可用 smudge filter 把空轉 checker 洗成真 checker |
    | checkout 之後重新 `init/add/commit` | `git add` 加不進 `checkout-index` 為 gitlink 造的空目錄，mode `160000` 被靜默丟掉 |
    | `objects/info/alternates` 引用來源 ODB | 快照看得見來源的**全部** object，包含 unreachable 的；真正的 clone 只拿得到 HEAD 可達物件。實測 hook 寫成「某個 dangling object 存在才 exec 真 gate，否則 exit 0」，本機與快照都通過而 clone 空轉 |
    | `git clone` 直接複製本機路徑 | detached HEAD 指向的 commit 若不在任何 ref 上就取不到，而要驗的正是那棵 tree |

    bundle 同時滿足：只含 HEAD 可達物件、dest 用自己的 config checkout、gitlink 原封保留、
    HEAD 是 rev 而不是 ref（detached 且完全沒有 branch 也可以）。

    代價：bundle 會打包 HEAD 的完整歷史，大 repo 上不便宜。只在明確 `--probe` 時執行。

    submodule 界線：等價於**普通、未遞迴**的 clone，gitlink 保留為未初始化的空目錄。
    依賴 submodule 內容才生效的 gate 會在快照 probe 失敗而判 INACTIVE —— fail-closed。

    成功回傳 None，失敗回傳原因字串。
    """
    cm = subprocess.run(['git','-C',str(root),'rev-parse','HEAD^{commit}'],
                        capture_output=True, text=True)
    if cm.returncode != 0 or not cm.stdout.strip():
        return 'HEAD 不存在（repository 還沒有任何 commit）'
    commit = cm.stdout.strip()
    src_tree = _head_tree(root)
    if not src_tree:
        return '無法取得來源 HEAD 的 tree'
    import tempfile
    fd, bundle = tempfile.mkstemp(prefix='starter-head-', suffix='.bundle')
    os.close(fd)
    try:
        r = subprocess.run(['git','-C',str(root),'bundle','create','-q',bundle,'HEAD'],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return f'無法建立 HEAD bundle：{(r.stderr or r.stdout).strip()}'
        r = subprocess.run(['git','clone','-q',bundle,str(dest)], capture_output=True, text=True)
        if r.returncode != 0:
            return f'無法從 bundle clone：{(r.stderr or r.stdout).strip()}'
        err = _normalize_snapshot_metadata(root, dest)
        if err:
            return err
    except OSError as exc:
        return f'HEAD 快照建立失敗：{exc}'
    finally:
        if os.path.exists(bundle):
            try: os.unlink(bundle)
            except OSError: pass
    got_commit = subprocess.run(['git','-C',str(dest),'rev-parse','HEAD^{commit}'],
                                capture_output=True, text=True).stdout.strip()
    got_tree = _head_tree(dest)
    if got_commit != commit or got_tree != src_tree:
        # 後置條件，有明確的失敗模型：**TOCTOU**。上面先讀了來源的 HEAD commit/tree，
        # 之後才 `bundle create`；兩者之間若有另一個行程移動 HEAD（例如同時在跑的
        # commit、rebase、checkout），bundle 拿到的會是新的 HEAD，而我們據以判斷的是舊的。
        # 此時回報 ACTIVE 等於為一份根本沒被驗證過的 tree 背書。
        # 它同時也擋下「未來有人把 materialization 換回會產生 synthetic commit 的做法」。
        return (f'HEAD 快照與來源不一致（commit {got_commit} != {commit}，'
                f'tree {got_tree} != {src_tree}）；'
                'bundle 建立期間 HEAD 可能被其他行程移動，請重跑')
    return None


def _normalize_snapshot_metadata(root:Path, dest:Path):
    """把 bundle clone 留下的、真正 clone 不會有的 git metadata 抹平。

    **這是保真度，不是防禦層。** bundle clone 會留下兩個明顯的 tell：
    `remote.origin.url` 指向一個隨即被刪除的 `.bundle` 檔，以及 detached HEAD。
    實測 hook 只要寫「origin 為空或以 .bundle 結尾就執行 gate，否則 exit 0」，
    本機與快照都通過而真正的 transport clone 空轉。

    正規化能擋下這一類「意外或刻意的環境指紋」，也讓因為別的理由而讀 origin 的**誠實**
    hook 不會在快照裡假性失敗。但它擋不住有心偵測執行環境的 hook —— 見 GATES.md
    的〈HEAD 快照的能力邊界〉：本模組不宣稱快照與任意 fresh clone 的完整行為等價。
    """
    origin = subprocess.run(['git','-C',str(root),'config','--get','remote.origin.url'],
                            capture_output=True, text=True).stdout.strip()
    if not origin:
        origin = os.path.realpath(str(root))     # 來源沒有 origin 時，clone 它會得到這個路徑
    r = subprocess.run(['git','-C',str(dest),'remote','set-url','origin',origin],
                       capture_output=True, text=True)
    if r.returncode != 0:
        r = subprocess.run(['git','-C',str(dest),'remote','add','origin',origin],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return f'無法正規化快照的 origin：{(r.stderr or r.stdout).strip()}'
    # 來源在具名 branch 上時，快照也應該在同名 branch 上而不是 detached。
    br = subprocess.run(['git','-C',str(root),'symbolic-ref','--quiet','--short','HEAD'],
                        capture_output=True, text=True).stdout.strip()
    if br:
        b = subprocess.run(['git','-C',str(dest),'checkout','-q','-B',br],
                           capture_output=True, text=True)
        if b.returncode != 0:
            return f'無法正規化快照的 branch：{(b.stderr or b.stdout).strip()}'
    return None


def probe_head_enforcement(root:Path, hooks_dir_rel:str)->dict:
    """對 HEAD 實體化出來的快照跑同一套行為驗證。

    worktree probe 只證明「此刻本機有效」，但 fresh clone 拿到的是 HEAD。實測可重現的
    四種分歧，worktree probe 全部會通過而 clone 之後 gate 不存在或不生效：

    1. hook 只 `git add` 未 commit —— clone 沒有這個檔案。
    2. HEAD 的 mode 是 100644、本機 `update-index --chmod=+x` —— clone 拿到不可執行的檔案。
    3. HEAD 存空轉 hook、worktree 才是真 bridge —— clone 拿到空轉版。
    4. HEAD 的 check-implementation-gate.py 是空轉、worktree 才是真 checker ——
       hook 內容一致、gate_impl_sha256 也一致（它讀的是 worktree），clone 卻不會拒絕。

    這四種只靠比對路徑或 digest 都擋不完全（chained hook 可經任意 wrapper 間接呼叫 gate，
    要比對的檔案集合無法事先枚舉）。直接對 HEAD 快照執行一次，驗的是整條實際依賴鏈。
    """
    result = {'ok': False, 'reason': '', 'output': ''}
    import tempfile, shutil
    tmpdir = tempfile.mkdtemp(prefix='starter-head-snapshot-')
    dest = Path(tmpdir)/'snapshot'
    try:
        dest.mkdir(parents=True)
        err = _materialize_head(root, dest)
        if err:
            result['reason'] = err
            return result
        if hooks_dir_rel and hooks_dir_rel != '.':
            cfg = subprocess.run(['git','-C',str(dest),'config','core.hooksPath',hooks_dir_rel],
                                 capture_output=True, text=True)
            if cfg.returncode != 0:
                result['reason'] = f'無法在 HEAD 快照設定 core.hooksPath：{cfg.stderr.strip()}'
                return result
        inner = probe_enforcement(dest)
        result['ok'] = inner['ok']
        result['output'] = inner['output']
        result['reason'] = '' if inner['ok'] else f"HEAD 快照未攔下 Control Plane mutation：{inner['reason']}"
        return result
    except OSError as exc:
        result['reason'] = f'HEAD 快照驗證失敗：{exc}'
        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def probe_fingerprint(root:Path, hook:Path):
    """公開入口。呼叫端必須在 probe **開始之前**取得 F0，見 finalize_probe_receipt。"""
    return _probe_fingerprint(root, hook)


def invalidate_probe_receipt(root:Path)->None:
    """移除 receipt。狀態在 probe 期間變動時必須呼叫 —— 留著舊 receipt 會讓下一次
    `enforcement-status`（不加 --probe）繼續宣稱「行為驗證通過」。"""
    p = probe_receipt_path(root)
    if p is None: return
    try: p.unlink()
    except OSError: pass


def record_probe_receipt(root:Path, hook:Path, fingerprint=None)->bool:
    p = probe_receipt_path(root)
    if p is None: return False
    data = dict(fingerprint) if fingerprint is not None else _probe_fingerprint(root, hook)
    data['recorded_at'] = now_iso()
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except OSError:
        return False


def finalize_probe_receipt(root:Path, hook:Path, before:dict):
    """在 probe 全部通過之後寫 receipt，但**只替 `before` 這個狀態背書**。

    回傳 (ok, reason)。

    為什麼不能在 probe 之後重新採樣 fingerprint（原本的作法）：hook 是被實際執行的
    程式，它可以在被 probe 的過程中改變自己或改變 gate 實作。實測重現 —— 一個
    chained hook 先呼叫真 gate（於是兩層 probe 都通過），再用 `mv` 把自己換成
    `#!/bin/sh` + `exit 0`。舊流程在那之後才量 worktree，於是 receipt 記下的是空轉版
    的 hook_sha256，`probe_receipt_valid` 回 True，之後每次 doctor 都繼續宣稱
    「行為驗證通過於 …」，而 gate 已經不存在。

    （用 `printf > "$0"` 寫的版本不會重現：那會截斷 shell 正在讀的檔案，`exit` 那行
    讀不到，hook 回 0 而被 probe 判失敗。這是自我改寫腳本的 artifact，不是防禦。）

    所以不變式是：**receipt 綁定的必須是 probe 之前捕獲、而且整段 probe 期間沒有變過
    的狀態**。不需要 lock。

    能力邊界：若狀態在 probe 期間變成 B 又變回 A，F0 == F1 會成立，而 probe 實際跑的
    是 B。要關掉這個視窗需要 lock 或 kernel 級的變更通知，兩者都超出 Starter 的範圍。
    receipt 的宣稱因此是「這個 fingerprint 被 probe 過，且前後未變」，不是
    「probe 期間不存在其他狀態」。
    """
    after = _probe_fingerprint(root, hook)
    if after != before:
        invalidate_probe_receipt(root)
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        return False, ('probe 期間狀態發生變動，不能為它背書（變動欄位：'
                       + ', '.join(changed) + '）\n'
                       '  被驗證的狀態與現在磁碟上的狀態不同 —— hook 可能在執行過程中\n'
                       '  改寫了自己或 gate 實作。receipt 已作廢，請釐清原因後重跑。')
    if not record_probe_receipt(root, hook, fingerprint=before):
        return False, '行為驗證通過，但無法寫入 probe receipt'
    ok, why = probe_receipt_valid(root, hook)
    if not ok:
        # 寫完立刻以現況回驗。寫入本身也有時間，這一步把「寫入期間又變了」關掉。
        invalidate_probe_receipt(root)
        return False, f'receipt 寫入後立即回驗失敗：{why}'
    return True, ''


def probe_receipt_valid(root:Path, hook:Path):
    p = probe_receipt_path(root)
    if p is None or not p.exists(): return False, '尚未執行行為驗證'
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return False, 'probe receipt 無法解析'
    current = _probe_fingerprint(root, hook)
    if set(data) - {'recorded_at'} != set(current):
        return False, 'probe receipt 的欄位與現況不符（managed／chained 身分已改變）'
    for key in current:
        if data.get(key) != current[key]:
            return False, f'probe receipt 已失效（{key} 有變動）'
    return True, data.get('recorded_at','')

def repository_enforcement(root:Path)->dict:
    """回傳 Repository enforcement 的診斷結果。"""
    info = {'state': ENFORCEMENT_UNKNOWN, 'hook': None, 'executable': None,
            'index_mode': None, 'head_mode': None, 'hooks_dir_rel': None,
            'chained': None, 'reason': '', 'fix': '',
            'symlink': None, 'resolved': None}
    iw = subprocess.run(['git','-C',str(root),'rev-parse','--is-inside-work-tree'],
                        capture_output=True, text=True)
    # 必須檢查輸出，不能只看 return code：bare repository 會 exit 0 並印出 false，
    # 而 bare 沒有 worktree，本模組的 fresh-clone 不變式不適用。
    if iw.returncode != 0 or iw.stdout.strip() != 'true':
        info['state'] = ENFORCEMENT_INACTIVE
        info['reason'] = 'Git 尚未初始化，或此處不是 worktree（bare repository 不支援）'
        info['fix'] = '先執行 git init 或 bash workflow/bin/bootstrap.sh'
        return info

    hook = effective_pre_commit_hook(root)
    if hook is None:
        info['reason'] = '無法向 git 取得有效 pre-commit hook 路徑'
        return info
    info['hook'] = str(hook)

    if not hook.is_file():
        info['state'] = ENFORCEMENT_INACTIVE
        info['executable'] = False
        info['reason'] = f'有效 hook 不存在：{hook}'
        info['fix'] = '執行 bash workflow/bin/setup-git-hooks.sh'
        return info

    info['executable'] = os.access(hook, os.X_OK)
    info['symlink'] = hook.is_symlink()          # lstat：不跟隨最終元件
    if info['symlink']:
        try: info['resolved'] = str(hook.resolve())
        except OSError: info['resolved'] = '<無法解析>'

    # managed 身分用**實體目錄同一性**判斷，不用字串相等。
    # 字串相等會被同一個 .githooks 的別名繞過：case-insensitive 檔案系統上的
    # 「.GITHOOKS」、或指向本 repository 的絕對 ancestor symlink，都會讓 rel 不等於
    # '.githooks/pre-commit' 而落到 chained 分支，未追蹤的 symlink hook 於是 probe 通過。
    is_managed = is_managed_hook(root, hook)

    if is_managed:
        rel = MANAGED_HOOK_REL                    # 一律用 canonical 路徑查 index，不用別名
    else:
        # 非 managed：canonicalize parent（看穿 /tmp vs /private/tmp 與 ancestor symlink），
        # 最終元件保持字面。無法對應到 worktree 內的路徑時 rel 為 None，後續 fail-closed。
        try:
            rel = os.path.relpath(os.path.join(os.path.realpath(str(hook.parent)), hook.name),
                                  os.path.realpath(str(root)))
        except (OSError, ValueError):
            rel = None
        if rel is None or rel.startswith('..'):
            rel = None
    info['index_mode'] = _index_mode(root, rel) if rel else None
    info['head_mode'] = _head_mode(root, rel) if rel else None
    info['hooks_dir_rel'] = (os.path.dirname(rel) or '.') if rel else None

    # --- fresh-clone 不變式 -------------------------------------------------
    # Repository enforcement 的定義是「clone 之後 gate 仍然生效」。因此有效 hook
    # 必須是 worktree 內、已被 Git 追蹤、index mode 為 100755 的實體檔案。
    # 這一條對 managed 與 chained 一律適用 —— 只擋 managed 的話，
    # `core.hooksPath=.myhooks` + 未追蹤的 .myhooks/pre-commit（symlink 或普通檔）
    # 仍然是同一個「本機 ACTIVE、fresh clone INACTIVE」的繞過。
    if not info['executable']:
        info['state'] = ENFORCEMENT_INACTIVE
        info['reason'] = 'hook 沒有 executable bit；git 不會執行它'
        info['fix'] = f'chmod +x {rel or hook}'
        return info
    # 這是防禦層，不只是訊息。曾經誤判為死碼，反例：HEAD／index 存 mode 100755 的空轉
    # hook，worktree 把它換成指向「真的會拒絕」的 gate 的 symlink。tracked 與 mode 檢查
    # 都查 index，兩關都過；receipt 也擋不住，因為重新 probe 會產生一張綁定目前 symlink
    # 目標內容的新 receipt。移除本段實測會得到 ACTIVE_MANAGED，而 clone 拿到的是空轉版。
    # 註：HEAD 快照 probe 也涵蓋這個情境。兩層都保留 —— 不再宣稱任何一層不可達。
    if info['symlink']:
        info['state'] = ENFORCEMENT_INACTIVE
        info['reason'] = (f'有效 hook {rel or hook} 是 symlink（指向 {info["resolved"]}）；'
                          'clone 之後不保證存在或指向同一目標')
        info['fix'] = f'以實體檔案取代 symlink，並確認 index mode 為 100755'
        return info
    # .git/ 內的 hook 字面上位於 worktree 之下，但永遠不可能被追蹤 ——
    # 必須單獨辨識，否則會給出 `git add .git/hooks/pre-commit` 這種註定失敗的建議。
    if rel is None or _path_is_inside_git_dir(root, hook):
        info['state'] = ENFORCEMENT_INACTIVE
        info['reason'] = (f'有效 hook 位於 Git 目錄內（{hook}），不是版本控管的檔案；'
                          'clone 之後不會存在')
        info['fix'] = ('執行 bash workflow/bin/setup-git-hooks.sh —— 它會改用 '
                       f'core.hooksPath={MANAGED_HOOK_REL.split("/")[0]}，讓 hook 隨 repository 散佈')
        info['index_mode'] = None
        return info
    if info['index_mode'] is None and info['head_mode'] is None:
        info['state'] = ENFORCEMENT_INACTIVE
        info['reason'] = f'有效 hook {rel} 未被 Git 追蹤；clone 之後不會存在'
        info['fix'] = f'git add {rel} 並 commit，且確認 mode 為 100755'
        return info
    # 以下一律以 HEAD 為準，不以 index 為準。index 是本機狀態，攻擊者完全控制；
    # fresh clone 拿到的是 HEAD。「已 staged」不等於「clone 拿得到」。
    if info['head_mode'] is None:
        info['state'] = ENFORCEMENT_INACTIVE
        info['reason'] = (f'有效 hook {rel} 已 staged 但尚未 commit 進 HEAD；'
                          'clone 之後不會存在')
        info['fix'] = f'git commit -- {rel}'
        return info
    if info['head_mode'] != '100755':
        info['state'] = ENFORCEMENT_INACTIVE
        info['reason'] = f'HEAD 裡 hook 的 mode 是 {info["head_mode"]}，clone 之後不可執行'
        info['fix'] = f'git update-index --chmod=+x {rel} 之後 commit'
        return info
    # HEAD 過關代表「現在 clone 沒問題」；index 決定「下一次 commit 之後 clone 有沒有問題」。
    # 兩者都必須是 100755。已 staged 的移除或 mode 降級是一個正在生效中的迴歸，
    # 此時回報 ACTIVE 等於保證一件下一個 commit 就不成立的事。
    if info['index_mode'] != '100755':
        # 一層，兩種訊息 —— 不要拆成兩個 if 假裝是兩層防禦。
        info['state'] = ENFORCEMENT_INACTIVE
        if info['index_mode'] is None:
            info['reason'] = (f'有效 hook {rel} 在 HEAD 裡，但已被 staged 移除；'
                              '下一次 commit 之後 clone 不會有它')
            info['fix'] = f'git restore --staged {rel}'
        else:
            info['reason'] = (f'hook 的 git index mode 是 {info["index_mode"]}'
                              f'（HEAD 是 {info["head_mode"]}）；'
                              '下一次 commit 之後 clone 拿到的 hook 不可執行')
            info['fix'] = f'git update-index --chmod=+x {rel}'
        return info

    if is_managed:
        # managed hook 也必須經過行為驗證。tracked + 100755 + 內容一致都不足以證明它會拒絕 ——
        # 把 hook 或 check-implementation-gate.py 改成空轉並 commit，上述條件全部成立。
        receipt_ok, detail = probe_receipt_valid(root, hook)
        if receipt_ok:
            info['state'] = ENFORCEMENT_ACTIVE_MANAGED
            info['chained'] = True
            info['reason'] = f'行為驗證通過於 {detail}'
            return info
        info['state'] = ENFORCEMENT_CHAINED_STATIC
        info['chained'] = None
        info['reason'] = f'有效 hook 是 Starter 管理的 {MANAGED_HOOK_REL}，但{detail}'
        info['fix'] = 'bash workflow/bin/setup-git-hooks.sh --probe'
        return info

    try:
        text = hook.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        info['reason'] = f'無法讀取有效 hook：{exc}'
        return info

    # 行為驗證優先：receipt 有效就是 ACTIVE_CHAINED，不要求靜態字串命中。
    # 透過 wrapper／變數／framework dispatcher 間接呼叫 gate 的整合，靜態看不出來但 probe 驗得出。
    receipt_ok, detail = probe_receipt_valid(root, hook)
    if receipt_ok:
        info['state'] = ENFORCEMENT_ACTIVE_CHAINED
        info['chained'] = True
        info['reason'] = f'行為驗證通過於 {detail}'
        return info

    if _bridge_present(text):
        info['chained'] = True
        info['state'] = ENFORCEMENT_CHAINED_STATIC
        info['reason'] = f'靜態找到 bridge，但{detail}；靜態比對無法證明該行會被執行'
        info['fix'] = '執行 python3 workflow/bin/workflow_transition.py enforcement-status --probe'
        return info

    # 有自訂 hook 但既沒有靜態 bridge 也沒有通過的行為驗證 —— 無法確認，不得樂觀。
    info['state'] = ENFORCEMENT_UNKNOWN
    info['chained'] = False
    info['reason'] = f'有效 hook 是 {rel or hook}，但無法靜態確認是否串接 Starter gate'
    info['fix'] = ('若你以 wrapper 或 framework dispatcher 間接呼叫 gate，請執行 '
                   'python3 workflow/bin/workflow_transition.py enforcement-status --probe 進行行為驗證；'
                   f'否則請加入：{GATE_BRIDGE_COMMAND} || exit 1')
    return info




def enforcement_is_active(info:dict)->bool:
    """CHAINED_STATIC 刻意不算 active —— 靜態命中不是行為證明。"""
    return info['state'] in {ENFORCEMENT_ACTIVE_MANAGED, ENFORCEMENT_ACTIVE_CHAINED}


def installation_conflicts(root:Path)->list[GitChange]:
    """Tracked pre-existing Control Plane files changed in the working tree before Starter installation."""
    if subprocess.run(['git','-C',str(root),'rev-parse','--verify','HEAD'],capture_output=True).returncode!=0:
        return []
    changes=_git_name_status_z(root,'diff','HEAD')
    return [c for c in changes if c.status!='A' and change_touches_installation_control_plane(c)]

def installation_overwrites(root:Path)->list[GitChange]:
    """Tracked Starter-owned non-Control-Plane files that would be overwritten by Brownfield installation."""
    if subprocess.run(['git','-C',str(root),'rev-parse','--verify','HEAD'],capture_output=True).returncode!=0:
        return []
    changes=_git_name_status_z(root,'diff','HEAD')
    out=[]
    for c in changes:
        # Only existing tracked-file mutations can be overwrites. New Starter files are not conflicts.
        if c.status not in {'M','D','R'}:
            continue
        if not installation_change_allowed(c):
            continue
        if change_touches_installation_control_plane(c):
            continue
        out.append(c)
    return out

def installation_preflight(root:Path):
    """Single source of truth for Brownfield install preflight."""
    return installation_conflicts(root), installation_overwrites(root)

def installation_baseline(root:Path,changes:list[GitChange],source:str)->bool:
    """Sanctioned starter install: pristine STATE is newly added and all CP mutations are initial additions."""
    state_add=[c for c in changes if c.status=='A' and c.new_path=='workflow/STATE.md']
    if len(state_add)!=1: return False
    state_bytes=_blob_bytes(root,f':workflow/STATE.md' if source=='staged' else f'{source}:workflow/STATE.md')
    if state_bytes is None: return False
    try: state_text=state_bytes.decode('utf-8')
    except UnicodeDecodeError: return False
    if state_hash_text(state_text)!=initial_state_hash(): return False
    required={'workflow/STATE.md','workflow/bin/workflow_transition.py','.githooks/pre-commit'}
    added={c.new_path for c in changes if c.status=='A' and c.new_path}
    if not required.issubset(added): return False
    # Installation must not mutate or delete pre-existing Control Plane paths.
    phase=AUDIT_FAIL_CLOSED_PHASE
    for c in changes:
        if change_touches_control_plane(c,phase) and c.status!='A':
            return False
    return True


def change_touches_control_plane(change:GitChange,phase:str)->bool:
    return any(path_is_control_plane(p,phase) for p in change.paths)

def change_touches_installation_control_plane(change:GitChange)->bool:
    """Brownfield installation occurs with pristine DISCOVERY state; use that phase consistently."""
    return change_touches_control_plane(change,INSTALLATION_PHASE)


def control_plane_digest(root:Path,changes:list[GitChange],source:str='staged')->str:
    """Binary-safe digest of mutation type + old/new paths + resulting content."""
    h=hashlib.sha256()
    for ch in sorted(changes,key=lambda x:(x.status,x.old_path or '',x.new_path or '')):
        h.update(ch.status.encode()+b'\0')
        h.update((ch.old_path or '').encode('utf-8','surrogateescape')+b'\0')
        h.update((ch.new_path or '').encode('utf-8','surrogateescape')+b'\0')
        if ch.status=='D' or not ch.new_path:
            data=b'<deleted>'
        else:
            spec=f':{ch.new_path}' if source=='staged' else f'{source}:{ch.new_path}'
            r=subprocess.run(['git','-C',str(root),'show',spec],capture_output=True)
            data=r.stdout if r.returncode==0 else b'<missing>'
        h.update(data+b'\0')
    return h.hexdigest()

@dataclass
class WorkflowState:
    phase:str; project_mode:str; active_change:str; spec_approved:str; test_design_approved:str; verification_passed:str; approved_by:str; last_updated:str
    # 人類在 approve-spec 當下實際看到並批准的那份 profile 的 digest。
    # 預設 'none' 表示尚未批准，或這份 STATE 早於本欄位存在 —— 兩者都必須 fail-closed。
    profile_digest:str='none'
    @property
    def implementation_allowed(self):
        return self.phase=="ENGINEERING" and self.spec_approved=="yes" and self.test_design_approved=="yes"

def parse_state_text(text:str)->WorkflowState:
    values={}
    for key in REQUIRED_FIELDS:
        m=re.findall(rf"^{re.escape(key)}:[ \t]*(.*?)[ \t]*$",text,re.M)
        if len(m)!=1: raise ValueError(f"STATE 欄位缺失或重複: {key}")
        values[key]=m[0]
    if values["Phase"] not in VALID_PHASES: raise ValueError(f"非法 Phase: {values['Phase']}")
    if values["Project mode"] not in VALID_PROJECT_MODES: raise ValueError(f"非法 Project mode: {values['Project mode']}")
    for k in ("Spec approved","Test design approved","Verification passed"):
        if values[k] not in YESNO: raise ValueError(f"{k} 必須是 yes/no")
    # 讀取端也要驗。CLI 的驗證擋住新的污染，這一條擋住**已經在檔案裡**的污染 ——
    # 例如舊版寫入的 `..`，或有人繞過工具直接編輯。value 是 'none' 表示沒有綁定 change。
    if values["Active OpenSpec change"] != "none":
        err=validate_change_id(values["Active OpenSpec change"])
        if err: raise ValueError(f"STATE 的 Active OpenSpec change 不合法：{err}")
    # 刻意讀成可選：這個欄位是後加的。舊的 STATE.md 缺少它時要能被解析並回報
    # 'none'，由 start-engineering fail-closed 要求重新批准 —— 而不是讓工具在
    # 讀取階段就整個掛掉，把「schema 舊了」變成「Control Plane 壞了」。
    dg=re.findall(r"^Approved profile digest:[ \t]*(.*?)[ \t]*$",text,re.M)
    if len(dg)>1: raise ValueError("STATE 欄位重複: Approved profile digest")
    return WorkflowState(values["Phase"],values["Project mode"],values["Active OpenSpec change"],values["Spec approved"],values["Test design approved"],values["Verification passed"],values["Approved by"],values["Last updated"],dg[0] if dg else 'none')

def parse_state(path:Path)->WorkflowState:
    if not path.exists(): raise ValueError("workflow/STATE.md 不存在")
    return parse_state_text(path.read_text(encoding="utf-8"))

def render_state(s:WorkflowState)->str:
    return (
        "# Workflow State\n"
        "> 本檔是 Control Plane。不得手動編輯；請使用 `python3 workflow/bin/workflow_transition.py ...`。\n"
        "> `Implementation allowed` 為推導值，不儲存在 STATE：僅當 Phase=ENGINEERING 且 Spec/Test Design 均 approved 時為 true。\n\n"
        f"Phase: {s.phase}\nProject mode: {s.project_mode}\nActive OpenSpec change: {s.active_change}\n"
        f"Spec approved: {s.spec_approved}\nTest design approved: {s.test_design_approved}\nVerification passed: {s.verification_passed}\n"
        f"Approved by: {s.approved_by}\nApproved profile digest: {s.profile_digest}\nLast updated: {s.last_updated}\n"
    )

def write_state(path:Path,s:WorkflowState):
    tmp=path.with_suffix('.tmp'); tmp.write_text(render_state(s),encoding='utf-8'); tmp.replace(path)
def now_iso(): return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
def state_hash_text(text:str): return hashlib.sha256(text.replace('\r\n','\n').encode()).hexdigest()
def state_hash_path(path:Path): return state_hash_text(path.read_text(encoding='utf-8'))
def initial_state_hash():
    s=WorkflowState('DISCOVERY','UNSET','none','no','no','no','none','none')
    return state_hash_text(render_state(s))

def path_is_control_plane(rel:str,phase:str)->bool:
    if rel in CONTROL_PLANE_FILES or any(rel.startswith(p) for p in CONTROL_PLANE_PREFIXES): return True
    return rel in EARLY_MUTABLE_POLICY_FILES and phase not in {'DISCOVERY','SPECIFICATION'}

def path_is_ai_writable_non_product(rel:str,phase:str)->bool:
    if rel in AI_WRITABLE_ROOT or any(rel.startswith(p) for p in AI_WRITABLE_PREFIXES): return True
    if BROWSER_EVIDENCE_RE.match(rel): return True
    if rel=='PROJECT-PROFILE.md' and phase in {'DISCOVERY','SPECIFICATION'}: return True
    return False

# --- Core verification 政策與 check 規劃（R3）------------------------------
# 規則：預設情況下至少要實際執行一個具名、有 command 與 exit code 的 automated
# check，否則不得產生 PASS。不要求一定有 test —— lint / typecheck / build /
# 專案自訂 verifier 都算。見 GATES.md 的 Core verification policy。
VERIFICATION_POLICIES = {'auto', 'custom', 'not-applicable'}
CHECK_RUNNABLE = 'runnable'
CHECK_UNAVAILABLE = 'unavailable'


def _profile_field(root:Path, name:str):
    p = root/'PROJECT-PROFILE.md'
    if not p.exists():
        return None
    m = re.search(rf"^{re.escape(name)}:[ \t]*(.*?)[ \t]*$", p.read_text(encoding='utf-8'), re.M)
    return m.group(1).strip() if m else None


# 進 ENGINEERING 之前必須解析完成的 profile 欄位。判準是「會影響 Gate、驗證契約、
# 安全政策或工程行為」；純展示欄位不列入。
# 值的意義分三層，這是本設計的核心：未知／候選／已批准。UNKNOWN 可以進 review，
# 不能進 engineering；候選由 AI 在 ADR 提出，定案由 approve-spec 授權。
PROFILE_TYPES = ('WEB_APP','API','CLI','LIBRARY','MOBILE','OTHER')
PROFILE_WEB_REQUIRED = ('auto','yes','no')
PROFILE_MONOREPO = ('yes','no')
# 目標本身可被檢查的測試資料庫隔離策略。保留 `other: <描述>` 逃生口 —— Starter 不
# 可能列舉所有資料庫的隔離手法，強迫從清單裡選會逼人選錯，那比自由文字更糟。
# 但 `other:` 後面必須有非空描述：單獨一個 `other:` 是 UNKNOWN 換皮。
TESTDB_STRATEGIES = ('not-applicable','separate-database','transaction-rollback',
                     'ephemeral-container','schema-per-worker')

# 進 ENGINEERING 之前必須解析完成的 profile 欄位。判準是「會影響 Gate、驗證契約、
# 安全政策或工程行為」；純展示欄位不列入。
# 值的意義分三層，這是本設計的核心：未知／候選／已批准。UNKNOWN 可以進 review，
# 不能進 engineering；候選由 AI 在 ADR 提出，定案由 approve-spec 授權。
#
# 第三個元素是 allowed vocabulary（None 表示自由文字）。**沒有 vocabulary 檢查的
# 欄位會 fail-open**：實測 `Type: WEB_AP`（少一個字母）會被當成已解析，而
# project_web_status 因為它不等於 WEB_APP 判為 NON_WEB —— 一個 typo 就靜默關掉
# Browser Gate。`Primary stack` / `Package manager` / `CI provider` 沒有正式
# vocabulary，維持自由文字。
PROFILE_REQUIRED_FOR_ENGINEERING = (
    ('Type', ('UNKNOWN',), PROFILE_TYPES),
    ('Web verification required', ('auto',), PROFILE_WEB_REQUIRED),  # auto 在此欄位是「未決」
    ('Primary stack', ('UNKNOWN',), None),
    ('Package manager', ('UNKNOWN',), None),
    ('Monorepo', ('UNKNOWN',), PROFILE_MONOREPO),
    ('CI provider', ('UNKNOWN',), None),
    ('Test database strategy', ('UNKNOWN',), TESTDB_STRATEGIES),
)

# 有預設值、因此永遠「已解析」，但**會決定驗證契約**的欄位。它們不進 unresolved
# （`auto` 是合法的最終值，不是未決），但必須進 digest 也必須顯示在 TTY 上。
#
# 為什麼：`Core verification policy: not-applicable` + `Verification exception
# reason: skip automated checks` 可以在 SPECIFICATION 階段寫進去，七個必填欄位
# 全部通過，TTY 畫面宣稱列出「即將定案的 PROJECT-PROFILE」卻完全不提這件事，
# digest 也不涵蓋它。人類於是批准了一份看不到 verification waiver 的 profile，
# 之後 zero-check 的 NOT_APPLICABLE 就依這個從未被明示批准的政策通過。
PROFILE_POLICY_FIELDS = (
    ('Core verification policy', 'auto', tuple(sorted(VERIFICATION_POLICIES))),
    ('Custom verification command', 'none', None),
    ('Verification exception reason', 'none', None),
)


def _profile_value_error(name, value, allowed):
    """回傳該值不合法的理由，合法時回傳 None。"""
    if allowed is None:
        return None
    if name == 'Test database strategy' and value.startswith('other:'):
        return None if value[len('other:'):].strip() else (
            '`other:` 後面必須有非空描述；單獨的 `other:` 等於未決')
    if value in allowed:
        return None
    extra = '，或 `other: <描述>`' if name == 'Test database strategy' else ''
    return f'不是可辨識的值。允許：{"、".join(allowed)}{extra}'


def profile_resolution(root:Path):
    """回傳 (unresolved, invalid, resolved, digest)。

    為什麼不是「UNKNOWN → 具體值可由 machine-verified transition 完成」：那個方向對
    stack 不是單調收緊 —— Next.js / Rails / Django 之間沒有嚴格順序，而
    `Test database strategy: UNKNOWN → NOT_APPLICABLE` 其實是放寬。machine 只能證明
    格式與來源，不能授權「選擇」。因此定案必須由人類在 approve-spec 授權。

    `invalid` 必須跟 `unresolved` 分開回報：「你填了一個無法辨識的值」跟「你還沒填」
    是兩件不同的事，用同一句話會讓人以為自己沒存檔。
    """
    unresolved, invalid, resolved = [], [], {}
    h = hashlib.sha256()
    for name, undecided, allowed in PROFILE_REQUIRED_FOR_ENGINEERING:
        v = _profile_field(root, name)
        if v is None or not v or v in undecided:
            unresolved.append(name); continue
        why = _profile_value_error(name, v, allowed)
        if why:
            invalid.append((name, v, why)); continue
        resolved[name] = v
    for name, default, allowed in PROFILE_POLICY_FIELDS:
        v = _profile_field(root, name)
        if v is None or not v: v = default
        why = _profile_value_error(name, v, allowed)
        if why:
            invalid.append((name, v, why)); continue
        resolved[name] = v
    # digest 只在完全沒有問題時產生。有 invalid 卻仍給 digest 等於把一個爛值
    # 記進「已批准」的稽核紀錄。
    if unresolved or invalid:
        return unresolved, invalid, resolved, None
    for name in sorted(resolved):
        h.update(name.encode()+b'\0'+resolved[name].encode()+b'\0')
    return unresolved, invalid, resolved, h.hexdigest()


def approved_profile_status(root:Path, state):
    """**批准後每一項能力的單一共用判準。** 回傳 (ok, reason)。

    為什麼不能只在 `start-engineering` 檢查一次：那是關卡，不是不變式。實測兩個繞過 ——

    1. 已經在 ENGINEERING 的舊 STATE（沒有 `Approved profile digest` 欄位）解析後
       `profile_digest == 'none'`，但 `implementation_allowed` 仍為 True，產品 commit
       照樣放行。它永遠不會再碰到 start-engineering 的那次拒絕。
    2. 批准 `Core verification policy: auto` 之後進入 ENGINEERING，**只在 worktree**
       把它改成 `not-applicable`（不 stage），`verification-pass` 會產生一份
       `Checks executed: 0` / `Outcome: NOT_APPLICABLE` 的 evidence 並接受它；
       事後把檔案 restore 回去，git 看不到任何 profile mutation。
       fresh clone 拿到的是批准過的 `auto`，而 archived evidence 是依從未被批准的
       `not-applicable` 產生的。

    所以 `none` 的語意必須是「可解析，但不具備任何批准後權限」，而不是
    「下次 start-engineering 會擋」。
    """
    if getattr(state,'profile_digest','none')=='none':
        return False, ('STATE 沒有記錄批准時的 PROJECT-PROFILE digest。\n'
                       '  這份 STATE 早於該欄位存在，或批准流程未完成 —— 無法證明現在的\n'
                       '  profile 就是人類批准過的那一份。請重新執行 approve-spec。')
    unresolved, invalid, _, current = profile_resolution(root)
    if unresolved or invalid:
        return False, ('PROJECT-PROFILE.md 目前無法產生 digest'
                       f'（未解析：{unresolved or "無"}；非法值：'
                       f'{[n for n,_,_ in invalid] or "無"}）')
    if current is None or current != state.profile_digest:
        return False, ('PROJECT-PROFILE.md 與人類批准的內容不一致。\n'
                       f'  批准時 digest: {state.profile_digest[:16]}\n'
                       f'  目前 digest:   {(current or "（無法計算）")[:16]}\n'
                       '  profile 定案之後要改，必須回 SPECIFICATION 修訂 ADR/OpenSpec '
                       '並重新 review。')
    return True, ''


def implementation_authorized(root:Path, state):
    """實作授權 = STATE 的推導值 **且** profile 仍與批准內容相符。回傳 (ok, reason)。

    `implementation_allowed` 只看 phase 與兩個 approval flag，那是 STATE 內部的推導；
    它看不到 PROJECT-PROFILE 是否已經被換掉。pre-commit gate 必須用這一條。
    """
    if not state.implementation_allowed:
        return False, 'Derived Implementation allowed=no'
    return approved_profile_status(root, state)


PROVENANCE_INFO='INFO'
PROVENANCE_WARN='WARN'


def _user_claude_dir():
    return Path(os.path.expanduser('~'))/'.claude'


def effective_git_hooks_path(root:Path):
    """git 在**目前 process 環境下**回報的 core.hooksPath 與它的來源。

    不要只讀 .git/config：使用者全域 config、`GIT_CONFIG_*` 環境介面、
    以及任何跑過 `git config` 的 hook 都可能改變它。這裡問的是 git 自己。
    """
    v = subprocess.run(['git','-C',str(root),'config','--get','core.hooksPath'],
                       capture_output=True, text=True)
    if v.returncode != 0 or not v.stdout.strip():
        return None, None
    src = subprocess.run(['git','-C',str(root),'config','--show-origin','--get','core.hooksPath'],
                         capture_output=True, text=True)
    origin = src.stdout.split('\t')[0].strip() if src.returncode == 0 and '\t' in src.stdout else '<未知來源>'
    return v.stdout.strip(), origin


def agent_environment_provenance(root:Path)->dict:
    """列出**專案版控之外**、但會影響 agent 行為的指令來源。

    這是**可觀測性訊號，不是 enforcement**。它不改變 Repository enforcement 的
    ACTIVE/INACTIVE —— 那兩件事的權威來源不同：enforcement 問的是「clone 之後 gate
    還在不在」，provenance 問的是「這台機器上還有誰在對 agent 說話」。
    把後者混進前者，等於讓 Starter 對它無法驗證的東西下判斷。

    **本函式只做 filesystem inventory，不是完整的 effective runtime inventory。**
    看不到的來源列在回傳的 `unknowns`：managed policy、CLI `--settings`、
    session hooks、plugin 與 skill/agent frontmatter 帶的 hooks、MCP、subagents、
    以及執行中的 shell environment。

    輸出刻意**不含** hook command 本文、環境變數值與 skill 內容 ——
    那些可能含憑證與私人設定，doctor 的輸出常被貼進 issue 與聊天室。
    """
    items, level = [], None
    u = _user_claude_dir()

    def add(lv, kind, name, detail=''):
        nonlocal level
        items.append({'level': lv, 'kind': kind, 'name': name, 'detail': detail})
        if lv == PROVENANCE_WARN or level is None:
            level = lv if lv == PROVENANCE_WARN else (level or lv)

    for rel, kind in (('settings.json','使用者 settings'), ('CLAUDE.md','使用者指令'),
                      ('rules','使用者 rules'), ('hooks','使用者 hooks'),
                      ('skills','使用者 skills'), ('plugins','plugins')):
        q = u/rel
        if not q.exists():
            continue
        detail = ''
        if q.is_symlink():
            try: detail = f'symlink → {os.readlink(str(q))}'
            except OSError: detail = 'symlink → <無法解析>'
        elif q.is_dir():
            detail = f'{sum(1 for _ in q.iterdir())} 項'
        add(PROVENANCE_INFO, kind, rel, detail)

    # 同名 skill 碰撞是**結構上確定的覆蓋**，不是語意猜測：
    # 官方優先序是 managed > user > project，使用者版本會遮蔽專案版本。
    proj_skills = root/'.claude/skills'
    user_skills = u/'skills'
    if proj_skills.is_dir() and user_skills.is_dir():
        try:
            pn = {q.name for q in proj_skills.iterdir() if q.is_dir()}
            un = {q.name for q in user_skills.iterdir() if q.is_dir()}
            for name in sorted(pn & un):
                add(PROVENANCE_WARN, 'skill 覆蓋', name,
                    '使用者層級同名 skill 會遮蔽專案版本（優先序 managed > user > project）')
        except OSError:
            pass

    # 專案本地、未追蹤、但優先於共享 project settings
    if (root/'.claude/settings.local.json').exists():
        add(PROVENANCE_WARN, '未追蹤設定', '.claude/settings.local.json',
            '未進版控且優先於共享的 .claude/settings.json；clone 的人不會有它')

    hp, origin = effective_git_hooks_path(root)
    if hp is not None:
        managed = root/MANAGED_HOOK_REL.split('/')[0]
        try:
            is_ours = (root/hp).resolve() == managed.resolve()
        except OSError:
            is_ours = False
        if not is_ours:
            add(PROVENANCE_WARN, 'git hooksPath', hp, f'來源：{origin}')

    unknowns = ['managed policy 與 CLI --settings', 'session hooks',
                'plugin 與 skill/agent frontmatter 帶的 hooks',
                'MCP server 與 subagent 的名稱碰撞', '執行中的 shell environment']
    return {'level': level or PROVENANCE_INFO if items else None,
            'items': items, 'unknowns': unknowns}


def verification_policy(root:Path)->dict:
    """回傳 core verification 政策。未指定時預設 auto（向後相容）。"""
    raw = _profile_field(root, 'Core verification policy') or 'auto'
    policy = raw if raw in VERIFICATION_POLICIES else 'invalid'
    custom = _profile_field(root, 'Custom verification command') or 'none'
    reason = _profile_field(root, 'Verification exception reason') or 'none'
    return {'policy': policy, 'raw': raw,
            'custom_command': '' if custom.lower() == 'none' else custom,
            'exception_reason': '' if reason.lower() == 'none' else reason}


def _resolve_python_runner(root:Path, tool:str):
    """依序尋找已啟用環境與專案 .venv。回傳可執行的指令字串或 None。

    刻意不自動採用 `uv run` / `poetry run`：這兩者存在不代表工具已安裝在該環境，
    實測會誤判為 runnable、執行時才失敗，並在使用者專案產生非預期的 .venv。
    找不到時回報 unavailable 並在訊息中建議這些做法，由人類決定。
    """
    if shutil.which(tool):
        return tool
    for candidate in (root/'.venv'/'bin'/tool, root/'venv'/'bin'/tool):
        if candidate.exists() and os.access(candidate, os.X_OK):
            return f'./{candidate.relative_to(root)}'
    return None


def _node_scripts(root:Path)->dict:
    """以 Python 解析 package.json，不因 node 不在 PATH 就假裝 scripts 不存在。"""
    p = root/'package.json'
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {}
    scripts = data.get('scripts')
    return scripts if isinstance(scripts, dict) else {}


def _node_package_manager(root:Path):
    """回傳 (pm, reason)。lockfile 指定的 package manager 不可用時不得靜默退回 npm ——
    那會用錯的工具跑測試，或掩蓋「環境缺工具」這件事。"""
    for lock, pm in (('pnpm-lock.yaml','pnpm'), ('yarn.lock','yarn'), ('bun.lockb','bun'), ('bun.lock','bun')):
        if (root/lock).exists():
            if shutil.which(pm):
                return pm, ''
            return None, f'{lock} 指定使用 {pm}，但目前環境找不到 {pm}'
    if shutil.which('npm'):
        return 'npm', ''
    return None, 'package.json 存在，但目前環境找不到 npm'


def _python_tool_configured(root:Path, tool:str)->bool:
    pyproject = root/'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8', errors='replace') if pyproject.exists() else ''
    if f'[tool.{tool}' in text:
        return True
    for name in (f'{tool}.ini', f'.{tool}.ini', f'{tool}.toml', f'.{tool}.toml'):
        if (root/name).exists():
            return True
    if tool in ('mypy','ruff'):
        cfg = root/'setup.cfg'
        if cfg.exists() and f'[{tool}' in cfg.read_text(encoding='utf-8', errors='replace'):
            return True
    if tool == 'pytest':
        # tests/ 只證明「有測試」，不證明「用 pytest」——unittest / doctest 專案會被誤判，
        # 進而回報不存在的 configured-but-unavailable。必須有明確的 pytest 依據。
        for name, section in (('pytest.ini','[pytest'), ('tox.ini','[pytest'), ('setup.cfg','[tool:pytest')):
            f = root/name
            if f.exists() and section in f.read_text(encoding='utf-8', errors='replace'):
                return True
        if 'pytest' in text:   # pyproject 的 dependencies / optional-dependencies
            return True
        for lock in ('requirements.txt','requirements-dev.txt','poetry.lock','uv.lock'):
            f = root/lock
            if f.exists() and 'pytest' in f.read_text(encoding='utf-8', errors='replace'):
                return True
    return False


def plan_checks(root:Path, mode:str='full')->list:
    """回傳 check 計畫：[{name, command, status, reason}]。

    status=runnable    → 可執行
    status=unavailable → 已配置但 runner 不可用；呼叫端必須失敗，不得當作沒有這個檢查
    """
    plan = []
    scripts = _node_scripts(root)
    if scripts:
        pm, pm_reason = _node_package_manager(root)
        wanted = [('lint','lint'), ('typecheck','typecheck'), ('test','test')]
        if mode == 'full':
            wanted.append(('build','build'))
            for cand in ('test:e2e','e2e','playwright'):
                if cand in scripts:
                    wanted.append(('e2e', cand)); break
        for name, script in wanted:
            if script not in scripts:
                continue
            if pm is None:
                plan.append({'name': name, 'command': f'<package manager> run {script}',
                             'status': CHECK_UNAVAILABLE,
                             'reason': f'package.json 已定義 {script} script，但{pm_reason}'})
            else:
                run = 'test' if (pm == 'npm' and script == 'test') else f'run {script}'
                plan.append({'name': name, 'command': f'{pm} {run}', 'status': CHECK_RUNNABLE, 'reason': ''})

    python_markers = ('pyproject.toml','requirements.txt','requirements-dev.txt','setup.py',
                      'setup.cfg','pytest.ini','tox.ini','ruff.toml','.ruff.toml','mypy.ini','.mypy.ini')
    if any((root/m).exists() for m in python_markers):
        wanted = [('ruff','ruff','ruff check .'), ('pytest','pytest','pytest')]
        if mode == 'full':
            wanted.append(('mypy','mypy','mypy .'))
        for name, tool, argline in wanted:
            if not _python_tool_configured(root, tool):
                continue
            runner = _resolve_python_runner(root, tool)
            if runner is None:
                plan.append({'name': name, 'command': argline, 'status': CHECK_UNAVAILABLE,
                             'reason': f'{tool} 已在專案中配置，但 PATH 與 ./.venv/bin 都找不到可執行檔；請啟用虛擬環境，或改用 uv run / poetry run 並在 PROJECT-PROFILE 設定 Core verification policy: custom'})
            else:
                rest = argline.split(' ', 1)[1] if ' ' in argline else ''
                plan.append({'name': name, 'command': f'{runner} {rest}'.strip(),
                             'status': CHECK_RUNNABLE, 'reason': ''})
    return plan


def project_web_status(root:Path)->str:
    p=root/'PROJECT-PROFILE.md'
    if not p.exists(): return 'UNRESOLVED'
    text=p.read_text(encoding='utf-8')
    def field(name):
        m=re.search(rf"^{re.escape(name)}:[ \t]*(.*?)[ \t]*$",text,re.M); return m.group(1).strip() if m else None
    typ,req=field('Type'),field('Web verification required')
    if typ is None or req is None:return 'UNRESOLVED'
    # 無法辨識的 Type 一律 fail-closed。這是決定 Browser Gate 開關的那一層，
    # 不能因為值「不等於 WEB_APP」就推論它是非 Web —— `WEB_AP` 也不等於 WEB_APP。
    # 'UNKNOWN' 保持原語意（明確的未決），不併入這條。
    if typ not in PROFILE_TYPES and typ!='UNKNOWN':return 'UNRESOLVED'
    if req not in PROFILE_WEB_REQUIRED:return 'UNRESOLVED'
    if req=='yes':return 'WEB'
    if req=='no':return 'WEB' if typ=='WEB_APP' else 'NON_WEB'
    if req!='auto':return 'UNRESOLVED'
    if typ=='WEB_APP':return 'WEB'
    return 'UNRESOLVED'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--is-web',action='store_true');ap.add_argument('--state-hash')
    ap.add_argument('--verification-plan',choices=['full','pre-commit'])
    ap.add_argument('--verification-policy',action='store_true');a=ap.parse_args()
    root=Path(__file__).resolve().parents[2]
    if a.verification_policy:
        info=verification_policy(root)
        print(f"{info['policy']}\t{info['custom_command']}\t{info['exception_reason']}")
        raise SystemExit(0 if info['policy']!='invalid' else 2)
    if a.verification_plan:
        for c in plan_checks(root,a.verification_plan):
            print(f"{c['status']}\t{c['name']}\t{c['command']}\t{c['reason']}")
        raise SystemExit(0)
    if a.is_web:
        s=project_web_status(Path(__file__).resolve().parents[2]);print(s);raise SystemExit({'WEB':0,'NON_WEB':1,'UNRESOLVED':2}[s])
    if a.state_hash:print(state_hash_path(Path(a.state_hash)))
if __name__=='__main__':main()
