// Copyright (c) 2019 The Wagerr developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "bet.h"
#include "payouts.h"
#include "wallet.h"

#include <assert.h>

std::vector<CTxOut> GetBetPayoutsDebug(int height)
{
    std::vector<CTxOut> vexpectedPayouts;
    int nCurrentHeight = chainActive.Height();

    // Get all the results posted in the latest block.
    std::vector<CPeerlessResult> results = getEventResults(height);

    // Traverse the blockchain for an event to match a result and all the bets on a result.
    for (const auto& result : results) {
        // Look back the chain 14 days for any events and bets.
        CBlockIndex *BlocksIndex = NULL;
        BlocksIndex = chainActive[nCurrentHeight - Params().BetBlocksIndexTimespan()];

        uint64_t oddsDivisor  = Params().OddsDivisor();
        uint64_t betXPermille = Params().BetXPermille();

        OutcomeType nMoneylineResult = (OutcomeType) 0;
        std::vector<OutcomeType> vSpreadsResult;
        std::vector<OutcomeType> vTotalsResult;

        uint64_t nMoneylineOdds     = 0;
        uint64_t nSpreadsOdds       = 0;
        uint64_t nTotalsOdds        = 0;
        uint64_t nTotalsPoints      = result.nHomeScore + result.nAwayScore;
        uint64_t nSpreadsDifference = 0;
        bool HomeFavorite               = false;

        // We keep temp values as we can't be sure of the order of the TX's being stored in a block.
        // This can lead to a case were some bets don't
        uint64_t nTempMoneylineOdds = 0;
        uint64_t nTempSpreadsOdds   = 0;
        uint64_t nTempTotalsOdds    = 0;

        bool UpdateMoneyLine = false;
        bool UpdateSpreads   = false;
        bool UpdateTotals    = false;
        uint64_t nSpreadsWinner = 0;
        uint64_t nTotalsWinner  = 0;

        time_t tempEventStartTime   = 0;
        time_t latestEventStartTime = 0;
        bool eventFound = false;
        bool spreadsFound = false;
        bool totalsFound = false;

        // Find MoneyLine outcome (result).
        if (result.nHomeScore > result.nAwayScore) {
            nMoneylineResult = moneyLineWin;
        }
        else if (result.nHomeScore < result.nAwayScore) {
            nMoneylineResult = moneyLineLose;
        }
        else if (result.nHomeScore == result.nAwayScore) {
            nMoneylineResult = moneyLineDraw;
        }

        // Traverse the block chain to find events and bets.
        while (BlocksIndex) {
            CBlock block;
            ReadBlockFromDisk(block, BlocksIndex);
            time_t transactionTime = block.nTime;

            BOOST_FOREACH(CTransaction &tx, block.vtx) {
                // Check all TX vouts for an OP RETURN.
                for (unsigned int i = 0; i < tx.vout.size(); i++) {

                    const CTxOut &txout = tx.vout[i];
                    std::string scriptPubKey = txout.scriptPubKey.ToString();
                    CAmount betAmount = txout.nValue;

                    if (scriptPubKey.length() > 0 && 0 == strncmp(scriptPubKey.c_str(), "OP_RETURN", 9)) {

                        // Ensure TX has it been posted by Oracle wallet.
                        const CTxIn &txin = tx.vin[0];
                        bool validOracleTx = IsValidOracleTx(txin);

                        // Get the OP CODE from the transaction scriptPubKey.
                        vector<unsigned char> vOpCode = ParseHex(scriptPubKey.substr(9, string::npos));
                        std::string opCode(vOpCode.begin(), vOpCode.end());

                        // Peerless event OP RETURN transaction.
                        CPeerlessEvent pe;
                        if (validOracleTx && CPeerlessEvent::FromOpCode(opCode, pe)) {

                            // If the current event matches the result we can now set the odds.
                            if (result.nEventId == pe.nEventId) {

                                LogPrintf("EVENT OP CODE - %s \n", opCode.c_str());

                                UpdateMoneyLine    = true;
                                eventFound         = true;
                                tempEventStartTime = pe.nStartTime;

                                // Set the temp moneyline odds.
                                if (nMoneylineResult == moneyLineWin) {
                                    nTempMoneylineOdds = pe.nHomeOdds;
                                }
                                else if (nMoneylineResult == moneyLineLose) {
                                    nTempMoneylineOdds = pe.nAwayOdds;
                                }
                                else if (nMoneylineResult == moneyLineDraw) {
                                    nTempMoneylineOdds = pe.nDrawOdds;
                                }

                                // Set which team is the favorite, used for calculating spreads difference & winner.
                                if (pe.nHomeOdds < pe.nAwayOdds) {
                                    HomeFavorite = true;
                                    if (result.nHomeScore > result.nAwayScore) {
                                        nSpreadsDifference = result.nHomeScore - result.nAwayScore;
                                    }
                                    else{
                                        nSpreadsDifference = 0;
                                    }
                                }
                                else {
                                    HomeFavorite = false;
                                    if (result.nAwayScore > result.nHomeScore) {
                                        nSpreadsDifference = result.nAwayScore - result.nHomeScore;
                                    }

                                    else{
                                        nSpreadsDifference = 0;
                                    }
                                }
                            }
                        }

                        // Peerless update odds OP RETURN transaction.
                        CPeerlessUpdateOdds puo;
                        if (eventFound && validOracleTx && CPeerlessUpdateOdds::FromOpCode(opCode, puo) && result.nEventId == puo.nEventId ) {

                            LogPrintf("PUO EVENT OP CODE - %s \n", opCode.c_str());

                            UpdateMoneyLine = true;

                            // If current event ID matches result ID set the odds.
                            if (nMoneylineResult == moneyLineWin) {
                                nTempMoneylineOdds = puo.nHomeOdds;
                            }
                            else if (nMoneylineResult == moneyLineLose) {
                                nTempMoneylineOdds = puo.nAwayOdds;
                            }
                            else if (nMoneylineResult == moneyLineDraw) {
                                nTempMoneylineOdds = puo.nDrawOdds;
                            }
                        }

                        // Handle PSE, when we find a Spreads event on chain we need to update the Spreads odds.
                        CPeerlessSpreadsEvent pse;
                        if (eventFound && validOracleTx && CPeerlessSpreadsEvent::FromOpCode(opCode, pse) && result.nEventId == pse.nEventId) {

                            LogPrintf("PSE EVENT OP CODE - %s \n", opCode.c_str());

                            UpdateSpreads = true;
                            spreadsFound  = true;

                            // If the home team is the favourite.
                            if (HomeFavorite){
                                //  Choose the spreads winner.
                                if (nSpreadsDifference == 0) {
                                    nSpreadsWinner = WinnerType::awayWin;
                                }
                                else if (pse.nPoints < nSpreadsDifference) {
                                    nSpreadsWinner = WinnerType::homeWin;
                                }
                                else if (pse.nPoints > nSpreadsDifference) {
                                    nSpreadsWinner = WinnerType::awayWin;
                                }
                                else {
                                    nSpreadsWinner = WinnerType::push;
                                }
                            }
                            // If the away team is the favourite.
                            else {
                                // Cho0se the winner.
                                if (nSpreadsDifference == 0) {
                                    nSpreadsWinner = WinnerType::homeWin;
                                }
                                else if (pse.nPoints > nSpreadsDifference) {
                                    nSpreadsWinner = WinnerType::homeWin;
                                }
                                else if (pse.nPoints < nSpreadsDifference) {
                                    nSpreadsWinner = WinnerType::awayWin;
                                }
                                else {
                                    nSpreadsWinner = WinnerType::push;
                                }
                            }

                            // Set the temp spread odds.
                            if (nSpreadsWinner == WinnerType::push) {
                                nTempSpreadsOdds = Params().OddsDivisor();
                            }
                            else if (nSpreadsWinner == WinnerType::awayWin) {
                                nTempSpreadsOdds = pse.nAwayOdds;
                            }
                            else if (nSpreadsWinner == WinnerType::homeWin) {
                                nTempSpreadsOdds = pse.nHomeOdds;
                            }
                        }

                        // Handle PTE, when we find an Totals event on chain we need to update the Totals odds.
                        CPeerlessTotalsEvent pte;
                        if (eventFound && validOracleTx && CPeerlessTotalsEvent::FromOpCode(opCode, pte) && result.nEventId == pte.nEventId) {

                            LogPrintf("PTE EVENT OP CODE - %s \n", opCode.c_str());

                            UpdateTotals = true;
                            totalsFound  = true;

                            // Find totals outcome (result).
                            if (pte.nPoints == nTotalsPoints) {
                                nTotalsWinner = WinnerType::push;
                            }
                            else if (pte.nPoints > nTotalsPoints) {
                                nTotalsWinner = WinnerType::awayWin;
                            }
                            else {
                                nTotalsWinner = WinnerType::homeWin;
                            }

                            // Set the totals temp odds.
                            if (nTotalsWinner == WinnerType::push) {
                                nTempTotalsOdds = Params().OddsDivisor();
                            }
                            else if (nTotalsWinner == WinnerType::awayWin) {
                                nTempTotalsOdds = pte.nUnderOdds;
                            }
                            else if (nTotalsWinner == WinnerType::homeWin) {
                                nTempTotalsOdds = pte.nOverOdds;
                            }
                        }

                        // If we encounter the result after cycling the chain then we dont need go any furture so finish the payout.
                        CPeerlessResult pr;
                        if (eventFound && validOracleTx && CPeerlessResult::FromOpCode(opCode, pr) && result.nEventId == pr.nEventId ) {

                            LogPrintf("Result found ending search \n");

                            return vexpectedPayouts;
                        }

                        // Only payout bets that are between 25 - 10000 WRG inclusive (MaxBetPayoutRange).
                        if (eventFound && betAmount >= (Params().MinBetPayoutRange() * COIN) && betAmount <= (Params().MaxBetPayoutRange() * COIN)) {

                            // Bet OP RETURN transaction.
                            CPeerlessBet pb;
                            if (CPeerlessBet::FromOpCode(opCode, pb)) {

                                CAmount payout = 0 * COIN;

                                // If bet was placed less than 20 mins before event start or after event start discard it.
                                if (latestEventStartTime > 0 && (unsigned int) transactionTime > (latestEventStartTime - Params().BetPlaceTimeoutBlocks())) {
                                    continue;
                                }

                                // Is the bet a winning bet?
                                if (result.nEventId == pb.nEventId) {
                                    CAmount winnings = 0;

                                    // If bet payout result.
                                    if (result.nResultType ==  ResultType::standardResult) {

                                        // Calculate winnings.
                                        if (pb.nOutcome == nMoneylineResult) {
                                            winnings = betAmount * nMoneylineOdds;
                                        }
                                        else if (spreadsFound && (pb.nOutcome == vSpreadsResult.at(0) || pb.nOutcome == vSpreadsResult.at(1))) {
                                            winnings = betAmount * nSpreadsOdds;
                                        }
                                        else if (totalsFound && (pb.nOutcome == vTotalsResult.at(0) || pb.nOutcome == vTotalsResult.at(1))) {
                                           winnings = betAmount * nTotalsOdds;
                                        }

                                        // Calculate the bet winnings for the current bet.
                                        if (winnings > 0) {
                                            payout = (winnings - ((winnings - betAmount*oddsDivisor) / 1000 * betXPermille)) / oddsDivisor;
                                        }
                                        else {
                                            payout = 0;
                                        }
                                    }
                                    // Bet refund result.
                                    else if (result.nResultType ==  ResultType::eventRefund){
                                        payout = betAmount;
                                    }

                                    // Get the users payout address from the vin of the bet TX they used to place the bet.
                                    CTxDestination payoutAddress;
                                    const CTxIn &txin = tx.vin[0];
                                    COutPoint prevout = txin.prevout;

                                    uint256 hashBlock;
                                    CTransaction txPrev;
                                    if (GetTransaction(prevout.hash, txPrev, hashBlock, true)) {
                                        ExtractDestination( txPrev.vout[prevout.n].scriptPubKey, payoutAddress );
                                    }

                                    LogPrintf("WINNING PAYOUT :)\n");
                                    LogPrintf("AMOUNT: %li \n", payout);
                                    LogPrintf("ADDRESS: %s \n", CBitcoinAddress( payoutAddress ).ToString().c_str());

                                    // Only add valid payouts to the vector.
                                    if (payout > 0) {
                                        // Add winning bet payout to the bet vector.
                                        vexpectedPayouts.emplace_back(payout, GetScriptForDestination(CBitcoinAddress(payoutAddress).Get()), betAmount);
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // If an update transaction came in on this block, the bool would be set to true and the odds/winners will be updated (below) for the next block
            if (UpdateMoneyLine){
                UpdateMoneyLine      = false;
                nMoneylineOdds       = nTempMoneylineOdds;
                latestEventStartTime = tempEventStartTime;
            }

            // If we need to update the spreads odds using temp values.
            if (UpdateSpreads) {
                UpdateSpreads = false;
                //set the payout odds (using the temp odds)
                nSpreadsOdds = nTempSpreadsOdds;
                //clear the winner vector (used to determine which bets to payout).
                vSpreadsResult.clear();

                //Depending on the calculations above we populate the winner vector (push/away/home)
                if (nSpreadsWinner == WinnerType::homeWin) {
                    vSpreadsResult.emplace_back(spreadHome);
                    vSpreadsResult.emplace_back(spreadHome);
                }
                else if (nSpreadsWinner == WinnerType::awayWin) {
                    vSpreadsResult.emplace_back(spreadAway);
                    vSpreadsResult.emplace_back(spreadAway);
                }
                else if (nSpreadsWinner == WinnerType::push) {
                    vSpreadsResult.emplace_back(spreadHome);
                    vSpreadsResult.emplace_back(spreadAway);
                }

                nSpreadsWinner = 0;
            }

            // If we need to update the totals odds using the temp values.
            if (UpdateTotals) {
                UpdateTotals = false;
                nTotalsOdds  = nTempTotalsOdds;
                vTotalsResult.clear();

                if (nTotalsWinner == WinnerType::homeWin) {
                    vTotalsResult.emplace_back(totalOver);
                    vTotalsResult.emplace_back(totalOver);
                }
                else if (nTotalsWinner == WinnerType::awayWin) {
                    vTotalsResult.emplace_back(totalUnder);
                    vTotalsResult.emplace_back(totalUnder);
                }
                else if (nTotalsWinner == WinnerType::push) {
                    vTotalsResult.emplace_back(totalOver);
                    vTotalsResult.emplace_back(totalUnder);
                }

                nTotalsWinner = 0;
            }

            BlocksIndex = chainActive.Next(BlocksIndex);
        }
    }

    return vexpectedPayouts;
}
