// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

/// @notice Inert reservation counters; no assets or external calls.
contract ReservationFlawed {
    uint256 private constant CAPACITY = 100;
    uint256 private available = CAPACITY;
    uint256 private reserved;
    uint256 private settled;
    bool private started;

    function start() external {
        started = true;
    }

    function reserve(uint256 amount) external {
        if (!started || amount == 0 || amount > available) return;
        available -= amount;
        reserved += amount;
    }

    function settle(uint256 amount) external {
        if (!started || amount == 0 || amount > reserved) return;
        settled += amount;
        if (amount == reserved) {
            // Defect: the close-out path credits settlement but leaves the
            // reservation outstanding, counting those units twice.
            return;
        }
        reserved -= amount;
    }

    function propertyHolds() public view returns (bool) {
        return available + reserved + settled == CAPACITY;
    }

    function observe() external view returns (uint256, uint256, uint256, bool) {
        return (available, reserved, settled, !propertyHolds());
    }

    function invariantHolds() external view returns (bool) {
        return available <= CAPACITY && reserved <= CAPACITY && settled <= CAPACITY;
    }
}
