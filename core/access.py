"""Normal actor-bound interfaces; unsafe fixture paths remain for Phase 1."""
from types import MappingProxyType

ROLE_TOOLS=MappingProxyType({
    'Professor':frozenset({'view','read_job','read_private','approve_job','dispatch_job','kill_job','finish_job'}),
    'PhD':frozenset({'view','read_job','read_private','submit_job','revise_job','cancel_job','finish_job'}),
    'Master':frozenset({'view','read_job','read_private','submit_job','revise_job','cancel_job','finish_job'}),
    'Runner':frozenset({'record_completion'}),
})

def can_read(role,job):return role=='Professor' or job['owner']==role
