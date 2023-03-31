from typing import Union, List
from .message import ReadTransaction, WriteTransaction, SWAMPMessage, MemReset
from threading import Condition, Lock


class SynchronizedMemory:

    def __init__(self, transport,
                 memory_size: int,
                 default_mem_pattern: Union[bytearray, None] = None):
        """
        Initialize a new SynchronizedMemory instance.

        :param transport: The transport object to use for message
                          communication.
        :param memory_size: The size of the memory.
        :param default_mem_pattern: The default memory pattern (optional).
        """

        if default_mem_pattern is not None \
                and len(default_mem_pattern) != memory_size:
            raise ValueError(
                "Memory size does not match size of default memory pattern")
        if default_mem_pattern is None:
            default_mem_pattern = bytearray([0 for _ in range(memory_size)])
        self.mem_default: bytearray = default_mem_pattern
        self.transport = transport
        self.memory_cache = bytearray(
            default_mem_pattern) if default_mem_pattern \
            else bytearray(memory_size)
        self.memory_committed = bytearray(self.memory_cache)
        self.read_complete = Condition()
        self.transactions_waited_on = []
        self.in_flight_transactions = []
        self.id = transport.attach_callback(self.receive_response)
        self.transaction_lock = Lock()
        self.rw_lock = Lock()
        self.read_error = None

    @staticmethod
    def update_memory(memory: bytearray, address: int, bitmask: int, value: int):
        """
        Update the memory with the given address, bitmask, and value.

        :param memory: The memory to be updated.
        :param address: The address in memory to be updated.
        :param bitmask: The bitmask to apply the update.
        :param value: The value to be written to memory.
        :return: The updated memory.
        """

        memory[address] = (memory[address] & ~bitmask) | (value & bitmask)
        return memory

    def write(self, messages):
        """
        Write messages to the memory cache and send corresponding transactions.

        Transactions that would override each other are performd as instructed
        The caller is responsible for optimizing the order and number of
        transactions performed.

        :param messages: A list of messages, where each message is a tuple
                         (address, bitmask, value).
        """
        with self.rw_lock:
            with self.transaction_lock:
                for message in messages:
                    address, bitmask, value = message
                    if (self.memory_cache[address] & bitmask) != (value & bitmask):
                        self.memory_cache = self.update_memory(
                            self.memory_cache, address, bitmask, value)
                        value = self.memory_cache[address]
                        transaction = WriteTransaction(
                            address, value, origin_id=self.id)
                        self.in_flight_transactions.append(transaction)
                        self.transport.send_transaction(transaction)

    def read(self, addresses: Union[int, List[int]], from_hardware=False):
        """
        Read a value from the memory cache or committed memory.

        :param address: The address to read from.
        :param committed: A flag to read from the committed memory (default is False).
        :return: The value at the specified address.
        """
        if isinstance(addresses, int):
            addresses = [addresses]

        if from_hardware:
            with self.rw_lock:
                for address in addresses:
                    transaction = ReadTransaction(address,
                                                  origin_id=self.id)
                    with self.transaction_lock:
                        self.in_flight_transactions.append(transaction)
                        self.transactions_waited_on.append(transaction)
                        self.transport.send_transaction(transaction)
                with self.read_complete as cleared_to_read:
                    cleared_to_read.wait()
                if self.read_error is not None:
                    raise ValueError(self.read_error)
                committed_values = [self.memory_committed[adr]
                                    for adr in addresses]
            return committed_values
        else:
            return [self.memory_cache[adr] for adr in addresses]

    def receive_response(self, transactions: Union[SWAMPMessage, List[SWAMPMessage]]):
        """
        Process received transactions and update the memory state accordingly.

        This fuction is intended to be called by the transport and is passed
        as a callback method to the transport during construction of the
        SynchronizedMemory. It waits for threads manipulating the 'in_flight_transactions'
        list to finish their updates and then processes the transactions one by one.

        In case of the MemReset it simply resets the committed memmory.

        In the case of the Write transaction it propagates the change to the
        committed memmory. If any of the transactions failed, this thread will
        raise an error.

        For the Read transactions this method removes the transaction from the
        list of transactions that an update thread is waiting for and notifies
        all waiting threads if the last read transaction has completed. If an error
        occurres it is placed in the 'read error' field of the object that is
        checked by the read method.

        :param transactions: A single transaction or a list of transactions.
        """

        if not isinstance(transactions, list):
            transactions = [transactions]

        with self.transaction_lock:
            for transaction in transactions:
                if transaction in self.in_flight_transactions:
                    del self.in_flight_transactions[
                        self.in_flight_transactions.index(transaction)]

                    if isinstance(transaction, MemReset):
                        if transaction.state == "committed":
                            self.memory_committed = bytearray(self.mem_default)
                        elif transaction.state == "error":
                            raise RuntimeError(
                                f"Transaction {transaction.id} "
                                f"returned an error: {transaction.error_message}")

                    if isinstance(transaction, WriteTransaction):
                        if transaction.state == "committed":
                            bitmask = 0xFF
                            self.memory_committed = self.update_memory(
                                self.memory_committed,
                                transaction.address,
                                bitmask,
                                transaction.value)
                        elif transaction.state == "error":
                            raise RuntimeError(
                                f"Transaction {transaction.id} "
                                f"returned an error: {transaction.error_message}")

                    if isinstance(transaction, ReadTransaction):
                        if transaction in self.transactions_waited_on:
                            del self.transactions_waited_on[
                                self.transactions_waited_on.index(transaction)]
                        if transaction.state == "error":
                            self.read_error = f"Transaction {transaction.id} " + \
                                f"returned an error: {transaction.error_message}"
                        if self.memory_committed[transaction.address] != transaction.value:
                            self.read_error = "Memory read from the hardware does not match the committed memmory"
                        if len(self.transactions_waited_on) == 0:
                            with self.read_complete as rc:
                                rc.notify_all()

    def outstanding_commits(self) -> List[int]:
        """
        Get a list of outstanding uncommitted transactions.

        :return: A list of uncommitted transactions as (address, value) tuples.
        """

        return list(self.in_flight_transactions)

    def reset(self):
        """
        Reset the committed memory to its default state and rebuild the cache from
        the uncommitted transactions.
        """

        with self.transaction_lock:
            self.memory_cache = bytearray(self.mem_default)
            transaction = MemReset(origin_id=self.id)
            self.in_flight_transactions.append(transaction)
            self.transport.send_transaction(transaction)
