from typing import Callable, List
from time import sleep
from swamp.message import SWAMPMessage, MemReset
from threading import Thread


class MockTransport:
    """
    Class used to mock the transport component of a swamp object to
    aid in testing the Syncronized memory
    """
    def __init__(self):
        self.transactions: List[SWAMPMessage] = []
        self.callback: Callable = None
        self.log = []
        self.thread = None
        self.kill = False

    def multithreaded_operation(self, transaction_status: List[bool]):
        """
        As the swamp message passing is done concurrently,
        we need to be able to stop and reawaken the DUT. This needs to
        be done by a different thread, which is started here

        :param transaction_status: A list of statuses that the incoming
                                   transactions are acknowledged with.
                                   The length of the list determins after
                                   how many transactions the thread exists
                                   The thread is killed upon destruction
                                   of the mock-transport
        """
        self.thread = Thread(target=self.listen, args=transaction_status)
        self.thread.start()

    def listen(self, transaction_status: List[bool]):
        """
        This function listens for transactions from the DUT and processes them.


        """
        for status in transaction_status:
            while len(self.transactions) == 0:
                if self.kill:
                    return
                self.log.append('nothing to do and waiting on message')
                sleep(0.5)
            assert len(self.transactions) > 0
            self.log.append(
                    f'received transaction, processing it with status {status}')
            self.process_transaction(status)

    def __del__(self):
        self.kill = True
        self.thread.join()


    def attach_callback(self, callback: Callable[[SWAMPMessage], None]) -> int:
        self.callback = callback
        return 1  # The mock transport will use 1 as the caller_id

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
