// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

/// @notice A local teaching state machine with a deliberately broad target interval.
/// @dev It holds no assets, performs no external calls, and uses no environment values.
contract RangeGate {
    uint256 private phase;
    uint256 private bound;
    uint256 private offset;
    bool private goal;

    function begin() external {
        if (phase != 0) return;
        phase = 1;
    }

    function configure(uint256 raw) external {
        if (phase != 1) return;
        bound = (raw % 21) + 10;
        phase = 2;
    }

    function passRange(uint256 arg0) external {
        if (phase != 2 || arg0 < bound || arg0 > bound + 32) return;
        offset = arg0 - bound;
        goal = true;
        phase = 3;
    }

    function observe() external view returns (uint256, uint256, uint256, bool) {
        return (phase, bound, offset, goal);
    }

    function invariantHolds() external view returns (bool) {
        if (phase > 3 || goal != (phase == 3)) return false;
        if (phase < 2) return bound == 0 && offset == 0;
        if (bound < 10 || bound > 30) return false;
        if (phase == 2) return offset == 0;
        return offset <= 32;
    }
}
