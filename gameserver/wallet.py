from struct import pack, unpack, unpack_from, calcsize
import unittest
from uuid import uuid4, UUID
from types import IntType, FloatType
from persistent import Persistent

class Wallet(Persistent):

    HDR_FMT = "f"
    MSG_FMT = "16sf"

    def __init__(self, items=None):
        self._total = 0.0
        self._entries = {}
        
        if items is not None:
            for player, amount in items:
                self.add(player, amount)

        
    def _add(self, player_id, amount):
        self._total -= self._entries.get(player_id, 0)
        if amount > 0:
            self._entries[player_id] = amount
            self._total += amount
        else:
            try:
                del self._entries[player_id]
            except KeyError:
                pass
        self._p_changed = 1


    def add(self, player_id, amount):
        if isinstance(player_id, UUID):
            player_id = player_id.bytes
        elif len(player_id) == 36 and player_id[8] == '-':
            player_id = UUID(player_id).bytes
        self._add(player_id, amount)

    @property
    def total(self):
        return self._total

    def __len__(self):
        return len(self._entries)

    def __repr__(self):
        return "<Wallet total: {:.2f}>".format(self._total)

    def dumps(self):
        fmt = self.MSG_FMT
        return pack(self.HDR_FMT, self._total) + \
            ''.join([pack(fmt, k,v) for (k,v) in self._entries.items()])

    def loads(self, data):
        hdr_len = calcsize(self.HDR_FMT)
        hdr,data = data[:hdr_len], data[hdr_len:]
        self._total = unpack(self.HDR_FMT, hdr)[0]
        msg_len = calcsize(self.MSG_FMT)
        fmt = self.MSG_FMT
        for i in range(0, len(data), msg_len):
            k,v = unpack(fmt, data[i:i+msg_len])
            self._entries[k] = v

        self._p_changed = 1
            
    def __getitem__(self, index):
        return self._entries[index]

    def get(self, player_id, default=None):
        if isinstance(player_id, UUID):
            player_id = player_id.bytes
        elif len(player_id) == 36 and player_id[8] == '-':
            player_id = UUID(player_id).bytes

        return self._entries.get(player_id, default)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False
        if self._total != other._total:
            return False
        if self.todict() != other.todict():
            return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def todict(self):
        return { str(UUID(bytes=k)): v for (k,v) in self._entries.items() }

    def transfer(self, dest, amount):
        if amount > self.total:
            raise ValueError, "Transfer amount too high"

        if not self.total:
            return

        ratio = amount / self.total
        amounts = {}

        # go through source wallet and work out how much to transfer
        # from each player as a ratio of the total amount
        # store that in amounts so we can add it later
        # construct a new source wallet with amounts deducted
        _e = self._entries
        for player in _e:
            amount =  _e[player] * ratio
            amounts[player] = amount
            _e[player] -= amount

        self._entries = { k:v for (k,v) in self._entries.items() if v > 0.001 }
        self._total = sum([x for x in self._entries.values()])
        
        # Go through a combined list of players in amounts and dest
        # entries and add them up in new dict, keeping running total
        _de = dest._entries
        _a = amounts
        _ne = {}
        _nt = 0.0
        for p,v in _a.items() + _de.items():
            t = _ne.get(p, 0.0) + v
            _nt += v
            _ne[p] = t
        
        # assign new values to dest
        dest._total = _nt
        dest._entries = _ne

        self._p_changed = 1
        dest._p_changed = 1
        
    def leak(self, factor):
        _e = self._entries
        for p in _e:
            t = _e[p] * factor
            _e[p] -= t
            self._total -= t

        self._p_changed = 1

    def __mul__(self, other):
        if type(other) not in [IntType, FloatType]:
            raise ValueError

        new_wallet = self.__class__()
        for player,amount in self._entries.iteritems():
            new_wallet._add(player, amount * other)

        return new_wallet

    def __add__(self, other):
        if type(other) not in [IntType, FloatType]:
            raise ValueError

        total = self._total
        new_total = self._total + other
        factor = new_total / total
        new_wallet = self.__class__()
        for player,amount in self._entries.iteritems():
            new_wallet._add(player, amount * factor)

        return new_wallet

    def __sub__(self, other):
        return self.__add__(-other)

    def __and__(self, other):
        if not isinstance(other, type(self)):
            raise ValueError

        a = self._entries
        b = other._entries
        new_wallet = self.__class__()

        nwa = new_wallet._add
        aget = a.get
        bget = b.get
        for key in set(a) | set(b):
            nwa(key, aget(key, 0.0) + bget(key, 0.0))

        return new_wallet

    def items(self):
        return self._entries.items()

