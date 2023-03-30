from typing import Union, List
from .message import ReadTransaction, WriteTransaction, SWAMPMessage, MemReset


class SynchronizedMemory:

    def __init__(self, transport,
                 memory_size: int,
                 default_mem_pattern: Union[bytearray, None] = None):
        """
        Initialize a new SynchronizedMemory instance.

        :param transport: The transport object to use for message communication.
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
        self.caller_id = transport.attach_callback(self.receive_response)
        self.uncommitted_transactions = {}

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

        :param messages: A list of messages, where each message is a tuple (address, bitmask, value).
        """

        for message in messages:
            address, bitmask, value = message
            if (self.memory_cache[address] & bitmask) != (value & bitmask):
                self.memory_cache = self.update_memory(
                    self.memory_cache, address, bitmask, value)
                value = self.memory_cache[address]
                transaction = WriteTransaction(
                    address, value, origin_id=self.caller_id)
                self.uncommitted_transactions[transaction.transaction_id] = (
                    address, value)
                self.transport.send_transaction(transaction)

    def read(self, address, committed=False):
        """
        Read a value from the memory cache or committed memory.

        :param address: The address to read from.
        :param committed: A flag to read from the committed memory (default is False).
        :return: The value at the specified address.
        """

        if committed:
            if any(stored_address == address
                   for stored_address, _ in
                   self.uncommitted_transactions.values()):
                raise ValueError(
                    "Uncommitted changes present at the requested address.")
            return self.memory_committed[address]

        transaction = ReadTransaction(address, origin_id=self.caller_id)
        self.transport.send_transaction(transaction)
        return self.memory_cache[address]

    def receive_response(self, transactions: Union[SWAMPMessage, List[SWAMPMessage]]):
        """
        Process received transactions and update the memory state accordingly.

        This fuction is intended to be called by the transport and is passed
        as a callback method to the transport during construction of the
        SynchronizedMemory.

        :param transactions: A single transaction or a list of transactions.
        """

        if not isinstance(transactions, list):
            transactions = [transactions]

        for transaction in transactions:
            transaction_id = transaction.transaction_id
            if isinstance(transaction, MemReset):
                self.reset()
            elif transaction_id in self.uncommitted_transactions:
                if transaction.state == "committed":
                    if isinstance(transaction, WriteTransaction):
                        address, value = self.uncommitted_transactions[transaction_id]
                        bitmask = 0xFF
                        self.memory_committed = self.update_memory(
                            self.memory_committed, address, bitmask, value)
                    del self.uncommitted_transactions[transaction_id]
                elif transaction.state == "error":
                    address, value = self.uncommitted_transactions[transaction_id]
                    del self.uncommitted_transactions[transaction_id]
                    raise RuntimeError(
                        f"Transaction {transaction_id} "
                        f"returned an error: {transaction.error_message}")

    def outstanding_commits(self) -> List[int]:
        """
        Get a list of outstanding uncommitted transactions.

        :return: A list of uncommitted transactions as (address, value) tuples.
        """

        return list(map(lambda x: x[0],
                        self.uncommitted_transactions.values()))

    def reset(self):
        """
        Reset the committed memory to its default state and rebuild the cache from
        the uncommitted transactions.
        """

        self.memory_committed = bytearray(self.mem_default)
        self.memory_cache = bytearray(self.mem_default)
        for address, value in self.uncommitted_transactions.values():
            bitmask = 0xFF
            self.memory_cache = self.update_memory(
                self.memory_cache, address, bitmask, value)
