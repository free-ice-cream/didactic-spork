import random as orig_random
from decorator import decorator
import binascii
import struct
import hashlib

random = orig_random.Random()
random.seed()

def message_to_dict(message):
    data = {'time': message.timestamp,
            'message': message.message,
            }
    return data

def player_to_funding_dict(player):
    funding = []
    for edge in player.lower_edges:
        funding.append({'id': edge.higher_node.id,
                        'amount_set': edge.weight,
                        'amount_actual': edge.weight if player.balance > 0 else 0,
                        })
    data = {'id': player.id,
            'name': player.name,
            'funding': funding,
            }
    return data

def player_to_league_dict(player):
    data = {'id': player.id,
            'name': player.name,
            'goal': player.goal.name if player.goal else None,
            'goal_id': player.goal.id if player.goal else None,
            'goal_short_name': player.goal.short_name if player.goal else None,
            'goal_contribution': float("{:.2f}".format(player.goal_funded)),
            'goal_total': float("{:.2f}".format(player.goal.balance if player.goal else 0)),
            }
    return data

def player_to_dict(player):
    if player.goal:
        goal = dict(id=player.goal.id,
                    name=player.goal.name)
    else:
        goal = None

    policies = [dict(id=x.id, name=x.name) for x in player.children()]

    return dict(id=player.id,
                name=player.name,
                balance=player.balance,
                unclaimed_budget=player.unclaimed_budget or 0.0,
                goal=goal,
                goal_contribution='{:.2f}'.format(player.goal_funded),
                goal_total='{:.2f}'.format(player.goal.balance if player.goal else 0),
                policies=policies,
                table=player.table_id,
                )

def node_to_dict(node):
    data = node_to_dict2(node)
    data['connections'] = [ edge_to_dict2(e) for e in node.lower_edges ]
    return data

def node_to_dict2(node):
    data = {"id": node.id,
            "name": node.name,
            "short_name": node.short_name,
            "leakage": float("{:.2f}".format(node.leak)),
            "max_amount": float("{:.2f}".format(node.max_level or 0)),
            "activation_amount": float("{:.2f}".format(node.activation or 0)),
            "active_level": float("{:.2f}".format(node.active_level)),
            "active": node.active and True or False,
            "active_percent": node.active_percent,
            "balance": float("{:.2f}".format(node.balance)),
            "resources": float("{:.2f}".format(node.balance)),
            }
    if node.group is not None:
        data["group"] = int(node.group)
    return data

def edge_to_dict(edge):
    data = {'id': edge.id,
            'source': edge.lower_node.id,
            'target': edge.higher_node.id,
            'weight': float("{:.6f}".format(edge.weight)),
            }
    return data

def edge_to_dict2(edge):
    data = {'id': edge.id,
            'from_id': edge.lower_node.id,
            'to_id': edge.higher_node.id,
            'weight': float("{:.6f}".format(edge.weight)),
            }
    return data

def edges_to_checksum(edges):
    checksum = hashlib.sha1()
    for link in sorted(edges, key=lambda x: x['id']):
        checksum.update(link['source'])
        checksum.update(link['target'])
    return checksum.hexdigest()


def update_node_from_dict(node, d):
    node.id = d['id']
    node.name = d['name']
    if d.get('short_name') is not None: 
        node.short_name = d['short_name']
    if d.get('group') is not None:
        node.group = int(d['group'])
    node.leak = float(d['leakage'])
    node.max_level = float(d['max_amount'])
    node.activation = float(d['activation_amount'])


def pack_amount(value):
    return binascii.hexlify(struct.pack("f", value)).decode('ascii')

def unpack_amount(value):
    return struct.unpack("f", binascii.unhexlify(value))[0]

def checksum(seller_id, policy_id, price, salt):
    input = "{}{}{}{}".format(seller_id, policy_id, pack_amount(price), salt)
    return hashlib.sha1(input).hexdigest()

class FakeMemcache:

    def __init__(self):
        self.clear()

    def clear(self):
        self.cache = {}

    def add(self, key, value, time=0, min_compress_len=0, namespace=None):
        self.cache[key] = value

    def get(self, key, namespace=None, for_cas=False):
        return self.cache.get(key)

    def set(self, key, value, time=0, min_compress_len=0, namespace=None):
        self.cache[key] = value

    def set_multi(self, mapping, time=0, key_prefix='', min_compress_len=0, namespace=None):
        for k,v in mapping.items():
            self.set(k, v, time)

fake_memcache = FakeMemcache()
