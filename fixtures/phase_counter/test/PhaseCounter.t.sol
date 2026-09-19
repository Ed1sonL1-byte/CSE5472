// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {PhaseCounter} from "../src/PhaseCounter.sol";

contract PhaseCounterTest {
    function assertObservation(
        PhaseCounter target,
        uint256 expectedPhase,
        uint256 expectedCounter,
        bool expectedGoal
    ) internal view {
        (uint256 phase, uint256 counter, uint256 unused, bool goal) = target.observe();
        assert(phase == expectedPhase);
        assert(counter == expectedCounter);
        assert(unused == 0);
        assert(goal == expectedGoal);
        assert(target.invariantHolds());
    }

    function testInitialAndOutOfOrderCallsAreNoops() external {
        PhaseCounter target = new PhaseCounter();
        target.advance(type(uint256).max);
        target.complete(type(uint256).max);
        assertObservation(target, 0, 0, false);
        target.begin();
        target.begin();
        target.complete(32);
        assertObservation(target, 1, 0, false);
    }

    function testMarkerRequiresTheExactValue() external {
        PhaseCounter target = new PhaseCounter();
        target.begin();
        target.advance(5);
        assertObservation(target, 2, 8, false);
        target.complete(66);
        assertObservation(target, 2, 8, false);
        target.complete(67);
        assertObservation(target, 3, 8, true);
    }

    function testLargestInputDoesNotRevert() external {
        PhaseCounter target = new PhaseCounter();
        target.begin();
        target.advance(type(uint256).max);
        uint256 expectedCounter = (type(uint256).max % 17) + 3;
        target.complete(type(uint256).max);
        assertObservation(target, 2, expectedCounter, false);
        target.complete(expectedCounter * 7 + 11);
        assertObservation(target, 3, expectedCounter, true);
    }

    function testCompletedStateIsStable() external {
        PhaseCounter target = new PhaseCounter();
        target.begin();
        target.advance(0);
        target.complete(32);
        target.begin();
        target.advance(type(uint256).max);
        target.complete(0);
        assertObservation(target, 3, 3, true);
    }

    // Halmos checks typed symbolic inputs; Forge only runs the concrete test* functions.
    function check_invariant(uint256 delta, uint256 marker) external {
        PhaseCounter target = new PhaseCounter();
        assert(target.invariantHolds());
        target.begin();
        assert(target.invariantHolds());
        target.advance(delta);
        assert(target.invariantHolds());
        target.complete(marker);
        assert(target.invariantHolds());
    }

    function check_initialNoops(uint256 delta, uint256 marker) external {
        PhaseCounter target = new PhaseCounter();
        target.advance(delta);
        target.complete(marker);
        assertObservation(target, 0, 0, false);
    }
}
