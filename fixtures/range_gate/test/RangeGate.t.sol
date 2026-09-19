// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {RangeGate} from "../src/RangeGate.sol";

contract RangeGateTest {
    function assertObservation(
        RangeGate target,
        uint256 expectedPhase,
        uint256 expectedBound,
        uint256 expectedOffset,
        bool expectedGoal
    ) internal view {
        (uint256 phase, uint256 bound, uint256 offset, bool goal) = target.observe();
        assert(phase == expectedPhase);
        assert(bound == expectedBound);
        assert(offset == expectedOffset);
        assert(goal == expectedGoal);
        assert(target.invariantHolds());
    }

    function testOutOfOrderCallsAreNoops() external {
        RangeGate target = new RangeGate();
        target.configure(0);
        target.passRange(32);
        assertObservation(target, 0, 0, 0, false);
    }

    function testOrdinaryBoundaryInputReachesGoal() external {
        RangeGate target = new RangeGate();
        target.begin();
        target.configure(20);
        assertObservation(target, 2, 30, 0, false);
        target.passRange(29);
        assertObservation(target, 2, 30, 0, false);
        target.passRange(32);
        assertObservation(target, 3, 30, 2, true);
    }

    function testLargestInputDoesNotRevert() external {
        RangeGate target = new RangeGate();
        target.begin();
        target.configure(type(uint256).max);
        (, uint256 bound, , ) = target.observe();
        target.passRange(type(uint256).max);
        assertObservation(target, 2, bound, 0, false);
        target.passRange(bound + 32);
        assertObservation(target, 3, bound, 32, true);
    }

    function testCompletedStateIsStable() external {
        RangeGate target = new RangeGate();
        target.begin();
        target.configure(0);
        target.passRange(10);
        target.begin();
        target.configure(7);
        target.passRange(0);
        assertObservation(target, 3, 10, 0, true);
    }

    function check_invariant(uint256 raw, uint256 marker) external {
        RangeGate target = new RangeGate();
        target.begin();
        target.configure(raw);
        target.passRange(marker);
        assert(target.invariantHolds());
    }
}
