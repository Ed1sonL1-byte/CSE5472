// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

/// @notice A local teaching workflow whose goal does not terminate later state transitions.
/// @dev It holds no assets, performs no external calls, and uses no environment values.
contract WorkflowGate {
    uint256 private phase;
    uint256 private lane;
    uint256 private progress;
    bool private goal;

    function start() external {
        if (phase != 0) return;
        phase = 1;
    }

    function choose(uint256 raw) external {
        if (phase != 1) return;
        lane = raw % 4;
        progress = 1;
        phase = 2;
    }

    function unlock(uint256 arg0) external {
        if (phase != 2) return;
        bool accepted;
        if (lane == 0) accepted = arg0 % 16 == 3;
        else if (lane == 1) accepted = arg0 % 16 >= 4 && arg0 % 16 <= 7;
        else if (lane == 2) accepted = (arg0 & 255) == 165;
        else accepted = arg0 % 31 == 9;
        if (!accepted) return;
        progress = 2;
        goal = true;
        phase = 3;
    }

    function continueWork(uint256 token) external {
        if (phase != 3 || !goal) return;
        uint256 branch = token % 2;
        progress = 3 + branch;
        phase = 4 + branch;
    }

    function observe() external view returns (uint256, uint256, uint256, bool) {
        return (phase, lane, progress, goal);
    }

    function invariantHolds() external view returns (bool) {
        if (phase > 5 || lane > 3 || progress > 4) return false;
        if (phase == 0) return !goal && lane == 0 && progress == 0;
        if (phase == 1) return !goal && lane == 0 && progress == 0;
        if (phase == 2) return !goal && progress == 1;
        if (phase == 3) return goal && progress == 2;
        return goal && progress == phase - 1;
    }
}
