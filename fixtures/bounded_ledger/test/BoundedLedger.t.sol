// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {BoundedLedger} from "../src/BoundedLedger.sol";

contract BoundedLedgerTest {
    function assertObservation(
        BoundedLedger target,
        uint256 expectedPhase,
        uint256 expectedTotal,
        uint256 expectedReserved,
        bool expectedGoal
    ) internal view {
        (uint256 phase, uint256 total, uint256 reserved, bool goal) = target.observe();
        assert(phase == expectedPhase);
        assert(total == expectedTotal);
        assert(reserved == expectedReserved);
        assert(goal == expectedGoal);
        assert(target.invariantHolds());
    }

    function testInitialAndOutOfOrderCallsAreNoops() external {
        BoundedLedger target = new BoundedLedger();
        target.reserve(type(uint256).max);
        target.settle(type(uint256).max);
        assertObservation(target, 0, 0, 0, false);
        target.open();
        target.open();
        target.settle(56);
        assertObservation(target, 1, 0, 0, false);
    }

    function testMarkerPreservesAccounting() external {
        BoundedLedger target = new BoundedLedger();
        target.open();
        target.reserve(4);
        assertObservation(target, 2, 12, 5, false);
        target.settle(87);
        assertObservation(target, 2, 12, 5, false);
        target.settle(88);
        assertObservation(target, 3, 12, 5, true);
    }

    function testLargestInputDoesNotRevert() external {
        BoundedLedger target = new BoundedLedger();
        target.open();
        target.reserve(type(uint256).max);
        uint256 expectedReserved = (type(uint256).max % 23) + 1;
        uint256 expectedTotal = expectedReserved + 7;
        target.settle(type(uint256).max);
        assertObservation(target, 2, expectedTotal, expectedReserved, false);
        target.settle(expectedTotal * 5 + expectedReserved * 3 + 13);
        assertObservation(target, 3, expectedTotal, expectedReserved, true);
    }

    function testCompletedStateIsStable() external {
        BoundedLedger target = new BoundedLedger();
        target.open();
        target.reserve(0);
        target.settle(56);
        target.open();
        target.reserve(type(uint256).max);
        target.settle(0);
        assertObservation(target, 3, 8, 1, true);
    }

    // Halmos checks typed symbolic inputs; Forge only runs the concrete test* functions.
    function check_invariant(uint256 units, uint256 marker) external {
        BoundedLedger target = new BoundedLedger();
        assert(target.invariantHolds());
        target.open();
        assert(target.invariantHolds());
        target.reserve(units);
        assert(target.invariantHolds());
        target.settle(marker);
        assert(target.invariantHolds());
    }

    function check_initialNoops(uint256 units, uint256 marker) external {
        BoundedLedger target = new BoundedLedger();
        target.reserve(units);
        target.settle(marker);
        assertObservation(target, 0, 0, 0, false);
    }
}
