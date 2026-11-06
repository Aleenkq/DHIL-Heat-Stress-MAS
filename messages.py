"""messages.py -- ACL-like messaging + base agent for DHIL."""
import itertools
from dataclasses import dataclass, field

PERFORMATIVES = {"INFORM", "REQUEST", "CFP", "PROPOSE", "ACCEPT", "REFUSE", "FAILURE"}
ONTOLOGY = "dhil-heat-stress"
_ids = itertools.count(1)


@dataclass
class Message:
    sender: str
    receiver: str
    performative: str
    content: dict
    ontology: str = ONTOLOGY
    conversation_id: str = ""
    in_reply_to: int = 0
    step: int = 0
    delivered: bool = True
    msg_id: int = field(default_factory=lambda: next(_ids))

    def __post_init__(self):
        if self.performative not in PERFORMATIVES:
            raise ValueError(f"Unknown performative: {self.performative}")

    def __str__(self):
        flag = "" if self.delivered else "  [UNDELIVERED]"
        return (f"#{self.msg_id} step={self.step} ({self.performative} :sender {self.sender} "
                f":receiver {self.receiver} :ontology {self.ontology} "
                f":conv {self.conversation_id or '-'} :content {self.content}){flag}")


class MessageBus:
    """Delivers messages between agents and keeps the log shown in the UI."""

    def __init__(self):
        self.agents = {}
        self.log = []
        self.failed = set()      # agents currently "down" (failure scenarios)
        self.step = 0

    def register(self, agent):
        self.agents[agent.name] = agent

    def fail(self, name):
        self.failed.add(name)

    def recover(self, name):
        self.failed.discard(name)

    def send(self, msg):
        msg.step = self.step
        target = self.agents.get(msg.receiver)
        if target is None or msg.receiver in self.failed:
            msg.delivered = False
        else:
            target.inbox.append(msg)
        self.log.append(msg)
        return msg


class BaseAgent:
    def __init__(self, name, bus):
        self.name = name
        self.bus = bus
        self.inbox = []
        self.status = "idle"
        bus.register(self)

    @property
    def is_failed(self):
        return self.name in self.bus.failed

    def send(self, receiver, performative, content, conversation_id="", in_reply_to=0):
        return self.bus.send(Message(self.name, receiver, performative, content,
                                     conversation_id=conversation_id, in_reply_to=in_reply_to))

    def read_inbox(self):
        msgs, self.inbox = self.inbox, []
        return msgs
