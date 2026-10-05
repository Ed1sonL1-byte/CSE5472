// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {AccountingFlawed} from "../src/AccountingFlawed.sol";

contract AccountingFlawedTest {
    function testKnownFullSpendViolatesIndependentBalance() external {
        AccountingFlawed target = new AccountingFlawed();
        target.open();
        (uint256 beforeAllocated, uint256 beforeSpent, uint256 beforeRemaining, bool beforeViolation) = target.observe();
        assert(beforeAllocated == 100 && beforeSpent == 0 && beforeRemaining == 100 && !beforeViolation);
        target.spend(100);
        (uint256 allocated, uint256 spent, uint256 remaining, bool reportedViolation) = target.observe();
        assert(allocated == 100 && spent == 0 && remaining == 0);
        assert(allocated != spent + remaining); // Independent property calculation.
        assert(reportedViolation && !target.propertyHolds() && target.invariantHolds());
    }

    function testOrdinaryPartialSpendsAgreeWithAccounting() external {
        AccountingFlawed target = new AccountingFlawed();
        target.open();
        target.spend(7);
        target.spend(13);
        (uint256 allocated, uint256 spent, uint256 remaining, bool violation) = target.observe();
        assert(allocated == 100 && spent == 20 && remaining == 80 && !violation);
        assert(allocated == spent + remaining && target.propertyHolds() && target.invariantHolds());
    }

    function testUnopenedAndOverLimitCallsAreNoops() external {
        AccountingFlawed target = new AccountingFlawed();
        target.spend(1);
        target.open();
        target.spend(101);
        (uint256 allocated, uint256 spent, uint256 remaining, bool violation) = target.observe();
        assert(allocated == 100 && spent == 0 && remaining == 100 && !violation);
    }
}
