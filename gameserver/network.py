import logging.config
from itertools import chain
from time import time

from wallet import Wallet
from flaskext.zodb import Object, List, BTree

log = logging.getLogger(__name__)

def convert_to_dict(l):
    if type(l) == type({}):
        return BTree(l)
    elif type(l) == type([]):
        return BTree({ x.id: x for x in l })
    else:
        return BTree()
    

class Network(Object):

    def __init__(self, policies=None, goals=None, edges=None, players=None):
        self.policies = convert_to_dict(policies)
        self.goals = convert_to_dict(goals)
        self.edges = convert_to_dict(edges)
        self.players = convert_to_dict(players)
        self.ranked_nodes = []
        self.rank()

    @property
    def total_player_inflow(self):
        return sum([ p.max_outflow or 0 for p in self.players.values() ])

    @property
    def nodes(self):
        return dict(list(self.policies.items()) +
                    list(self.goals.items()) +
                    list(self.players.items()))

    def rank(self):
        self.ranked_nodes = sorted(list(self.policies.values()) + list(self.goals.values()), key=lambda x: (x.rank, x.id))

    def fund_network(self):
        for player in self.players.values():
            for policy_id,amount in player.policies.items():
                if amount > 0:
                    player.balance -= amount
                    policy = self.policies[policy_id]
                    if not hasattr(policy, '_v_incoming'):
                        policy._v_incoming = Wallet()
                    policy._v_incoming &= Wallet([(player.id, amount)])

    def propagate(self):

        total_player_inflow = self.total_player_inflow
        for policy in self.ranked_nodes:
            previous_balance = policy.balance

            # funds coming in from players
            if hasattr(policy, '_v_incoming'):
                policy.wallet &= policy._v_incoming
                del policy._v_incoming

            # funds coming in from other nodes
            edges = policy.higher_edges
            for edge in edges:
                if getattr(edge, '_v_wallet', None):
                    policy.wallet &= edge._v_wallet
                    # delete the wallet after we get from it
                    del edge._v_wallet

            new_balance = policy.balance
            max_level = policy.max_level or 0
            if max_level and new_balance > max_level:
                # if we are over out level then remove excess
                policy.wallet -= new_balance - max_level
            # set the active level on the node
            if total_player_inflow > 0:
                policy.active_level = (new_balance - previous_balance) / total_player_inflow
            else:
                policy.active_level = 1.0

            # check if we are active
            if policy.active_level < policy.activation:
                # not active so stop here
                continue
            # yes we are active so distribute funds
            if policy.balance <= 0:
                continue # no balance to propogate

            total_balance = policy.balance
            total_children_weight = policy.total_children_weight # XXX

            if not total_children_weight:
                continue # no children weight so return

            # max we can distribute is our balance or what children need
            current_outflow = min(total_children_weight, total_balance)

            # calculate the factor to multiply each player amount by
            total_out_factor = min(1.0, total_balance / total_children_weight)

            for edge in policy.lower_edges:
                amount = edge.weight
                if amount <= 0: # don't try to propogate negative values
                    continue
                factored_amount = amount * total_out_factor

                # due to rounding errors in floats this is needed
                # otherwise we overdraw by like 5.10702591328e-15
                if factored_amount > policy.balance:
                    factored_amount = policy.balance

                # create a wallet on the edge and transfer to it
                edge._v_wallet = Wallet()
                policy.wallet.transfer(edge._v_wallet, factored_amount)

