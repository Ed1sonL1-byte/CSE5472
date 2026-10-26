// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

/// @notice Inert request/approval counters; no assets or external calls.
contract RequestRepaired {
    uint256 private constant MAX_REQUEST = 100;
    uint256 private phase;
    uint256 private requested;
    uint256 private approved;

    error InvalidRequest();
    error InvalidConfirmation();

    function start() external {
        if (phase == 0) phase = 1;
    }

    function request(uint256 amount) external {
        if (phase != 1 || amount == 0 || amount > MAX_REQUEST) revert InvalidRequest();
        requested = amount;
        phase = 2;
    }

    function confirm(uint256 amount) external {
        if (phase != 2 || amount == 0 || amount > MAX_REQUEST || amount > requested) {
            revert InvalidConfirmation();
        }
        approved = amount;
        phase = 3;
    }

    function propertyHolds() public view returns (bool) {
        return approved <= requested;
    }

    function observe() external view returns (uint256, uint256, uint256, bool) {
        return (phase, requested, approved, !propertyHolds());
    }

    function invariantHolds() external view returns (bool) {
        return phase <= 3 && requested <= MAX_REQUEST && approved <= MAX_REQUEST;
    }
}
