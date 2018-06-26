import unittest
from datetime import datetime, timedelta
import time
import dateutil
import mock
import transaction

import flask_testing

from models import Base, Edge, Node, Player, Goal, Policy, Funding, Budget
from network import Network
from game import Game, get_game
from utils import random
from wallet import Wallet
from main import app
from settings import APP_VERSION
from database import get_db

import json

def fake_get_random_goal(self):
    goals = tuple(self.get_goals())
    if goals:
        return sorted(goals, key=lambda x: x.name)[0]

def fake_get_n_policies(self, n=5):
    policies = list(self.get_policies())
    if not policies:
        return []
    return sorted(policies, key=lambda x: x.name)[:n]

goal_patcher = mock.patch('gameserver.game.Game.get_random_goal', new=fake_get_random_goal)
policy_patcher = mock.patch('gameserver.game.Game.get_n_policies', new=fake_get_n_policies)
goal_patcher.start()
policy_patcher.start()

class ModelTestCase(unittest.TestCase):

    def setUp(self):
        pass
    
    def tearDown(self):
        pass

class SimpleModelTests(ModelTestCase):

    def testNodeEdgeRelationship(self):

        n1 = Node.new('node 1')
        n2 = Node.new('node 2')
        e1 = Edge.new(n1, n2, 1.0)

        self.assertEqual(e1.higher_node, n1)
        self.assertEqual(e1.lower_node, n2)

    def testNodeEdgeBackRelationship(self):

        n1 = Node.new('node 1')
        n2 = Node.new('node 2')
        e1 = Edge.new(n1, n2, 1.0)

        self.assertEqual(n1.children, [n2,])
        self.assertEqual(n2.parents, [n1,])

    def testNodeSetBalance(self):

        n1 = Node.new('node 1', balance=1000)
        self.assertEqual(n1.balance, 1000.0)

def setup_with_context_manager(testcase, cm):
    """Use a contextmanager to setUp a test case."""
    val = cm.__enter__()
    testcase.addCleanup(cm.__exit__, None, None, None)
    return val

class ControllerTestCase(ModelTestCase):

    def setUp(self):
        ModelTestCase.setUp(self)

        app.config['ZODB_STORAGE'] = 'memory://'
        app.config['TESTING'] = True
        setup_with_context_manager(self, app.test_request_context())
        self.game = get_game()
        self.game.start(2017, 2025, 10, 12000000)
        test_client = self.game.add_client('tests')
        self.api_key = test_client.id
        self.client = app.test_client()

    def tearDown(self):
        db = get_db()
        del db['game']
        
    def add_20_goals_and_policies(self):
        for x in range(20):
            id = "G{}".format(x)
            g = Goal(id=id)
            g.name = id
            self.game.network.goals[g.id] = g
            id = "P{}".format(x)
            p = Policy(id=id)
            p.name = id
            self.game.network.policies[p.id] = p


class ViewTestCase(ControllerTestCase):
    pass


class CoreGameTests(ControllerTestCase):

    def testRandomGoalIsRandom(self):
        self.add_20_goals_and_policies()

        g = self.game.get_random_goal()
        self.assertEqual(g.id, 'G0')

        goal_patcher.stop()

        g1 = self.game.get_random_goal()
        g2 = self.game.get_random_goal()
        g3 = self.game.get_random_goal()
        self.assertFalse(g1.id == g2.id == g3.id)

        goal_patcher.start()
        

    def testGetNPoliciesIsRandom(self):
        self.add_20_goals_and_policies()

        policies = self.game.get_n_policies()
        self.assertEqual([p.name for p in policies], [u'P0', u'P1', u'P10', u'P11', u'P12'])

        policy_patcher.stop()

        policies1 = [p.name for p in self.game.get_n_policies()]
        policies2 = [p.name for p in self.game.get_n_policies()]
        policies3 = [p.name for p in self.game.get_n_policies()]
        self.assertFalse(policies1 == policies2 == policies3)

        policy_patcher.start()

    def testAddPlayer(self):

        p1 = self.game.create_player('Matt')
        
        self.assertEqual(self.game.get_player(p1.id), p1)
        self.assertEqual(self.game.num_players, 1)

        p2 = self.game.create_player('Simon')

        self.assertEqual(self.game.get_player(p2.id), p2)
        self.assertEqual(self.game.num_players, 2)

    def testGameCreatePlayer(self):
        
        self.add_20_goals_and_policies()

        p = self.game.create_player('Matt')
        self.assertEqual(self.game.get_player(p.id), p)
        self.assertEqual(self.game.get_goal(p.goal_id).name, 'G0')
        policies = p.policies
        self.assertEqual(sorted([x for x in policies]), sorted([u'P0', u'P1', u'P10', u'P11', u'P12']))

    def testGameClearPlayers(self):
        self.add_20_goals_and_policies()
        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        self.assertEqual(len(self.game.network.players), 2)
        self.assertEqual(len(self.game.network.goals), 20)

        self.game.clear_players()
        
        self.assertEqual(len(self.game.network.players), 0)
        self.assertEqual(len(self.game.network.goals), 20)

    def testPlayerHasWallet(self):

        p = self.game.create_player('Matt')

        self.assertEqual(self.game.get_player(p.id), p)
        self.assertAlmostEqual(p.balance, self.game.settings.budget_per_cycle)

    def testPlayerSetBalance(self):

        p = self.game.create_player('Matt')
        p.balance = 5000

        self.assertAlmostEqual(p.balance, 5000.0)

    def testAddPolicy(self):

        p = self.game.add_policy('Arms Embargo', leak=0.1)

        self.assertEqual(self.game.get_policy(p.id), p)
        self.assertEqual(self.game.get_policy(p.id).leak, 0.1)

    def testAddWalletToPolicy(self):

        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        p1 = self.game.create_player('Matt')
        w1 = Wallet([(p1.id, 100)])
        po1.wallet = w1

        self.assertIn(p1.id, w1.todict())
        self.assertEqual(po1.wallet, w1)


    def testAddGoal(self):

        g = self.game.add_goal('World Peace', leak=0.5)
        self.assertEqual(self.game.get_goal(g.id), g)
        self.assertEqual(self.game.get_goal(g.id).leak, 0.5)

    def testGetRandomGoal(self):
        
        self.add_20_goals_and_policies()

        self.assertEqual(self.game.get_random_goal().name, 'G0')

    def testAddPlayerAndGoal(self):
        g1 = self.game.add_goal('World Peace')
        p1 = self.game.create_player('Matt', goal_id=g1.id)

        self.assertEqual(p1.goal_id, g1.id)
        self.assertIn(p1, self.game.get_players_for_goal(g1.id))

    def testAddWalletToGoal(self):

        g = self.game.add_goal('World Peace')
        p1 = self.game.create_player('Matt')
        w1 = Wallet([(p1.id, 100.0)])
        g.wallet = w1

        self.assertEqual(g.wallet, w1)

    def testGetNPolicies(self):
        g1 = self.game.add_goal('A')
        self.add_20_goals_and_policies()

        policies = [u'P0', u'P1', u'P10', u'P11', u'P12']
        self.assertEqual([x.name for x in self.game.get_n_policies()], policies)
        
    def testModifyPolicies(self):

        p1 = self.game.add_policy('Policy 1', leak=0.1)
        p2 = self.game.add_policy('Policy 2', leak=0.2)

        self.assertEqual(self.game.get_policy(p1.id).leak, 0.1)

        p1.leak = 0.3
        self.assertEqual(self.game.get_policy(p1.id).leak, 0.3)
        self.assertEqual(self.game.get_policy(p2.id).leak, 0.2)

    def testChildParentRelationship(self):
        a = Node.new('A')
        b = Node.new('B')

        l = self.game.add_link(a, b, 1.0)
        self.assertIn(a, b.parents)
        self.assertIn(b, a.children)

    def testPlayerFundedPolicies(self):
        p1 = self.game.add_policy('Policy 1')
        p2 = self.game.add_policy('Policy 2')
        p3 = self.game.add_policy('Policy 3')
        p = self.game.create_player('Matt')

        self.game.set_policy_funding_for_player(p, [(p1.id,20), (p2.id,30), (p3.id, 0)])

        self.assertEqual(sorted(p.policies), sorted([p1.id,p2.id,p3.id]))
        self.assertEqual(sorted(p.funded_policies), sorted([p1.id,p2.id]))

    def testSimpleNetwork(self):
        n1 = self.game.add_policy('Policy 1')
        n2 = self.game.add_goal('Goal 1')
        l1 = self.game.add_link(n1, n2, 0.5)

        self.assertEqual(self.game.get_link(l1.id), l1)
        self.assertIn(n2, n1.children)
        
    def testMultiLevelNetwork(self):
        n1 = self.game.add_policy('Policy 1')
        n2 = self.game.add_policy('Policy 2')
        n3 = self.game.add_goal('Goal 1')
        
        l1 = self.game.add_link(n1, n2, 0.5)
        l2 = self.game.add_link(n2, n3, 0.5)

        self.assertEqual(n3, n1.children[0].children[0])

    def testAddWallets(self):
        n1 = self.game.add_policy('Policy 1')
        p1 = self.game.create_player('Matt')

        self.assertEqual(n1.balance, 0)

        w1 = Wallet([(p1.id, 5.0)])
        self.assertEqual(n1.balance, 0)
        n1.wallet = w1
        self.assertEqual(n1.balance, 5.0)

        w2 = Wallet([(p1.id, 10.0)])
        n1.wallet &= w2

        self.assertEqual(n1.balance, 15.0)

    def testNodeLeak2(self):
        n1 = self.game.add_policy('Policy 1', leak=2.0)
        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        n1.wallet = Wallet([(p1.id, 5.0),
                            (p2.id, 10.0),])

        self.assertEqual(n1.balance, 15.0)
        n1.do_leak()
        self.assertAlmostEqual(n1.balance, 13.0, 5)
        n1.do_leak()
        self.assertEqual(n1.balance, 11.0)

    def testNodeLeak0(self):
        n1 = self.game.add_policy('Policy 1', leak=0.0)
        p1 = self.game.create_player('Matt')
        n1.wallet = Wallet([(p1.id, 15.0)])

        self.assertEqual(n1.balance, 15.0)
        n1.do_leak()
        self.assertEqual(n1.balance, 15.0)
        n1.do_leak()
        self.assertEqual(n1.balance, 15.0)

    def testNodeLeak5(self):
        n1 = self.game.add_policy('Policy 1', leak=5.0)
        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        n1.wallet = Wallet([(p1.id, 5.0),
                            (p2.id, 10.0),])

        self.assertEqual(n1.balance, 15.0)
        n1.do_leak()
        self.assertAlmostEqual(n1.balance, 10.0, 5)
        n1.do_leak()
        self.assertAlmostEqual(n1.balance, 5.0, 5)

        # Check the individual wallets
        d = n1.wallet.todict()
        self.assertAlmostEqual(d[p1.id], 1.66666, 3)
        self.assertAlmostEqual(d[p2.id], 3.33333, 3)

    def testNodeLeakNegative20(self):
        n1 = self.game.add_policy('Policy 1', leak=0.2)
        g1 = self.game.add_goal('Goal 1', leak=0.2)
        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        g1.wallet = Wallet([(p1.id, 5.0),
                            (p2.id, 10.0),])

        # add a negative impact edge
        l1 = self.game.add_link(n1, g1, -0.5)

        self.assertEqual(g1.balance, 15.0)
        g1.do_leak()
        self.assertAlmostEqual(g1.balance, 4.5)
        g1.do_leak()
        self.assertAlmostEqual(g1.balance, 1.35)

        # Check the individual wallets
        d = g1.wallet.todict()
        self.assertAlmostEqual(d[p1.id], 0.45, 5)
        self.assertAlmostEqual(d[p2.id], 0.9, 5)
