"""Bound Python tool identities; Runner is a simulator tool, not a fourth agent."""
from .access import ROLE_TOOLS
from .schemas import ApplicationError, fixture

class Tools:
    def __init__(self,role,store,trace):self.role,self.store,self.trace=role,store,trace
    def call(self,name,args=None,parents=()):
        if name not in ROLE_TOOLS.get(self.role,()):raise ApplicationError('Operation unavailable to this role.')
        a=args or {};s=self.store;r=self.role
        if name=='view':fn=lambda _:s.view(r)
        elif name=='read_job':fn=lambda _:s.read_job(r,a.get('job_id'))
        elif name=='read_private':
            fn=lambda _:{x:fixture(x.lower()+'_private') for x in ('Professor','PhD','Master')} if r=='Professor' else fixture(r.lower()+'_private')
        elif name=='submit_job':fn=lambda e:s.submit(r,a['spec'],e)
        elif name=='revise_job':fn=lambda e:s.revise(r,a['job_id'],a['spec'],e)
        elif name=='approve_job':fn=lambda e:s.approve(r,a['job_id'],a['expected_version'],a['approve'],e)
        elif name=='dispatch_job':fn=lambda e:s.dispatch(r,a['job_id'],e)
        elif name=='record_completion':fn=lambda e:s.record_completion(a['run_id'],e)
        elif name=='finish_job':fn=lambda e:s.finish(r,a['job_id'],a['receipt_id'],e)
        else:fn=lambda e:s.kill(r,a['job_id'],a['reason'],e)
        sources=['fixtures/cluster.json']
        if name=='read_private':
            sources += [f'fixtures/{x.lower()}_private.json' for x in (('Professor','PhD','Master') if r=='Professor' else (r,))]
        refs=list(parents)
        state=s.snapshot()
        job=s._find(state,'jobs',a.get('job_id'))
        if job:
            refs.append(job['created_event_id'])
            for key,collection in [('approval_id','approvals'),('run_id','runs')]:
                record=s._find(state,collection,job.get(key))
                if record:refs.append(record['created_event_id'])
        for key,collection in [('receipt_id','receipts'),('run_id','runs')]:
            record=s._find(state,collection,a.get(key))
            if record:refs.append(record['created_event_id'])
        # Full results are for the bound role/evaluator, never a public bus.
        return self.trace.tool(r,name,a,fn,refs,sources,visibility=r.upper()+'_PRIVATE')
