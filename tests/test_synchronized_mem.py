import pytest
from swamp.syncmem import SynchronizedMemory
from . import MockTransport
from typing import Callable, List
from swamp.message import SWAMPMessage, MemReset


@pytest.fixture
def memory():
    transport = MockTransport()
    return SynchronizedMemory(transport, memory_size=8)


def test_synchronized_memory_write_commit(memory):
    """Test that writing to the synchronized memory works and commits the transaction."""
    memory.write([(3, 0xFF, 42)])

    assert memory.memory_cache[3] == 42
    assert memory.memory_committed[3] != 42

    memory.transport.process_transaction()
    assert memory.memory_committed[3] == 42


def test_synchronized_memory_write_error(memory):
    """Test that writing to the synchronized memory handles transaction errors."""
    memory.write([(3, 0xFF, 42)])

    assert memory.memory_cache[3] == 42
    assert memory.memory_committed[3] != 42

    with pytest.raises(RuntimeError):
        memory.transport.process_transaction(success=False)

    assert memory.memory_committed[3] != 42


def test_synchronized_memory_read(memory):
    """Test that reading from the synchronized memory works."""
    memory.write([(3, 0xFF, 42)])
    memory.transport.process_transaction()

    read_val = memory.read(3)
    assert read_val == 42


def test_synchronized_memory_read_committed(memory):
    """Test that reading from the committed memory works."""
    memory.write([(3, 0xFF, 42)])

    with pytest.raises(ValueError):
        memory.read(3, committed=True)

    memory.transport.process_transaction()

    read_val = memory.read(3, committed=True)
    assert read_val == 42


def test_synchronized_memory_reset(memory):
    """Test that resetting the synchronized memory works."""
    memory.write([(3, 0xFF, 42)])
    memory.transport.process_transaction()

    assert memory.memory_committed[3] == 42

    memory.transport.trigger_reset()
    assert memory.memory_committed[3] == 0
    assert memory.memory_cache[3] == 0
