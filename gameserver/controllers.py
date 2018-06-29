import logging.config
from decorator import decorator
from flask import request, abort, g

from game import Game
from utils import node_to_dict, player_to_dict, node_to_dict2, edge_to_dict, edges_to_checksum, player_to_league_dict, message_to_dict, player_to_funding_dict
from settings import APP_VERSION
from hashlib import sha1
from time import asctime, time
import dateutil.parser
from datetime import datetime

from gameserver.models import Player, Goal, Edge, Policy, Table
from gameserver.database import get_db
from gameserver.game import get_game

log = logging.getLogger(__name__)

def app_version():
    return dict(version=APP_VERSION)

@decorator
def require_user_key(f, *args, **kw):
    key = request.headers.get('X-USER-KEY')
    player_id = request.view_args['player_id']
    mkey = "{}-player-token".format(player_id)
    game = get_game()
    player = game.get_player(player_id)
    if not player:
        abort(404)
    if not (key and player.token == key):
        abort(401)

    return f(*args, **kw)

@decorator
def require_api_key(f, *args, **kw):
    key = request.headers.get('X-API-KEY')
    if not key:
        abort(401)
    game = get_game()
    mkey = "{}-client-key".format(key)
    client_name = game.validate_api_key(key)
    if not (key and client_name is not None):
        abort(401)

    return f(*args, **kw)

@require_api_key
def do_tick():
    t0 = time()
    game = get_game()
    t1 = time()
    if not game.is_running():
        return "Game not running", 202
    game.tick()
    t2 = time()
    msg = 'entire tick {:.2f}, get_game: {:.2f}'.format(t2-t1, t1-t0)
    log.debug(msg)

    return msg, 200

@require_api_key
def clear_players():
    game = get_game()
    game.clear_players()
    return None, 200

@require_api_key
def player_fundings():
    game = get_game()
    fundings = []
    for player in game.get_players():
        fundings.append(player_to_funding_dict(game, player.id))

    return fundings, 200

@require_api_key
def league_table():
    res = _league_table()
    return res, 200

def _league_table():
    game = get_game()
    res = []
    top = game.top_players()
    for t in top:
        
        if not t.goal_id:
            continue 

        goal = game.get_goal(t.goal_id)
        r = {'id': t.id,
             'name': t.name,
             'goal': goal.name,
             'goal_contribution': "{:.2f}".format(game.goal_funded_by_player(t.id)),
             'goal_total': "{:.2f}".format(goal.balance),
             }
        res.append(r)

    return dict(rows=res)

@require_api_key
def create_network(network):
    game = get_game()
    game.clear_network()
    game.create_network(network)

    return _get_network(), 201

@require_api_key
def get_network():
    return _get_network(), 200

def _get_network():
    game = get_game()
    network =  game.get_network()
    network['goals'] = [ node_to_dict(g) for g in network['goals'] ]
    network['policies'] = [ node_to_dict(p) for p in network['policies'] ]
    network['generated'] = asctime()
    return network

@require_api_key
def update_network(network):
    game = get_game()
    game.update_network(network)
    network =  game.get_network()
    network['goals'] = [ node_to_dict(g) for g in network['goals'] ]
    network['policies'] = [ node_to_dict(p) for p in network['policies'] ]

    return network, 200

@require_api_key
def get_node(id):
    game = get_game()
    node = game.get_node(id)
    if not node:
        return "Node not found", 404
    return node_to_dict(node), 200

@require_api_key
def get_wallets(id):
    game = get_game()
    wallet = game.get_node(id).wallet
    if not wallet:
        return "No wallet found", 404
    res = []
    for player_id, amount in wallet.todict().items():
        res.append({'owner': player_id,
                    'location': id,
                    'balance': float("{:.2f}".format(amount)),
                    })

    return res, 200
    
#@require_api_key
def get_player(player_id):
    game = get_game()
    player = game.get_player(player_id)
    if player:
        return player_to_dict(game, player), 200
    else:
        return "Player not found", 404


@require_api_key
def create_player(player=None):
    """
    Creates a new game player.
    """
    game = get_game()
    if player:
        player = game.create_player(player['name'])
        d = player_to_dict(game, player)
        d['token'] = player.token
        return d, 201
    else:
        return "error", 500

@require_api_key
@require_user_key
def update_player(player_id, player=None):
    """
    Updates a player
    """
    if not player:
        return 500
    p = game.get_player(player_id)
    if not p:
        return "Player not found", 404

    for key, value in player.items():
        if key == 'table':
            table = game.get_table(value)
            p.table = table

    db_session.commit()
    return player_to_dict(p), 200

@require_api_key
@require_user_key
def set_player_table(player_id, table_id):
    """
    Adds / Updates the table a player is on
    """
    game = get_game()
    p = game.get_player(player_id)
    if not p:
        return "Player not found", 404

    t = game.get_table(table_id)
    if not t:
        return "Table not found", 404

    game.add_player_to_table(player_id, table_id)

    return player_to_dict(game, p), 200

@require_api_key
@require_user_key
def delete_player_table(player_id, table_id):
    """
    Adds / Updates the table a player is on
    """
    game = get_game()
    p = game.get_player(player_id)
    if not p:
        return "Player not found", 404

    t = game.get_table(table_id)
    if not t:
        return "Table not found", 404

    game.remove_player_from_table(player_id, table_id)

    return player_to_dict(game, p), 200