###

    @unittest.skip
    def testNodeLeak100(self):
        n1 = self.game.add_policy('Policy 1', leak=1.0)
        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        n1.wallet = Wallet([(p1.id, 5.0),
                            (p2.id, 10.0),])

        self.assertEqual(n1.balance, 15.0)
        n1.do_leak()
        self.assertEqual(n1.balance, 0.0)
        n1.do_leak()
        self.assertEqual(n1.balance, 0.0)

    @unittest.skip
    def testNodeLeak0(self):
        n1 = self.game.add_policy('Policy 1', leak=0.0)
        p1 = self.game.create_player('Matt')
        n1.wallet = Wallet([(p1.id, 15.0)])

        self.assertEqual(n1.balance, 15.0)
        n1.do_leak()
        self.assertEqual(n1.balance, 15.0)
        n1.do_leak()
        self.assertEqual(n1.balance, 15.0)

    @unittest.skip
    def testNodeLeak20(self):
        n1 = self.game.add_policy('Policy 1', leak=0.2)
        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        n1.wallet = Wallet([(p1.id, 5.0),
                            (p2.id, 10.0),])

        self.assertEqual(n1.balance, 15.0)
        n1.do_leak()
        self.assertAlmostEqual(n1.balance, 12.0, 5)
        n1.do_leak()
        self.assertAlmostEqual(n1.balance, 9.6, 5)

        # Check the individual wallets
        d = n1.wallet.todict()
        self.assertAlmostEqual(d[p1.id], 3.2, 5)
        self.assertAlmostEqual(d[p2.id], 6.4, 5)

    @unittest.skip
    def testNodeLeakNegative20(self):
        n1 = self.game.add_policy('Policy 1', leak=0.2)
        g1 = self.game.add_goal('Goal 1', leak=0.2)
        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        g1.wallet = Wallet([(p1.id, 5.0),
                            (p2.id, 10.0),])

        # add a negative impact edge
        l1 = self.game.add_link(n1, g1, -0.5)

        self.assertEqual(g1.balance, 15.0)
        g1.do_leak()
        self.assertAlmostEqual(g1.balance, 4.5)
        g1.do_leak()
        self.assertAlmostEqual(g1.balance, 1.35)

        # Check the individual wallets
        d = g1.wallet.todict()
        self.assertAlmostEqual(d[p1.id], 0.45, 5)
        self.assertAlmostEqual(d[p2.id], 0.9, 5)
