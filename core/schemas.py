"""Small structured job protocol; task execution is simulated, never shell execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ROLES=('Professor','PhD','Master')
STATES=('QUEUED','RUNNING','COMPLETED','TERMINATED')

class ApplicationError(RuntimeError):pass

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def fixture(name):return json.loads((ROOT/'fixtures'/f'{name}.json').read_text())

def strict_json(value):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('Duplicate JSON key')
            result[k]=v
        return result
    def invalid(_):raise ValueError('Nonfinite JSON number')
    return json.loads(value,object_pairs_hook=pairs,parse_constant=invalid)

def bounded_text(value,limit=1200):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise ApplicationError('Expected bounded text.')
    try:value.encode('utf-8')
    except UnicodeError:raise ApplicationError('Invalid Unicode.') from None

def integer(value,low,high):
    if type(value)is not int or not low<=value<=high:raise ApplicationError('Expected bounded integer.')

SPEC_KEYS={'title','node_type','cpu_cores','memory_gb','runtime_minutes'}
def validate_spec(spec):
    if not isinstance(spec,dict) or set(spec)!=SPEC_KEYS:raise ApplicationError('Unexpected job specification fields.')
    bounded_text(spec['title'],100)
    if spec['node_type'] not in ('CPU','GPU'):raise ApplicationError('Unknown node type.')
    for name,maximum in [('cpu_cores',64),('memory_gb',256),('runtime_minutes',240)]:
        integer(spec[name],1,maximum)
    return deepcopy(spec)

SHAPES={
    'submit':{'summary':'short text','message':'public text to Professor','spec':{
        'title':'short public task name','node_type':'CPU|GPU','cpu_cores':'integer',
        'memory_gb':'integer','runtime_minutes':'integer'}},
    'review':{'summary':'short text','message':'reply to task owner','approve':'boolean'},
    'schedule':{'summary':'short text','message':'dispatch explanation','job_id':'eligible job id or null if none'},
    'control':{'summary':'short text','message':'reply','action':'kill|keep','job_id':'current running job id','reason':'specific reason'},
    'report':{'summary':'short text','message':'completion report','report':'complete|wait'},
    'accept':{'accepted':'boolean','message':'text','summary':'text'},
}

def validate_decision(stage,value,context):
    if not isinstance(value,dict) or set(value)!=set(SHAPES[stage]):
        raise ApplicationError('Output must contain exactly the required fields, including summary.')
    for k in ('summary','message'):bounded_text(value[k])
    if stage=='submit':validate_spec(value['spec'])
    elif stage in ('review','accept'):
        if type(value['approve' if stage=='review' else 'accepted']) is not bool:
            raise ApplicationError('Expected strict boolean.')
    elif stage=='schedule':
        if value['job_id'] is not None:bounded_text(value['job_id'],40)
    elif stage=='control':
        if value['action'] not in ('kill','keep'):raise ApplicationError('Invalid control action.')
        bounded_text(value['job_id'],40);bounded_text(value['reason'])
    elif stage=='report' and value['report'] not in ('complete','wait'):
        raise ApplicationError('Invalid completion report.')
    return value
