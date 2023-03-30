import uuid


class SWAMPMessage:
    def __init__(self, address, origin_id, target_id=0):
        self.transaction_id = int(uuid.uuid4().int & (1 << 64) - 1)
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


class WriteTransaction(SWAMPMessage):
    def __init__(self, address, value, origin_id, target_id=0):
        super().__init__(address, origin_id, target_id)
        self.value = value


class ReadTransaction(SWAMPMessage):
    def __init__(self, address, origin_id, target_id=0):
        super().__init__(address, origin_id, target_id)


class MemReset(SWAMPMessage):
    def __init__(self, origin_id: int, target_id: int = 0):
        super().__init__(origin_id, target_id)
        self.state = "pending"