###

    def testTransferWalletToWallet(self):
        p1 = self.game.create_player('Matt')
        w1 = Wallet([(p1.id, 100.0)])
        w2 = Wallet([(p1.id, 20.0)])

        self.assertAlmostEqual(w1.total, 100.0)
        self.assertAlmostEqual(w2.total, 20.0)

        w1.transfer(w2, 30.0)

        self.assertAlmostEqual(w1.total, 70.0)
        self.assertAlmostEqual(w2.total, 50.0)

    def testTransferToWalletInsufficientFunds(self):
        n1 = self.game.add_policy('Policy 1')
        p1 = self.game.create_player('Matt')
        n1.wallet = Wallet([(p1.id, 100.0)])
        n2 = self.game.add_policy('Policy 2')

        self.assertAlmostEqual(n1.balance, 100.0)
        self.assertAlmostEqual(n2.balance, 0.0)

        with self.assertRaises(ValueError):
            n1.wallet.transfer(n2.wallet, 110.0)

        self.assertAlmostEqual(n1.wallet.total, 100.0)
        self.assertAlmostEqual(n2.wallet.total, 0.0)


    def testAllocateFunds(self):
        p1 = self.game.create_player('Matt', balance=1000)
        n1 = self.game.add_policy('Policy 1', leak=1.0)

        self.assertEqual(p1.balance, 1000.0)
        self.assertEqual(n1.balance, 0.0)

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 1000.0)
        self.assertEqual(n1.balance, 0.0)

        self.game.set_policy_funding_for_player(p1, [(n1.id, 100),])

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 900.0)
        self.assertEqual(n1.balance, 100.0)

    def testAllocateDifferentFunds(self):
        p1 = self.game.create_player('Matt', balance=1000)
        n1 = self.game.add_policy('Policy 1', leak=1.0)

        self.game.set_policy_funding_for_player(p1, [(n1.id, 60),])

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 940.0)
        self.assertEqual(n1.balance, 60.0)

        self.game.set_policy_funding_for_player(p1, [(n1.id, 80),])

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 860.0)
        self.assertEqual(n1.balance, 140.0)

    def testDeleteFunds(self):
        p1 = self.game.create_player('Matt')
        p1.balance = 1000.0
        n1 = self.game.add_policy('Policy 1', leak=1.0)

        self.game.set_policy_funding_for_player(p1, [(n1.id, 100),])
        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 900.0)
        self.assertEqual(n1.balance, 100.0)

        self.game.set_policy_funding_for_player(p1, [(n1.id, 0),])
        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 900.0)
        self.assertEqual(n1.balance, 100.0)

        # test that we keep the link even when funding stopped
        self.assertEqual(len(p1.policies), 1)

    def testGameTotalInflow(self):
        p1 = self.game.create_player('Matt')
        self.assertEqual(self.game.total_players_inflow, 1000)
        p2 = self.game.create_player('Simon')
        self.assertEqual(self.game.total_players_inflow, 2000)

    def testGameTotalActiveInflow(self):
        p1 = self.game.create_player('Matt')
        p1.unclaimed_budget = 1500000
        self.assertEqual(self.game.total_active_players_inflow, 1000)
        p2 = self.game.create_player('Simon')
        self.assertEqual(self.game.total_active_players_inflow, 2000)

        p1.last_budget_claim = datetime.now()-timedelta(hours=6)
        self.assertEqual(self.game.total_active_players_inflow, 1000)

        p1.claim_budget()
        self.assertEqual(self.game.total_active_players_inflow, 2000)


    def testPlayerTotalFunding(self):
        p1 = self.game.create_player('Matt', balance=1000)
        po1 = self.game.add_policy('Policy 1', leak=1.0)
        po2 = self.game.add_policy('Policy 2', leak=1.0)
        po3 = self.game.add_policy('Policy 3', leak=1.0)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 10), (po2.id, 20), (po3.id, 30)])

        self.assertEqual(p1.total_funding, 60)

        self.game.set_policy_funding_for_player(p1, [(po1.id, 10), (po2.id, 20), (po3.id, 10)])
        self.assertEqual(p1.total_funding, 40)

        self.game.set_policy_funding_for_player(p1, [(po1.id, 10), (po2.id, 0), (po3.id, 10)])
        self.assertEqual(p1.total_funding, 20)

    def testPlayerMaxOutflow(self):
        p1 = self.game.create_player('Matt')
        self.assertEqual(p1.max_outflow, self.game.settings.max_spend_per_tick)
        
    def testPlayerExceedMaxOutflow(self):
        p1 = self.game.create_player('Matt', balance=1000, max_outflow=1000)
        po1 = self.game.add_policy('Policy 1', leak=1.0)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 100),])
        po2 = self.game.add_policy('Policy 2', leak=1.0)
        self.game.set_policy_funding_for_player(p1, [(po2.id, 200),])
        po3 = self.game.add_policy('Policy 3', leak=1.0)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 100), (po2.id, 200)])

        with self.assertRaises(ValueError):
            self.game.set_policy_funding_for_player(p1, [(po1.id, 100), (po2.id, 200), (po3.id, 800)])

        self.assertEqual(p1.total_funding, 300)

        self.game.set_policy_funding_for_player(p1, [(po1.id, 100), (po2.id, 200), (po3.id, 700)])
        self.assertEqual(p1.total_funding, 1000)

    def testGoalActive(self):
        p1 = self.game.create_player('Player 1', balance=1000)
        po1 = self.game.add_policy('Policy 1')
        g1 = self.game.add_goal('Goal 1', activation=400)
        l1 = self.game.add_link(po1, g1, 200.0)
        p1.goal_id = g1.id
        self.game.set_policy_funding_for_player(p1, [(po1.id, 200.0),])


        self.assertAlmostEqual(self.game.goal_funded_by_player(p1.id), 0.0)        
        self.game.do_propogate_funds()

        self.assertAlmostEqual(p1.balance, 800)

        self.assertAlmostEqual(g1.balance, 200)
        self.assertAlmostEqual(self.game.goal_funded_by_player(p1.id), 200)

        self.assertFalse(g1.active)

        self.game.do_propogate_funds()
        self.assertTrue(g1.active)


    def testNodeActivationFromPlayer(self):
        p1 = self.game.create_player('Matt', balance=1000)
        po1 = self.game.add_policy('Policy 1', activation=0.2)

        self.assertFalse(po1.active)
        self.assertAlmostEqual(po1.active_level, 0)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 200.0),])
        self.game.do_propogate_funds()
        
        self.assertTrue(po1.active)

    def testNodeActivationFromNode(self):
        p1 = self.game.create_player('Matt', balance=10000)
        po1 = self.game.add_policy('Policy 1', activation=0.1)

        self.assertAlmostEqual(po1.active_level, 0)
        self.assertFalse(po1.active)

        po2 = self.game.add_policy('Policy 2', activation=0.2)
        l1 = self.game.add_link(po1, po2, 50.0)

        self.assertAlmostEqual(po1.active, 0.0)
        self.assertFalse(po1.active)

        self.game.set_policy_funding_for_player(p1, [(po1.id, 200.0),])
        for x in range(5):
            self.game.do_propogate_funds()
        
        self.assertTrue(po1.active)
        self.assertAlmostEqual(po1.active_level, 0.2)
        self.assertAlmostEqual(po1.active_percent, 2.0)
        self.assertFalse(po2.active)

        self.game.set_policy_funding_for_player(p1, [(po1.id, 400.0),])
        self.assertTrue(po1.active)
        self.assertAlmostEqual(po1.active_percent, 2.0)
        self.assertFalse(po2.active)
        self.assertAlmostEqual(po2.active_percent, 0.25)

        l1.weight = 400.0
        self.game.do_propogate_funds()
        self.assertTrue(po1.active)
        self.assertTrue(po2.active)
        self.assertAlmostEqual(po2.active_percent, 2.0)

    def testTwoPlayersFundPolicy(self):
        p1 = self.game.create_player('Matt', balance=1000)
        p2 = self.game.create_player('Simon', balance=1000)
        n1 = self.game.add_policy('Policy 1')

        self.game.set_policy_funding_for_player(p1, [(n1.id, 100),])
        self.game.set_policy_funding_for_player(p2, [(n1.id, 90),])

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 900.0)
        self.assertEqual(p2.balance, 910.0)
        self.assertEqual(n1.balance, 190.0)

    def testGameTransferFunds(self):
        p1 = self.game.create_player('Matt', balance=1000)
        p2 = self.game.create_player('Simon', balance=1000)
        p3 = self.game.create_player('Rich', balance=1000)
    
        n1 = self.game.add_policy('Policy 1')

        self.game.set_policy_funding_for_player(p1, [(n1.id, 10),])
        self.game.set_policy_funding_for_player(p2, [(n1.id, 20),])
        self.game.set_policy_funding_for_player(p3, [(n1.id, 50),])

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 990.0)
        self.assertEqual(p2.balance, 980.0)
        self.assertEqual(p3.balance, 950.0)
        self.assertEqual(n1.balance, 80.0)

    def testGameTransferFundsNoMaxLevel(self):
        p1 = self.game.create_player('Matt', balance=1000)
    
        n1 = self.game.add_policy('Policy 1', max_level=0)
        self.game.set_policy_funding_for_player(p1, [(n1.id, 10),])

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 990.0)
        self.assertEqual(n1.balance, 10.0)

    def testGameTransferFundsMaxLevel(self):
        p1 = self.game.create_player('Matt', balance=1000)
    
        n1 = self.game.add_policy('Policy 1', leak=1.0, max_level=5.0)
        self.game.set_policy_funding_for_player(p1, [(n1.id, 10),])

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 990.0)
        self.assertEqual(n1.balance, 5.0)

    def testGameTransferFundsMaxLevelMultiplePlayers(self):
        p1 = self.game.create_player('Matt', balance=1000)
        p2 = self.game.create_player('Simon', balance=1000)

        n1 = self.game.add_policy('Policy 1', max_level=5.0)
        self.game.set_policy_funding_for_player(p1, [(n1.id, 10),])
        self.game.set_policy_funding_for_player(p2, [(n1.id, 5),])

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 990.0)
        self.assertEqual(p2.balance, 995.0)
        self.assertEqual(n1.balance, 5.0)

    def testGameTransferFundsComplex(self):
        p1 = self.game.create_player('Matt', balance=1000)
        p2 = self.game.create_player('Simon', balance=1000)
        p3 = self.game.create_player('Rich', balance=1000)
    
        n1 = self.game.add_policy('Policy 1')
        n2 = self.game.add_policy('Policy 2')

        self.game.set_policy_funding_for_player(p1, [(n1.id, 10),])
        self.game.set_policy_funding_for_player(p2, [(n1.id, 20),(n2.id, 50)])
        self.game.set_policy_funding_for_player(p3, [(n1.id, 50),(n2.id, 40)])

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 990.0)
        self.assertEqual(p2.balance, 930.0)
        self.assertEqual(p3.balance, 910.0)
        self.assertEqual(n1.balance, 80.0)
        self.assertEqual(n2.balance, 90.0)

    def testAllocateFundsMultiplePolicies(self):
        p1 = self.game.create_player('Matt', balance=1000)
        n1 = self.game.add_policy('Policy 1')
        n2 = self.game.add_policy('Policy 2')

        self.assertEqual(p1.balance, 1000.0)
        self.assertEqual(n1.balance, 0.0)
        self.assertEqual(n2.balance, 0.0)

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 1000.0)
        self.assertEqual(n1.balance, 0.0)
        self.assertEqual(n2.balance, 0.0)

        self.game.set_policy_funding_for_player(p1, [(n1.id, 10), (n2.id, 30)])

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 960.0)
        self.assertEqual(n1.balance, 10.0)
        self.assertEqual(n2.balance, 30.0)

    def testGameLeak100(self):
        n1 = self.game.add_policy('Policy 1', leak=1.0)
        n2 = self.game.add_policy('Policy 2', leak=1.0)
        p1 = self.game.create_player('Matt')
        n1.wallet = Wallet([(p1.id, 100.0)])
        n2.wallet = Wallet([(p1.id, 100.0)])

        self.assertEqual(n1.balance, 100.0)
        self.assertEqual(n2.balance, 100.0)

        self.game.do_leak()
        self.assertEqual(n1.balance, 0.0)
        self.assertEqual(n2.balance, 0.0)

    def testGameLeak0_100(self):
        n1 = self.game.add_policy('Policy 1', leak=0.0)
        n2 = self.game.add_policy('Policy 2', leak=1.0)
        p1 = self.game.create_player('Matt')
        n1.wallet = Wallet([(p1.id, 100.0)])
        n2.wallet = Wallet([(p1.id, 100.0)])

        self.assertEqual(n1.balance, 100.0)
        self.assertEqual(n2.balance, 100.0)

        self.game.do_leak()
        self.assertEqual(n1.balance, 100.0)
        self.assertAlmostEqual(n2.balance, 99.0, 5)

    def testGameLeak50(self):
        n1 = self.game.add_policy('Policy 1', leak=0.5)
        n2 = self.game.add_policy('Policy 2', leak=0.2)
        p1 = self.game.create_player('Matt')
        n1.wallet = Wallet([(p1.id, 100.0)])
        n2.wallet = Wallet([(p1.id, 100.0)])

        self.assertEqual(n1.balance, 100.0)
        self.assertEqual(n2.balance, 100.0)

        self.game.do_leak()
        self.assertAlmostEqual(n1.balance, 50.0)
        self.assertAlmostEqual(n2.balance, 80.0)

        self.game.do_leak()
        self.assertAlmostEqual(n1.balance, 25.0)
        self.assertAlmostEqual(n2.balance, 64.0)

    @unittest.skip
    def testGameLeak100(self):
        n1 = self.game.add_policy('Policy 1', leak=1.0)
        n2 = self.game.add_policy('Policy 2', leak=1.0)
        p1 = self.game.create_player('Matt')
        n1.wallet = Wallet([(p1.id, 100.0)])
        n2.wallet = Wallet([(p1.id, 100.0)])

        self.assertEqual(n1.balance, 100.0)
        self.assertEqual(n2.balance, 100.0)

        self.game.do_leak()
        self.assertEqual(n1.balance, 0.0)
        self.assertEqual(n2.balance, 0.0)

    @unittest.skip
    def testGameLeak0_100(self):
        n1 = self.game.add_policy('Policy 1', leak=0.0)
        n2 = self.game.add_policy('Policy 2', leak=1.0)
        p1 = self.game.create_player('Matt')
        n1.wallet = Wallet([(p1.id, 100.0)])
        n2.wallet = Wallet([(p1.id, 100.0)])

        self.assertEqual(n1.balance, 100.0)
        self.assertEqual(n2.balance, 100.0)

        self.game.do_leak()
        self.assertEqual(n1.balance, 100.0)
        self.assertEqual(n2.balance, 0.0)

    @unittest.skip
    def testGameLeak50(self):
        n1 = self.game.add_policy('Policy 1', leak=0.5)
        n2 = self.game.add_policy('Policy 2', leak=0.2)
        p1 = self.game.create_player('Matt')
        n1.wallet = Wallet([(p1.id, 100.0)])
        n2.wallet = Wallet([(p1.id, 100.0)])

        self.assertEqual(n1.balance, 100.0)
        self.assertEqual(n2.balance, 100.0)

        self.game.do_leak()
        self.assertAlmostEqual(n1.balance, 50.0)
        self.assertAlmostEqual(n2.balance, 80.0)

        self.game.do_leak()
        self.assertAlmostEqual(n1.balance, 25.0)
        self.assertAlmostEqual(n2.balance, 64.0)

    def testGameGetWallets(self):
        p1 = self.game.create_player('Matt', balance=1000)
        p2 = self.game.create_player('Simon', balance=1000)
        n1 = self.game.add_policy('Policy 1')

        self.game.set_policy_funding_for_player(p1, [(n1.id, 100),])
        self.game.set_policy_funding_for_player(p2, [(n1.id, 90),])
        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 900.0)
        self.assertEqual(p2.balance, 910.0)
        self.assertEqual(n1.balance, 190.0)

        expected = {p1.id: 100.0,
                    p2.id: 90.0,}

        wallets = self.game.get_wallets_by_location(n1.id)

        self.assertEqual(wallets, expected)

    def testFundPlayers(self):
        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        p3 = self.game.create_player('Rich')

        self.game.do_replenish_budget()

        self.assertAlmostEqual(p1.balance, self.game.settings.budget_per_cycle)
        self.assertAlmostEqual(p2.balance, self.game.settings.budget_per_cycle)
        self.assertAlmostEqual(p3.balance, self.game.settings.budget_per_cycle)

        n1 = self.game.add_policy('Policy 1')

        p1.transfer_funds_to_node(n1, 100)
        p2.transfer_funds_to_node(n1, 200)
        p3.transfer_funds_to_node(n1, 400)

        self.assertAlmostEqual(p1.balance, self.game.settings.budget_per_cycle-100)
        self.assertAlmostEqual(p2.balance, self.game.settings.budget_per_cycle-200)
        self.assertAlmostEqual(p3.balance, self.game.settings.budget_per_cycle-400)

        self.assertAlmostEqual(n1.balance, 100+200+400)

        self.game.do_replenish_budget()

        self.assertAlmostEqual(p1.balance, self.game.settings.budget_per_cycle-100)
        self.assertAlmostEqual(p2.balance, self.game.settings.budget_per_cycle-200)
        self.assertAlmostEqual(p3.balance, self.game.settings.budget_per_cycle-400)

        self.assertAlmostEqual(p1.unclaimed_budget, self.game.settings.budget_per_cycle)
        self.assertAlmostEqual(p2.unclaimed_budget, self.game.settings.budget_per_cycle)
        self.assertAlmostEqual(p3.unclaimed_budget, self.game.settings.budget_per_cycle)


        self.assertAlmostEqual(n1.balance, 100+200+400)
        

    def testGameTransfer15_30(self):
        n1 = self.game.add_policy('Policy 1')
        n2 = self.game.add_policy('Policy 2')
        n3 = self.game.add_policy('Policy 3')
        p1 = self.game.create_player('Matt')
        l1 = self.game.add_link(n1, n2, 15.0)
        l2 = self.game.add_link(n1, n3, 30.0)

        self.game.network.rank()
        
        self.game.do_replenish_budget()

        p1.transfer_funds_to_node(n1, 100)

        self.assertEqual(n1.balance, 100)
        self.assertEqual(n2.balance, 0)
        self.assertEqual(n3.balance, 0)
        
        self.game.do_propogate_funds()

        self.assertAlmostEqual(n1.balance, 55.0)
        self.assertAlmostEqual(n2.balance, 15.0)
        self.assertAlmostEqual(n3.balance, 30.0)

        self.game.do_propogate_funds()

        self.assertAlmostEqual(n1.balance, 10.0)
        self.assertAlmostEqual(n2.balance, 30.0)
        self.assertAlmostEqual(n3.balance, 60.0)


    def testRankNodes(self):
        n1 = self.game.add_policy('Policy 1', leak=0.5)
        n2 = self.game.add_policy('Policy 2', leak=0.5)
        n3 = self.game.add_policy('Policy 3', leak=0.5)
        n4 = self.game.add_policy('Policy 4', leak=0.5)
        n5 = self.game.add_policy('Policy 5', leak=0.5)
        g1 = self.game.add_goal('Goal 1', leak=0.5)
        g2 = self.game.add_goal('Goal 2', leak=0.5)
        g3 = self.game.add_goal('Goal 3', leak=0.5)
        p1 = self.game.create_player('Matt')

        l1 = self.game.add_link(n1, n2, 4.0)
        l2 = self.game.add_link(n1, n3, 3.0)
        l3 = self.game.add_link(n3, n5, 3.0)
        l4 = self.game.add_link(n5, n4, 3.0)

        l5 = self.game.add_link(n2, g1, 1.0)
        l6 = self.game.add_link(n4, g2, 3.0)
        l7 = self.game.add_link(n3, g3, 5.0)

        self.game.do_replenish_budget()

        self.assertEqual(n1.balance, 0)
        self.assertEqual(n2.balance, 0)
        self.assertEqual(n3.balance, 0)

        self.assertEqual(g1.balance, 0)
        self.assertEqual(g2.balance, 0)
        self.assertEqual(g3.balance, 0)

        self.game.network.rank()
        self.assertEqual(self.game.get_ranked_nodes(), [ n1, n2, n3, n5, g1, g3, n4, g2 ])

    def testGameTransfer50_goal(self):
        n1 = self.game.add_policy('Policy 1', leak=0.5)
        n2 = self.game.add_policy('Policy 2', leak=0.5)
        n3 = self.game.add_policy('Policy 3', leak=0.5)
        g1 = self.game.add_goal('Goal 1', leak=0.5)
        g2 = self.game.add_goal('Goal 2', leak=0.5)
        g3 = self.game.add_goal('Goal 3', leak=0.5)
        p1 = self.game.create_player('Matt')

        l1 = self.game.add_link(n1, n2, 4.0)
        l2 = self.game.add_link(n1, n3, 3.0)

        l3 = self.game.add_link(n2, g1, 1.0)
        l4 = self.game.add_link(n3, g2, 3.0)
        l5 = self.game.add_link(n3, g3, 5.0)

        self.game.do_replenish_budget()

        self.assertEqual(n1.balance, 0)
        self.assertEqual(n2.balance, 0)
        self.assertEqual(n3.balance, 0)

        self.assertEqual(g1.balance, 0)
        self.assertEqual(g2.balance, 0)
        self.assertEqual(g3.balance, 0)

        for i in range(200):
            p1.transfer_funds_to_node(n1, 10)
            p1.transfer_funds_to_node(n2, 10)
            p1.transfer_funds_to_node(n3, 10)
            self.game.do_propogate_funds()

        self.assertAlmostEqual(n1.balance, 600.0)
        self.assertAlmostEqual(n2.balance, 2600.0)
        self.assertAlmostEqual(n3.balance, 1000.0)

        self.assertAlmostEqual(g1.balance, 200.0)
        self.assertAlmostEqual(g2.balance, 600.0)
        self.assertAlmostEqual(g3.balance, 1000.0)


    def testSimpleNetwork(self):
        p1 = self.game.create_player('Player 1', balance=1000)
        po1 = self.game.add_policy('Policy 1')
        g1 = self.game.add_goal('Goal 1')
        g2 = self.game.add_goal('Goal 2')

        l1 = self.game.add_link(po1, g1, 3.0)
        l2 = self.game.add_link(po1, g2, 4.0)

        p1.transfer_funds_to_node(po1, 10)

        self.game.do_propogate_funds()

        self.assertAlmostEqual(p1.balance, 990)

        self.assertAlmostEqual(g1.balance, 3.0)
        self.assertAlmostEqual(g2.balance, 4.0)

    def testSimpleNetworkLessThanBalance(self):
        p1 = self.game.create_player('Player 1', balance=1000)
        po1 = self.game.add_policy('Policy 1')
        g1 = self.game.add_goal('Goal 1')
        g2 = self.game.add_goal('Goal 2')

        l1 = self.game.add_link(po1, g1, 10.0)
        l2 = self.game.add_link(po1, g2, 40.0)

        p1.transfer_funds_to_node(po1, 10)

        self.game.do_propogate_funds()

        self.assertAlmostEqual(p1.balance, 990)

        self.assertAlmostEqual(g1.balance, 2.0)
        self.assertAlmostEqual(g2.balance, 8.0)

    def testSimpleNetworkTwoWallets(self):
        p1 = self.game.create_player('Player 1', balance=1000)
        p2 = self.game.create_player('Player 2', balance=1000)
        po1 = self.game.add_policy('Policy 1')
        g1 = self.game.add_goal('Goal 1',)
        g2 = self.game.add_goal('Goal 2')

        l1 = self.game.add_link(po1, g1, 3.0)
        l2 = self.game.add_link(po1, g2, 5.0)

        p1.transfer_funds_to_node(po1, 10)
        p2.transfer_funds_to_node(po1, 30)

        self.game.do_propogate_funds()

        self.assertAlmostEqual(p1.balance, 990)
        self.assertAlmostEqual(p2.balance, 970)

        self.assertAlmostEqual(g1.balance, 3.0)
        self.assertEqual(g1.wallet_owner_map, {p1.id: 0.75,
                                               p2.id: 2.25})
        
        self.assertAlmostEqual(g2.balance, 5.0)
        self.assertEqual(g2.wallet_owner_map, {p1.id: 1.25,
                                               p2.id: 3.75})

    def testSimpleNetworkTwoWalletsLessThanBalance(self):
        p1 = self.game.create_player('Player 1', balance=1000)
        p2 = self.game.create_player('Player 2', balance=1000)
        po1 = self.game.add_policy('Policy 1')
        g1 = self.game.add_goal('Goal 1')
        g2 = self.game.add_goal('Goal 2')

        l1 = self.game.add_link(po1, g1, 3.0)
        l2 = self.game.add_link(po1, g2, 5.0)

        p1.transfer_funds_to_node(po1, 1)
        p2.transfer_funds_to_node(po1, 3)

        self.assertAlmostEqual(p1.balance, 999)
        self.assertAlmostEqual(p2.balance, 997)
        self.assertAlmostEqual(po1.balance, 4)

        self.game.do_propogate_funds()

        self.assertAlmostEqual(g1.balance, 1.5)
        self.assertEqual(g1.wallet_owner_map, {p1.id: 0.375,
                                               p2.id: 1.125})
        
        self.assertAlmostEqual(g2.balance, 2.5)
        self.assertEqual(g2.wallet_owner_map, {p1.id: 0.625,
                                               p2.id: 1.875})
        

    def testSimplePlayerCoinsNetwork(self):
        p1 = self.game.create_player('Matt', balance=1000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 50),])

        self.assertEqual(p1.balance, 1000)
        self.assertEqual(po1.balance, 0)

        p1.transfer_funds_to_node(po1, 60)
        self.assertEqual(po1.balance, 60)

        self.assertEqual(p1.balance, 940)
        self.assertEqual(po1.balance, 60)

    def testTransferPartialFunds(self):
        p1 = self.game.create_player('Matt', balance=1000)
        po1 = self.game.add_policy('Arms Embargo')
        self.game.set_policy_funding_for_player(p1, [(po1.id, 100.0),])

        g1 = self.game.add_goal('World Peace')
        l1 = self.game.add_link(po1, g1, 1.0)

        self.game.do_propogate_funds()
        
        self.assertEqual(p1.balance, 900)
        self.assertEqual(po1.balance, 99.0)
        self.assertEqual(g1.balance, 1.0)

    def testTransferFullFunds(self):
        p1 = self.game.create_player('Matt', balance=1000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 100),])

        g1 = self.game.add_goal('World Peace', leak=1.0)
        l1 = self.game.add_link(po1, g1, 2.0)

        self.game.do_propogate_funds()
        
        self.assertEqual(p1.balance, 900)
        self.assertEqual(po1.balance, 98.0)
        self.assertEqual(g1.balance, 2.0)
        

    def testTransferGreaterThan100_300(self):
        p1 = self.game.create_player('Matt', balance=1000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 3.0),])

        self.assertEqual(p1.balance, 1000)
        self.assertEqual(po1.balance, 0)

        for x in range(50):
            self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 850)
        self.assertEqual(po1.balance, 150)


    def testTransferSlowFunds(self):
        p1 = self.game.create_player('Matt', balance=1000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 1.0)])

        g1 = self.game.add_goal('World Peace', leak=1.0)
        l1 = self.game.add_link(po1, g1, 2.0)

        self.game.do_propogate_funds()
        
        self.assertEqual(p1.balance, 999)
        self.assertEqual(po1.balance, 0.0)
        self.assertEqual(g1.balance, 1.0)

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 998)
        self.assertEqual(po1.balance, 0.0)
        self.assertEqual(g1.balance, 2.0)

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 997)
        self.assertEqual(po1.balance, 0.0)
        self.assertEqual(g1.balance, 3.0)

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 996)
        self.assertEqual(po1.balance, 0.0)
        self.assertEqual(g1.balance, 4.0)

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 995)
        self.assertEqual(po1.balance, 0.0)
        self.assertEqual(g1.balance, 5.0)
        
    def testTransferFastFunds(self):
        p1 = self.game.create_player('Matt', balance=1000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 3.0),])

        g1 = self.game.add_goal('World Peace', leak=1.0)
        l1 = self.game.add_link(po1, g1, 1.0)

        self.game.do_propogate_funds()
        
        self.assertEqual(p1.balance, 997)
        self.assertEqual(po1.balance, 2.0)
        self.assertEqual(g1.balance, 1.0)

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 994)
        self.assertEqual(po1.balance, 4.0)
        self.assertEqual(g1.balance, 2.0)

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 991)
        self.assertEqual(po1.balance, 6.0)
        self.assertEqual(g1.balance, 3.0)

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 988)
        self.assertEqual(po1.balance, 8.0)
        self.assertEqual(g1.balance, 4.0)

        self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 985)
        self.assertEqual(po1.balance, 10.0)
        self.assertEqual(g1.balance, 5.0)
        

    def testMoreComplexPlayerCoinsNetwork(self):
        p1 = self.game.create_player('Matt', balance=1000)
        po1 = self.game.add_policy('Arms Embargo')
        po2 = self.game.add_policy('Pollution control')
        self.game.set_policy_funding_for_player(p1, [(po1.id, 0.5), (po2.id, 1.0)])

        g1 = self.game.add_goal('World Peace')
        g2 = self.game.add_goal('Clean Water')
        l3 = self.game.add_link(po1, g1, 1.0)
        l4 = self.game.add_link(po2, g2, 2.0)

        self.assertEqual(p1.balance, 1000)
        self.assertEqual(po1.balance, 0)

        for x in range(100):
            self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 850)
        self.assertEqual(po1.balance, 0)
        self.assertEqual(po2.balance, 0)

        self.assertEqual(g1.balance, 50)
        self.assertEqual(g2.balance, 100)

    def testMoreComplexPlayerCoinsNetworkWithFullTick(self):
        p1 = self.game.create_player('Matt', balance=5000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        po2 = self.game.add_policy('Pollution control', leak=0.1)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 10.0), (po2.id, 15.0)])

        g1 = self.game.add_goal('World Peace', leak=0.5)
        g2 = self.game.add_goal('Clean Water', leak=0.5)
        l3 = self.game.add_link(po1, g1, 5.0)
        l4 = self.game.add_link(po2, g2, 9.0)

        self.assertEqual(p1.balance, 5000)
        self.assertEqual(po1.balance, 0)

        for x in range(100):
            self.game.tick()

        self.assertEqual(p1.balance, 2500)
        self.assertAlmostEqual(po1.balance, 490, 2)
        self.assertAlmostEqual(po2.balance, 60, 2)

        self.assertEqual(g1.balance, 10.0)
        self.assertEqual(g2.balance, 18.0)

    @unittest.skip
    def testMoreComplexPlayerCoinsNetworkWithFullTick(self):
        p1 = self.game.create_player('Matt', balance=5000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        po2 = self.game.add_policy('Pollution control', leak=0.1)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 10.0), (po2.id, 15.0)])

        g1 = self.game.add_goal('World Peace', leak=0.5)
        g2 = self.game.add_goal('Clean Water', leak=0.5)
        l3 = self.game.add_link(po1, g1, 5.0)
        l4 = self.game.add_link(po2, g2, 9.0)

        self.assertEqual(p1.balance, 5000)
        self.assertEqual(po1.balance, 0)

        for x in range(100):
            self.game.tick()

        self.assertEqual(p1.balance, 2500)
        self.assertAlmostEqual(po1.balance, 50, 2)
        self.assertAlmostEqual(po2.balance, 60, 2)

        self.assertEqual(g1.balance, 10.0)
        self.assertEqual(g2.balance, 18.0)

    def testTwoPlayersFundAPolicyEqually(self):
        p1 = self.game.create_player('Matt', balance=1000)
        p2 = self.game.create_player('Simon', balance=1000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 1.0),])
        self.game.set_policy_funding_for_player(p2, [(po1.id, 1.0),])

        self.assertEqual(po1.balance, 0)

        for x in range(100):
            self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 900)
        self.assertEqual(p2.balance, 900)

        self.assertEqual(po1.balance, 200)


    def testActivationLevelLow(self):
        p1 = self.game.create_player('Matt', balance=1000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1, activation=0.2)
        g1 = self.game.add_goal('World Peace', leak=0.5)

        f = self.game.set_policy_funding_for_player(p1, [(po1.id, 5.0),])
        l2 = self.game.add_link(po1, g1, 1.0)

        self.assertEqual(po1.balance, 0)

        for x in range(100):
            self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 500.0)
        self.assertEqual(po1.balance, 500.0)
        self.assertEqual(g1.balance, 0)

    def testActivationLevelHigh(self):
        p1 = self.game.create_player('Matt', balance=10000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1, activation=0.2)
        g1 = self.game.add_goal('World Peace', leak=0.5)

        f = self.game.set_policy_funding_for_player(p1, [(po1.id, 250.0),])
        l2 = self.game.add_link(po1, g1, 1.0)

        self.assertEqual(po1.balance, 0)

        for x in range(10):
            self.game.do_propogate_funds()

        self.assertEqual(p1.balance, 7500)
        self.assertEqual(po1.balance, 2490)
        self.assertEqual(g1.balance, 10)

    def testGetBudget(self):
        self.add_20_goals_and_policies()
        player = self.game.create_player('Matt', balance=1000)
        
        budget = self.game.get_policy_funding_for_player(player)
        actual = sorted([ {'policy_id': p, 'amount': amount} for (p,amount) in budget ])
        expected = sorted([{'amount': 0.0, 'policy_id': 'P0'}, 
                   {'amount': 0.0, 'policy_id': 'P1'}, 
                   {'amount': 0.0, 'policy_id': 'P10'}, 
                   {'amount': 0.0, 'policy_id': 'P11'}, 
                   {'amount': 0.0, 'policy_id': 'P12'}])

        self.assertEqual(expected, actual)

    def testSetBudget(self):
        self.add_20_goals_and_policies()
        player = self.game.create_player('Matt', balance=1000)
        
        fundings = [ ('P0', 10),
                     ('P1', 20),
                     ('P2', 30),
                     ]
                   
        self.game.set_policy_funding_for_player(player, fundings)

        budget = self.game.get_policy_funding_for_player(player)
        actual = sorted([ {'policy_id': p, 'amount': amount} for (p,amount) in budget if amount > 0])
        expected = sorted([{'amount': 10.0, 'policy_id': 'P0'}, 
                           {'amount': 20.0, 'policy_id': 'P1'}, 
                           {'amount': 30.0, 'policy_id': 'P2'}])

        self.assertEqual(expected, actual)

    def testCreateTable(self):
        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        table = self.game.create_table('table a')

        self.assertEqual(list(table.players), [])

        self.game.add_player_to_table(p1.id, table.id)
        
        self.assertEqual(list(table.players), [p1.id,])

        self.game.add_player_to_table(p2.id, table.id)
        
        self.assertEqual(sorted(list(table.players)), sorted([p1.id,p2.id]))

        self.game.remove_player_from_table(p1.id, table.id)
        
        self.assertEqual(list(table.players), [p2.id,])
        

    @unittest.skip("needs fixing after network re-jig")
    def testGetNetworkForTable(self):

        data = json.load(open('examples/network.json', 'r'))
        self.game.create_network(data)
        
        t1 = self.game.create_table('T1')

        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        p3 = self.game.create_player('Richard')

        table_uuid = default_uuid()

        self.assertEqual(self.game.get_network_for_table('nonexistant'), None)

        table = self.game.get_network_for_table(t1.id)
        self.assertEqual(len(table['goals']), 6)
        self.assertEqual(len(table['policies']), 30)

        t1.players.append(p1)

        table = self.game.get_network_for_table(t1.id)
        self.assertEqual(len(table['goals']), 1)
        self.assertEqual(len(table['policies']), 5)

        t1.players.append(p2)

        table = self.game.get_network_for_table(t1.id)
        self.assertEqual(len(table['goals']), 2)
        self.assertEqual(len(table['policies']), 7)

        p2.table = None

        table = self.game.get_network_for_table(t1.id)
        self.assertEqual(len(table['goals']), 1)
        self.assertEqual(len(table['policies']), 5)

    def testTopPlayers(self):
        g1 = self.game.add_goal('G1')
        g2 = self.game.add_goal('G2')

        po1 = self.game.add_policy('Po1')
        po2 = self.game.add_policy('Po2')

        self.game.add_link(po1, g1, 100)
        self.game.add_link(po2, g2, 100)

        p1 = self.game.create_player('Matt', goal_id=g1.id)
        p2 = self.game.create_player('Simon', goal_id=g1.id)
        p3 = self.game.create_player('Richard', goal_id=g2.id)

        self.game.set_policy_funding_for_player(p1, [(po1.id, 10),])
        self.game.set_policy_funding_for_player(p2, [(po1.id, 20),(po2.id, 40),])
        self.game.set_policy_funding_for_player(p3, [(po2.id, 15),])

        self.game.tick()

        self.assertEqual(p1.balance, 1499990)
        self.assertEqual(p2.balance, 1499940)
        self.assertEqual(p3.balance, 1499985)

        top = self.game.top_players()
        self.assertEqual(top, [p2,p3,p1])

        self.game.set_policy_funding_for_player(p1, [(po1.id, 100),])

        self.game.tick()

        top = self.game.top_players()
        self.assertEqual(top, [p1,p2,p3])

    def testGoalFunded(self):
        g1 = self.game.add_goal('G1')
        g2 = self.game.add_goal('G2')

        po1 = self.game.add_policy('Po1')
        po2 = self.game.add_policy('Po2')

        l1 = self.game.add_link(po1, g1, 100)
        l2 = self.game.add_link(po2, g2, 100)

        p1 = self.game.create_player('Matt', balance=1000, goal_id=g1.id)
        
        self.assertEqual(self.game.goal_funded_by_player(p1.id), 0)

        self.game.set_policy_funding_for_player(p1, [(po1.id, 10), (po2.id, 30)])

        self.game.tick()

        self.assertEqual(p1.balance, 960)
        self.assertEqual(self.game.goal_funded_by_player(p1.id), 10)

        self.game.tick()

        self.assertEqual(p1.balance, 920)
        self.assertEqual(self.game.goal_funded_by_player(p1.id), 20)
        self.assertEqual(g2.balance, 60)

    def testOfferPolicy(self):
        p1 = self.game.create_player('Matt')
        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 0),])

        data = self.game.offer_policy(p1.id, po1.id, 5000)

        self.assertEqual(data['seller_id'], p1.id)
        self.assertEqual(data['policy_id'], po1.id)
        self.assertEqual(data['price'], 5000)
        self.assertEqual(len(data['checksum']), 40)

    def testBuyPolicy(self):
        
        seller = self.game.create_player('Matt')
        buyer = self.game.create_player('Simon')

        self.assertEqual(seller.balance, 1500000)
        self.assertEqual(buyer.balance, 1500000)

        p1 = self.game.add_policy('Policy 1')
        
        self.game.set_policy_funding_for_player(seller, [(p1.id, 0),])
        self.assertIn(p1.id, seller.policies)
        self.assertNotIn(p1.id, buyer.policies)

        offer = self.game.offer_policy(seller.id, p1.id, 20000)
        self.game.buy_policy(buyer.id, offer)

        self.assertIn(p1.id, buyer.policies)
        self.assertIn(p1.id, seller.policies)
        self.assertEqual(seller.balance, 1500000+20000)
        self.assertEqual(buyer.balance, 1500000-20000)
        
    def testBuyPolicyFailDupe(self):
        
        seller = self.game.create_player('Matt')
        buyer = self.game.create_player('Simon')

        self.assertEqual(seller.balance, 1500000)
        self.assertEqual(buyer.balance, 1500000)

        p1 = self.game.add_policy('Policy 1')
        
        self.game.set_policy_funding_for_player(seller, [(p1.id, 0),])
        self.game.set_policy_funding_for_player(buyer, [(p1.id, 0),])
        self.assertIn(p1.id, seller.policies)
        self.assertIn(p1.id, buyer.policies)

        offer = self.game.offer_policy(seller.id, p1.id, 20000)
        with self.assertRaises(ValueError):
            self.game.buy_policy(buyer.id, offer)

        self.assertIn(p1.id, buyer.policies)
        self.assertIn(p1.id, seller.policies)
        self.assertEqual(seller.balance, 1500000)
        self.assertEqual(buyer.balance, 1500000)
        
    def testBuyPolicyFailNoFunds(self):
        
        seller = self.game.create_player('Matt')
        buyer = self.game.create_player('Simon')

        self.assertEqual(seller.balance, 1500000)
        self.assertEqual(buyer.balance, 1500000)

        p1 = self.game.add_policy('Policy 1')
        
        self.game.set_policy_funding_for_player(seller, [(p1.id, 0),])
        self.assertIn(p1.id, seller.policies)
        self.assertNotIn(p1.id, buyer.policies)

        offer = self.game.offer_policy(seller.id, p1.id, 2000000)
        with self.assertRaises(ValueError):
            self.game.buy_policy(buyer.id, offer)

        self.assertNotIn(p1.id, buyer.policies)
        self.assertIn(p1.id, seller.policies)
        self.assertEqual(seller.balance, 1500000)
        self.assertEqual(buyer.balance, 1500000)
        
    def testBuyPolicyFailNoPolicy(self):
        
        seller = self.game.create_player('Matt')
        buyer = self.game.create_player('Simon')

        self.assertEqual(seller.balance, 1500000)
        self.assertEqual(buyer.balance, 1500000)

        p1 = self.game.add_policy('Policy 1')
        
        self.assertNotIn(p1, seller.policies)
        self.assertNotIn(p1, buyer.policies)

        with self.assertRaises(ValueError):
            offer = self.game.offer_policy(seller.id, p1.id, 20000)
            self.game.buy_policy(buyer.id, offer)

        self.assertNotIn(p1, buyer.policies)
        self.assertNotIn(p1, seller.policies)
        self.assertEqual(seller.balance, 1500000)
        self.assertEqual(buyer.balance, 1500000)

    def testGameStartStop(self):
        self.assertTrue(self.game.is_running())

        year = self.game.stop()
        self.assertEqual(year, 2017)

        self.assertFalse(self.game.is_running())

    def testMessages(self):
        messages = tuple(self.game.get_messages())
        self.assertEqual(len(messages), 0)
        
        t1 = datetime.now()
        m1 = self.game.add_message(t1, "policy", "message 1")

        messages = tuple(self.game.get_messages())
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].timestamp, t1)
        self.assertEqual(messages[0].message, "message 1")
        self.assertEqual(messages[0].type, "policy")

        t2 = datetime.now()
        m2 = self.game.add_message(t2, "event", "message 2")
        messages = tuple(self.game.get_messages())

        self.assertEqual(len(messages), 2)
        
        self.game.clear_messages()
        messages = tuple(self.game.get_messages())
        self.assertEqual(len(messages), 0)
        
    def testClaimBudget(self):
        p1 = self.game.create_player('Matt')
        p1.balance = 1000
        p1.unclaimed_budget = 1500000

        p1.claim_budget()

        self.assertEqual(p1.balance, 1500000)
        self.assertEqual(p1.unclaimed_budget, 0)

        # 2nd claim with no unclaimed budget should do no-op
        p1.balance = 1400000
        p1.claim_budget()

        self.assertEqual(p1.balance, 1400000)
        self.assertEqual(p1.unclaimed_budget, 0)
        

        
