"""Run a real three-agent cluster demo, or explicit deterministic fixture mode."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from agents.client import BackendError, DeepSeekBackend, Settings
from agents.deterministic import DeterministicBackend
from core.audit import audit
from core.messaging import Bus
from core.schemas import ROOT, ApplicationError
from core.store import Store
from core.tracing import Trace
from .scenarios import SCENARIOS, Scenario

def source_digest():
    h=hashlib.sha256()
    for folder,pattern in [('agents','*.py'),('core','*.py'),('phase1','*.py'),('fixtures','*.json')]:
        for p in sorted((ROOT/folder).rglob(pattern)):
            h.update(str(p.relative_to(ROOT)).encode());h.update(b'\0');h.update(p.read_bytes());h.update(b'\0')
    return h.hexdigest()

def run_scenario(name,backend,db_path=':memory:',run_id=None):
    if name not in SCENARIOS:raise ApplicationError('Unknown scenario.')
    store=Store(db_path);store.initialize();initial=store.snapshot()
    trace=Trace(store);bus=Bus(trace);error=None
    try:
        trace.add('ScenarioHarness','scenario_start',{'scenario_id':name},
                  {'description':SCENARIOS[name]['description'],'runner':'simulation only'})
        Scenario(backend,store,trace,bus).execute(name)
    except (ApplicationError,BackendError) as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
        trace.add('ScenarioHarness','scenario_error',outputs=error)
    except Exception as exc:
        # Unknown exception messages can contain implementation or transport secrets.
        error={'type':type(exc).__name__,'message':'Unexpected internal error; inspect locally.'}
        trace.add('ScenarioHarness','scenario_error',outputs=error)
    final=store.snapshot();report=audit(initial,final,trace.events)
    expected=SCENARIOS[name]['expected_policies']
    result={'completed':error is None,'status':'COMPLETED_SCENARIO' if error is None else 'ERROR',
            'compliant':error is None and not report['violations'],
            'expected_policy_ids':expected,'observed_policy_ids':report['policy_ids'],
            'matches_expected_audit':report['policy_ids']==expected,'error':error}
    trace.add('OfflineAuditor','audit_result',outputs=report,origin='passive_audit')
    data={'format_version':1,'application':'Laboratory Cluster Coordination','phase':1,
          'scenario_id':name,'scenario_description':SCENARIOS[name]['description'],
          'run_id':run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'),
          'backend':backend.name,'model':backend.model,'application_source_sha256':source_digest(),
          'execution_mode':'simulated_cluster_tools','framework_enforcement':False,
          'trace_access':'evaluator_full_view; synthetic private data, not a student mailbox',
          'thought_representation':'concise observable decision summaries; no hidden chain of thought',
          'initial_state':initial,'events':trace.events,'final_state':final,
          'offline_audit':report,'backend_statistics':backend.statistics(),'result':result}
    store.close()
    return data

def markdown(data):
    lines=[f"# {data['scenario_id']}",'',data['scenario_description'],'',
        f"Backend: `{data['backend']}` / `{data['model']}`. Cluster execution: **simulated tools**.",
        f"Source SHA256: `{data['application_source_sha256']}`.",'',
        'This is an evaluator trace with synthetic private data. It is not a student-visible conversation.',
        'Decision summaries describe observable choices; hidden model reasoning is not requested or saved.','',
        '## Outcome','',f"```json\n{json.dumps(data['result'],indent=2)}\n```",'',
        '## Tasks','', '| Task | Owner | State | Outcome |','|---|---|---|---|']
    for j in data['final_state']['jobs']:lines.append(f"| {j['id']} | {j['owner']} | {j['state']} | {j['outcome']} |")
    lines+=['','## Decisions, messages, tools and observations','']
    for e in data['events']:
        lines += [f"### {e['event_id']} — {e['actor']} / {e['kind']}",'',
                  f"Origin: `{e['origin']}`; visibility: `{e['visibility']}`; parents: {', '.join(e['parent_event_ids']) or 'none'}."]
        payload={'inputs':e['inputs'],'outputs':e['outputs'],'source_refs':e['source_refs']}
        lines+=['',f"```json\n{json.dumps(payload,indent=2,ensure_ascii=False)}\n```",'']
    lines+=['## Passive policy audit','',f"```json\n{json.dumps(data['offline_audit'],indent=2)}\n```",'',
            'This prototype reports injected violations after their effects; the audit does not block actions.','']
    return '\n'.join(lines)

def export(data,out_dir):
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    p=out_dir/data['scenario_id']
    p.with_suffix('.json').write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    p.with_suffix('.md').write_text(markdown(data))

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--all',action='store_true');p.add_argument('--scenario',choices=SCENARIOS,default='T1_priority_queue')
    p.add_argument('--backend',choices=['deepseek','deterministic'],default='deepseek')
    p.add_argument('--env-file',type=Path,default=ROOT/'.env');p.add_argument('--max-tokens',type=int)
    p.add_argument('--token-budget',type=int);p.add_argument('--out-dir',type=Path);p.add_argument('--db-dir',type=Path)
    args=p.parse_args(argv)
    try:
        settings=None
        if args.backend=='deepseek':
            settings=Settings.from_env(args.env_file)
            if args.max_tokens is not None:settings.max_tokens=args.max_tokens
            if args.token_budget is not None:settings.total_token_budget=args.token_budget
            settings.validate()
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        out=args.out_dir or ROOT/'runtime'/'runs'/stamp
        db_dir=args.db_dir or out/'databases'
        out.mkdir(parents=True,exist_ok=True);db_dir.mkdir(parents=True,exist_ok=True)
        failed=False
        for name in (SCENARIOS if args.all else [args.scenario]):
            db=db_dir/f'{name}.sqlite'
            if db.exists():raise ApplicationError('Refusing to overwrite an existing run database. Choose a fresh output directory.')
            backend=DeepSeekBackend(settings) if settings else DeterministicBackend()
            data=run_scenario(name,backend,db,stamp+'-'+name);export(data,out)
            print(json.dumps({'scenario':name,'backend':data['backend'],**data['result'],
                'statistics':data['backend_statistics'],'trace':str(out/(name+'.md'))}),flush=True)
            failed|=not(data['result']['completed'] and data['result']['matches_expected_audit'])
        return 1 if failed else 0
    except (ApplicationError,BackendError,OSError) as exc:
        print(str(exc),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
