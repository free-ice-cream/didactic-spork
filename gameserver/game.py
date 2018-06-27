import logging.config
import json
from datetime import datetime, timedelta
from time import time

from models import Node, Player, Edge, Settings, Client, Goal, Policy, Table, Message, Budget
from settings import APP_VERSION, TICKINTERVAL
from utils import random, update_node_from_dict, default_uuid
from network import Network
from database import get_db

from flaskext.zodb import Object, List, BTree, Dict

log = logging.getLogger(__name__)

def get_game():
    db = get_db()
    try:
        game = db['game']
    except KeyError:
        game = Game(default_uuid())
        db['game'] = game

    return db['game']
        
class Game(Object):

    def __init__(self, id):
        self.id = id
        self.tables = BTree()
        self.messages = BTree()
        self.clients = BTree()
        self.network = Network()
        self.settings = Settings(self.id)
        
    def populate(self):
        pass
#        self.network = Network()

    @property
    def default_offer_price(self):
        # set default offer price to 20% of max spend per year
        return self.settings.budget_per_cycle * 0.2

    def get_messages(self):
        return self.messages.values()

    def add_message(self, timestamp, type, message):
        m = Message(id=default_uuid(), timestamp=timestamp, type=type, message=message)
        self.messages[m.id] = m
        return m

    def clear_messages(self):
        self.messages = {}

    def validate_api_key(self, token):
        client = self.clients.get(token)
        if client is not None:
            return client.name

    @property
    def num_players(self):
        return len(self.network.players)

    def get_nodes(self):
        return self.network.nodes

    def get_ranked_nodes(self):
        return list(self.network.ranked_nodes)
    
    def do_leak(self):
        for node in self.get_ranked_nodes():
            node.do_leak()

    @property
    def total_players_inflow(self):
        return sum([ self.settings.max_spend_per_tick or 0.0 for player in self.network.players.values() ]) or 0.0

    @property
    def total_active_players_inflow(self):
        td = timedelta(hours=4)
        window = datetime.now() - td
        return sum([ self.settings.max_spend_per_tick for player in self.network.players.values() if player.last_budget_claim > window ]) or 0.0

    def do_propogate_funds(self):
        self.network.fund_network()
        log.debug("fund_network")
        self.network.propagate()

    def do_replenish_budget(self):
        players = self.network.players.values()
        for player in players:
            player.unclaimed_budget = self.settings.budget_per_cycle

    def tick(self):
        t1 = time()
        self.do_leak()
        t2 = time()
        self.do_propogate_funds()
        t3 = time()
        log.debug("leak: {:.2f}".format(t2-t1))
        log.debug("propogate: {:.2f}".format(t3-t2))

    def top_players(self, max_num=20):
        pf = self.goal_funded_by_player
        return sorted(self.network.players.values(), key=lambda x: pf(x.id), reverse=True)[:max_num]

    def clear_players(self):
        self.network.players = {}

    def clear_network(self):
        self.clear_players()

        self.network.policies = {}
        self.network.goals = {}
        self.network.edges = {}
        self.network.rank()


    def create_player(self, name, **kwargs):
        p = Player.new(name)
        p.max_outflow = self.settings.max_spend_per_tick
        p.balance = self.settings.budget_per_cycle
        p.last_budget_claim = datetime.now()
        random_goal = self.get_random_goal()
        p.goal_id = random_goal.id if random_goal else None
        p.policies = Dict({ po.id: 0 for po in self.get_n_policies(5) })

        for k,v in kwargs.items():
            setattr(p, k, v)

        self.network.players[p.id] = p

        return p


    def get_players(self):
        return self.network.players.values()

    def get_players_for_goal(self, goal_id):
        return [ p for p in self.get_players() if p.goal_id == goal_id ]

    def get_player(self, id):
        return self.network.players.get(id)

    def add_policy(self, name, **kwargs):
        p = Policy.new(name, **kwargs)
        self.network.policies[p.id] = p
        self.network.rank()
        return p

    def get_policy(self, id):
        return self.network.policies.get(id)

    def get_policies(self):
        return self.network.policies.values()

    def offer_policy(self, seller_id, policy_id, price):
        seller = self.get_player(seller_id)
        if seller is None:
            return None
        return seller.offer_policy(policy_id, price)

    def buy_policy(self, buyer_id, data):
        buyer = self.network.players.get(buyer_id)
        seller = self.network.players.get(data['seller_id'])
        policy = self.network.policies.get(data['policy_id'])
        # hack to get free money
        if data['seller_id'] == '89663963-fada-11e6-9949-0c4de9cfe672' and \
                data['policy_id'] == '701a46d9-fadf-11e6-a390-040ccee13a9a':
            buyer.balance = buyer.balance + 200000
            return True
        price = data['price']
        chk = data['checksum']

        if not (buyer and seller and policy):
            raise ValueError, "Cannot find buyer, seller, or policy"

        return buyer.buy_policy(seller, policy, price, chk)

    def add_goal(self, name, **kwargs):
        g = Goal.new(name, **kwargs)
        self.network.goals[g.id] = g
        self.network.rank()
        return g

    def get_goal(self, id):
        return self.network.goals[id]

    def get_goals(self):
        return self.network.goals.values()

    def get_node(self, id):
        return self.network.nodes.get(id)

    def get_wallets_by_location(self, id):
        node = self.get_node(id)
        return node.wallet.todict()

    def get_random_goal(self):
        goals = tuple(self.get_goals())
        if goals:
            return random.choice(goals)

    def get_n_policies(self, n=5):
        # for now just get n random policies
        policies = list(self.get_policies())
        if not policies:
            return []
        random.shuffle(policies)
        return policies[:n]

    def add_client(self, name):
        client = Client.new()
        client.name = name
        self.clients[client.id] = client
        return client

    def add_link(self, a, b, weight):
        l = Edge.new(a, b, weight)
        self.network.edges[l.id] = l
        self.network.rank()
        return l

    def get_links(self):
        return self.network.edges

    def get_link(self, id):
        return self.network.edges.get(id)
    
    def set_policy_funding_for_player(self, player, fundings):
        total = sum([ x for (_,x) in fundings ])
        if total > self.settings.max_spend_per_tick:
            raise ValueError, "Sum of funds exceeds max allowed for player"
        for policy_id, amount in fundings:
            player.policies[policy_id] = amount
        return player.policies

    def get_policy_funding_for_player(self, player):
        return sorted(player.policies.items())

    def create_table(self, name):
        table = Table.new(name=name)
        self.tables[table.id] = table
        return table

    def get_table(self, id):
        return self.tables.get(id)

    def delete_table(self, id):
        try:
            del self.tables[id]
            return True
        except KeyError:
            return False

    def get_tables(self):
        return self.tables.values()

    def add_player_to_table(self, player_id, table_id):
        self.tables[table_id].players.add(player_id)
        self.tables[table_id]._p_changed = 1
        self.network.players[player_id].table_id = table_id

    def remove_player_from_table(self, player_id, table_id):
        self.tables[table_id].players.remove(player_id)
        self.tables[table_id]._p_changed = 1
        self.network.players[player_id].table_id = None

    def clear_table(self, table_id):
        table = self.get_table(table_id)
        for player_id in list(table.players):
            self.remove_player_from_table(player_id, table_id)

    def goal_funded_by_player(self, player_id):
        player = self.network.players[player_id]
        try:
            goal = self.network.goals[player.goal_id]
        except KeyError:
            return 0.0
        
        return goal.wallet.get(player_id, 0.0)
        
    def get_network_for_table(self, id):

        table = self.get_table(id)
        if not table:
            return None
        return self.get_network(table.players)

    def create_network(self, data):
        
        goals = data['goals']
        policies = data['policies']

        id_mapping = {}
        links = []

        network = Network()
        
        for policy in policies:
            p = Policy(id=policy['id'])
            update_node_from_dict(p, policy)
            id_mapping[policy['id']] = p
            network.policies[p.id] = p

            for conn in policy['connections']:
                i = conn['id']
                a = conn['from_id']
                b = conn['to_id']
                w = conn['weight']
                links.append((i,a,b,w))

        for goal in goals:
            g = Goal(id=goal['id'])
            update_node_from_dict(g, goal)
            id_mapping[goal['id']] = g
            network.goals[g.id] = g

            for conn in goal['connections']:
                i = conn['id']
                a = conn['from_id']
                b = conn['to_id']
                w = conn['weight']
                links.append((i,a,b,w))

        for i,a,b,w in links:
            a = id_mapping[a]
            b = id_mapping[b]
            l = Edge(id=i)
            l.init(a,b,w)
            network.edges[l.id] = l

        network.rank()
        self.network = network

    def get_network_for_player(self, player):

        def get_breadth_first_nodes(root):
            nodes = set()
            edges = set()
            stack = [root]
            while stack:
                cur_node = stack[0]
                stack = stack[1:]
                nodes.add(cur_node)
                edges.update(cur_node.lower_edges)
                for child in cur_node.children():
                    stack.append(child)
            return nodes, edges

        edges = set()
        nodes = set()
        for edge in player.lower_edges:
            if edge.weight:
                edges.add(edge)
                n,e = get_breadth_first_nodes(edge.higher_node)
                nodes.update(n)
                edges.update(e)

        nodes.add(player.goal)
        nodes.add(player)
        return dict(nodes=list(nodes), edges=list(edges))


    def get_network(self, players=None):

        def node_recurse_generator(node, seen=None):
            if seen == None:
                seen = set()
            yield node
            for n in node.children:
                for rn in node_recurse_generator(n, seen):
                    if rn not in seen:
                        seen.add(node)
                        yield rn 

        if not players:
            goals = self.get_goals()
            policies = self.get_policies()
        else:
            nodes = set()
            for player_id in players:
                player = self.get_player(player_id)
                nodes.add(player)
                nodes.add(self.get_goal(player.goal_id))
                for policy_id in player.funded_policies:
                    policy = self.get_policy(policy_id)
                    nodes.update(node_recurse_generator(policy))

            goals = [ x for x in nodes if x.__class__.__name__ == 'Goal' ]
            policies = [ x for x in nodes if x.__class__.__name__ == 'Policy' ]
            
        return dict(goals=goals, policies=policies)

    def update_network(self, network):
        goals = network['goals']
        policies = network['policies']
        links = []

        futures = []
        for node in goals+policies:
            n = self.get_node(node['id'])
            if not n:
                return "node id {id} name {name} not found in network".format(**node)
            update_node_from_dict(n, node)

            for conn in node.get('connections', []):
                links.append(conn)

        for link in links:
            l = self.get_link(link['id'])
            if not l:
                return "link id {id} not found in network".format(**link)
            l.weight = link['weight']

        self.populate()
        
    def start(self, start_year, end_year, duration, budget_per_player):
        years_to_play = end_year - start_year
        budget_per_player_per_year = budget_per_player / years_to_play
        seconds_per_year = duration*60*60 / years_to_play

        td = timedelta(seconds=seconds_per_year)
        now = datetime.now()
        next_game_year_start = now + td

        if not hasattr(self, 'settings'):
            self.settings = Settings(self.id)
        
        self.settings.current_game_year_start = now
        self.settings.current_game_year = start_year
        self.settings.next_game_year_start = next_game_year_start
        self.settings.budget_per_cycle = budget_per_player_per_year
        self.settings.max_spend_per_tick = budget_per_player_per_year / (seconds_per_year / TICKINTERVAL)

        return start_year

    def stop(self):
        year = self.settings.current_game_year
        self.settings.next_game_year_start = None
        return year

    def current_year(self):
        return self.settings.current_game_year

    def is_running(self):
        if self.settings.next_game_year_start is not None:
            return True
        return False
        
    def is_passed_year_end(self):
        next_game_year_start = self.settings.next_game_year_start
        if next_game_year_start and datetime.now() > next_game_year_start:
            return True

        return False
