// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

/// @notice Inert teaching ledger. Units are counters, not assets.
contract AccountingRepaired {
    uint256 private constant INITIAL_ALLOCATION = 100;
    uint256 private allocated;
    uint256 private spent;
    uint256 private remaining;

    function open() external {
        if (allocated != 0) return;
        allocated = INITIAL_ALLOCATION;
        remaining = INITIAL_ALLOCATION;
    }

    function spend(uint256 amount) external {
        if (allocated == 0 || amount > remaining) return;
        remaining -= amount;
        spent += amount;
    }

    function propertyHolds() public view returns (bool) {
        return allocated == spent + remaining;
    }

    function observe() external view returns (uint256, uint256, uint256, bool) {
        return (allocated, spent, remaining, !propertyHolds());
    }

    function invariantHolds() external view returns (bool) {
        return allocated <= INITIAL_ALLOCATION && spent <= INITIAL_ALLOCATION
            && remaining <= INITIAL_ALLOCATION;
    }
}
