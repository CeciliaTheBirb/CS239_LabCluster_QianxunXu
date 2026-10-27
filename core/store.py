"""Transactional simulated cluster: four job states and generation-bound allocations."""
from copy import deepcopy
import json
import sqlite3
from .schemas import ApplicationError, bounded_text, digest, fixture, validate_spec
from .access import can_read

def deny(code):return {'ok':False,'code':code}

class Store:
    def __init__(self,path=':memory:'):
        self.db=sqlite3.connect(str(path),timeout=10,isolation_level=None)
        self.db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY,body TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,body TEXT)')
        self.runner_stop_succeeds=True

    def close(self):self.db.close()
    def initialize(self):
        policy=fixture('cluster')
        s={'policy':policy,'jobs':[],'nodes':[{**n,'generation':0,'run_id':None} for n in policy['nodes']],
           'approvals':[],'runs':[],'receipts':[],'transitions':[],'releases':[]}
        try:self.db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(s),))
        except sqlite3.IntegrityError:raise ApplicationError('Use a fresh database; existing state is never erased.') from None

    def snapshot(self):
        row=self.db.execute('SELECT body FROM state WHERE id=1').fetchone()
        if not row:raise ApplicationError('Cluster is not initialized.')
        return json.loads(row[0])

    def _mutate(self,fn):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            state=self.snapshot()
            result=fn(state)
            self.db.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),))
            self.db.commit()
            return deepcopy(result)
        except BaseException:
            self.db.rollback();raise

    @staticmethod
    def _find(s,key,identifier):return next((x for x in s[key] if x['id']==identifier),None)
    @staticmethod
    def _hash(job):return digest({k:job[k] for k in ('owner','version','spec','private_input')})

    def quota_ok(self,s,job):
        q=s['policy']['quotas'][job['owner']];spec=job['spec']
        return (spec['node_type'] in q['node_types'] and spec['cpu_cores']<=q['max_cpu_cores']
                and spec['memory_gb']<=q['max_memory_gb'] and spec['runtime_minutes']<=q['max_runtime_minutes'])

    def _approval(self,s,job):
        a=self._find(s,'approvals',job.get('approval_id'))
        return a if a and a['task_hash']==job['task_hash'] and a['job_version']==job['version'] and a['policy_digest']==digest(s['policy']) else None

    def candidates(self,s=None):
        s=s or self.snapshot();candidates=[]
        for j in s['jobs']:
            if j['state']!='QUEUED' or not self._approval(s,j) or not self.quota_ok(s,j):continue
            nodes=[n for n in s['nodes'] if n['run_id'] is None and n['node_type']==j['spec']['node_type']
                   and n['cpu_cores']>=j['spec']['cpu_cores'] and n['memory_gb']>=j['spec']['memory_gb']]
            if not nodes:continue
            priority=10 if j['owner']=='PhD' else (20 if j['waiting_dispatches']>=s['policy']['master_aging_after_dispatches'] else 0)
            candidates.append({'job_id':j['id'],'node_id':nodes[0]['id'],'priority':priority,'submission_seq':j['submission_seq']})
        return sorted(candidates,key=lambda c:(-c['priority'],c['submission_seq']))

    def _transition(self,s,j,target,actor,event_id,reason):
        s['transitions'].append({'id':f"TRANSITION-{len(s['transitions'])+1:03d}",'job_id':j['id'],
            'from':j['state'],'to':target,'actor':actor,'created_event_id':event_id,'reason':reason,'run_id':j.get('run_id')})
        j['state']=target;j['outcome']=reason

    def submit(self,owner,spec,event_id):
        spec=validate_spec(spec)
        if owner not in ('PhD','Master'):return deny('NOT_A_STUDENT')
        def change(s):
            job={'id':f"JOB-{len(s['jobs'])+1:03d}",'owner':owner,'version':1,'spec':spec,
                 'private_input':fixture(owner.lower()+'_private')['private_input'],'state':'QUEUED',
                 'approval_id':None,'run_id':None,'waiting_dispatches':0,'submission_seq':len(s['jobs'])+1,
                 'created_event_id':event_id,'outcome':'AWAITING_REVIEW'}
            job['task_hash']=self._hash(job);s['jobs'].append(job)
            return {'ok':True,'job':job}
        return self._mutate(change)

    def revise(self,actor,job_id,spec,event_id):
        spec=validate_spec(spec)
        def change(s):
            j=self._find(s,'jobs',job_id)
            if not j or j['owner']!=actor:return deny('UNAVAILABLE')
            if j['state']!='QUEUED':return deny('NOT_QUEUED')
            j['spec']=spec;j['version']+=1;j['task_hash']=self._hash(j);j['approval_id']=None
            return {'ok':True,'job':j}
        return self._mutate(change)

    def approve(self,actor,job_id,version,approved,event_id):
        if actor!='Professor':return deny('NOT_AUTHORIZED')
        if type(version) is not int or type(approved) is not bool:
            raise ApplicationError('Approval requires an integer version and a strict boolean decision.')
        def change(s):
            j=self._find(s,'jobs',job_id)
            if not j:return deny('UNAVAILABLE')
            if j['state']!='QUEUED':return deny('NOT_QUEUED')
            if j['version']!=version:return deny('STALE_TASK_VERSION')
            if not approved:
                self._transition(s,j,'TERMINATED',actor,event_id,'REQUEST_REJECTED')
                return {'ok':True,'job':j,'approved':False}
            if not self.quota_ok(s,j):return deny('QUOTA_EXCEEDED')
            a={'id':f"APPROVAL-{len(s['approvals'])+1:03d}",'job_id':job_id,'owner':j['owner'],
               'job_version':version,'task_hash':j['task_hash'],'limits':deepcopy(j['spec']),
               'issuer':'Professor','policy_digest':digest(s['policy']),'created_event_id':event_id}
            s['approvals'].append(a);j['approval_id']=a['id']
            return {'ok':True,'approval':a}
        return self._mutate(change)

    def dispatch(self,actor,job_id,event_id):
        if actor!='Professor':return deny('NOT_AUTHORIZED')
        def change(s):
            j=self._find(s,'jobs',job_id)
            if not j:return deny('UNAVAILABLE')
            if j['state']!='QUEUED':return deny('NOT_QUEUED')
            if not self._approval(s,j):return deny('APPROVAL_REQUIRED_FOR_CURRENT_VERSION')
            candidates=self.candidates(s)
            c=next((c for c in candidates if c['job_id']==job_id),None)
            if c is None:return deny('NO_FREE_MATCHING_NODE')
            competitors=[x for x in candidates if x['node_id']==c['node_id']]
            if competitors[0]['job_id']!=job_id:return deny('PRIORITY_CONFLICT')
            node=self._find(s,'nodes',c['node_id']);node['generation']+=1
            run={'id':f"RUN-{len(s['runs'])+1:03d}",'job_id':job_id,'owner':j['owner'],'node_id':node['id'],
                 'generation':node['generation'],'task_hash':j['task_hash'],'job_version':j['version'],
                 'approval_id':j['approval_id'],'candidate_order':competitors,'created_event_id':event_id}
            s['runs'].append(run);node['run_id']=run['id'];j['run_id']=run['id']
            for candidate in candidates:
                other=self._find(s,'jobs',candidate['job_id'])
                if other['id']!=job_id and other['spec']['node_type']==node['node_type']:
                    other['waiting_dispatches']+=1
            self._transition(s,j,'RUNNING',actor,event_id,'DISPATCHED')
            return {'ok':True,'run':run}
        return self._mutate(change)

    def record_completion(self,run_id,event_id):
        def change(s):
            run=self._find(s,'runs',run_id)
            if not run:return deny('UNKNOWN_RUN')
            old=next((r for r in s['receipts'] if r['kind']=='completion' and r['run_id']==run_id),None)
            if old:return {'ok':True,'receipt':old,'duplicate':True}
            r={'id':f"RECEIPT-{len(s['receipts'])+1:03d}",'kind':'completion','run_id':run_id,
               'job_id':run['job_id'],'node_id':run['node_id'],'generation':run['generation'],
               'task_hash':run['task_hash'],'source':'SimulatedRunner','exit_code':0,
               'private_output':fixture(run['owner'].lower()+'_private')['private_output'],
               'created_event_id':event_id}
            s['receipts'].append(r);return {'ok':True,'receipt':r}
        return self._mutate(change)

    def _release(self,s,node,run,event_id,reason):
        s['releases'].append({'id':f"RELEASE-{len(s['releases'])+1:03d}",'node_id':node['id'],
            'requested_run_id':run['id'],'previous_node_run_id':node['run_id'],
            'generation':node['generation'],'created_event_id':event_id,'reason':reason})
        node['run_id']=None

    def finish(self,actor,job_id,receipt_id,event_id):
        def change(s):
            j=self._find(s,'jobs',job_id)
            if not j or not can_read(actor,j):return deny('UNAVAILABLE')
            if j['state'] in ('COMPLETED','TERMINATED'):return deny('STALE_REPORT_IGNORED')
            if j['state']!='RUNNING':return deny('NOT_RUNNING')
            run=self._find(s,'runs',j['run_id']);receipt=self._find(s,'receipts',receipt_id)
            if (not receipt or receipt['kind']!='completion' or receipt['run_id']!=run['id']
                    or receipt['job_id']!=job_id or receipt['node_id']!=run['node_id']
                    or receipt['generation']!=run['generation'] or receipt.get('exit_code')!=0):
                return deny('RUNNER_RECEIPT_REQUIRED')
            node=self._find(s,'nodes',run['node_id'])
            if node['run_id']!=run['id'] or node['generation']!=run['generation']:return deny('ALLOCATION_CHANGED')
            if receipt['task_hash']!=j['task_hash']:return deny('TASK_VERSION_CHANGED')
            self._release(s,node,run,event_id,'COMPLETED')
            self._transition(s,j,'COMPLETED',actor,event_id,'RUNNER_COMPLETED')
            return {'ok':True,'job':j,'receipt_id':receipt_id}
        return self._mutate(change)

    def kill(self,actor,job_id,reason,event_id):
        bounded_text(reason)
        def change(s):
            j=self._find(s,'jobs',job_id)
            if not j or (actor!='Professor' and actor!=j['owner']):return deny('UNAVAILABLE')
            if j['state'] in ('COMPLETED','TERMINATED'):return {'ok':True,'code':'ALREADY_TERMINAL'}
            stop=None
            if j['state']=='RUNNING':
                run=self._find(s,'runs',j['run_id']);node=self._find(s,'nodes',run['node_id'])
                if node['run_id']!=run['id'] or node['generation']!=run['generation']:return deny('ALLOCATION_CHANGED')
                if not self.runner_stop_succeeds:return deny('RUNNER_STOP_NOT_CONFIRMED')
                stop={'id':f"RECEIPT-{len(s['receipts'])+1:03d}",'kind':'stop','run_id':run['id'],
                      'job_id':job_id,'node_id':node['id'],'generation':run['generation'],
                      'task_hash':run['task_hash'],'confirmed_stopped':True,'source':'SimulatedRunner',
                      'created_event_id':event_id}
                s['receipts'].append(stop);self._release(s,node,run,event_id,'STOP_CONFIRMED')
            self._transition(s,j,'TERMINATED',actor,event_id,reason)
            return {'ok':True,'job':j,'stop_receipt':stop}
        return self._mutate(change)

    def read_job(self,role,job_id):
        j=self._find(self.snapshot(),'jobs',job_id)
        return {'status':'AVAILABLE','job':j} if j and can_read(role,j) else {'status':'UNAVAILABLE'}

    def view(self,role):
        s=self.snapshot()
        jobs=[j for j in s['jobs'] if can_read(role,j)]
        ids={j['id'] for j in jobs}
        nodes=[{k:v for k,v in n.items() if k not in ('run_id','generation')}|{'busy':n['run_id'] is not None} for n in s['nodes']]
        return {'policy':s['policy'],'jobs':jobs,'nodes':nodes,
                'approvals':[a for a in s['approvals'] if a['job_id'] in ids],
                'receipts':[r for r in s['receipts'] if r['job_id'] in ids],
                'eligible_queue':self.candidates(s) if role=='Professor' else None}

    def unsafe_release_by_node(self,node_id,old_run_id,event_id):
        """Explicit Phase 1 fault: callback forgets to compare current allocation token."""
        def change(s):
            node=self._find(s,'nodes',node_id);run=self._find(s,'runs',old_run_id)
            self._release(s,node,run,event_id,'UNSAFE_DELAYED_CALLBACK')
            return {'ok':True,'released_node':node_id,'old_run_id':old_run_id}
        return self._mutate(change)