class DataLoadTests(ControllerTestCase):

    def testCreateNetwork(self):
        json_file = open('examples/example-network.json', 'r')
        self.game.create_network(json.load(json_file))
        self.assertEqual(80, len(self.game.network.edges))
        self.assertEqual(44, len(self.game.network.ranked_nodes))
        self.assertEqual(37, len(self.game.network.policies))
        self.assertEqual(7, len(self.game.network.goals))

        self.assertEqual(80, len(self.game.network.edges))
        self.assertEqual(37, len(self.game.network.policies))
        self.assertEqual(7, len(self.game.network.goals))


    def testGetNetwork(self):
        p1 = self.game.create_player('Matt', balance=5000)
        po1 = self.game.add_policy('Arms Embargo', leak=0.1)
        po2 = self.game.add_policy('Pollution control', leak=0.1)
        self.game.set_policy_funding_for_player(p1, [(po1.id, 10.0), (po2.id, 15.0),])

        g1 = self.game.add_goal('World Peace', leak=0.5)
        g2 = self.game.add_goal('Clean Water', leak=0.5)
        g3 = self.game.add_goal('Equal Rights', leak=0.2)
        l3 = self.game.add_link(po1, g1, 5.0)
        l4 = self.game.add_link(po2, g2, 9.0)

        self.assertEqual(p1.balance, 5000)
        self.assertEqual(po1.balance, 0)

        for x in range(20):
            self.game.tick()
        
        network = self.game.get_network()

        policies = tuple(network['policies'])
        goals = tuple(network['goals'])

        self.assertEqual(len(policies), 2)
        self.assertEqual(len(goals), 3)

        # todo: add more tests here

    def testClearNetwork(self):
        json_file = open('examples/example-network.json', 'r')
        self.game.create_network(json.load(json_file))
        n = self.game.network
        self.assertEqual(80, len(n.edges))
        self.assertEqual(44, len(n.ranked_nodes))
        self.assertEqual(37, len(n.policies))
        self.assertEqual(7, len(n.goals))

        self.game.clear_network()
        n = self.game.network
        self.assertEqual(0, len(n.edges))
        self.assertEqual(0, len(n.ranked_nodes))
        self.assertEqual(0, len(n.policies))
        self.assertEqual(0, len(n.goals))


    def testGetWallets(self):
        self.add_20_goals_and_policies()

        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')

        new_fundings = []
        fundings = self.game.get_policy_funding_for_player(p1)
        for i,(p_id,a) in enumerate(fundings):
            new_fundings.append((p_id,i))
        self.game.set_policy_funding_for_player(p1, new_fundings)

        new_fundings = []
        fundings = self.game.get_policy_funding_for_player(p2)
        for i,(p_id,a) in enumerate(fundings):
            new_fundings.append((p_id,i))
        self.game.set_policy_funding_for_player(p2, new_fundings)

        self.game.network.rank()

        self.game.do_propogate_funds()
        nodes = [ self.game.network.policies[x] for x in
                  set(p1.policies.keys() + p2.policies.keys()) ]

        wallets = []
        for n in nodes:
            for player_id,amount in n.wallet.todict().items():
                wallets.append(dict(location=n.id,
                                    owner=self.game.get_player(player_id).id,
                                    balance=float("{:.2f}".format(amount))))

        expected = [{'owner': p1.id, 'balance': 1.0, 'location': 'P1'}, 
                    {'owner': p2.id, 'balance': 1.0, 'location': 'P1'}, 
                    {'owner': p1.id, 'balance': 2.0, 'location': 'P10'}, 
                    {'owner': p2.id, 'balance': 2.0, 'location': 'P10'}, 
                    {'owner': p2.id, 'balance': 3.0, 'location': 'P11'}, 
                    {'owner': p1.id, 'balance': 3.0, 'location': 'P11'}, 
                    {'owner': p1.id, 'balance': 4.0, 'location': 'P12'}, 
                    {'owner': p2.id, 'balance': 4.0, 'location': 'P12'}]

        self.assertEqual(sorted(expected), sorted(wallets))


