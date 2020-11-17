#!/usr/bin/env python3
# Copyright (c) 2014-2017 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test running bitcoind with -reindex and -reindex-chainstate options.

- Start a single node and generate 3 blocks.
- Stop the node and restart it with -reindex. Verify that the node has reindexed up to block 3.
- Stop the node and restart it with -reindex-chainstate. Verify that the node has reindexed up to block 3.
"""

from test_framework.betting_opcode import *
from test_framework.authproxy import JSONRPCException
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import wait_until, rpc_port, assert_equal, assert_raises_rpc_error
from distutils.dir_util import copy_tree, remove_tree
from decimal import *
import pprint
import time
import os
import ctypes

WGR_WALLET_ORACLE = { "addr": "TXuoB9DNEuZx1RCfKw3Hsv7jNUHTt4sVG1", "key": "TBwvXbNNUiq7tDkR2EXiCbPxEJRTxA1i6euNyAE9Ag753w36c1FZ" }
WGR_WALLET_EVENT = { "addr": "TFvZVYGdrxxNunQLzSnRSC58BSRA7si6zu", "key": "TCDjD2i4e32kx2Fc87bDJKGBedEyG7oZPaZfp7E1PQG29YnvArQ8" }
WGR_WALLET_DEV = { "addr": "TLuTVND9QbZURHmtuqD5ESECrGuB9jLZTs", "key": "TFCrxaUt3EjHzMGKXeBqA7sfy3iaeihg5yZPSrf9KEyy4PHUMWVe" }
WGR_WALLET_OMNO = { "addr": "THofaueWReDjeZQZEECiySqV9GP4byP3qr", "key": "TDJnwRkSk8JiopQrB484Ny9gMcL1x7bQUUFFFNwJZmmWA7U79uRk" }

sport_names = ["Football", "MMA", "CSGO", "DOTA2", "Test Sport", "V2-V3 Sport", "ML Sport One", "Parlay Sport", "Parlay Sport 2", "Spread Sport"]
round_names = ["round1", "round2", "round3", "round4"]
tournament_names = ["UEFA Champions League", "UFC244", "PGL Major Krakow", "EPICENTER Major", "Test Tournament", "V2-V3 Tournament", "ML Tournament One", "Parlay Tournament", "Parlay Tournament 2", "Spread Tournament"]
team_names = ["Real Madrid", "Barcelona", "Jorge Masvidal", "Nate Diaz", "Astralis", "Gambit", "Virtus Pro", "Team Liquid", "Test Team1", "Test Team2","V2-V3 Team1", "V2-V3 Team2", "ML Team One", "ML Team Two", "Parlay Team One", "Parlay Team Two", "Parlay 2 Team One", "Parlay 2 Team Two", "Spread Team One", "Spread Team Two"]

outcome_home_win = 1
outcome_away_win = 2
outcome_draw = 3
outcome_spread_home = 4
outcome_spread_away = 5
outcome_total_over = 6
outcome_total_under = 7

ODDS_DIVISOR = 10000
BETX_PERMILLE = 60

def check_bet_payouts_info(listbets, listpayoutsinfo):
    for bet in listbets:
        info_found = False
        for info in listpayoutsinfo:
            info_type = info['payoutInfo']['payoutType']
            if info_type == 'Betting Payout' or info_type == 'Betting Refund':
                if info['payoutInfo']['betBlockHeight'] == bet['betBlockHeight']:
                    if info['payoutInfo']['betTxHash'] == bet['betTxHash']:
                        if info['payoutInfo']['betTxOut'] == bet['betTxOut']:
                            info_found = True
        assert(info_found)

class BettingTest(BitcoinTestFramework):
    def get_cache_dir_name(self, node_index, block_count):
        return ".test-chain-{0}-{1}-.node{2}".format(self.num_nodes, block_count, node_index)

    def get_node_setting(self, node_index, setting_name):
        with open(os.path.join(self.nodes[node_index].datadir, "wagerr.conf"), 'r', encoding='utf8') as f:
            for line in f:
                if line.startswith(setting_name + "="):
                    return line.split("=")[1].strip("\n")
        return None

    def get_local_peer(self, node_index, is_rpc=False):
        port = self.get_node_setting(node_index, "rpcport" if is_rpc else "port")
        return "127.0.0.1:" + str(rpc_port(node_index) if port is None else port)

    def sync_node_datadir(self, node_index, left, right):
        node = self.nodes[node_index]
        node.stop_node()
        node.wait_until_stopped()
        if not left:
            left = self.nodes[node_index].datadir
        if not right:
            right = self.nodes[node_index].datadir
        if os.path.isdir(right):
            remove_tree(right)
        copy_tree(left, right)
        node.rpchost = self.get_local_peer(node_index, True)
        node.start(self.extra_args)
        node.wait_for_rpc_connection()

    def set_test_params(self):
        self.extra_args = None
        #self.extra_args = [["-debug"], ["-debug"], ["-debug"], ["-debug"]]
        self.setup_clean_chain = True
        self.num_nodes = 4
        self.players = []

    def connect_network(self):
        for pair in [[n, n + 1 if n + 1 < self.num_nodes else 0] for n in range(self.num_nodes)]:
            for i in range(len(pair)):
                assert i < 2
                self.nodes[pair[i]].addnode(self.get_local_peer(pair[1 - i]), "onetry")
                wait_until(lambda:  all(peer['version'] != 0 for peer in self.nodes[pair[i]].getpeerinfo()))
        self.sync_all()
        for n in range(self.num_nodes):
            idx_l = n
            idx_r = n + 1 if n + 1 < self.num_nodes else 0
            assert_equal(self.nodes[idx_l].getblockcount(), self.nodes[idx_r].getblockcount())

    def setup_network(self):
        self.log.info("Setup Network")
        self.setup_nodes()
        self.connect_network()

    def save_cache(self, force=False):
        dir_names = dict()
        for n in range(self.num_nodes):
            dir_name = self.get_cache_dir_name(n, self.nodes[n].getblockcount())
            if force or not os.path.isdir(dir_name):
                dir_names[n] = dir_name
        if len(dir_names) > 0:
            for node_index in dir_names.keys():
                self.sync_node_datadir(node_index, None, dir_names[node_index])
            self.connect_network()

    def load_cache(self, block_count):
        dir_names = dict()
        for n in range(self.num_nodes):
            dir_name = self.get_cache_dir_name(n, block_count)
            if os.path.isdir(dir_name):
                dir_names[n] = dir_name
        if len(dir_names) == self.num_nodes:
            for node_index in range(self.num_nodes):
                self.sync_node_datadir(node_index, dir_names[node_index], None)
            self.connect_network()
            return True
        return False

    def check_minting(self, block_count=250):
        self.log.info("Check Minting...")

        self.nodes[1].importprivkey(WGR_WALLET_ORACLE['key'])
        self.nodes[1].importprivkey(WGR_WALLET_EVENT['key'])
        self.nodes[1].importprivkey(WGR_WALLET_DEV['key'])
        self.nodes[1].importprivkey(WGR_WALLET_OMNO['key'])

        self.players.append(self.nodes[2].getnewaddress('Node2Addr'))
        self.players.append(self.nodes[3].getnewaddress('Node3Addr'))

        for i in range(block_count - 1):
            blocks = self.nodes[0].generate(1)
            blockinfo = self.nodes[0].getblock(blocks[0])
            # get coinbase tx
            rawTx = self.nodes[0].getrawtransaction(blockinfo['tx'][0])
            decodedTx = self.nodes[0].decoderawtransaction(rawTx)
            address = decodedTx['vout'][0]['scriptPubKey']['addresses'][0]
            if (i > 0):
                # minting must process to sigle address
                assert_equal(address, prevAddr)
            prevAddr = address

        for i in range(20):
            self.nodes[0].sendtoaddress(WGR_WALLET_ORACLE['addr'], 2000)
            self.nodes[0].sendtoaddress(WGR_WALLET_EVENT['addr'], 2000)
            self.nodes[0].sendtoaddress(self.players[0], 2000)
            self.nodes[0].sendtoaddress(self.players[1], 2000)

        self.nodes[0].generate(1)

        self.sync_all()

        for n in range(self.num_nodes):
            assert_equal( self.nodes[n].getblockcount(), block_count)

        # check oracle balance
        assert_equal(self.nodes[1].getbalance(), 80000)
        # check players balance
        assert_equal(self.nodes[2].getbalance(), 40000)
        assert_equal(self.nodes[3].getbalance(), 40000)

        self.log.info("Minting Success")

    def check_mapping(self):
        self.log.info("Check Mapping...")

        self.nodes[0].generate(1)
        self.sync_all()

        assert_raises_rpc_error(-1, "No mapping exist for the mapping index you provided.", self.nodes[0].getmappingid, "", "")
        assert_raises_rpc_error(-1, "No mapping exist for the mapping index you provided.", self.nodes[0].getmappingname, "abc123", 0)

        # add sports to mapping
        for id in range(len(sport_names)):
            mapping_opcode = make_mapping(SPORT_MAPPING, id, sport_names[id])
            post_opcode(self.nodes[1], mapping_opcode, WGR_WALLET_ORACLE['addr'])

        # generate block for unlocking used Oracle's UTXO
        self.sync_all()
        self.nodes[0].generate(1)
        self.sync_all()

        # add rounds to mapping
        for id in range(len(round_names)):
            mapping_opcode = make_mapping(ROUND_MAPPING, id, round_names[id])
            post_opcode(self.nodes[1], mapping_opcode, WGR_WALLET_ORACLE['addr'])

        # generate block for unlocking used Oracle's UTXO
        self.sync_all()
        self.nodes[0].generate(1)
        self.sync_all()

        # add teams to mapping
        for id in range(len(team_names)):
            mapping_opcode = make_mapping(TEAM_MAPPING, id, team_names[id])
            post_opcode(self.nodes[1], mapping_opcode, WGR_WALLET_ORACLE['addr'])

        # generate block for unlocking used Oracle's UTXO
        self.sync_all()
        self.nodes[0].generate(1)
        self.sync_all()

        # add tournaments to mapping
        for id in range(len(tournament_names)):
            mapping_opcode = make_mapping(TOURNAMENT_MAPPING, id, tournament_names[id])
            post_opcode(self.nodes[1], mapping_opcode, WGR_WALLET_ORACLE['addr'])

        self.sync_all()
        self.nodes[0].generate(1)
        self.sync_all()

        for node in self.nodes:
            # Check sports mapping
            for id in range(len(sport_names)):
                mapping = node.getmappingname("sports", id)[0]
                assert_equal(mapping['exists'], True)
                assert_equal(mapping['mapping-name'], sport_names[id])
                assert_equal(mapping['mapping-type'], "sports")
                assert_equal(mapping['mapping-index'], id)
                mappingid = node.getmappingid("sports", sport_names[id])[0]
                assert_equal(mappingid['exists'], True)
                assert_equal(mappingid['mapping-index'], "sports")
                assert_equal(mappingid['mapping-id'], id)

            # Check rounds mapping
            for id in range(len(round_names)):
                mapping = node.getmappingname("rounds", id)[0]
                assert_equal(mapping['exists'], True)
                assert_equal(mapping['mapping-name'], round_names[id])
                assert_equal(mapping['mapping-type'], "rounds")
                assert_equal(mapping['mapping-index'], id)
                mappingid = node.getmappingid("rounds", round_names[id])[0]
                assert_equal(mappingid['exists'], True)
                assert_equal(mappingid['mapping-index'], "rounds")
                assert_equal(mappingid['mapping-id'], id)

            # Check teams mapping
            for id in range(len(team_names)):
                mapping = node.getmappingname("teamnames", id)[0]
                assert_equal(mapping['exists'], True)
                assert_equal(mapping['mapping-name'], team_names[id])
                assert_equal(mapping['mapping-type'], "teamnames")
                assert_equal(mapping['mapping-index'], id)
                mappingid = node.getmappingid("teamnames", team_names[id])[0]
                assert_equal(mappingid['exists'], True)
                assert_equal(mappingid['mapping-index'], "teamnames")
                assert_equal(mappingid['mapping-id'], id)

            # Check tournaments mapping
            for id in range(len(tournament_names)):
                mapping = node.getmappingname("tournaments", id)[0]
                assert_equal(mapping['exists'], True)
                assert_equal(mapping['mapping-name'], tournament_names[id])
                assert_equal(mapping['mapping-type'], "tournaments")
                assert_equal(mapping['mapping-index'], id)
                mappingid = node.getmappingid("tournaments", tournament_names[id])[0]
                assert_equal(mappingid['exists'], True)
                assert_equal(mappingid['mapping-index'], "tournaments")
                assert_equal(mappingid['mapping-id'], id)
        self.log.info("Mapping Success")

    def check_event(self):
        self.log.info("Check Event creation...")

        self.start_time = int(time.time() + 60 * 60)
        # array for odds of events
        self.odds_events = []

        # 0: Football - UEFA Champions League - Real Madrid vs Barcelona
        mlevent = make_event(0, # Event ID
                            self.start_time, # start time = current + hour
                            sport_names.index("Football"), # Sport ID
                            tournament_names.index("UEFA Champions League"), # Tournament ID
                            round_names.index("round1"), # Round ID
                            team_names.index("Real Madrid"), # Home Team
                            team_names.index("Barcelona"), # Away Team
                            15000, # home odds
                            18000, # away odds
                            13000) # draw odds
        self.odds_events.append({'homeOdds': 15000, 'awayOdds': 18000, 'drawOdds': 13000})
        post_opcode(self.nodes[1], mlevent, WGR_WALLET_EVENT['addr'])

        # 1: MMA - UFC244 - Jorge Masvidal vs Nate Diaz
        mlevent = make_event(1, # Event ID
                            self.start_time, # start time = current + hour
                            sport_names.index("MMA"), # Sport ID
                            tournament_names.index("UFC244"), # Tournament ID
                            round_names.index("round1"), # Round ID
                            team_names.index("Jorge Masvidal"), # Home Team
                            team_names.index("Nate Diaz"), # Away Team
                            14000, # home odds
                            28000, # away odds
                            50000) # draw odds
        self.odds_events.append({'homeOdds': 14000, 'awayOdds': 28000, 'drawOdds': 50000})
        post_opcode(self.nodes[1], mlevent, WGR_WALLET_EVENT['addr'])

        # 2: CSGO - PGL Major Krakow - Astralis vs Gambit
        mlevent = make_event(2, # Event ID
                            self.start_time, # start time = current + hour
                            sport_names.index("CSGO"), # Sport ID
                            tournament_names.index("PGL Major Krakow"), # Tournament ID
                            round_names.index("round1"), # Round ID
                            team_names.index("Astralis"), # Home Team
                            team_names.index("Gambit"), # Away Team
                            14000, # home odds
                            33000, # away odds
                            0) # draw odds
        self.odds_events.append({'homeOdds': 14000, 'awayOdds': 33000, 'drawOdds': 0})
        post_opcode(self.nodes[1], mlevent, WGR_WALLET_EVENT['addr'])
        # 3: DOTA2 - EPICENTER Major - Virtus Pro vs Team Liquid
        mlevent = make_event(3, # Event ID
                            self.start_time, # start time = current + hour
                            sport_names.index("DOTA2"), # Sport ID
                            tournament_names.index("EPICENTER Major"), # Tournament ID
                            round_names.index("round1"), # Round ID
                            team_names.index("Virtus Pro"), # Home Team
                            team_names.index("Team Liquid"), # Away Team
                            24000, # home odds
                            17000, # away odds
                            0) # draw odds
        self.odds_events.append({'homeOdds': 24000, 'awayOdds': 17000, 'drawOdds': 0})
        post_opcode(self.nodes[1], mlevent, WGR_WALLET_EVENT['addr'])

        self.sync_all()

        self.nodes[0].generate(1)

        self.sync_all()

        for node in self.nodes:
            list_events = node.listevents()
            found_events = 0
            for event in list_events:
                event_id = event['event_id']
                assert_equal(event['sport'], sport_names[event_id])
                assert_equal(event['tournament'], tournament_names[event_id])
                assert_equal(event['teams']['home'], team_names[2 * event_id])
                assert_equal(event['teams']['away'], team_names[(2 * event_id) + 1])

                found_events = found_events | (1 << event['event_id'])
            # check that all events found
            assert_equal(found_events, 0b1111)

        self.log.info("Event creation Success")

    def check_v2_v3_bet(self):
        self.log.info("Check V2 to V3 Bets...")
        # generate so we get to block 300 after event creation & first round bets but before payout sent
        # change this number to change where generate block 300 takes place generate(41) is block 300 for payout
        self.nodes[0].generate(38)
        player1_expected_win = 0
        player2_expected_win = 0
        # make new event, expected result is 1:0
        self.odds_events = []
        mlevent = make_event(10, # Event ID
                    self.start_time, # start time = current + hour
                    sport_names.index("V2-V3 Sport"), # Sport ID
                    tournament_names.index("V2-V3 Tournament"), # Tournament ID
                    round_names.index("round1"), # Round ID
                    team_names.index("V2-V3 Team1"), # Home Team
                    team_names.index("V2-V3 Team2"), # Away Team
                    15000, # home odds
                    18000, # away odds
                    13000) # draw odds
        self.odds_events.append({'homeOdds': 15000, 'awayOdds': 18000, 'drawOdds': 13000})
        post_opcode(self.nodes[1], mlevent, WGR_WALLET_EVENT['addr'])


        self.sync_all()
        self.nodes[0].generate(1)
        self.sync_all()

        # create spread event
        spread_event_opcode = make_spread_event(10, -125, 14000, 26000)
        post_opcode(self.nodes[1], spread_event_opcode, WGR_WALLET_EVENT['addr'])

        self.sync_all()
        self.nodes[0].generate(1)
        self.sync_all()
        #self.log.info("Events")
        #pprint.pprint(self.nodes[1].listevents())

        #events_before=self.nodes[0].listevents()
        #pprint.pprint(events_before[10])

        # place spread bet to spread home
        # in our result it mean 50% bet lose, 50% bet refund
        player1_bet = 400
        self.nodes[2].placebet(10, outcome_spread_home, player1_bet)
        winnings = Decimal(player1_bet * 0.5 * ODDS_DIVISOR)
        player1_expected_win = player1_expected_win + (winnings / ODDS_DIVISOR)

        # change spread condition for event 10
        spread_event_opcode = make_spread_event(10, -75, 13000, 27000)
        post_opcode(self.nodes[1], spread_event_opcode, WGR_WALLET_EVENT['addr'])

        self.log.info("Events before odds updating")
        pprint.pprint(self.nodes[0].listevents())

        self.sync_all()
        self.nodes[0].generate(1)
        self.sync_all()
        
        self.log.info("Events after updating")
        pprint.pprint(self.nodes[0].listevents())

        #should be block height 300
        self.log.info("Block Height %s" % self.nodes[0].getblockcount())
        player1_bet = 300
        self.nodes[2].placebet(10, outcome_spread_away, player1_bet)
        winnings = Decimal(player1_bet * 0.5 * ODDS_DIVISOR)
        player1_expected_win = player1_expected_win + (winnings / ODDS_DIVISOR)

        player2_bet = 600
        # place spread bet to spread away
        # in our result it mean 50% bet lose, 50% bet refund
        self.nodes[3].placebet(10, outcome_spread_away, player2_bet)
        winnings = Decimal(player2_bet * 0.5 * ODDS_DIVISOR)
        player2_expected_win = player2_expected_win + (winnings / ODDS_DIVISOR)

        # place result for event 10 (creates block 301):
        result_opcode = make_result(10, STANDARD_RESULT, 100, 0)
        post_opcode(self.nodes[1], result_opcode, WGR_WALLET_EVENT['addr'])

        self.sync_all()
        self.nodes[0].generate(1)
        self.sync_all()

        player1_balance_before = Decimal(self.nodes[2].getbalance())
        player2_balance_before = Decimal(self.nodes[3].getbalance())

        print("player1 balance before: ", player1_balance_before)
        print("player1 exp win: ", player1_expected_win)
        print("player2 balance before: ", player2_balance_before)
        print("player2 exp win: ", player2_expected_win)

        # generate block with payouts
        blockhash = self.nodes[0].generate(1)[0]
        block = self.nodes[0].getblock(blockhash)
        #should be block height 302
        self.log.info("Block Height %s " % self.nodes[0].getblockcount())

        self.sync_all()
        #time.sleep(2000)

        # print(pprint.pformat(block))

        player1_balance_after = Decimal(self.nodes[2].getbalance())
        player2_balance_after = Decimal(self.nodes[3].getbalance())

        print("player1 balance after: ", player1_balance_after)
        print("player2 balance after: ", player2_balance_after)

        assert_equal(player1_balance_before + player1_expected_win, player1_balance_after)
        assert_equal(player2_balance_before + player2_expected_win, player2_balance_after)

        self.log.info("V2 to V3 Bets Success")

    def check_bets(self):
        self.log.info("Check Bets")
        #time.sleep(2000)
        betam1 = 0
        betpay1 = 0
        betam2 = 0
        betpay2 = 0
        for bets in range(self.num_nodes):
            if bets == 0:
                mybets=self.nodes[bets].getmybets()
                #self.log.info("Bets Node %d" % bets)
                assert_equal(mybets, [])
            elif bets == 1:
                mybets=self.nodes[bets].getmybets()
                #self.log.info("Bets Node %d" % bets)
                assert_equal(mybets, [])
            elif bets == 2:
                mybets=self.nodes[bets].getmybets("Node2Addr", 100)
                #self.log.info("Bets Node %d" % bets)
                #self.log.info("Bet length %d" % len(mybets))
                for bet in range(len(mybets)):
                    #self.log.info("Bet Result %s " % mybets[bet]['betResultType'])
                    betam1 = betam1 + mybets[bet]['amount']
                    #self.log.info("Bet Amount %d " % mybets[bet]['amount'])
                    #self.log.info("Bet Payout %d " % mybets[bet]['payout'])
                    betpay1 = betpay1 + mybets[bet]['payout']
            elif bets == 3:
                mybets=self.nodes[bets].getmybets("Node3Addr", 100)
                #self.log.info("Bets Node %d" % bets)
                #self.log.info("Bet length %d" % len(mybets))
                for bet in range(len(mybets)):
                    #self.log.info("Bet Result %s " % mybets[bet]['betResultType'])
                    #self.log.info("Bet Amount %d " % mybets[bet]['amount'])
                    betam2 = betam2 + mybets[bet]['amount']
                    #self.log.info("Bet Payout %d " % mybets[bet]['payout'])
                    betpay2 = betpay2 + mybets[bet]['payout']
            else:
                self.log.info("No Bets on this Node")

        self.log.info("Total Amount Bet Player 1 %s" % betam1)
        assert_equal(betam1, 700.0000000)
        self.log.info("Total Amount Won Player 1 %s" % betpay1)
        assert_equal(round(Decimal(betpay1), 8), round(Decimal(350.00000000), 8))
        self.log.info("Total Amount Bet Player 2 %s" % betam2)
        assert_equal(betam2, 600.0000000)
        self.log.info("Total Amount Won Player 2 %s" % betpay2)
        assert_equal(round(Decimal(betpay2), 8), round(Decimal(300.00000000), 8))


        self.log.info("Check Bets Success")

    def run_test(self):
        self.check_minting()
        self.check_mapping()
        self.check_event()
        self.check_v2_v3_bet()
        self.check_bets()
        #time.sleep(2000)

if __name__ == '__main__':
    BettingTest().main()
