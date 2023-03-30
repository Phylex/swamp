from typing import Callable, List
from swamp.message import SWAMPMessage, MemReset


class MockTransport:
    def __init__(self):
        self.transactions: List[SWAMPMessage] = []
        self.callback: Callable = None

    def attach_callback(self, callback: Callable[[SWAMPMessage], None]) -> int:
        self.callback = callback
        return 1  # The mock transport will use 0 as the caller_id

    def send_transaction(self, transaction: SWAMPMessage):
        self.transactions.append(transaction)

    def process_transaction(self, success: bool = True):
        transaction = self.transactions.pop()
        if success:
            transaction.state = "committed"
        else:
            transaction.state = "error"
            transaction.error_message = "Mock error to test handling"
        self.callback(transaction)

    def trigger_reset(self):
        reset_msg = MemReset(origin_id=0)
        self.callback(reset_msg)