class RestAPITests(ViewTestCase):

    def testTick(self):
        transaction.commit()
        headers = {'X-API-KEY': self.api_key}
        response = self.client.put("/v1/game/tick",
                                   headers=headers,
                                   content_type='application/json')
        self.assertEquals(response.status_code, 200)


    def testPlayerFunding(self):
        headers = {'X-API-KEY': self.api_key}

        p1 = self.game.create_player('Matt', balance=1000)
        p2 = self.game.create_player('Simon', balance=0)
        n1 = self.game.add_policy('Policy 1')
        n2 = self.game.add_policy('Policy 2')
        self.game.set_policy_funding_for_player(p1, [(n1.id, 100), (n2.id, 100),])
        self.game.set_policy_funding_for_player(p2, [(n2.id, 200),])

        transaction.commit()
        
        # temp unavailable as not computed yet
        response = self.client.get("/v1/game/player_fundings",
                                   headers=headers,
                                   content_type='application/json')
        self.assertEquals(response.status_code, 200)

        response = self.client.put("/v1/game/tick",
                                   headers=headers,
                                   content_type='application/json')
        self.assertEquals(response.status_code, 200)

        response = self.client.get("/v1/game/player_fundings",
                                   headers=headers,
                                   content_type='application/json')
        self.assertEquals(response.status_code, 200)

        expected = [{'id': p1.id,
                     'name': p1.name,
                     'funding': [{'id': n1.id,
                                  'amount_set': 100,
                                  'amount_actual': 100},
                                 {'id': n2.id,
                                  'amount_set': 100,
                                  'amount_actual': 100,},
                                 ]},
                    {'id': p2.id,
                     'name': p2.name,
                     'funding': [{'id': n2.id,
                                  'amount_set': 200,
                                  'amount_actual': 0},
                                 ]}
                    ]

        self.assertEqual(sorted(expected), sorted(response.json))

    def testGetSpecificPlayer(self):
        name = 'Matt'
        player = self.game.create_player(name)
        id = player.id

        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/players/{}".format(id), headers=headers)
        self.assertEquals(response.status_code, 200)
        self.assertDictContainsSubset(dict(name=name, id=id), response.json)
        self.assertFalse(response.json.has_key('token'))

    def testGetNonExistentPlayer(self):
        transaction.commit()
        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/players/nobody", headers=headers)
        self.assertEquals(response.status_code, 404)

    def testCreateNewPlayer(self):
        data = dict(name='Matt')

        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key}
        response = self.client.post("/v1/players/", data=json.dumps(data),
                                    headers=headers,
                                    content_type='application/json')
        self.assertEquals(response.status_code, 201)
        id = response.json['id']
        token = response.json['token']

        player = self.game.get_player(id)
        self.assertEquals(id, player.id)
        self.assertEquals(token, player.token)

    def testCreateThenGetNewPlayer(self):
        transaction.commit()
        name = 'Matt {}'.format(time.time())
        data = dict(name=name)
        headers = {'X-API-KEY': self.api_key}
        response = self.client.post("/v1/players/", data=json.dumps(data),
                                    headers=headers,
                                    content_type='application/json')
        self.assertEquals(response.status_code, 201)
        id = response.json['id']

        response = self.client.get("/v1/players/{}".format(id), headers=headers)
        self.assertEquals(response.status_code, 200)
        self.assertDictContainsSubset(dict(name=name, id=id), response.json)
        self.assertFalse(response.json.has_key('token'))
        
    def testCreateThenGetNewPlayerWithNodes(self):
        # create some nodes first
        self.add_20_goals_and_policies()

        transaction.commit()

        name = 'Matt {}'.format(time.time())
        data = dict(name=name)
        headers = {'X-API-KEY': self.api_key}
        response = self.client.post("/v1/players/", data=json.dumps(data),
                                    headers=headers,
                                    content_type='application/json')
        self.assertEquals(response.status_code, 201)
        id = response.json['id']

        response = self.client.get("/v1/players/{}".format(id), headers=headers)
        self.assertEquals(response.status_code, 200)
        self.assertDictContainsSubset(dict(name=name, id=id), response.json)
        self.assertEquals(response.json['goal']['id'], 'G0')
        policies = response.json['policies']
        policies = [ x['id'] for x in policies ] 
        policies.sort()
        self.assertEquals(policies, [u'P0', u'P1', u'P10', u'P11', u'P12'])
        self.assertFalse(response.json.has_key('token'))

        name = 'Simon {}'.format(time.time())
        data = dict(name=name)
        response = self.client.post("/v1/players/", data=json.dumps(data),
                                    headers=headers,
                                    content_type='application/json')
        self.assertEquals(response.status_code, 201)
        id = response.json['id']

        response = self.client.get("/v1/players/{}".format(id), headers=headers)
        self.assertEquals(response.status_code, 200)
        self.assertDictContainsSubset(dict(name=name, id=id), response.json)
        self.assertEquals(response.json['goal']['id'], 'G0')
        policies = response.json['policies']
        policies = [ x['id'] for x in policies ] 
        policies.sort()
        self.assertEquals(policies, [u'P0', u'P1', u'P10', u'P11', u'P12'])
        self.assertFalse(response.json.has_key('token'))

    @unittest.skip("needs fixing after network re-jig")
    def testGetNetwork(self):
        p1 = self.game.create_player('Matt')
        p1.balance = 5000
        po1 = self.game.add_policy('Arms Embargo', 0.1)
        self.game.add_fund(p1, po1, 10.0)
        po2 = self.game.add_policy('Pollution control', 0.1)
        self.game.add_fund(p1, po2, 15.0)

        g1 = self.game.add_goal('World Peace', 0.5)
        g2 = self.game.add_goal('Clean Water', 0.5)
        g3 = self.game.add_goal('Equal Rights', 0.2)
        l3 = self.game.add_link(po1, g1, 5.0)
        l4 = self.game.add_link(po2, g2, 9.0)

        self.assertEqual(p1.balance, 5000)
        self.assertEqual(po1.balance, 0)

        for x in range(20):
            self.game.tick()

        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/network/", headers=headers)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(len(response.json['policies']), 2)
        self.assertEquals(len(response.json['goals']), 3)

    def testCreateNetwork(self):
        data = json.load(open('examples/example-network.json', 'r'))

        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key}
        response = self.client.post("/v1/network/", data=json.dumps(data),
                                    headers=headers,
                                    content_type='application/json')
        self.assertEquals(response.status_code, 201)

        self.game.populate()

        self.assertEqual(80, len(self.game.network.edges))
        self.assertEqual(44, len(self.game.network.ranked_nodes))
        self.assertEqual(37, len(self.game.network.policies))
        self.assertEqual(7, len(self.game.network.goals))

        self.assertEqual(80, len(self.game.network.edges))
        self.assertEqual(37, len(self.game.network.policies))
        self.assertEqual(7, len(self.game.network.goals))

    @unittest.skip("needs fixing after network re-jig")
    def testCreateThenGetNetwork(self):
        data = json.load(open('examples/example-network.json', 'r'))

        headers = {'X-API-KEY': self.api_key}
        response = self.client.post("/v1/network/", data=json.dumps(data),
                                    headers=headers,
                                    content_type='application/json')
        self.assertEquals(response.status_code, 201)

        response = self.client.get("/v1/network/", headers=headers)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(len(response.json['policies']), 37)
        self.assertEquals(len(response.json['goals']), 7)

        self.assertEqual(data, response.json)

    def testUpdateNetwork(self):
        data = json.load(open('examples/example-network.json', 'r'))

        self.game.create_network(data)
        self.game.tick()

        self.assertEqual(80, len(self.game.network.edges))
        self.assertEqual(44, len(self.game.network.ranked_nodes))
        self.assertEqual(37, len(self.game.network.policies))
        self.assertEqual(7, len(self.game.network.goals))

        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/network/", headers=headers)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(len(response.json['policies']), 37)
        self.assertEquals(len(response.json['goals']), 7)

        expected = response.json
        e = expected['goals'][0]

        e['short_name'] = 'new short name'
        e['group'] = 1
        e['name'] = 'long name'
        e['max_amount'] = 100.0
        e['activation_amount'] = 10.0
        e['leakage'] = 0.2

        id_ = e['id']

        response2 = self.client.put("/v1/network/", data=json.dumps(expected),
                                    headers=headers,
                                    content_type='application/json')
        self.assertEquals(response2.status_code, 200)
        d = { x['id']: x for x in response2.json['goals'] }
        self.assertEqual(d[id_]['short_name'], 'new short name')
        # remove generation time
        del expected['generated']
        self.assertEqual(sorted(expected), sorted(response2.json))

    def testCreateTable(self):
        transaction.commit()
        data = {'name': 'Table A'}
        headers = {'X-API-KEY': self.api_key}
        response = self.client.post("/v1/tables/", data=json.dumps(data),
                                    headers=headers,
                                    content_type='application/json')
        self.assertEquals(response.status_code, 201)
        self.assertEquals(response.json['name'], 'Table A')
        self.assertEquals(response.json['players'], [])

        id = response.json['id']
        self.assertEquals(self.game.get_table(id).id, id)

    def testDeleteTable(self):
        table = self.game.create_table('Table A')
        id = table.id

        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key}
        response = self.client.delete("/v1/tables/{}".format(id),
                                    headers=headers,
                                    content_type='application/json')
        self.assertEquals(response.status_code, 200)
        self.assertEquals(self.game.get_table(id), None)

    def testGetTableEmpty(self):
        data = json.load(open('examples/example-network.json', 'r'))
        self.game.create_network(data)

        table = self.game.create_table('Table A')

        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/tables/{}".format(table.id), headers=headers)
        self.assertEquals(response.status_code, 200)
        result = response.json
        self.assertEquals(result['id'], table.id)
        self.assertEquals(result['name'], 'Table A')
        self.assertEquals(result['players'], [])
        self.assertEquals(len(result['network']['nodes']), 44)
        self.assertEquals(len(result['network']['links']), 80)

    def testGetTableWithOnePlayer(self):
        data = json.load(open('examples/example-network.json', 'r'))
        self.game.create_network(data)

        p1 = self.game.create_player('Matt')
        self.game.set_policy_funding_for_player(p1, [(sorted(p1.policies)[0], 10)],)

        table = self.game.create_table('Table A')
        self.game.add_player_to_table(p1.id, table.id)

        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/tables/{}".format(table.id), headers=headers)
        self.assertEquals(response.status_code, 200)
        result = response.json
        self.assertEquals(result['id'], table.id)
        self.assertEquals(result['name'], 'Table A')
        self.assertEquals(result['players'][0]['name'], 'Matt')
        self.assertEquals(len(result['network']['nodes']), 5)
        self.assertEquals(len(result['network']['links']), 2)

    def testGetTableWithTwoPlayers(self):
        data = json.load(open('examples/example-network.json', 'r'))
        self.game.create_network(data)

        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        self.game.set_policy_funding_for_player(p1, [(sorted(p1.policies)[0], 10)],)
        self.game.set_policy_funding_for_player(p2, [(sorted(p2.policies)[1], 10)],)

        table = self.game.create_table('Table A')
        self.game.add_player_to_table(p1.id, table.id)
        self.game.add_player_to_table(p2.id, table.id)

        transaction.commit()

        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/tables/{}".format(table.id), headers=headers)
        self.assertEquals(response.status_code, 200)
        result = response.json
        self.assertEquals(result['id'], table.id)
        self.assertEquals(result['name'], 'Table A')
        self.assertEquals(sorted(result['players'])[0]['name'], 'Matt')
        self.assertEquals(len(result['network']['nodes']), 7)
        self.assertEquals(len(result['network']['links']), 3)

    def testGetTableChecksum(self):
        data = json.load(open('examples/example-network.json', 'r'))
        self.game.create_network(data)

        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')
        self.game.set_policy_funding_for_player(p1, [(sorted(p1.policies)[0], 10), (sorted(p1.policies)[1], 0)])
        self.game.set_policy_funding_for_player(p2, [(sorted(p2.policies)[1], 10), (sorted(p2.policies)[2], 0)])

        table = self.game.create_table('Table A')
