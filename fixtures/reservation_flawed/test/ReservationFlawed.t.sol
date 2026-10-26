// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;
import {ReservationFlawed} from "../src/ReservationFlawed.sol";

contract ReservationFlawedTest {
    function testFullSettlementDuplicatesOutstandingUnits() external {
        ReservationFlawed target = new ReservationFlawed();
        target.start();
        target.reserve(20);
        (uint256 a, uint256 r, uint256 s, bool v) = target.observe();
        assert(a == 80 && r == 20 && s == 0 && !v);
        target.settle(20);
        (a, r, s, v) = target.observe();
        assert(a == 80 && r == 20 && s == 20 && v);
        assert(a + r + s != 100 && !target.propertyHolds());
        assert(target.invariantHolds());
    }

    function testOrdinaryPartialSettlementConservesUnits() external {
        ReservationFlawed target = new ReservationFlawed();
        target.start();
        target.reserve(20);
        target.settle(7);
        (uint256 a, uint256 r, uint256 s, bool v) = target.observe();
        assert(a == 80 && r == 13 && s == 7 && !v && a + r + s == 100);
    }

    function testInvalidOperationsAreNoops() external {
        ReservationFlawed target = new ReservationFlawed();
        target.reserve(10);
        target.settle(10);
        target.start();
        target.reserve(101);
        target.settle(10);
        (uint256 a, uint256 r, uint256 s, bool v) = target.observe();
        assert(a == 100 && r == 0 && s == 0 && !v);
    }
}
