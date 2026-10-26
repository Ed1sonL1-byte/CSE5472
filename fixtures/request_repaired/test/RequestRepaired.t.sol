// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;
import {RequestRepaired} from "../src/RequestRepaired.sol";

contract RequestRepairedTest {
    function testSameOverApprovalIsRejected() external {
        RequestRepaired target = new RequestRepaired();
        target.start();
        target.request(7);
        (uint256 p, uint256 r, uint256 a, bool v) = target.observe();
        assert(p == 2 && r == 7 && a == 0 && !v);
        bool rejected;
        try target.confirm(8) { rejected = false; } catch { rejected = true; }
        assert(rejected);
        (p, r, a, v) = target.observe();
        assert(p == 2 && r == 7 && a == 0 && !v);
        assert(a <= r && target.propertyHolds() && target.invariantHolds());
    }

    function testPartialApprovalAndInvalidRequests() external {
        RequestRepaired target = new RequestRepaired();
        target.start();
        bool rejected;
        try target.request(0) { rejected = false; } catch { rejected = true; }
        assert(rejected);
        target.request(20);
        target.confirm(13);
        (uint256 p, uint256 r, uint256 a, bool v) = target.observe();
        assert(p == 3 && r == 20 && a == 13 && !v);
    }

    function testConfirmationWithoutRequestReverts() external {
        RequestRepaired target = new RequestRepaired();
        target.start();
        bool rejected;
        try target.confirm(1) { rejected = false; } catch { rejected = true; }
        assert(rejected);
        (uint256 p, uint256 r, uint256 a, bool v) = target.observe();
        assert(p == 1 && r == 0 && a == 0 && !v);
    }
}