#        table.players.append(p1)
        self.game.add_player_to_table(p1.id, table.id)

        self.game.tick()
        
        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/tables/{}".format(table.id), headers=headers)
        self.assertEquals(response.status_code, 200)
        result = response.json
        chksum1 = result['layout_checksum']

        response = self.client.get("/v1/tables/{}".format(table.id), headers=headers)
        self.assertEquals(response.status_code, 200)
        result = response.json
        self.assertEqual(chksum1, result['layout_checksum'])

#        p1.policies[0].lower_edges[0].weight = 0.5
        fundings = self.game.get_policy_funding_for_player(p1)
        fundings = [(fundings[0][0], 0.5), (fundings[1][0], 0)]
        self.game.set_policy_funding_for_player(p1, fundings)

        response = self.client.get("/v1/tables/{}".format(table.id), headers=headers)
        self.assertEquals(response.status_code, 200)
        result = response.json
        self.assertEqual(chksum1, result['layout_checksum'])

#        p1.fund(p1.policies[1], 10)
        fundings = self.game.get_policy_funding_for_player(p1)
        fundings = [(fundings[0][0], 10), (fundings[1][0], 10)]
        self.game.set_policy_funding_for_player(p1, fundings)

        self.game.tick()

        transaction.commit()

        response = self.client.get("/v1/tables/{}".format(table.id), headers=headers)
        self.assertEquals(response.status_code, 200)
        result = response.json
        self.assertNotEqual(chksum1, result['layout_checksum'])



    def testGetFunding(self):
        self.add_20_goals_and_policies()
        name = 'Matt'
        player = self.game.create_player(name)
        id = player.id

        self.game.set_policy_funding_for_player(player, [(p_id,a) for a,p_id in enumerate(player.policies)])

        funding = []
        for amount,policy in enumerate(player.policies):
            funding.append({u'to_id': policy, 
                            u'amount': amount, 
                            u'from_id': id})

        transaction.commit()
            
        headers = {'X-USER-KEY': player.token,
                   'X-API-KEY': self.api_key}
        response = self.client.get("/v1/players/{}/funding".format(id),
                                   headers=headers)

        self.assertEquals(response.status_code, 200)
        self.assertEquals(sorted(funding), sorted(response.json))
        
    def testGetFundingFailAuth(self):
        self.add_20_goals_and_policies()
        name = 'Matt'
        player = self.game.create_player(name)
        id = player.id

        funding = []
        for amount,edge in enumerate(player.lower_edges):
            edge.weight = amount
            dest_id = edge.higher_node.id
            funding.append({'from_id':id, 'to_id': dest_id, 'amount': amount})

        headers = {'X-USER-KEY': 'bogus',
                   'X-API-KEY': self.api_key}
        response = self.client.get("/v1/players/{}/funding".format(id),
                                   headers=headers)
        self.assertEquals(response.status_code, 401)

    def testSetFunding(self):

        for x in range(5):
            p = self.game.add_policy("P{}".format(x))

        name = 'Matt'
        player = self.game.create_player(name)
        id = player.id

        fundings = self.game.get_policy_funding_for_player(player)

        self.assertEqual([ amount for (_,amount) in fundings ], [0,0,0,0,0])

        new_fundings = [ {"from_id": player.id, "to_id": policy_id, "amount": i} for (i,(policy_id,amount)) in enumerate(fundings) ]

        transaction.commit()
        
        headers = {'X-USER-KEY': player.token,
                   'X-API-KEY': self.api_key}
        response = self.client.put("/v1/players/{}/funding".format(id),
                                   data=json.dumps(new_fundings),
                                   headers=headers,
                                   content_type='application/json')
        self.assertEquals(response.status_code, 200)

        actual = self.game.get_policy_funding_for_player(player)
        self.assertEqual([ amount for (_,amount) in actual ], [0,1,2,3,4])

    def testSetFundingMaxOverflow(self):

        for x in range(5):
            p = self.game.add_policy("P{}".format(x))

        name = 'Matt'
        player = self.game.create_player(name)
        id = player.id

        fundings = self.game.get_policy_funding_for_player(player)

        self.assertEqual([ amount for (_,amount) in fundings ], [0,0,0,0,0])

        new_fundings = [ {"from_id": player.id, "to_id": policy_id, "amount": i*200} for (i,(policy_id,amount)) in enumerate(fundings) ]

        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key,
                   'X-USER-KEY': player.token}
        response = self.client.put("/v1/players/{}/funding".format(id),
                                   data=json.dumps(new_fundings),
                                   headers=headers,
                                   content_type='application/json')
        self.assertEquals(response.status_code, 400)

    def testGetWallets(self):
        self.add_20_goals_and_policies()

        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')

        new_fundings = []
        fundings = self.game.get_policy_funding_for_player(p1)
        for i,(p_id,a) in enumerate(fundings):
            new_fundings.append((p_id,i))
        self.game.set_policy_funding_for_player(p1, new_fundings)

        new_fundings = []
        fundings = self.game.get_policy_funding_for_player(p2)
        for i,(p_id,a) in enumerate(fundings):
            new_fundings.append((p_id,i))
        self.game.set_policy_funding_for_player(p2, new_fundings)

        self.game.network.rank()
        self.game.do_propogate_funds()

        transaction.commit()
        
        wallets = []
        nodes = set(p1.policies.keys() + p2.policies.keys())
        for n in nodes:
            headers = {'X-API-KEY': self.api_key}
            response = self.client.get("/v1/network/{}/wallets".format(n), headers=headers)
            if response.status_code == 200:
                wallets.extend(response.json)

        expected = [{'owner': p1.id, 'balance': 1.0, 'location': 'P1'}, 
                    {'owner': p2.id, 'balance': 1.0, 'location': 'P1'}, 
                    {'owner': p1.id, 'balance': 2.0, 'location': 'P10'}, 
                    {'owner': p2.id, 'balance': 2.0, 'location': 'P10'}, 
                    {'owner': p2.id, 'balance': 3.0, 'location': 'P11'}, 
                    {'owner': p1.id, 'balance': 3.0, 'location': 'P11'}, 
                    {'owner': p1.id, 'balance': 4.0, 'location': 'P12'}, 
                    {'owner': p2.id, 'balance': 4.0, 'location': 'P12'}]

        self.assertEqual(sorted(expected), sorted(wallets))

    def testGetNode(self):
        n1 = self.game.add_policy('A')
        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/network/{}".format(n1.id), headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['id'], n1.id)
        self.assertEqual(response.json['name'], 'A')

    def testGetOfferDefaultPrice(self):
        seller = self.game.create_player('Matt', balance=1500000)
        self.assertEqual(seller.balance, 1500000)
        p1 = self.game.add_policy('Policy 1')
        
        self.game.set_policy_funding_for_player(seller, [(p1.id, 0),])
        self.assertIn(p1.id, seller.policies)

        transaction.commit()

        headers = {'X-USER-KEY': seller.token,
                   'X-API-KEY': self.api_key}
        response = self.client.get("/v1/players/{}/policies/{}/offer".format(seller.id, p1.id), 
                                   headers=headers)
        self.assertEqual(response.status_code, 200)
        offer = response.json
        self.assertEqual(offer['price'], self.game.default_offer_price)

    def testGetOfferCustomPrice(self):
        seller = self.game.create_player('Matt', balance=1500000)
        self.assertEqual(seller.balance, 1500000)
        p1 = self.game.add_policy('Policy 1')
        
        self.game.set_policy_funding_for_player(seller, [(p1.id, 0),])
        self.assertIn(p1.id, seller.policies)

        transaction.commit()
        
        headers = {'X-USER-KEY': seller.token,
                   'X-API-KEY': self.api_key}
        response = self.client.get("/v1/players/{}/policies/{}/offer?price={}".format(seller.id, p1.id, 0), 
                                   headers=headers)
        self.assertEqual(response.status_code, 200)
        offer = response.json
        self.assertEqual(offer['price'], 0)

    def testBuyPolicy(self):
        
        seller = self.game.create_player('Matt')
        buyer = self.game.create_player('Simon')

        self.assertEqual(seller.balance, 1500000)
        self.assertEqual(buyer.balance, 1500000)

        p1 = self.game.add_policy('Policy 1')
        
        self.game.set_policy_funding_for_player(seller, [(p1.id, 0),])
        self.assertIn(p1.id, seller.policies)
        self.assertNotIn(p1.id, buyer.policies)

        transaction.commit()
        
        headers = {'X-USER-KEY': seller.token,
                   'X-API-KEY': self.api_key}
        response = self.client.get("/v1/players/{}/policies/{}/offer".format(seller.id, p1.id), 
                                   headers=headers)
        self.assertEqual(response.status_code, 200)
        offer = response.json

        headers = {'X-USER-KEY': buyer.token,
                   'X-API-KEY': self.api_key}
        response = self.client.post("/v1/players/{}/policies/".format(buyer.id),
                                    data=json.dumps(offer),
                                    headers=headers,
                                    content_type='application/json')

        self.assertEqual(response.status_code, 200)

        self.assertIn(p1.id, buyer.policies)
        self.assertIn(p1.id, seller.policies)
        self.assertEqual(seller.balance, 1500000+300000)
        self.assertEqual(buyer.balance, 1500000-300000)
        
    def testBuyPolicyFail(self):
        
        seller = self.game.create_player('Matt')
        buyer = self.game.create_player('Simon', balance=1000)

        self.assertEqual(seller.balance, 1500000)
        self.assertEqual(buyer.balance, 1000)

        p1 = self.game.add_policy('Policy 1')
        
        self.game.set_policy_funding_for_player(seller, [(p1.id, 0),])
        self.assertIn(p1.id, seller.policies)
        self.assertNotIn(p1.id, buyer.policies)

        transaction.commit()
        
        headers = {'X-USER-KEY': seller.token,
                   'X-API-KEY': self.api_key}
        response = self.client.get("/v1/players/{}/policies/{}/offer".format(seller.id, p1.id), 
                                   headers=headers)
        self.assertEqual(response.status_code, 200)
        offer = response.json

        headers = {'X-USER-KEY': buyer.token,
                   'X-API-KEY': self.api_key}
        response = self.client.post("/v1/players/{}/policies/".format(buyer.id),
                                    data=json.dumps(offer),
                                    headers=headers,
                                    content_type='application/json')

        self.assertEqual(response.status_code, 400)

        self.assertNotIn(p1.id, buyer.policies)
        self.assertIn(p1.id, seller.policies)
        self.assertEqual(seller.balance, 1500000)
        self.assertEqual(buyer.balance, 1000)

    def testLeagueTable(self):
        g1 = self.game.add_goal('G1')
        g2 = self.game.add_goal('G2')

        p1 = self.game.create_player('Matt', goal_id=g1.id)
        p2 = self.game.create_player('Simon', goal_id=g1.id)
        p3 = self.game.create_player('Richard', goal_id=g2.id)

        po1 = self.game.add_policy('po1')
        po2 = self.game.add_policy('po2')

        self.game.add_link(po1, g1, 100)
        self.game.add_link(po2, g2, 100)

        self.game.set_policy_funding_for_player(p1, [(po1.id, 10),])
        self.game.set_policy_funding_for_player(p2, [(po1.id, 20),])
        self.game.set_policy_funding_for_player(p3, [(po2.id, 15),])

        self.game.tick()

        self.assertEqual(p1.balance, 1499990)
        self.assertEqual(p2.balance, 1499980)
        self.assertEqual(p3.balance, 1499985)