@require_api_key
@require_user_key
def set_funding(player_id, funding = None):
    game = get_game()
    player = game.get_player(player_id)
    try:
        funding = [ (x['to_id'], x['amount']) for x in funding ]
        game.set_policy_funding_for_player(player, funding)
        return funding, 200
    except ValueError:
        return "Sum of funds exceeds max allowed", 400

@require_api_key
@require_user_key
def get_funding(player_id):
    game = get_game()
    player = game.get_player(player_id)
    funds = []
    for policy_id,amount in game.get_policy_funding_for_player(player):
        funds.append({'from_id':player_id, 'to_id': policy_id, 'amount': amount})
            
    return funds, 200

@require_api_key
@require_user_key
def get_policy_offer(player_id, policy_id, price=None):
    game = get_game()
    if price == None:
        price = game.default_offer_price
    try:
        offer = game.offer_policy(player_id, policy_id, price)
        if offer is None:
            return "Player of policy not found", 404
        return offer, 200
    except ValueError, e:
        return str(e), 400
    
@require_api_key
@require_user_key
def buy_policy(player_id, offer):
    game = get_game()
    try:
        buy = game.buy_policy(player_id, offer)
        return buy, 200
    except ValueError, e:
        return str(e), 400
   
@require_api_key
@require_user_key
def claim_budget(player_id):
    game = get_game()
    try:
        player = game.get_player(player_id)
        if player is None:
            return "Player not found", 404
        player.claim_budget()
        return "budget claimed", 200
    except ValueError, e:
        return str(e), 400

@require_api_key
def create_table(table = None):
    game = get_game()
    table = game.create_table(table['name'])
    return generate_table_data(table), 201

@require_api_key
def clear_table(id):
    game = get_game()
    table = game.get_table(id)
    if not table:
        return "Table not found", 404

    game.clear_table(id)
    
    return "table cleared", 200

@require_api_key
def get_table(id):
    game = get_game()
    table = game.get_table(id)
    if not table:
        return "Table not found", 404

    data = generate_table_data(table)
    return data, 200

@require_api_key
def delete_table(id):
    game = get_game()
    if game.delete_table(id):
        return "Table deleted", 200
    else:
        return "Table not found", 404


def generate_table_data(table):
    game = get_game()
    name = table.name
    players = tuple(table.players)
    network = game.get_network(players)

    nodes = {}
    links = []

    for player_id in players:
        n = game.get_player(player_id)
        nodes[n.id] = {'id': n.id,
                       'name': n.name,
                       'group': 8,
                       'resources': "{:.2f}".format(n.balance),
                       }
        links.extend([edge_to_dict(e) for e in n.lower_edges])

    for n in network['policies']:
        data = node_to_dict2(n)
        data['group'] = 0
        nodes[n.id] = data
        links.extend([edge_to_dict(e) for e in n.lower_edges])

    for n in network['goals']:
        data = node_to_dict2(n)
        nodes[n.id] = data

    links = [ l for l in links 
              if l['source'] in nodes
              and l['target'] in nodes
              ]

    network =  {'nodes': nodes.values(), 'links': links}
    players_dict = [ player_to_dict(game,game.get_player(p)) for p in players ]

    return dict(id=table.id,
                name=name,
                players=players_dict,
                network=network,
                layout_checksum=edges_to_checksum(links),
                )

@require_api_key
def get_tables():
    game = get_game()
    tables = game.get_tables()
    return [ dict(id=t.id,name=t.name) for t in tables ], 200

@require_api_key
def get_metadata():
    return _get_metadata(), 200

def _get_metadata():
    game = get_game()
    settings = game.settings
    return {'game_year': settings.current_game_year,
            'game_year_start': settings.current_game_year_start,
            'next_game_year': settings.current_game_year+1 if settings.current_game_year else None,
            'next_game_year_start': settings.next_game_year_start if settings.next_game_year_start else None,
            'version': APP_VERSION,
            'total_players_inflow': game.total_players_inflow,
            'total_active_players_inflow': game.total_active_players_inflow,
            'budget_per_cycle': settings.budget_per_cycle,
            'max_spend_per_tick': settings.max_spend_per_tick,
            }

# move to game class
@require_api_key
def stop_game():
    game = get_game()
    year = game.stop()
    return "game stopped at year {}".format(year), 200

@require_api_key
def start_game(params):
    game = get_game()
    year = game.start(params['start_year'], params['end_year'], params['duration'], params['budget_per_player'])
    game.do_replenish_budget()
    return "game started, year {}".format(year), 200

@require_api_key
def set_messages(messages):
    game = get_game()
    game.clear_messages()
    for m in messages['budgets']:
        ts = dateutil.parser.parse(m['time']).replace(tzinfo=None)
        game.add_message(ts, "budget", m['message'])
    for m in messages['events']:
        ts = dateutil.parser.parse(m['time']).replace(tzinfo=None)
        game.add_message(ts, "event", m['message'])

@require_api_key
def get_messages():
    game = get_game()
    budgets = []
    events = []
    for m in sorted(game.get_messages(), key=lambda x: x.timestamp):
        data = message_to_dict(m)
        if m.type == 'budget':
            budgets.append(data)
        elif m.type == 'event':
            events.append(data)

    return dict(budgets=budgets, events=events), 200
