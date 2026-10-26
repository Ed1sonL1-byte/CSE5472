// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;
import {RequestFlawed} from "../src/RequestFlawed.sol";

contract RequestFlawedTest {
    function testOverApprovalViolatesRequestBound() external {
        RequestFlawed target = new RequestFlawed();
        target.start();
        target.request(7);
        (uint256 p, uint256 r, uint256 a, bool v) = target.observe();
        assert(p == 2 && r == 7 && a == 0 && !v);
        target.confirm(8);
        (p, r, a, v) = target.observe();
        assert(p == 3 && r == 7 && a == 8 && v);
        assert(a > r && !target.propertyHolds() && target.invariantHolds());
    }

    function testEqualApprovalAndInvalidRequests() external {
        RequestFlawed target = new RequestFlawed();
        target.start();
        bool rejected;
        try target.request(0) { rejected = false; } catch { rejected = true; }
        assert(rejected);
        target.request(20);
        target.confirm(20);
        (uint256 p, uint256 r, uint256 a, bool v) = target.observe();
        assert(p == 3 && r == 20 && a == 20 && !v);
    }

    function testConfirmationWithoutRequestReverts() external {
        RequestFlawed target = new RequestFlawed();
        target.start();
        bool rejected;
        try target.confirm(1) { rejected = false; } catch { rejected = true; }
        assert(rejected);
        (uint256 p, uint256 r, uint256 a, bool v) = target.observe();
        assert(p == 1 && r == 0 && a == 0 && !v);
    }
}
