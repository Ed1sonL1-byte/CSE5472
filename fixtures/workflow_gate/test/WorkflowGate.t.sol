// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {WorkflowGate} from "../src/WorkflowGate.sol";

contract WorkflowGateTest {
    function assertObservation(
        WorkflowGate target,
        uint256 expectedPhase,
        uint256 expectedLane,
        uint256 expectedProgress,
        bool expectedGoal
    ) internal view {
        (uint256 phase, uint256 lane, uint256 progress, bool goal) = target.observe();
        assert(phase == expectedPhase);
        assert(lane == expectedLane);
        assert(progress == expectedProgress);
        assert(goal == expectedGoal);
        assert(target.invariantHolds());
    }

    function testOutOfOrderCallsAreNoops() external {
        WorkflowGate target = new WorkflowGate();
        target.choose(2);
        target.unlock(165);
        target.continueWork(1);
        assertObservation(target, 0, 0, 0, false);
    }

    function testSegmentedConditions() external {
        WorkflowGate target = new WorkflowGate();
        target.start();
        target.choose(2);
        assertObservation(target, 2, 2, 1, false);
        target.unlock(164);
        assertObservation(target, 2, 2, 1, false);
        target.unlock(165);
        assertObservation(target, 3, 2, 2, true);
    }

    function testGoalAllowsFurtherStateAndCoverage() external {
        WorkflowGate left = new WorkflowGate();
        left.start();
        left.choose(0);
        left.unlock(3);
        assertObservation(left, 3, 0, 2, true);
        left.continueWork(0);
        assertObservation(left, 4, 0, 3, true);

        WorkflowGate right = new WorkflowGate();
        right.start();
        right.choose(1);
        right.unlock(7);
        right.continueWork(1);
        assertObservation(right, 5, 1, 4, true);
    }

    function testLargestInputDoesNotRevert() external {
        WorkflowGate target = new WorkflowGate();
        target.start();
        target.choose(type(uint256).max);
        target.unlock(type(uint256).max);
        assert(target.invariantHolds());
    }

    function check_invariant(uint256 raw, uint256 marker, uint256 continuation) external {
        WorkflowGate target = new WorkflowGate();
        target.start();
        target.choose(raw);
        target.unlock(marker);
        target.continueWork(continuation);
        assert(target.invariantHolds());
    }
}
