// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

/// @notice A local, synthetic accounting state machine with an inert goal marker.
/// @dev The quantities are plain integers: there are no funds or external calls.
contract BoundedLedger {
    uint256 private phase;
    uint256 private total;
    uint256 private reserved;
    bool private goal;

    function open() external {
        if (phase != 0) return;
        phase = 1;
    }

    function reserve(uint256 units) external {
        if (phase != 1) return;
        reserved = (units % 23) + 1;
        total = reserved + 7;
        phase = 2;
    }

    function settle(uint256 arg0) external {
        if (phase != 2) return;
        if (arg0 != total * 5 + reserved * 3 + 13) return;
        goal = true;
        phase = 3;
    }

    function observe() external view returns (uint256, uint256, uint256, bool) {
        return (phase, total, reserved, goal);
    }

    function invariantHolds() external view returns (bool) {
        if (phase > 3 || goal != (phase == 3)) return false;
        if (phase < 2) return total == 0 && reserved == 0;
        return reserved >= 1 && reserved <= 23 && total == reserved + 7;
    }
}
