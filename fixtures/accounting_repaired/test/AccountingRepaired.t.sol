// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {AccountingRepaired} from "../src/AccountingRepaired.sol";

contract AccountingRepairedTest {
    function testSameKnownFullSpendPreservesIndependentBalance() external {
        AccountingRepaired target = new AccountingRepaired();
        target.open();
        target.spend(100);
        (uint256 allocated, uint256 spent, uint256 remaining, bool reportedViolation) = target.observe();
        assert(allocated == 100 && spent == 100 && remaining == 0);
        assert(allocated == spent + remaining); // Independent property calculation.
        assert(!reportedViolation && target.propertyHolds() && target.invariantHolds());
    }

    function testOrdinaryPartialSpendsAgreeWithAccounting() external {
        AccountingRepaired target = new AccountingRepaired();
        target.open();
        target.spend(7);
        target.spend(13);
        (uint256 allocated, uint256 spent, uint256 remaining, bool violation) = target.observe();
        assert(allocated == 100 && spent == 20 && remaining == 80 && !violation);
        assert(allocated == spent + remaining && target.propertyHolds() && target.invariantHolds());
    }

    function testUnopenedAndOverLimitCallsAreNoops() external {
        AccountingRepaired target = new AccountingRepaired();
        target.spend(1);
        target.open();
        target.spend(101);
        (uint256 allocated, uint256 spent, uint256 remaining, bool violation) = target.observe();
        assert(allocated == 100 && spent == 0 && remaining == 100 && !violation);
    }
}
