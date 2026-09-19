// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// Synthetic feasibility fixtures, not a production implementation or an
// independently sourced benchmark. There are no external dependencies.
interface Vm {
    function deal(address who, uint256 balance) external;
}

contract Receiver {
    receive() external payable {}
}

contract RejectingReceiver {
    receive() external payable { revert("recipient rejects payment"); }
    function claim(Queue queue, address payable to) external {
        queue.claim(to);
    }
}

contract Queue {
    struct Payment { address payable recipient; uint256 amount; }
    Payment[] public payments;
    mapping(address => uint256) public deferred;
    uint256 public cursor;
    bool public immutable isolateFailure;

    constructor(bool isolate) { isolateFailure = isolate; }

    function enqueue(address payable recipient) external payable {
        require(msg.value > 0);
        payments.push(Payment(recipient, msg.value));
    }

    function process(uint256 count) external {
        uint256 end = cursor + count;
        if (end > payments.length) end = payments.length;
        while (cursor < end) {
            Payment memory payment = payments[cursor++];
            (bool ok,) = payment.recipient.call{value: payment.amount, gas: 30_000}("");
            if (!ok) {
                require(isolateFailure, "whole batch reverts");
                deferred[payment.recipient] += payment.amount;
            }
        }
    }

    function claim(address payable recipient) external {
        uint256 amount = deferred[msg.sender];
        require(amount > 0);
        deferred[msg.sender] = 0;
        (bool ok,) = recipient.call{value: amount}("");
        require(ok);
    }
}

contract PauseVault {
    mapping(address => uint256) public credit;
    address public immutable admin;
    uint8 public immutable mode;
    bool public paused;

    // 0: alternate withdrawal bypasses pause.
    // 1: emergency exit accidentally blocked by shared pause condition.
    // 2: fixture satisfies the explicitly selected policy.
    constructor(uint8 selectedMode) { admin = msg.sender; mode = selectedMode; }

    function setPaused(bool value) external {
        require(msg.sender == admin);
        paused = value;
    }

    function deposit() external payable {
        require(!paused);
        credit[msg.sender] += msg.value;
    }

    function withdraw(uint256 amount) external {
        require(!paused);
        _pay(msg.sender, amount);
    }

    function withdrawTo(address recipient, uint256 amount) external {
        if (mode != 0) require(!paused);
        _pay(recipient, amount);
    }

    function emergencyWithdraw() external {
        require(paused);
        _pay(msg.sender, credit[msg.sender]);
    }

    function _pay(address recipient, uint256 amount) internal {
        if (mode == 1) require(!paused);
        credit[msg.sender] -= amount;
        (bool ok,) = payable(recipient).call{value: amount}("");
        require(ok);
    }
}

contract FeasibilityTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 constant UNIT = 1 ether;
    receive() external payable {}

    function queueFixture(bool isolated)
        internal returns (Queue queue, Receiver alice, RejectingReceiver bad, Receiver bob)
    {
        vm.deal(address(this), 10 * UNIT);
        queue = new Queue(isolated);
        alice = new Receiver();
        bad = new RejectingReceiver();
        bob = new Receiver();
        // Funding occurs only through the public enqueue operation.
        queue.enqueue{value: UNIT}(payable(address(alice)));
        queue.enqueue{value: UNIT}(payable(address(bad)));
        queue.enqueue{value: UNIT}(payable(address(bob)));
    }

    function testLiveBatchFailureBlocksBothHonestUsers() external {
        (Queue queue, Receiver alice,, Receiver bob) = queueFixture(false);
        (bool ok,) = address(queue).call(abi.encodeCall(Queue.process, (3)));
        require(!ok && queue.cursor() == 0, "expected batch rollback");
        require(address(alice).balance == 0 && address(bob).balance == 0);
    }

    function testLivePaginationAloneLeavesHonestUserBlocked() external {
        (Queue queue, Receiver alice,, Receiver bob) = queueFixture(false);
        queue.process(1);
        require(address(alice).balance == UNIT);
        for (uint256 i = 0; i < 3; i++) {
            (bool ok,) = address(queue).call(abi.encodeCall(Queue.process, (1)));
            require(!ok && queue.cursor() == 1);
        }
        require(address(bob).balance == 0, "later honest user still blocked");
    }

    function testLiveIsolationPaysHonestUsersAndPreservesDeferredCredit() external {
        (Queue queue, Receiver alice, RejectingReceiver bad, Receiver bob) = queueFixture(true);
        queue.process(3);
        require(address(alice).balance == UNIT && address(bob).balance == UNIT);
        require(queue.cursor() == 3 && queue.deferred(address(bad)) == UNIT);
        require(address(queue).balance == UNIT, "unpaid funds must be preserved");
        Receiver alternative = new Receiver();
        bad.claim(queue, payable(address(alternative)));
        require(address(alternative).balance == UNIT && address(queue).balance == 0);
        require(queue.deferred(address(bad)) == 0);
        (bool repeat,) = address(bad).call(abi.encodeCall(RejectingReceiver.claim, (queue, payable(address(alternative)))));
        require(!repeat, "deferred payment must not be paid twice");
    }

    function pauseFixture(uint8 mode) internal returns (PauseVault vault) {
        vm.deal(address(this), 10 * UNIT);
        vault = new PauseVault(mode);
        vault.deposit{value: 2 * UNIT}();
    }

    function testPauseAlternativeEntryReallyTransfersFunds() external {
        PauseVault vault = pauseFixture(0);
        Receiver recipient = new Receiver();
        vault.setPaused(true);
        (bool regular,) = address(vault).call(abi.encodeCall(PauseVault.withdraw, (UNIT)));
        require(!regular);
        vault.withdrawTo(address(recipient), UNIT);
        require(address(recipient).balance == UNIT && vault.credit(address(this)) == UNIT);
    }

    function testPauseSharedGuardBlocksRequiredEmergencyExit() external {
        PauseVault vault = pauseFixture(1);
        // Valid normal withdrawal demonstrates sufficient balance and valid caller.
        vault.withdraw(UNIT);
        vault.setPaused(true);
        (bool emergency,) = address(vault).call(abi.encodeCall(PauseVault.emergencyWithdraw, ()));
        require(!emergency && vault.credit(address(this)) == UNIT);
    }

    function testPauseCorrectPolicyAndResume() external {
        PauseVault vault = pauseFixture(2);
        vault.setPaused(true);
        (bool ordinary,) = address(vault).call(abi.encodeCall(PauseVault.withdraw, (UNIT)));
        (bool alternate,) = address(vault).call(abi.encodeCall(PauseVault.withdrawTo, (address(this), UNIT)));
        require(!ordinary && !alternate);
        vault.emergencyWithdraw();
        require(vault.credit(address(this)) == 0 && address(vault).balance == 0);
        vault.setPaused(false);
        vault.deposit{value: UNIT}();
        vault.withdraw(UNIT);
        require(vault.credit(address(this)) == 0 && address(vault).balance == 0);
    }
}
