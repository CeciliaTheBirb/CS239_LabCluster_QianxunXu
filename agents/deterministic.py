"""Explicit offline fixture decisions; never masquerades as an LLM call."""
from copy import deepcopy
from core.schemas import fixture, validate_decision

class DeterministicBackend:
    name='deterministic'
    model='offline-fixture-v1'
    last_metadata={'origin':'deterministic_fixture','new_api_call':False}

    def choose(self,role,stage,context,instructions=''):
        if stage=='submit':
            d={'summary':'Request the resources needed for my own experiment.',
               'message':'Please review my task and its requested resource limits.',
               'spec':deepcopy(fixture(role.lower()+'_private')['preferred_spec'])}
        elif stage=='review':
            d={'summary':'Check the current version against the role quota.',
               'message':'This review authorizes only this task version and resource request.',
               'approve':context['quota_eligible']}
        elif stage=='schedule':
            q=context['view']['eligible_queue']
            d={'summary':'Use the eligible queue for currently free compatible nodes; do not preempt.',
               'message':'Dispatch the first eligible task, or keep waiting when no node is free.',
               'job_id':q[0]['job_id'] if q else None}
        elif stage=='control':
            d={'summary':'An explicit management request requires reclaiming the CPU node.',
               'message':'Stop the specified task and wait for the runner stop acknowledgment.',
               'action':'kill','job_id':context['target_job_id'],
               'reason':context['management_request']}
        elif stage=='report':
            d={'summary':'Report completion only when a matching runner receipt is present.',
               'message':'The simulated runner returned a completion receipt for my task.',
               'report':'complete' if context.get('completion_receipt') else 'wait'}
        else:d={'summary':'Fixture protocol check.','message':'Accepted.','accepted':True}
        return validate_decision(stage,d,context)

    def statistics(self):
        return {'requests_attempted':0,'successful_decisions':0,'provider_reported_tokens':0}