#        p1.calc_goal_funded()
#        p2.calc_goal_funded()
#        p3.calc_goal_funded()

        transaction.commit()

        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/game/league_table", headers=headers)
        self.assertEqual(response.status_code, 200)
        expected = {'rows': [{'id': p2.id,
                              'name': p2.name,
                              'goal': 'G1',
                              'goal_total': '30.00',
                              'goal_contribution': '20.00',},
                             {'id': p3.id,
                              'name': p3.name,
                              'goal': 'G2',
                              'goal_total': '15.00',
                              'goal_contribution': '15.00',},
                             {'id': p1.id,
                              'name': p1.name,
                              'goal': 'G1',
                              'goal_total': '30.00',
                              'goal_contribution': '10.00',}
                             ]}

        self.assertEqual(response.json, expected)

    def testAddPlayerToTable(self):
        p1 = self.game.create_player('Matt')

        table = self.game.create_table('Table A')
        self.assertNotIn(p1, table.players)

        transaction.commit()
        
        headers = {'X-USER-KEY': p1.token,
                   'X-API-KEY': self.api_key}
        response = self.client.put("/v1/players/{}/table/{}".format(p1.id, table.id),
                                     headers=headers,
                                     content_type='application/json')

        self.assertEquals(response.status_code, 200)
        self.assertIn(p1.id, table.players)

    def testAddPlayerToNonexistantTable(self):
        p1 = self.game.create_player('Matt')

        table = self.game.create_table('Table A')
        self.assertNotIn(p1, table.players)

        transaction.commit()
        
        headers = {'X-USER-KEY': p1.token,
                   'X-API-KEY': self.api_key}
        response = self.client.put("/v1/players/{}/table/{}".format(p1.id, 'bogus'),
                                     headers=headers,
                                     content_type='application/json')

        self.assertEquals(response.status_code, 404)
        self.assertNotIn(p1, table.players)

    def testAddNonexistantPlayerToTable(self):
        p1 = self.game.create_player('Matt')

        table = self.game.create_table('Table A')
        self.assertNotIn(p1, table.players)

        transaction.commit()
        
        headers = {'X-USER-KEY': p1.token,
                   'X-API-KEY': self.api_key}

        response = self.client.put("/v1/players/{}/table/{}".format('bogus', table.id),
                                     headers=headers,
                                     content_type='application/json')

        self.assertEquals(response.status_code, 404)
        self.assertNotIn(p1, table.players)

    def testRemovePlayerFromTable(self):
        p1 = self.game.create_player('Matt')

        table = self.game.create_table('Table A')
        self.game.add_player_to_table(p1.id, table.id)
        self.assertIn(p1.id, table.players)

        transaction.commit()
        
        headers = {'X-USER-KEY': p1.token,
                   'X-API-KEY': self.api_key}
        response = self.client.delete("/v1/players/{}/table/{}".format(p1.id, table.id),
                                      headers=headers,
                                      content_type='application/json')

        self.assertEquals(response.status_code, 200)
        self.assertNotIn(p1.id, tuple(table.players))

    def testRemoveAllPlayersFromTable(self):
        p1 = self.game.create_player('Matt')
        p2 = self.game.create_player('Simon')

        table = self.game.create_table('Table A')
        self.game.add_player_to_table(p1.id, table.id)
        self.game.add_player_to_table(p2.id, table.id)
        self.assertIn(p1.id, table.players)
        self.assertIn(p2.id, table.players)

        transaction.commit()
        
        headers = {'X-USER-KEY': p1.token,
                   'X-API-KEY': self.api_key}
        response = self.client.put("/v1/tables/{}/clear".format(table.id),
                                   headers=headers,
                                   content_type='application/json')

        self.assertEquals(response.status_code, 200)
        self.assertEquals(tuple(table.players), ())
        self.assertEquals(p1.table_id, None)
        self.assertEquals(p2.table_id, None)

    def testSetMessages(self):
        transaction.commit()
        headers = {'X-API-KEY': self.api_key}
        data = {'budgets': [{'time': '2017-02-22T12:50:00',
                             'message': 'message 1',
                             },
                            {'time': '2017-02-22T12:51:00Z',
                             'message': 'message 2',
                             }],
                'events': [{'time': '2017-02-22T13:50:00',
                             'message': 'message 3',
                             },
                            {'time': '2017-02-22T13:51:00',
                             'message': 'message 4',
                             }],
                }
        response = self.client.put("/v1/game/messages",
                                   headers=headers,
                                   data=json.dumps(data),
                                   content_type='application/json')

        self.assertEquals(response.status_code, 200)
        messages = self.game.get_messages()
        self.assertEqual(len(tuple(messages)), 4)

    def testGetMessages(self):
        t1 = datetime(2017,02,22,12,50)
        m1 = self.game.add_message(t1, "budget", "message 1")
        t2 = datetime(2017,02,22,13,50)
        m2 = self.game.add_message(t2, "event", "message 2")

        transaction.commit()
        
        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/game/messages", headers=headers)
        self.assertEqual(response.status_code, 200)
        expected = {'budgets': [{'time': '2017-02-22T12:50:00Z',
                                 'message': 'message 1'}
                                ],
                    'events': [{'time': '2017-02-22T13:50:00Z',
                                'message': 'message 2'},
                               ],
                    }

        self.assertEqual(sorted(response.json.items()), sorted(expected.items()))

    def testClaimBudget(self):
        p1 = self.game.create_player('Matt', balance=1000, unclaimed_budget=1500000)

        transaction.commit()

        headers = {'X-USER-KEY': p1.token,
                   'X-API-KEY': self.api_key}
        response = self.client.put("/v1/players/{}/claim_budget".format(p1.id),
                                      headers=headers,
                                      content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.assertEqual(p1.balance, 1500000)
        self.assertEqual(p1.unclaimed_budget, 0)

        # 2nd claim with no unclaimed budget should do no-op
        p1.balance = 1400000
        
        transaction.commit()        
        
        headers = {'X-USER-KEY': p1.token,
                   'X-API-KEY': self.api_key}
        response = self.client.put("/v1/players/{}/claim_budget".format(p1.id),
                                      headers=headers,
                                      content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.assertEqual(p1.balance, 1400000)
        self.assertEqual(p1.unclaimed_budget, 0)


    def testGetGameMetadata(self):
        transaction.commit()
        headers = {'X-API-KEY': self.api_key}
        response = self.client.get("/v1/game",
                                   headers=headers,
                                   content_type='application/json')
        self.assertEqual(response.status_code, 200)

        data = response.json
        self.assertEqual(data['game_year'], 2017)
        game_year_start = dateutil.parser.parse(data['game_year_start']).replace(tzinfo=None)
        self.assertLess((datetime.now() - game_year_start).seconds, 5)
        self.assertEqual(data['next_game_year'], 2018)
        next_game_year_start = dateutil.parser.parse(data['next_game_year_start']).replace(tzinfo=None)
        self.assertEqual(next_game_year_start - game_year_start, timedelta(minutes=75))
        self.assertEqual(data['version'], APP_VERSION)
        self.assertEqual(data['total_players_inflow'], 0.0)
        self.assertEqual(data['budget_per_cycle'], 1500000.0)
        self.assertEqual(data['max_spend_per_tick'], 1000)

    def testMissingAPIKey(self):
        response = self.client.get("/v1/game",
                                   content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def testBadAPIKey(self):
        headers = {'X-API-KEY': "boguskey"}
        response = self.client.get("/v1/game",
                                   headers=headers,
                                   content_type='application/json')
        self.assertEqual(response.status_code, 401)


class NetworkTests(ModelTestCase):

    def testPlayerFunding(self):

        p1 = Player.new('Matt', balance=1000)
        p2 = Player.new('Simon', balance=0)
        n1 = Policy.new('Policy 1')
        n2 = Policy.new('Policy 2')
        p1.policies = {n1.id: 100, n2.id: 100}
        p2.policies = {n2.id: 200}

        policies = [n1, n2]
        players = [p1, p2]
        
        network = Network(policies, [], [], players)

        self.assertEqual(p1.balance, 1000)
        self.assertEqual(p2.balance, 0)

        network.fund_network()

        self.assertEqual(p1.balance, 800)
        self.assertEqual(p2.balance, 0)

    def testPolicyGoalPropogation(self):

        n1 = Policy.new('Policy 1', balance=100)
        g1 = Goal.new('Goal 1') 
        e1 = Edge.new(n1, g1, 1.0)

        policies = [n1,]
        goals = [g1,]
        edges = [e1,]

        network = Network(policies, goals, edges, [])

        self.assertEqual(n1.balance, 100)
        self.assertEqual(g1.balance, 0)

        network.propagate()

        self.assertEqual(n1.balance, 99)
        self.assertEqual(g1.balance, 1)


    def testAddWalletToPolicy(self):

        po1 = Policy.new('Arms Embargo')
        p1 = Player.new('Matt')
        w1 = Wallet([(p1.id, 100)])
        po1.wallet = w1

        self.assertIn(p1.id, w1.todict())
        self.assertEqual(po1.wallet, w1)

    def testNodeActivationFromPlayer(self):
        p1 = Player.new('Matt', balance=1000)
        po1 = Policy.new('Policy 1', activation=0.2)

        self.assertFalse(po1.active)
        self.assertAlmostEqual(po1.active_level, 0)
        p1.policies = {po1: 200.0}
        
        policies = [po1,]
        players = [p1,]

        network = Network(policies, [], [], players)

        self.assertFalse(po1.active)

        network.propagate()
        
        self.assertTrue(po1.active)


if __name__ == '__main__':
    unittest.main()

