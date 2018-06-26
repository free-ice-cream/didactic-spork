import logging.config
from datetime import datetime

from utils import default_uuid
from utils import pack_amount, checksum
from wallet import Wallet

from flaskext.zodb import Object, List, Dict

log = logging.getLogger(__name__)

class Hashable:
    def __hash__(self):
        return hash(self.id)

class Base(Object, Hashable):
    """ Base model """
    @classmethod
    def new(cls):
        return cls(id=default_uuid())

    def __init__(self, id, **kwargs):
        self.id = id
        for k,v in kwargs.items():
            setattr(self, k, v)

class Settings(Base):
    game_id = None
    current_game_year = None
    current_game_year_start = None
    next_game_year_start = None
    budget_per_cycle = None
    max_spend_per_tick = None


class Funding:
    policy_key = None
    amount = None


class Budget(Base):
    player = None
    fundings_ = []

    @classmethod
    def new(cls, player, fundings):
        b = cls(id=default_uuid())
        b.player = player
        b.fundings = fundings
        return b

    @property
    def fundings(self):
        # XXX make async
        return [ (x.policy_key.get(), x.amount) for x in self.fundings_ ]
        
    @fundings.setter
    def fundings(self, fs):
        self.fundings_ = [ Funding(policy_key=policy.key, amount=amount) for policy,amount in fs ]

    @property
    def total(self):
        return sum([ x for _,x in self.fundings])

class Client(Base):
    name = None


class Table(Base):
    """ Table model """
    name = None

    @classmethod
    def new(cls, name, **kwargs):
        t = cls(id=default_uuid())
        t.name = name
        t.players = set()
        return t

class Node(Base):

    name = None
    short_name = None
    group = None
    leak = 0.0
    activation = 0.0
    max_level = 0.0
    active_level = 0.0
    wallet = None
    
    def __eq__(self, other):
        try:
            return self.id == other.id and \
                self.name == other.name and \
                self.wallet == other.wallet
        except:
            return False

    def __init__(self, id, **kwargs):
        super(Node,self).__init__(id, **kwargs)
        self.higher_edges = []
        self.lower_edges = []
        self.wallet = Wallet()
        
    @classmethod
    def new(cls, name, **kwargs):
        n = cls(id=default_uuid())
        n.name = name
#        n.higher_edges = []
#        n.lower_edges = []
#        n.wallet = Wallet()

        for k,v in kwargs.items():
            setattr(n, k, v)
        return n

    @property
    def lower_neighbors(self):
        return [x.lower_node for x in self.lower_edges]

    @property
    def higher_neighbors(self):
        return [x.higher_node for x in self.higher_edges]

    children = lower_neighbors
    parents = higher_neighbors

    def get_leak(self):
        leak = self.leak
        for edge in self.higher_edges:
            if edge.weight < 0:
                leak += abs(edge.weight)

        return leak

    @property
    def total_children_weight(self):
        return sum([max(e.weight,0) for e in self.lower_edges])

    @property
    def active_percent(self):
        if not self.activation:
            return 1.0
        return self.active_level / self.activation

    @property
    def active(self):
        return self.active_level >= self.activation

    @property
    def balance(self):
        wallet = self.wallet
        if wallet is not None:
            return wallet.total
        else:
            return 0.0

    @balance.setter
    def balance(self, amount):
        self.wallet = Wallet([(self.id, amount)])

    def do_leak(self):
        leak = self.get_leak()
        if self.balance and leak:
            self.wallet.leak(leak)

    @property
    def wallet_owner_map(self):
        return self.wallet.todict()

    def reset(self):
        self.wallet = Wallet()

    @property
    def rank(self):
        return self._rank()

    def _rank(self, seen=None):
        rank = 1
        if seen is None:
            seen = set()
        try:
            for parent in self.parents:
                if parent.id not in seen:
                    seen.add(parent.id)
                    rank += parent._rank(seen)
        except RuntimeError:
            print "Max recursion detected. Current node: ", self.id
            raise

        return rank


class Edge(Base):

    @classmethod
    def new(cls, n1, n2, weight):
        e = cls(id=default_uuid())
        return e.init(n1, n2, weight)

    def init(self, n1, n2, weight):
        self.higher_node = n1
        self.lower_node = n2
        n1.lower_edges.append(self)
        n2.higher_edges.append(self)
        
        self.weight = weight
        self.wallet = None
        return self

    @property
    def current_flow(self):
        return self.lower_node.current_outflow


class Goal(Node):

    @property
    def active(self):
        return self.balance >= self.activation

class Policy(Node):

    pass


class Player(Node):

    unclaimed_budget = 0.0
    last_budget_claim = 0.0
    token = None
    budget_key = None
    policies = None
    
    goal_id = None
    table_id = None
    
    @property
    def funded_policies(self):
        return [ p for p,a in self.policies.items() if a>0 ]

    @classmethod
    def new(cls, name, **kwargs):
        p = cls(id=default_uuid())
        p.name = name
        p.reset()
        for k,v in kwargs.items():
            setattr(p, k, v)
        return p

    def transfer_funds_to_node(self, node, amount):
        self.wallet.transfer(node.wallet, amount)

    @property
    def active(self):
        return True

    @property
    def total_funding(self):
        return sum(self.policies.values())

    def transfer_funds(self):
        raise NotImplementedError
        for fund in self.lower_edges:
            self.transfer_funds_to_node(fund.higher_node, fund.weight)

    def do_propogate_funds(self, total_player_inflow):
        Node.do_propogate_funds(self, total_player_inflow)

    def offer_policy(self, policy_id, price):
        if policy_id not in self.policies:
            raise ValueError, "Seller doesn't have this policy"
        
        chk = checksum(self.id, policy_id, price, self.token)

        data = {'seller_id': self.id,
                'policy_id': policy_id,
                'price': price,
                'checksum': chk,
                }
        return data

    def buy_policy(self, seller, policy, price, chk):

        salt = seller.token
        if chk != checksum(seller.id, policy.id, price, salt):
            raise ValueError, "Checksum mismatch"

        # check the seller has the funds:
        if self.balance < price:
            raise ValueError, "Not enough funds for sale"

        # check the buyer doesn't alreay have this policy
        if policy.id in self.policies:
            raise ValueError, "The buyer already has this policy"

        # sort out the money first
        seller.balance += price
        self.balance -= price
        
        # then give the buyer the policy
        self.policies[policy.id] = 0.0

        return True

    def claim_budget(self):
        if self.unclaimed_budget > 0:
            self.balance = self.unclaimed_budget
            log.debug("set balance for {} to {}".format(self.id, self.balance))
            self.unclaimed_budget = 0
            log.debug("set unclaimed budget for {} to {}".format(self.id, self.unclaimed_budget))
            self.last_budget_claim = datetime.now()

    def reset(self):
        self.wallet = Wallet()
        self.token = default_uuid()
        self.goal_id = None
        self.policies = Dict()

class Message(Base):
    timestamp = None
    type = None
    message = None