class WalletTests(unittest.TestCase): # pragma: no cover

    def testEmptyWallet(self):
        w = Wallet()
        self.assertEqual(len(w), 0)
        self.assertEqual(w.total, 0)

    def testAddItemToEmptyWallet(self):
        w = Wallet()
        player_id = uuid4()
        w.add(player_id.bytes, 23.3)
        self.assertEqual(len(w), 1)
        self.assertEqual(w.total, 23.3)

    def testAddUUIDObject(self):
        w = Wallet()
        player_id = uuid4()
        w.add(player_id, 40.5)
        self.assertEqual(len(w), 1)
        self.assertEqual(w.total, 40.5)
        self.assertEqual(w[player_id.bytes], 40.5)

    def testAddUUIDString(self):
        w = Wallet()
        player_id = uuid4()
        w.add(str(player_id), 40.5)
        self.assertEqual(len(w), 1)
        self.assertEqual(w.total, 40.5)
        self.assertEqual(w[player_id.bytes], 40.5)

    def testAddSeveralItemsToWallet(self):
        w = Wallet()
        player_id = uuid4()
        w.add(player_id.bytes, 23.3)
        self.assertEqual(len(w), 1)
        self.assertEqual(w.total, 23.3)

        player_id = uuid4()
        w.add(player_id.bytes, 10.0)
        self.assertEqual(len(w), 2)
        self.assertEqual(w.total, 33.3)

    def testIndexIntoWallet(self):
        w = Wallet()
        player2_id = uuid4()
        player1_id = uuid4()

        w.add(player1_id.bytes, 23.3)
        w.add(player2_id.bytes, 10.0)

        self.assertAlmostEqual(w[player1_id.bytes], 23.3, 5)
        self.assertAlmostEqual(w[player2_id.bytes], 10.0, 5)

    def testKeyError(self):
        w = Wallet()
        player_id = uuid4()
        w.add(player_id.bytes, 10.0)
        with self.assertRaises(KeyError):
            a = w[1]

    def testToDict(self):
        w = Wallet()
        player1_id = uuid4()
        player2_id = uuid4()
        w.add(player1_id, 10.0)
        w.add(player2_id, 20.0)

        d = w.todict()
        self.assertEquals(d, {str(player1_id): 10,
                              str(player2_id): 20})


    def testTransferSingleToEmptyWallet(self):
        w1 = Wallet()
        player_id = uuid4()
        w1.add(player_id.bytes, 10.0)
        
        w2 = Wallet()
        w1.transfer(w2, 4.0)

        self.assertAlmostEqual(w1.total, 6.0)
        self.assertEqual(len(w1), 1)

        self.assertAlmostEqual(w2.total, 4.0)
        self.assertEqual(len(w2), 1)

    def testTransferSingleToWalletTheyAlreadyIn(self):
        w1 = Wallet()
        player_id = uuid4()
        w1.add(player_id.bytes, 10.0)
        
        w2 = Wallet()
        w2.add(player_id.bytes, 25.5)
        w1.transfer(w2, 4.0)

        self.assertAlmostEqual(w1.total, 6.0)
        self.assertEqual(len(w1), 1)

        self.assertAlmostEqual(w2.total, 29.5)
        self.assertEqual(len(w2), 1)

    def testTransferMultipleToEmptyWallet(self):
        w1 = Wallet()
        players = sorted([ uuid4().bytes for x in range(3) ])
        amounts = [10.0, 8.0, 6.0]

        for player,amount in zip(players,amounts):
            w1.add(player,amount)
        
        self.assertAlmostEqual(w1.total, 24.0)

        w2 = Wallet()
        w1.transfer(w2, 6.0)

        self.assertAlmostEqual(w1.total, 18.0)
        self.assertEqual(len(w1), 3)
        self.assertAlmostEqual(w1[0][1], 7.5)
        self.assertAlmostEqual(w1[1][1], 6.0)
        self.assertAlmostEqual(w1[2][1], 4.5)

        self.assertAlmostEqual(w2.total, 6.0)
        self.assertEqual(len(w2), 3)
        self.assertAlmostEqual(w2[0][1], 2.5 )
        self.assertAlmostEqual(w2[1][1], 2.0)
        self.assertAlmostEqual(w2[2][1], 1.5)

    def testTransferMultipleToEmptyWallet(self):
        w1 = Wallet()

        player1_id = uuid4()
        player2_id = uuid4()
        player3_id = uuid4()

        w1.add(player1_id, 10.0)
        w1.add(player2_id, 8.0)
        w1.add(player3_id, 6.0)
        
        self.assertAlmostEqual(w1.total, 24.0)

        w2 = Wallet()
        w1.transfer(w2, 6.0)

        self.assertAlmostEqual(w1.total, 18.0)
        self.assertEqual(len(w1), 3)
        d1 = w1.todict()
        self.assertEqual(d1, {str(player1_id): 7.5,
                              str(player2_id): 6.0,
                              str(player3_id): 4.5})
        
        self.assertAlmostEqual(w2.total, 6.0)
        self.assertEqual(len(w2), 3)
        d2 = w2.todict()
        self.assertEqual(d2, {str(player1_id): 2.5,
                              str(player2_id): 2.0,
                              str(player3_id): 1.5})


    def testTransferMultipleToNonEmptyWallet1(self):
        w1 = Wallet()

        player1_id = uuid4()
        player2_id = uuid4()
        player3_id = uuid4()

        w1.add(player1_id, 10.0)
        w1.add(player2_id, 8.0)
        w1.add(player3_id, 6.0)
        
        self.assertAlmostEqual(w1.total, 24.0)

        w2 = Wallet()
        w2.add(player1_id, 20.0)

        w1.transfer(w2, 6.0)

        self.assertAlmostEqual(w1.total, 18.0)
        self.assertEqual(len(w1), 3)
        d1 = w1.todict()
        self.assertEqual(d1, {str(player1_id): 7.5,
                              str(player2_id): 6.0,
                              str(player3_id): 4.5})
        
        self.assertAlmostEqual(w2.total, 26.0)
        self.assertEqual(len(w2), 3)
        d2 = w2.todict()
        self.assertEqual(d2, {str(player1_id): 22.5,
                              str(player2_id): 2.0,
                              str(player3_id): 1.5})

    def testTransferMultipleToNonEmptyWallet2(self):
        w1 = Wallet()

        player1_id = uuid4()
        player2_id = uuid4()
        player3_id = uuid4()

        w1.add(player1_id, 10.0)
        
        self.assertAlmostEqual(w1.total, 10.0)

        w2 = Wallet()
        w2.add(player1_id, 20.0)
        w2.add(player2_id, 8.0)
        w2.add(player3_id, 6.0)

        self.assertAlmostEqual(w2.total, 34.0)

        w1.transfer(w2, 6.0)

        self.assertAlmostEqual(w1.total, 4.0)
        self.assertEqual(len(w1), 1)
        d1 = w1.todict()
        self.assertEqual(d1, {str(player1_id): 4.0,})
        
        self.assertAlmostEqual(w2.total, 40.0)
        self.assertEqual(len(w2), 3)
        d2 = w2.todict()
        self.assertEqual(d2, {str(player1_id): 26.0,
                              str(player2_id): 8.0,
                              str(player3_id): 6.0})

    def testDumpsLoads(self):
        w1 = Wallet()

        player1_id = uuid4().bytes
        player2_id = uuid4().bytes
        player3_id = uuid4().bytes

        w1.add(player1_id, 10.0)
        w1.add(player2_id, 20.0)
        w1.add(player3_id, 30.0)

        binary = w1.dumps()
        self.assertEqual(len(binary), 64)

        w2 = Wallet()
        w2.loads(binary)

        self.assertEqual(w1.total, w2.total)
        self.assertEqual(len(w1), len(w2))

    def testConstructWithList(self):
        expected = { str(uuid4()): 20.3,
                     str(uuid4()): 18.6,}
        w = Wallet(expected.items())

        for k,v in w.todict().items():
            self.assertAlmostEqual(v, expected[k], 5)

    def testEquality(self):
        w1 = Wallet()
        w2 = Wallet()

        self.assertEqual(w1, w2)
        
        u1 = str(uuid4())
        u2 = str(uuid4())
        w1 = Wallet([(u1, 20.0)])
        w2 = Wallet([(u1, 20.0)])

        self.assertEqual(w1, w2)

        w1 = Wallet([(u1, 20.0)])
        w2 = Wallet([(u2, 20.0)])

        self.assertNotEqual(w1, w2)

        w1 = Wallet([(u1, 20.0)])
        w2 = Wallet([(u1, 22.0)])

        self.assertNotEqual(w1, w2)

        w1 = Wallet([(u1, 10.0), (u2, 20.0)])
        w2 = Wallet([(u1, 20.0), (u2, 10.0)])

        self.assertNotEqual(w1, w2)
        
    def testLeak(self):
        u1 = str(uuid4())
        u2 = str(uuid4())
        w1 = Wallet([(u1, 100.0), (u2, 200.0)])

        orig_dict = w1.todict()
        expected = { k:v*0.9 for k,v in orig_dict.items() }
        w1.leak(0.1)
        res = w1.todict()
        
        for k in res:
            self.assertAlmostEqual(res[k], expected[k])

        self.assertEqual(len(w1), 2)
        self.assertEqual(w1.total, (100+200) * 0.9)

    def testWalletMultiply(self):
        u1 = str(uuid4())
        u2 = str(uuid4())
        w1 = Wallet([(u1, 100.0), (u2, 200.0)])

        orig_dict = w1.todict()
        expected = { k:v*0.9 for k,v in orig_dict.items() }

        w1 *= 0.9

        res = w1.todict()
        
        for k in res:
            self.assertAlmostEqual(res[k], expected[k])

        self.assertEqual(len(w1), 2)
        self.assertEqual(w1.total, (100+200) * 0.9)

    def testWalletMultiplyBadType(self):
        u1 = str(uuid4())
        u2 = str(uuid4())
        w1 = Wallet([(u1, 100.0), (u2, 200.0)])

        with self.assertRaises(ValueError):
            w1 *= w1

    def testWalletAddition(self):
        u1 = str(uuid4())
        u2 = str(uuid4())
        w1 = Wallet([(u1, 100.0), (u2, 200.0)])

        w1 += 50

        self.assertEqual(len(w1), 2)
        self.assertEqual(w1.total, 100+200+50)

    def testWalletAddBadType(self):
        u1 = str(uuid4())
        u2 = str(uuid4())
        w1 = Wallet([(u1, 100.0), (u2, 200.0)])

        with self.assertRaises(ValueError):
            w1 += w1
        
    def testWalletSubtraction(self):
        u1 = str(uuid4())
        u2 = str(uuid4())
        w1 = Wallet([(u1, 100.0), (u2, 200.0)])

        w1 -= 50

        self.assertEqual(len(w1), 2)
        self.assertAlmostEqual(w1.total, 100+200-50)

    def testUnionWallets(self):
        u1 = str(uuid4())
        u2 = str(uuid4())
        u3 = str(uuid4())
        w1 = Wallet([(u1, 100.0), (u2, 200.0)])
        w2 = Wallet([(u2, 100.0), (u3, 50.0)])

        expected = Wallet([(u1, 100.0), (u2, 300.0), (u3, 50.0)])

        self.assertEqual(w1 & w2, expected)

    def testUnionWalletsBadType(self):
        u1 = str(uuid4())
        u2 = str(uuid4())
        w1 = Wallet([(u1, 100.0), (u2, 200.0)])

        with self.assertRaises(ValueError):
            w1 &= 1.0
        
    def testAddExistingKeyTotalIsCorrect(self):
        u1 = str(uuid4())
        u2 = str(uuid4())

        w1 = Wallet([(u1, 100.0), (u2, 200.0)])
        self.assertEqual(w1.total, 300)
        w1.add(u1, 50)
        self.assertEqual(w1.total, 250) 

    def testAddNegativeValue(self):
        u1 = str(uuid4())
        u2 = str(uuid4())

        w1 = Wallet([(u1, 100.0), (u2, 200.0)])
        self.assertEqual(len(w1._entries), 2)

        w1.add(u1, -50)
        self.assertEqual(len(w1._entries), 1)
        self.assertEqual(w1.total, 200) 

    def testTransferExactBalanceFromWallet(self):
        w1 = Wallet()

        player1_id = uuid4()
        player2_id = uuid4()
        player3_id = uuid4()

        w1.add(player1_id, 10.0)
        w1.add(player2_id, 20.0)
        w1.add(player3_id, 0.5)
        
        self.assertAlmostEqual(w1.total, 30.5)

        w2 = Wallet()

        w1.transfer(w2, 30.5)

        self.assertAlmostEqual(w1.total, 0.0)
        self.assertEqual(len(w1), 0)

    def testGetByUUID(self):
        w1 = Wallet()

        player1_id = uuid4()

        w1.add(player1_id, 10.0)
        
        self.assertAlmostEqual(w1.get(player1_id), 10.0)

    def testTransferFromEmptyWallet(self):
        w1 = Wallet()
        w2 = Wallet()
 
        player1_id = uuid4()

        w2.add(player1_id, 10.0)

        w1.transfer(w2, 0)
        
        self.assertAlmostEqual(w1.total, 0)
        self.assertAlmostEqual(w2.total, 10)

    def testWalletItems(self):
        w1 = Wallet()
 
        player1_id = uuid4()

        w1.add(player1_id, 10.0)

        self.assertEqual(w1.items(), [(player1_id.bytes, 10.0)])

if __name__ == '__main__': # pragma: no cover               
    unittest.main()
