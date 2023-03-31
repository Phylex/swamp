from typing import List
from collections import defaultdict
import uuid


class SWAMPMessage:
    def __init__(self, address: int, origin_id: int, target_id: int = 0):
        self.id = self.generate_id()
        self.address = address
        self.origin_id = origin_id
        self.target_id = target_id
        self.state = 'pending'
        self.error_message = None

    def commit(self):
        self.state = 'committed'

    def set_error(self, error_message):
        self.state = 'error'
        self.error_message = error_message

    @staticmethod
    def generate_id() -> int:
        """
        generate integer based Id for a message or a group
        """
        return int(uuid.uuid4().int & (1 << 64) - 1)


class WriteTransaction(SWAMPMessage):
    def __init__(self, address, value, origin_id, target_id=0):
        super().__init__(address, origin_id, target_id)
        self.value = value


class ReadTransaction(SWAMPMessage):
    def __init__(self, address, origin_id, target_id=0):
        super().__init__(address, origin_id, target_id)
        self.value = None

    def commit(self, value: int):
        self.state = 'committed'
        self.value = value


class MemReset(SWAMPMessage):
    def __init__(self, origin_id: int, target_id: int = 0):
        super().__init__(-1, origin_id, target_id)
        self.state = "pending"
