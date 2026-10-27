"""Explicit agent mailboxes. Phase 1 free-text messages have no global content guard."""
from copy import deepcopy
from .schemas import ApplicationError, ROLES

class Bus:
    def __init__(self, trace):
        self.trace=trace
        self.inboxes={r:[] for r in ROLES}

    def send(self, sender, recipient, kind, body, parents=(), origin='application'):
        if sender not in ROLES or recipient not in ROLES or sender==recipient:
            raise ApplicationError('Invalid message route.')
        payload={'sender':sender,'recipient':recipient,'message_type':kind,'body':deepcopy(body)}
        sent=self.trace.add(sender,'message_sent',payload,parents=parents,
                            visibility=recipient.upper()+'_PRIVATE',origin=origin)
        received=self.trace.add(recipient,'message_received',payload,parents=[sent],
                                visibility=recipient.upper()+'_PRIVATE',origin=origin)
        self.inboxes[recipient].append({'message':payload,'received_event_id':received})
        return received

    def context(self, role):return deepcopy(self.inboxes[role])
