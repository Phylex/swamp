.. _`synchronous memory`:

Synchronized Memory Class
=========================

Overview
--------

The ``SynchronizedMemory`` class is a component of a SWAMP object that abstracts the details of managing and synchronizing memory operations between the SWAMP software tree and the hardware.
It is designed to work with a transport object for communication. The transport object is responsible for delivering the transactions to the root of the SWAMP tree. For this it uses a series of
SWAMP (Synchronized Write And Memory Protocol ;) ) messages to facilitate memory reads, writes, and resets.

The ``SynchronizedMemory`` maintains two copies of the memory it manages, a cache memory and a committed memory. It also maintains list of uncommitted or 'in flight' transactions.
It allows reading and writing to the memory cache and sending transactions via the transport object. 
The committed memory is only updated upon receiving a committed transaction from the transport whitch matches a committed transaction issued by the SynchronizedMemory.
This means that the committed memmory should track the state of the physical memory as close as possible.
In case of a reset, the memory cache and committed memory are reset to their default states, and any outstanding uncommitted transactions are applied to rebuild the cache memory.
The reset assumes the transactions from the same origin are processed in sequence.

Functionality
-------------

- ``__init__`` initializes the instance with a transport object, memory size, and an optional default memory pattern.
- ``update_memory`` is a static method that updates the memory with a given address, bitmask, and value.
- ``write`` writes messages to the memory cache and sends corresponding transactions.
- ``read`` reads a value from the memory cache or committed memory based on the ``committed`` flag.
- ``receive_response`` processes received transactions and updates the memory state accordingly. If an error is encountered, it raises a ``RuntimeError``.
- ``outstanding_commits`` returns a list of outstanding uncommitted transactions as (address, value) tuples.
- ``reset`` resets the committed memory to its default state and rebuilds the memory cache based on uncommitted transactions.

The ``SynchronizedMemory`` class provides a convenient and efficient way to manage and synchronize memory operations across multiple devices or processes using the Synchronized Write And Memory Protocol.

SWAMP Messages
--------------

The ``SWAMPMessage`` is a base class for different types of messages used in the Synchronized Write And Memory Protocol. It has two derived classes: ``I2CWriteTransaction`` and ``I2CReadTransaction``.

- ``I2CWriteTransaction`` is used when writing to memory. It contains the address, value, and a unique transaction ID. The transaction ID is used for tracking the transaction until it is committed or encounters an error.
- ``I2CReadTransaction`` is used when reading from memory. It contains the address and a unique transaction ID.

There is also a ``MemReset`` message that is used to signal a reset command to the ``SynchronizedMemory`` instance.

