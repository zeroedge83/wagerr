// Copyright (c) 2018 The Wagerr developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BITCOIN_BETTING_PAYOUTS_H
#define BITCOIN_BETTING_PAYOUTS_H

#include "payouts.h"

#include <univalue.h>

std::vector<CBetOut> GetBetPayoutsDebugOrig(int height, UniValue &debugObj);
std::vector<CBetOut> GetBetPayoutsDebug1(int height);
std::vector<CBetOut> GetBetPayoutsDebug2(int height);

#endif // BITCOIN_BETTING_PAYOUTS_H
