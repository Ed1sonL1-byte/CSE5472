// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

/// @notice A local, synthetic state machine for bounded reachability checks.
/// @dev No funds, external calls, access controls, or environment dependencies.
contract PhaseCounter {
    uint256 private phase;
    uint256 private counter;
    bool private goal;

    function begin() external {
        if (phase != 0) return;
        phase = 1;
    }

    function advance(uint256 delta) external {
        if (phase != 1) return;
        counter = (delta % 17) + 3;
        phase = 2;
    }

    function complete(uint256 arg0) external {
        if (phase != 2) return;
        if (arg0 != counter * 7 + 11) return;
        goal = true;
        phase = 3;
    }

    function observe() external view returns (uint256, uint256, uint256, bool) {
        return (phase, counter, 0, goal);
    }

    function invariantHolds() external view returns (bool) {
        if (phase > 3 || goal != (phase == 3)) return false;
        if (phase < 2) return counter == 0;
        return counter >= 3 && counter <= 19;
    }
}
